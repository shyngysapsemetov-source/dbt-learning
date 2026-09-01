#!/usr/bin/env python
"""One-time: turn an OAuth client into a long-lived BigQuery refresh token. No SA key needed.

Why this exists: the GCP organization enforces `iam.disableServiceAccountKeyCreation`
(Google's "Secure by Default"), so no service-account JSON key can be created. Creating an
**OAuth 2.0 client** is not governed by that constraint, so a user-consent flow is a way to
authenticate that the policy permits. dbt's `method: oauth-secrets` consumes exactly the
values this produces, and `bq_creds.py` feeds the same values to the Python loaders.

Prerequisites, both in the GCP console and neither blocked by the policy:

  1. APIs & Services -> OAuth consent screen
     User type **Internal**. This matters: an *External* app left in "Testing" status issues
     refresh tokens that expire after **7 days**, which would silently break every script a
     week from now. Internal has no such expiry.

  2. APIs & Services -> Credentials -> Create credentials -> OAuth client ID
     Application type **Desktop app**. Copy the client ID and client secret.

Then:

    python _migration/bq_oauth_setup.py --project <your-gcp-project-id>

A browser window opens for consent. The refresh token is written to
~/.dbt/keys/bq_oauth.json, outside every git repo. Client ID and secret are read
interactively rather than as arguments so they do not land in shell history.

Only the BigQuery scope is requested, not cloud-platform - narrower, and enough for
everything dbt and the loaders do.
"""

import argparse
import getpass
import json
import os
import stat
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

OUT = os.path.expanduser("~/.dbt/keys/bq_oauth.json")
SCOPES = ["https://www.googleapis.com/auth/bigquery"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True, help="GCP project id")
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args()

    print("Paste the OAuth *Desktop app* client credentials (not echoed).")
    client_id = input("  client id     : ").strip()
    client_secret = getpass.getpass("  client secret : ").strip()
    if not client_id or not client_secret:
        sys.exit("FAIL both client id and client secret are required")

    cfg = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }

    flow = InstalledAppFlow.from_client_config(cfg, scopes=SCOPES)
    # prompt="consent" + access_type=offline is what guarantees a refresh_token comes back;
    # without them Google may return only an access token on a repeat authorisation.
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")

    if not creds.refresh_token:
        sys.exit("FAIL no refresh token returned. Re-run; if it recurs, revoke the app at "
                 "https://myaccount.google.com/permissions and try again.")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    payload = {
        "type": "authorized_user",
        "project": args.project,
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": creds.refresh_token,
        "token_uri": "https://oauth2.googleapis.com/token",
    }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
        fh.write("\n")
    try:
        os.chmod(args.out, stat.S_IRUSR | stat.S_IWUSR)      # best effort on Windows
    except OSError:
        pass

    print("\nWrote {}".format(args.out))
    print("Verify with: python _migration/verify_phase1.py")
    print("\nprofiles.yml block for this credential:\n")
    print("""default:
  target: bq
  outputs:
    bq:
      type: bigquery
      method: oauth-secrets
      project: {project}
      dataset: dbt_learning
      location: EU
      threads: 16
      client_id: "{cid}"
      client_secret: "<from ~/.dbt/keys/bq_oauth.json>"
      refresh_token: "<from ~/.dbt/keys/bq_oauth.json>"
      token_uri: https://oauth2.googleapis.com/token""".format(
        project=args.project, cid=client_id))
    print("\n(profiles.yml is gitignored, but it lives in ~/.dbt/ anyway - not in the repo.)")


if __name__ == "__main__":
    main()
