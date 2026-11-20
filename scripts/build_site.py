"""Construit le site statique dans public/.

1. Lit les cours en euros dans la vue BigQuery `cours_eur` (une seule requête).
2. Écrit public/data/prices.json et copie les fichiers de site/.

    python scripts/build_site.py
    python -m http.server 8000 -d public     # prévisualisation locale
"""

import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from google.cloud import bigquery

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "imports"))

from bq_utils_import import get_bigquery_client  # noqa: E402
from etf_config import Actif, Config, charger_config  # noqa: E402

SOURCE = ROOT / "site"
PUBLIC = ROOT / "public"


def lire_cours_eur(config: Config, actifs: list[Actif]) -> pd.DataFrame:
    """Cours en euros (vue `cours_eur`, conversion faite par BigQuery) : id, Date, Close."""
    sql = f"""
        SELECT id_actif AS id, date AS Date, close_eur AS Close
        FROM `{config.objet(config.vue_cours_eur)}`
        WHERE id_actif IN UNNEST(@ids)
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ArrayQueryParameter("ids", "STRING", [a.id for a in actifs])]
    )
    rows = get_bigquery_client().query(sql, job_config=job_config).result()
    df = pd.DataFrame([dict(r) for r in rows], columns=["id", "Date", "Close"])
    df["Date"] = pd.to_datetime(df["Date"])
    return df.dropna().sort_values(["id", "Date"])


def construire_donnees(config: Config) -> dict:
    a_exporter = [config.parite, *(a for a in config.actifs if a.affiche)]
    df = lire_cours_eur(config, a_exporter)

    actifs, series = [], {}
    for actif in a_exporter:
        s = df.loc[df["id"] == actif.id].set_index("Date")["Close"]
        if s.empty:
            print(f"[{actif.id}] aucune donnée, ignoré", file=sys.stderr)
            continue
        actifs.append({
            "id": actif.id,
            "nom": actif.nom,
            "ticker": actif.ticker,
            "devise_origine": actif.devise,
            "categories": list(actif.categories),
            "est_parite": actif.id == config.parite.id,
        })
        series[actif.id] = {
            "dates": s.index.strftime("%Y-%m-%d").tolist(),
            "close": [round(float(v), 4) for v in s.to_numpy()],
        }
        print(f"[{actif.id}] {len(s)} points, du {s.index.min().date()} au {s.index.max().date()}")

    return {
        "genere_le": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "categories": config.categories,
        "actifs": actifs,
        "series": series,
    }


def main() -> None:
    load_dotenv(ROOT / ".env")
    donnees = construire_donnees(charger_config())

    if PUBLIC.exists():
        shutil.rmtree(PUBLIC)
    shutil.copytree(SOURCE, PUBLIC)
    (PUBLIC / "data").mkdir(exist_ok=True)
    chemin = PUBLIC / "data" / "prices.json"
    chemin.write_text(json.dumps(donnees, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Site généré dans {PUBLIC} ({chemin.stat().st_size / 1024:.0f} Ko de données)")


if __name__ == "__main__":
    main()
