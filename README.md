# EPG Europe

Agrégateur public de guides TV au format XMLTV. Le projet télécharge plusieurs sources publiques, fusionne les chaînes et les programmes, puis publie deux fichiers compressés utilisables dans un lecteur IPTV compatible XMLTV.

## Fichiers publiés

Après activation de GitHub Pages et une première exécution réussie :

- `https://skippy59.github.io/epg-europe/epg.xml.gz` : toutes les chaînes présentes dans les sources retenues.
- `https://skippy59.github.io/epg-europe/epg-filtered.xml.gz` : uniquement les chaînes disposant d'au moins un programme.
- `https://skippy59.github.io/epg-europe/status.json` : état de la dernière génération et statistiques.

## Sources initiales

Les sources et leurs priorités sont définies dans [config/sources.json](config/sources.json).

- XMLTV FR : guide complet français.
- IPTV-EPG.org : guides nationaux européens et balkaniques.

Les catalogues évoluent. Une source peut être indisponible temporairement ou modifier son URL ; le rapport de génération indique les échecs.

**Kosovo :** aucun flux national Kosovo dédié n'a été identifié dans le catalogue IPTV-EPG utilisé au démarrage. Des chaînes kosovares peuvent être présentes dans d'autres guides, mais leur couverture doit être vérifiée avant d'ajouter une source.

## Corriger les correspondances entre chaînes

Les identifiants XMLTV sont utilisés par les lecteurs IPTV pour associer les programmes aux chaînes. Deux noms proches ne suffisent pas à prouver qu'il s'agit de la même chaîne.

Le fichier [config/channel_overrides.json](config/channel_overrides.json) permet de corriger les correspondances manuellement.

Exemple :

```json
{
  "channel_id_map": {
    "IdentifiantSourceA": "IdentifiantCanonique",
    "IdentifiantSourceB": "IdentifiantCanonique"
  },
  "channel_overrides": {
    "IdentifiantCanonique": {
      "name": "Nom affiché",
      "icon": "https://exemple.org/logo.png"
    }
  }
}
```

Pour exclure une chaîne :

```json
{
  "channel_id_map": {},
  "channel_overrides": {
    "IdentifiantAExclure": {
      "exclude": true
    }
  }
}
```

Après modification, enregistrer le fichier dans GitHub : le workflow se relance automatiquement.

## Mise à jour automatique

GitHub Actions lance une génération deux fois par jour (04:17 et 16:17 UTC), ainsi qu'après une modification des fichiers de configuration ou du code.

Le workflow exige au minimum deux sources valides. Si trop de sources échouent, la génération s'arrête et la version déjà publiée n'est pas remplacée.

Les horaires sont en UTC dans le calendrier GitHub Actions.

## Activer GitHub Pages (à faire une seule fois)

1. Ouvrir **Settings** dans le dépôt.
2. Dans le menu latéral, choisir **Pages**.
3. Dans **Build and deployment**, sélectionner **GitHub Actions** comme source.

Ensuite, ouvrir l'onglet **Actions**, sélectionner **Build and publish EPG Europe**, puis lancer **Run workflow** pour le premier test.

## Lancer en local (facultatif)

Python 3.10 ou plus récent est nécessaire. Aucune dépendance Python externe n'est requise.

```bash
python scripts/build_epg.py --output-dir public
```

## Limites et bonnes pratiques

- Ce projet agrège des guides publics ; il ne récupère pas les flux vidéo IPTV.
- Ne jamais ajouter d'identifiants Xtream Codes, de playlist privée ou de données personnelles dans ce dépôt public.
- La fusion automatique utilise les identifiants XMLTV. Les chaînes dont les identifiants diffèrent doivent être rapprochées dans le fichier de correspondances.
- Les données, la profondeur des programmes et les conditions d'utilisation dépendent de chaque fournisseur de source.
