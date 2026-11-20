"""Client BigQuery pour les scripts d'import.

Ordre d'authentification :
1. GOOGLE_APPLICATION_CREDENTIALS_JSON : contenu JSON de la clé (secret GitHub Actions)
2. sinon, identifiants par défaut de Google : variable GOOGLE_APPLICATION_CREDENTIALS
   pointant vers un fichier de clé (fichier .env en local) ou `gcloud auth application-default login`
"""

import json
import os

from google.auth.exceptions import DefaultCredentialsError
from google.cloud import bigquery
from google.oauth2 import service_account


def get_bigquery_client() -> bigquery.Client:
    creds_json = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON")
    if creds_json:
        credentials = service_account.Credentials.from_service_account_info(json.loads(creds_json))
        return bigquery.Client(credentials=credentials, project=credentials.project_id)

    try:
        return bigquery.Client()
    except DefaultCredentialsError as e:
        raise RuntimeError(
            "Identifiants GCP introuvables : définir GOOGLE_APPLICATION_CREDENTIALS_JSON "
            "ou GOOGLE_APPLICATION_CREDENTIALS (voir .env)."
        ) from e
