#!/usr/bin/env python
"""One place that answers "how do we authenticate to BigQuery", for every local script.

Two auth paths exist because the org policy `iam.disableServiceAccountKeyCreation`
blocked service-account key creation on 2026-08-31/09-01. Rather than let that decide the
whole migration, the scripts accept either credential and prefer whichever is present:

  1. Service-account keyfile  ~/.dbt/keys/bq_dbt_sa.json    (if the policy is ever lifted)
  2. User OAuth refresh token ~/.dbt/keys/bq_oauth.json     (keyless, works under the policy)

Both files live in ~/.dbt/keys/, outside every git repo. Nothing here reads from the repo.

Honest note on the trade-off, because "keyless" is not automatically "safer": option 2 is
*your own user identity*, which holds Owner on the project, so it is broader than the
service account's Data Editor + Job User would have been. What it buys is that no long-lived
service-account key exists, which is what the org policy is actually protecting against, and
that the credential is tied to an account with MFA rather than a bare file. The BigQuery
query-usage quota is what bounds cost either way.
"""

import json
import os
import sys

SA_KEYFILE = os.path.expanduser("~/.dbt/keys/bq_dbt_sa.json")
OAUTH_FILE = os.path.expanduser("~/.dbt/keys/bq_oauth.json")

SCOPES = ["https://www.googleapis.com/auth/bigquery"]


def load():
    """Return (credentials, project, source). Exits with guidance if neither exists."""
    if os.path.exists(SA_KEYFILE):
        from google.oauth2 import service_account
        with open(SA_KEYFILE) as fh:
            info = json.load(fh)
        creds = service_account.Credentials.from_service_account_file(
            SA_KEYFILE, scopes=SCOPES)
        return creds, info.get("project_id"), "service-account keyfile"

    if os.path.exists(OAUTH_FILE):
        from google.oauth2.credentials import Credentials
        with open(OAUTH_FILE) as fh:
            info = json.load(fh)
        missing = [k for k in ("client_id", "client_secret", "refresh_token", "project")
                   if not info.get(k)]
        if missing:
            sys.exit("FAIL {} is missing: {}\n  re-run: python _migration/bq_oauth_setup.py"
                     .format(OAUTH_FILE, ", ".join(missing)))
        creds = Credentials(
            token=None,
            refresh_token=info["refresh_token"],
            client_id=info["client_id"],
            client_secret=info["client_secret"],
            token_uri=info.get("token_uri", "https://oauth2.googleapis.com/token"),
            scopes=SCOPES,
        )
        return creds, info["project"], "user OAuth refresh token"

    sys.exit(
        "FAIL no BigQuery credential found. Expected one of:\n"
        "  {}\n"
        "  {}\n\n"
        "If service-account keys are blocked by org policy, create an OAuth client and run:\n"
        "  python _migration/bq_oauth_setup.py".format(SA_KEYFILE, OAUTH_FILE))


def client():
    """A BigQuery client pinned to EU, plus the source string for logging."""
    from google.cloud import bigquery
    creds, project, source = load()
    return bigquery.Client(project=project, credentials=creds, location="EU"), source
