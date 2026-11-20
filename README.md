# etf_monitoring

Suivi des performances d'une sélection d'ETF avec des indicateurs simples : évolution en base 100,
variations par période, mix équipondéré et podium des meilleures performances.

Tout tourne dans le cloud :

```
EODHD (API)  ──►  GitHub Actions  ──►  BigQuery (projet etf-monitoring, dataset etf_data)  ──►  visualisation
```

> La visualisation Streamlit (`app.py`, `pages/`, `sections/`) est en cours de remplacement par un site
> statique HTML. Elle est conservée pour l'instant comme référence des calculs.

## Référentiel des actifs : `etfs.toml`

Un bloc `[[actifs]]` par ETF : ticker EODHD, table BigQuery, libellé, devise, catégories,
fréquence d'import et affichage. **Ajouter un ETF = ajouter un bloc dans ce fichier.**

- `devise = "USD"` : l'actif est converti en EUR avec la parité EUR/USD (bloc `[parite]`).
- `frequence` : le plan gratuit EODHD limite à 20 appels par jour, donc les actifs sont répartis
  entre `daily` (mardi-samedi) et `weekly` (dimanche).

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

- `requirements-prod.txt` : dépendances des imports (GitHub Actions).
- `requirements.txt` : dépendances de l'ancienne application Streamlit.
- `requirements-dev.txt` : environnement de développement complet.
