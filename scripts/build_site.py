"""Construit le site statique dans public/.

1. Lit tous les cours dans BigQuery (une seule requête).
2. Convertit en EUR les actifs cotés en USD, avec la parité EUR/USD du même jour.
3. Écrit public/data/prices.json et copie les fichiers de site/.

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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "imports"))

from bq_utils_import import get_bigquery_client  # noqa: E402
from etf_config import Actif, Config, charger_config  # noqa: E402

SOURCE = ROOT / "site"
PUBLIC = ROOT / "public"


def lire_cours(config: Config, actifs: list[Actif]) -> pd.DataFrame:
    """Tous les cours au format long : id, Date, Close."""
    sql = "\nUNION ALL\n".join(
        f"SELECT '{a.id}' AS id, Date, Close FROM `{config.table_id(a)}`" for a in actifs
    )
    client = get_bigquery_client()
    rows = client.query(sql).result()
    df = pd.DataFrame([dict(r) for r in rows], columns=["id", "Date", "Close"])
    df["Date"] = pd.to_datetime(df["Date"])
    return df.dropna().sort_values(["id", "Date"])


def serie_eur(df: pd.DataFrame, actif: Actif, fx: pd.Series) -> pd.Series:
    s = df.loc[df["id"] == actif.id].set_index("Date")["Close"]
    if actif.devise == "USD":
        # EURUSD = dollars pour 1 euro : prix en EUR = prix en USD / EURUSD (dates communes uniquement).
        s = (s / fx.reindex(s.index)).dropna()
    return s


def construire_donnees(config: Config) -> dict:
    a_exporter = [config.parite, *(a for a in config.actifs if a.affiche)]
    df = lire_cours(config, [config.parite, *config.actifs])
    fx = df.loc[df["id"] == config.parite.id].set_index("Date")["Close"]

    actifs, series = [], {}
    for actif in a_exporter:
        s = serie_eur(df, actif, fx)
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
