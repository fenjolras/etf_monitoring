"""Migration unique : 23 tables par actif -> table `cours`.

Copie toutes les lignes des anciennes tables dans `cours`, puis vérifie, actif par
actif, que le nombre de lignes et les dates extrêmes sont identiques.
Les anciennes tables ne sont PAS supprimées.

    python scripts/migrer_table_unique.py            # refuse si `cours` contient déjà des données
    python scripts/migrer_table_unique.py --force    # vide `cours` avant de recopier
"""

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "imports"))

from bq_modele import preparer_modele  # noqa: E402
from bq_utils_import import get_bigquery_client  # noqa: E402
from etf_config import charger_config  # noqa: E402


def lignes(client, sql):
    return [dict(r) for r in client.query(sql).result()]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    config = charger_config()
    client = get_bigquery_client()
    cours = config.objet(config.table_cours)

    preparer_modele(client, config)
    deja = lignes(client, f"SELECT COUNT(*) AS n FROM `{cours}`")[0]["n"]
    if deja and not args.force:
        print(f"`{cours}` contient déjà {deja} lignes : relancer avec --force pour recopier.", file=sys.stderr)
        return 1
    if deja:
        client.query(f"TRUNCATE TABLE `{cours}`").result()
        print(f"`{cours}` vidée ({deja} lignes)")

    selects = "\nUNION ALL\n".join(
        f"SELECT Date, '{a.id}', Close, CURRENT_TIMESTAMP() FROM `{config.table_id(a)}`" for a in config.tous
    )
    job = client.query(f"INSERT INTO `{cours}` (date, id_actif, close, importe_le)\n{selects}")
    job.result()
    print(f"{job.num_dml_affected_rows} lignes copiées dans `{cours}`")

    # Contrôle actif par actif : ancienne table vs nouvelle table
    ancien = "\nUNION ALL\n".join(
        f"SELECT '{a.id}' AS id_actif, COUNT(*) AS n, MIN(Date) AS dmin, MAX(Date) AS dmax FROM `{config.table_id(a)}`"
        for a in config.tous
    )
    controle = lignes(client, f"""
        WITH ancien AS ({ancien}),
        nouveau AS (
          SELECT id_actif, COUNT(*) AS n, COUNT(DISTINCT date) AS nd, MIN(date) AS dmin, MAX(date) AS dmax
          FROM `{cours}` GROUP BY id_actif
        )
        SELECT a.id_actif, a.n AS n_ancien, n.n AS n_nouveau, n.nd,
               a.dmin = n.dmin AND a.dmax = n.dmax AS dates_ok
        FROM ancien a LEFT JOIN nouveau n USING (id_actif)
        ORDER BY id_actif
    """)
    erreurs = [c for c in controle if c["n_ancien"] != c["n_nouveau"] or c["n_nouveau"] != c["nd"] or not c["dates_ok"]]
    for c in controle:
        etat = "OK" if c not in erreurs else "ÉCART"
        print(f"  {c['id_actif']:<7} {c['n_ancien']:>5} -> {c['n_nouveau']:>5}  {etat}")
    if erreurs:
        print(f"{len(erreurs)} actif(s) en écart", file=sys.stderr)
        return 1
    print("Migration vérifiée : toutes les lignes sont identiques.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
