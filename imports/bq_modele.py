"""Modèle BigQuery du projet.

- `cours`     : une ligne par (date, actif), tous actifs confondus.
                Partitionnée par mois, clusterisée par actif.
- `actifs`    : référentiel des actifs, copie de etfs.toml rafraîchie à chaque import.
- `cours_eur` : vue des cours convertis en euros (actifs USD / parité EUR/USD du même jour).
"""

from datetime import datetime, timezone

from google.cloud import bigquery

from etf_config import Config

SCHEMA_COURS = [
    bigquery.SchemaField("date", "DATE", mode="REQUIRED"),
    bigquery.SchemaField("id_actif", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("close", "FLOAT64", mode="REQUIRED", description="Cours de clôture, devise de cotation"),
    bigquery.SchemaField("importe_le", "TIMESTAMP", description="Date de chargement de la ligne"),
]

SCHEMA_ACTIFS = [
    bigquery.SchemaField("id_actif", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("ticker", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("nom", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("devise", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("categories", "STRING", mode="REPEATED"),
    bigquery.SchemaField("frequence", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("affiche", "BOOL", mode="REQUIRED"),
    bigquery.SchemaField("est_parite", "BOOL", mode="REQUIRED"),
    bigquery.SchemaField("maj_le", "TIMESTAMP", mode="REQUIRED"),
]


def creer_table_cours(client: bigquery.Client, config: Config) -> None:
    table = bigquery.Table(config.objet(config.table_cours), schema=SCHEMA_COURS)
    table.time_partitioning = bigquery.TimePartitioning(type_=bigquery.TimePartitioningType.MONTH, field="date")
    table.clustering_fields = ["id_actif"]
    table.description = "Cours de clôture journaliers de tous les actifs (source EODHD)"
    client.create_table(table, exists_ok=True)


def synchroniser_actifs(client: bigquery.Client, config: Config) -> None:
    """Remplace le contenu de la table `actifs` par etfs.toml (chargement gratuit)."""
    maintenant = datetime.now(timezone.utc).isoformat()
    lignes = [{
        "id_actif": a.id, "ticker": a.ticker, "nom": a.nom, "devise": a.devise,
        "categories": list(a.categories), "frequence": a.frequence, "affiche": a.affiche,
        "est_parite": a.id == config.parite.id, "maj_le": maintenant,
    } for a in config.tous]
    job_config = bigquery.LoadJobConfig(
        schema=SCHEMA_ACTIFS,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )
    client.load_table_from_json(lignes, config.objet(config.table_actifs), job_config=job_config).result()


def creer_vue_cours_eur(client: bigquery.Client, config: Config) -> None:
    cours, actifs = config.objet(config.table_cours), config.objet(config.table_actifs)
    sql = f"""
    CREATE OR REPLACE VIEW `{config.objet(config.vue_cours_eur)}`
    OPTIONS (description = "Cours de clôture en euros : actifs USD convertis avec la parité EUR/USD du même jour")
    AS
    WITH fx AS (
      SELECT date, close AS eurusd FROM `{cours}` WHERE id_actif = '{config.parite.id}'
    )
    SELECT
      c.date,
      c.id_actif,
      a.devise AS devise_origine,
      IF(a.devise = 'USD', c.close / fx.eurusd, c.close) AS close_eur
    FROM `{cours}` AS c
    JOIN `{actifs}` AS a USING (id_actif)
    LEFT JOIN fx USING (date)
    -- un actif USD sans parité ce jour-là est écarté plutôt que mal converti
    WHERE a.devise != 'USD' OR fx.eurusd IS NOT NULL
    """
    client.query(sql).result()


def preparer_modele(client: bigquery.Client, config: Config) -> None:
    """Crée la table de cours si besoin, rafraîchit le référentiel et la vue."""
    creer_table_cours(client, config)
    synchroniser_actifs(client, config)
    creer_vue_cours_eur(client, config)
