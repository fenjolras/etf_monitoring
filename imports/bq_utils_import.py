"""Client BigQuery commun aux imports et à la génération du site.

Ordre d'authentification :
1. GOOGLE_APPLICATION_CREDENTIALS_JSON : contenu JSON de la clé (secret GitHub Actions)
2. sinon, identifiants par défaut de Google : variable GOOGLE_APPLICATION_CREDENTIALS
   pointant vers un fichier de clé (fichier .env en local) ou `gcloud auth application-default login`

Garde-fou de coût : chaque requête est plafonnée à MAX_OCTETS_FACTURES. Une requête qui
dépasserait ce volume échoue (erreur bytesBilledLimitExceeded) au lieu d'être facturée.
Nos requêtes facturent de l'ordre de 10 à 20 Mo : 1 Gio laisse une marge x50.
"""

import json
import os

from google.auth.exceptions import DefaultCredentialsError
from google.cloud import bigquery
from google.oauth2 import service_account

MAX_OCTETS_FACTURES = 1024**3  # 1 Gio par requête


def _config_requetes() -> bigquery.QueryJobConfig:
    return bigquery.QueryJobConfig(maximum_bytes_billed=MAX_OCTETS_FACTURES)


def get_bigquery_client() -> bigquery.Client:
    creds_json = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON")
    if creds_json:
        credentials = service_account.Credentials.from_service_account_info(json.loads(creds_json))
        return bigquery.Client(
            credentials=credentials,
            project=credentials.project_id,
            default_query_job_config=_config_requetes(),
        )

    try:
        return bigquery.Client(default_query_job_config=_config_requetes())
    except DefaultCredentialsError as e:
        raise RuntimeError(
            "Identifiants GCP introuvables : définir GOOGLE_APPLICATION_CREDENTIALS_JSON "
            "ou GOOGLE_APPLICATION_CREDENTIALS (voir .env)."
        ) from e
