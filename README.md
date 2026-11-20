# etf_monitoring

Suivi des performances d'une sélection d'ETF avec des indicateurs simples : évolution en base 100,
variations par période, mix équipondéré et podium des meilleures performances.

Tout tourne dans le cloud :

```
EODHD (API)  ──►  GitHub Actions  ──►  BigQuery (projet etf-monitoring, dataset etf_data)  ──►  site statique
```

## Référentiel des actifs : `etfs.toml`

Un bloc `[[actifs]]` par ETF : ticker EODHD, table BigQuery, libellé, devise, catégories,
fréquence d'import et affichage. **Ajouter un ETF = ajouter un bloc dans ce fichier.**

- `devise = "USD"` : l'actif est converti en EUR avec la parité EUR/USD (bloc `[parite]`).
- `frequence` : le plan gratuit EODHD limite à 20 appels par jour (1 appel par actif), donc les
  actifs sont répartis entre `daily` (mardi-samedi, 20 appels) et `weekly` (dimanche, 3 appels).
  Le chargement de la config échoue si une fréquence dépasse `quota_appels_jour`.

## Import des données : `imports/`

- `import_prices.py` : pour chaque actif, lit la dernière date en base, télécharge les cours suivants
  depuis EODHD et les ajoute à la table. Un actif en erreur n'empêche pas les autres d'être traités,
  mais le script se termine en erreur pour que le workflow passe en rouge.
- `etf_config.py` : lecture et validation de `etfs.toml`.
- `bq_utils_import.py` : connexion à BigQuery.

```bash
python imports/import_prices.py --frequence daily      # daily | weekly | all
python imports/import_prices.py --ids EUNL SXR8        # actifs précis
python imports/import_prices.py --frequence all --dry-run   # lit BigQuery sans appeler EODHD
```

Le workflow `.github/workflows/imports.yml` lance ce script chaque matin à 5h UTC
(daily du mardi au samedi, weekly le dimanche), ou à la main depuis l'onglet Actions.
En lancement manuel, l'option « test à blanc » est cochée par défaut : aucun appel EODHD n'est fait.
Un import manuel réel consomme le quota du jour, à éviter un jour où le cron a déjà tourné.

## Site statique : `site/` et `scripts/build_site.py`

`build_site.py` lit tous les cours dans BigQuery, convertit en EUR les actifs cotés en USD,
écrit `public/data/prices.json` et copie les pages de `site/` dans `public/`, qui n'est pas versionné.
Les calculs (base 100, variations, podium) se font dans le navigateur : le site n'accède jamais à BigQuery.

| Page | Contenu |
|---|---|
| `index.html` | podiums à 3 mois et à 1 an, avec le classement complet |
| `comparateur.html` | jusqu'à 8 ETF en base 100, mix équipondéré, performance annualisée ; `?preset=harry_browne` |
| `etfs.html` | tous les ETF par catégorie, avec leurs variations |
| `etf.html?id=EUNL` | fiche d'un ETF : historique et variations |

```bash
python scripts/build_site.py
python -m http.server 8000 -d public    # puis http://localhost:8000
```

Seuls les actifs `affiche = true` de `etfs.toml` sont publiés. La publication sur GitHub Pages n'est pas
encore activée : elle attend la validation des conditions de rediffusion des données EODHD.

## Secrets

Aucun secret dans le dépôt.

| Où | Nom | Contenu |
|---|---|---|
| Secrets GitHub Actions | `EOD_API_KEY` | clé API EODHD |
| Secrets GitHub Actions | `GCP_CREDENTIALS_JSON` | contenu JSON de la clé du compte de service GCP |
| `.env` local (ignoré par git) | `EOD_API_KEY` | clé API EODHD |
| `.env` local (ignoré par git) | `GOOGLE_APPLICATION_CREDENTIALS` | chemin vers le fichier JSON de la clé, rangé hors du dépôt |

## Environnement local (Windows)

```bash
python -m venv venv
source venv/Scripts/activate
pip install -r requirements-prod.txt
```

- `requirements-prod.txt` : dépendances des imports et de la génération du site (GitHub Actions).
- `requirements-dev.txt` : environnement de développement complet (Jupyter, etc.).
