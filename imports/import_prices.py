"""Import incrémental des cours de clôture EODHD vers BigQuery (table `cours`).

1. Prépare le modèle : table `cours`, référentiel `actifs` (copie de etfs.toml), vue `cours_eur`.
2. Lit en une requête la dernière date en base de chaque actif.
3. Télécharge chez EODHD les cours postérieurs (1 appel par actif).
4. Charge les nouvelles lignes dans une table de transit, puis les fusionne dans
   `cours` avec un MERGE : une ligne (date, actif) déjà présente n'est jamais dupliquée.

Exemples :
    python imports/import_prices.py --frequence daily
    python imports/import_prices.py --ids EUNL SXR8
    python imports/import_prices.py --frequence all --dry-run

Code de sortie 1 si au moins un actif a échoué (le workflow passe alors en rouge),
les autres actifs étant tout de même importés.
"""

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from io import StringIO

import pandas as pd
import requests
from dotenv import load_dotenv
from google.cloud import bigquery

from bq_modele import preparer_modele
from bq_utils_import import get_bigquery_client
from etf_config import Actif, Config, charger_config

EOD_URL = "https://eodhistoricaldata.com/api/eod/{ticker}"
TABLE_TRANSIT = "_transit_cours"
SCHEMA_TRANSIT = [
    bigquery.SchemaField("date", "DATE", mode="REQUIRED"),
    bigquery.SchemaField("id_actif", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("close", "FLOAT64", mode="REQUIRED"),
]


def dernieres_dates(client: bigquery.Client, config: Config) -> dict[str, pd.Timestamp]:
    sql = f"SELECT id_actif, MAX(date) AS d FROM `{config.objet(config.table_cours)}` GROUP BY id_actif"
    return {r.id_actif: pd.Timestamp(r.d) for r in client.query(sql).result()}


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
    # Sans cotation sur la période (jour férié, séance pas encore close), EODHD renvoie "Value" seul.
    if df.empty:
        return pd.DataFrame(columns=["Date", "Close"])
    if not {"Date", "Close"} <= set(df.columns):
        raise RuntimeError(f"Colonnes inattendues dans la réponse EODHD : {list(df.columns)}")

    df = df[["Date", "Close"]]
    # EODHD peut ajouter des lignes parasites en fin de CSV : on ne garde que les vraies dates.
    df = df[df["Date"].astype(str).str.fullmatch(r"\d{4}-\d{2}-\d{2}", na=False)].copy()
    df["Date"] = pd.to_datetime(df["Date"])
    df["Close"] = pd.to_numeric(df["Close"], errors="coerce")
    return df.dropna().sort_values("Date")


def nouvelles_lignes(actif: Actif, fin: pd.Timestamp | None, config: Config, api_key: str) -> pd.DataFrame:
    depuis = fin + pd.Timedelta(days=1) if fin is not None else pd.Timestamp(config.date_debut_defaut)
    df = telecharger(actif.ticker, depuis, api_key)
    if fin is not None:
        df = df[df["Date"] > fin]
    if df.empty:
        print(f"[{actif.id}] aucune nouvelle donnée")
        return pd.DataFrame(columns=["date", "id_actif", "close"])
    print(f"[{actif.id}] {len(df)} ligne(s), jusqu'au {df['Date'].max().date()}")
    return pd.DataFrame({"date": df["Date"].dt.date, "id_actif": actif.id, "close": df["Close"]})


def fusionner(client: bigquery.Client, config: Config, df: pd.DataFrame) -> int:
    """Charge `df` en transit puis l'insère dans `cours` sans créer de doublon."""
    transit = config.objet(TABLE_TRANSIT)
    job_config = bigquery.LoadJobConfig(
        schema=SCHEMA_TRANSIT,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )
    client.load_table_from_dataframe(df, transit, job_config=job_config).result()
    # La table de transit disparaît d'elle-même si plus aucun import ne tourne.
    table = client.get_table(transit)
    table.expires = datetime.now(timezone.utc) + timedelta(days=7)
    client.update_table(table, ["expires"])

    job = client.query(f"""
        MERGE `{config.objet(config.table_cours)}` AS c
        USING `{transit}` AS t
        ON c.date = t.date AND c.id_actif = t.id_actif
        WHEN NOT MATCHED THEN
          INSERT (date, id_actif, close, importe_le)
          VALUES (t.date, t.id_actif, t.close, CURRENT_TIMESTAMP())
    """)
    job.result()
    return job.num_dml_affected_rows or 0


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
    if not args.dry_run:
        preparer_modele(client, config)
    fins = dernieres_dates(client, config)

    lots, echecs = [], []
    for actif in actifs:
        fin = fins.get(actif.id)
        print(f"[{actif.id}] dernière date en base : {fin.date() if fin is not None else 'aucune'}")
        if args.dry_run:
            continue
        try:
            lots.append(nouvelles_lignes(actif, fin, config, api_key))
        except Exception as e:  # on continue avec les actifs suivants
            message = str(e).replace(api_key, "***")  # les erreurs réseau citent l'URL
            print(f"[{actif.id}] ÉCHEC : {message}", file=sys.stderr)
            echecs.append(actif.id)

    nouveaux = pd.concat([l for l in lots if not l.empty], ignore_index=True) if any(not l.empty for l in lots) else None
    if nouveaux is not None:
        inseres = fusionner(client, config, nouveaux)
        print(f"{inseres} ligne(s) ajoutée(s) dans `{config.table_cours}`")

    if echecs:
        print(f"{len(echecs)} échec(s) : {', '.join(echecs)}", file=sys.stderr)
        return 1
    print("Import terminé sans erreur")
    return 0


if __name__ == "__main__":
    sys.exit(main())
