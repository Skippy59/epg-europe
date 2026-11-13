#!/usr/bin/env python3
"""Download, merge and publish public XMLTV EPG sources."""

from __future__ import annotations

import argparse
import concurrent.futures
import copy
import gzip
import json
import logging
import os
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zipfile import ZipFile
from io import BytesIO

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCES = ROOT / "config" / "sources.json"
DEFAULT_OVERRIDES = ROOT / "config" / "channel_overrides.json"
LOG = logging.getLogger("epg-europe")


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def decode_payload(payload: bytes) -> bytes:
    """Accept plain XML, gzip XML, or a ZIP containing an XML file."""
    if payload.startswith(b"\x1f\x8b"):
        return gzip.decompress(payload)
    if payload.startswith(b"PK\x03\x04"):
        with ZipFile(BytesIO(payload)) as archive:
            candidates = [n for n in archive.namelist() if n.lower().endswith(".xml")]
            if not candidates:
                raise ValueError("ZIP archive contains no .xml file")
            return archive.read(candidates[0])
    return payload


def fetch_source(source: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        source["url"],
        headers={
            "User-Agent": settings.get("user_agent", "EPG-Europe/1.0"),
            "Accept": "application/xml,text/xml,*/*",
            "Accept-Encoding": "identity",
        },
    )
    with urllib.request.urlopen(
        request, timeout=int(settings.get("request_timeout_seconds", 90))
    ) as response:
        raw = response.read()
    xml_bytes = decode_payload(raw)
    root = ET.fromstring(xml_bytes)
    if root.tag != "tv":
        raise ValueError(f"Unexpected XML root element: {root.tag}")
    channels = root.findall("channel")
    programmes = root.findall("programme")
    if not channels and not programmes:
        raise ValueError("XMLTV document contains no channels or programmes")
    return {
        "source": source,
        "channels": channels,
        "programmes": programmes,
    }


def canonical_channel_id(channel_id: str, id_map: dict[str, str]) -> str:
    """Resolve a manually configured channel ID alias, including simple chains."""
    seen: set[str] = set()
    current = channel_id
    while current in id_map and current not in seen:
        seen.add(current)
        current = id_map[current]
    return current


def add_display_name(channel: ET.Element, name: str) -> None:
    for node in channel.findall("display-name"):
        channel.remove(node)
    display = ET.Element("display-name")
    display.text = name
    channel.insert(0, display)


def build_documents(
    fetched: list[dict[str, Any]], overrides: dict[str, Any]
) -> tuple[ET.Element, ET.Element, dict[str, int]]:
    id_map = overrides.get("channel_id_map", {})
    channel_overrides = overrides.get("channel_overrides", {})
    channels: dict[str, tuple[int, ET.Element]] = {}
    programmes: dict[tuple[str, str, str], tuple[int, ET.Element]] = {}

    for item in sorted(fetched, key=lambda x: int(x["source"].get("priority", 100))):
        priority = int(item["source"].get("priority", 100))
        for original in item["channels"]:
            old_id = original.get("id", "").strip()
            if not old_id:
                continue
            new_id = canonical_channel_id(old_id, id_map)
            override = channel_overrides.get(new_id, {})
            if override.get("exclude", False):
                continue
            candidate = copy.deepcopy(original)
            candidate.set("id", new_id)
            if override.get("name"):
                add_display_name(candidate, str(override["name"]))
            if override.get("icon"):
                for icon in candidate.findall("icon"):
                    candidate.remove(icon)
                icon = ET.Element("icon", {"src": str(override["icon"])})
                candidate.append(icon)
            current = channels.get(new_id)
            if current is None or priority < current[0]:
                channels[new_id] = (priority, candidate)

        for original in item["programmes"]:
            old_id = original.get("channel", "").strip()
            start = original.get("start", "").strip()
            stop = original.get("stop", "").strip()
            if not old_id or not start or not stop:
                continue
            new_id = canonical_channel_id(old_id, id_map)
            override = channel_overrides.get(new_id, {})
            if override.get("exclude", False):
                continue
            candidate = copy.deepcopy(original)
            candidate.set("channel", new_id)
            key = (new_id, start, stop)
            current = programmes.get(key)
            if current is None or priority < current[0]:
                programmes[key] = (priority, candidate)
            if new_id not in channels:
                generated = ET.Element("channel", {"id": new_id})
                display = ET.SubElement(generated, "display-name")
                display.text = new_id
                channels[new_id] = (priority, generated)

    def make_tv(selected_channels: set[str] | None = None) -> ET.Element:
        tv = ET.Element(
            "tv",
            {
                "generator-info-name": "EPG Europe",
                "generator-info-url": "https://github.com/Skippy59/epg-europe",
            },
        )
        for channel_id in sorted(channels):
            if selected_channels is None or channel_id in selected_channels:
                tv.append(copy.deepcopy(channels[channel_id][1]))
        ordered = sorted(
            programmes.values(),
            key=lambda pair: (
                pair[1].get("start", ""),
                pair[1].get("channel", ""),
            ),
        )
        for _, programme in ordered:
            if selected_channels is None or programme.get("channel") in selected_channels:
                tv.append(copy.deepcopy(programme))
        return tv

    channels_with_programmes = {key[0] for key in programmes}
    full = make_tv()
    filtered = make_tv(channels_with_programmes)
    stats = {
        "channels_total": len(channels),
        "channels_with_programmes": len(channels_with_programmes),
        "programmes_total": len(programmes),
    }
    return full, filtered, stats


def write_xmltv(root: ET.Element, destination: Path) -> None:
    ET.indent(root, space="  ")
    xml_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as raw_handle:
        with gzip.GzipFile(
            filename="",
            mode="wb",
            fileobj=raw_handle,
            compresslevel=9,
            mtime=0,
        ) as handle:
            handle.write(xml_bytes)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=str(ROOT / "public"))
    parser.add_argument("--sources", default=str(DEFAULT_SOURCES))
    parser.add_argument("--overrides", default=str(DEFAULT_OVERRIDES))
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    source_config = load_json(Path(args.sources))
    overrides = load_json(Path(args.overrides))
    settings = source_config.get("settings", {})
    sources = [s for s in source_config.get("sources", []) if s.get("enabled", True)]
    if not sources:
        LOG.error("No enabled EPG sources configured")
        return 2

    LOG.info("Downloading %d enabled XMLTV sources", len(sources))
    fetched: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    workers = max(1, int(settings.get("max_parallel_downloads", 6)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        future_map = {
            pool.submit(fetch_source, source, settings): source for source in sources
        }
        for future in concurrent.futures.as_completed(future_map):
            source = future_map[future]
            try:
                item = future.result()
                fetched.append(item)
                LOG.info(
                    "OK %s: %d channels, %d programmes",
                    source["id"],
                    len(item["channels"]),
                    len(item["programmes"]),
                )
            except Exception as exc:  # one unavailable provider must not stop the others
                LOG.warning("FAILED %s: %s", source["id"], exc)
                failures.append({"id": source["id"], "error": str(exc)})

    minimum = int(settings.get("minimum_successful_sources", 2))
    if len(fetched) < minimum:
        LOG.error(
            "Only %d sources succeeded; at least %d are required. Existing published EPG will not be replaced.",
            len(fetched),
            minimum,
        )
        return 3

    full, filtered, stats = build_documents(fetched, overrides)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_xmltv(full, output_dir / "epg.xml.gz")
    write_xmltv(filtered, output_dir / "epg-filtered.xml.gz")

    source_status = []
    for item in fetched:
        source = item["source"]
        source_status.append(
            {
                "id": source["id"],
                "name": source["name"],
                "country": source.get("country"),
                "status": "ok",
                "channels": len(item["channels"]),
                "programmes": len(item["programmes"]),
            }
        )
    for failure in failures:
        source_status.append(
            {"id": failure["id"], "status": "error", "error": failure["error"]}
        )

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator_version": "1.0.0",
        "sources_enabled": len(sources),
        "sources_succeeded": len(fetched),
        "sources_failed": len(failures),
        **stats,
        "sources": sorted(source_status, key=lambda x: x["id"]),
    }
    (output_dir / "status.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    LOG.info("Build complete: %s", json.dumps(stats))
    LOG.info("Published files prepared in %s", output_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
