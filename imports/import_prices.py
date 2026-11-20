"""Import incrémental des cours de clôture EODHD vers BigQuery.

Pour chaque actif de etfs.toml : lit la dernière date en base, télécharge les
cours postérieurs depuis EODHD et les ajoute à la table (append).

Exemples :
    python imports/import_prices.py --frequence daily
    python imports/import_prices.py --ids EUNL SXR8
    python imports/import_prices.py --frequence all --dry-run

Code de sortie 1 si au moins un actif a échoué (le workflow passe alors en rouge),
les autres actifs étant tout de même traités.
"""

import argparse
import os
import sys
from io import StringIO

import pandas as pd
import requests
from dotenv import load_dotenv
from google.api_core.exceptions import NotFound
from google.cloud import bigquery

from bq_utils_import import get_bigquery_client
from etf_config import Actif, Config, charger_config

EOD_URL = "https://eodhistoricaldata.com/api/eod/{ticker}"
SCHEMA = [
    bigquery.SchemaField("Date", "DATE"),
    bigquery.SchemaField("Close", "FLOAT"),
]


def derniere_date(client: bigquery.Client, table_id: str) -> pd.Timestamp | None:
    try:
        row = next(iter(client.query(f"SELECT MAX(Date) AS d FROM `{table_id}`").result()))
    except NotFound:
        return None
    return pd.Timestamp(row.d) if row.d else None


def telecharger(ticker: str, depuis: pd.Timestamp, api_key: str) -> pd.DataFrame:
    """Cours de clôture journaliers depuis EODHD, à partir de `depuis` inclus."""
    response = requests.get(
        EOD_URL.format(ticker=ticker),
        params={"from": depuis.date().isoformat(), "api_token": api_key, "period": "d", "fmt": "csv"},
        timeout=30,
    )
    if response.status_code != 200:
        # Le corps ne contient pas la clé ; l'URL, si, donc on ne l'affiche pas.
        raise RuntimeError(f"EODHD a répondu {response.status_code} : {response.text[:200]}")

    texte = response.text.strip()
    if not texte:
        return pd.DataFrame(columns=["Date", "Close"])

    df = pd.read_csv(StringIO(texte))
    if not {"Date", "Close"} <= set(df.columns):
        raise RuntimeError(f"Colonnes inattendues dans la réponse EODHD : {list(df.columns)}")

    df = df[["Date", "Close"]]
    # EODHD peut ajouter des lignes parasites en fin de CSV : on ne garde que les vraies dates.
    df = df[df["Date"].astype(str).str.fullmatch(r"\d{4}-\d{2}-\d{2}", na=False)].copy()
    df["Date"] = pd.to_datetime(df["Date"])
    df["Close"] = pd.to_numeric(df["Close"], errors="coerce")
    return df.dropna().sort_values("Date")


def importer(actif: Actif, config: Config, client: bigquery.Client, api_key: str, dry_run: bool) -> int:
    """Importe un actif ; renvoie le nombre de lignes ajoutées."""
    table_id = config.table_id(actif)
    fin = derniere_date(client, table_id)
    depuis = fin + pd.Timedelta(days=1) if fin is not None else pd.Timestamp(config.date_debut_defaut)
    print(f"[{actif.id}] dernière date en base : {fin.date() if fin is not None else 'aucune'}"
          f" -> import depuis le {depuis.date()}")

    if dry_run:
        return 0

    df = telecharger(actif.ticker, depuis, api_key)
    # Protection contre les doublons si EODHD renvoie des dates déjà en base.
    if fin is not None:
        df = df[df["Date"] > fin]
    if df.empty:
        print(f"[{actif.id}] aucune nouvelle donnée")
        return 0

    job_config = bigquery.LoadJobConfig(
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        schema=SCHEMA,
    )
    client.load_table_from_dataframe(df, table_id, job_config=job_config).result()
    print(f"[{actif.id}] {len(df)} ligne(s) ajoutée(s), jusqu'au {df['Date'].max().date()}")
    return len(df)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--frequence", choices=["daily", "weekly", "all"], default="daily")
    parser.add_argument("--ids", nargs="+", help="identifiants précis (prioritaire sur --frequence)")
    parser.add_argument("--dry-run", action="store_true",
                        help="lit BigQuery sans appeler EODHD ni écrire")
    args = parser.parse_args()

    load_dotenv()
    api_key = os.getenv("EOD_API_KEY")
    if not api_key and not args.dry_run:
        print("Clé EOD_API_KEY manquante (secret GitHub ou fichier .env)", file=sys.stderr)
        return 1

    config = charger_config()
    actifs = config.a_importer(args.frequence, args.ids)
    print(f"{len(actifs)} actif(s) à traiter : {', '.join(a.id for a in actifs)}")

    client = get_bigquery_client()
    echecs = []
    for actif in actifs:
        try:
            importer(actif, config, client, api_key, args.dry_run)
        except Exception as e:  # on continue avec les actifs suivants
            message = str(e).replace(api_key, "***") if api_key else str(e)  # les erreurs réseau citent l'URL
            print(f"[{actif.id}] ÉCHEC : {message}", file=sys.stderr)
            echecs.append(actif.id)

    if echecs:
        print(f"{len(echecs)} échec(s) : {', '.join(echecs)}", file=sys.stderr)
        return 1
    print("Import terminé sans erreur")
    return 0


if __name__ == "__main__":
    sys.exit(main())
