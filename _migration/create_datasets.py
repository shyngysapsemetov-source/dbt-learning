#!/usr/bin/env python
"""Create the 8 BigQuery datasets for Phase 1, in EU, with no default table expiration.

Why a script and not console clicks: **dataset location is immutable**. Get it wrong and the
only remedy is delete-and-recreate, and you find out not at creation time but on the first
query that joins across regions ("Not found: Dataset ... was not found in location EU"). Eight
manual creations, each needing the same two non-default settings, is a coin flip. Here the
location and expiration are stated once, in code, and reviewable in the diff.

Idempotent: existing datasets are left alone, never modified or dropped. Re-running is safe.
It *reports* a mismatch rather than fixing one, because the fix for a wrong location is
destructive and that is not a script's decision to make.

    python _migration/create_datasets.py            # show what would change
    python _migration/create_datasets.py --apply    # create the missing ones

Authenticates via bq_creds, so it works with either the service-account key or user OAuth.
"""

import argparse
import os
import sys

from google.api_core import exceptions as gexc
from google.cloud import bigquery

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bq_creds  # noqa: E402

LOCATION = "EU"

# Phase 0's namespace model. Snowflake's database.schema.table has no direct BigQuery
# equivalent -- BigQuery has project.dataset.table, one level shallower -- so the three source
# databases collapse into name-prefixed datasets in a single project.
DATASETS = {
    "raw_jaffle_shop":        "Source: jaffle_shop raw tables (was raw.jaffle_shop)",
    "raw_stripe":             "Source: stripe raw tables (was raw.stripe)",
    "raw_mesh_jaffle_shop":   "Source: mesh project raw tables",
    "dbt_learning":           "Dev target for dbt_fundamentals",
    "dbt_learning_snapshots":  "Dev snapshots -- separate so a dev schema wipe cannot take "
                               "SCD2 history with it",
    "prod":                   "Production target, built by the dbt Cloud job",
    "prod_snapshots":         "Production snapshots -- holds orders_snapshot history",
    "mesh_dev":               "Dev target for the mesh projects (finance + platform)",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="actually create; default is a dry run")
    args = ap.parse_args()

    client, source = bq_creds.client()
    print("project  : {}".format(client.project))
    print("credential: {}".format(source))
    print("location : {}  (immutable once set)".format(LOCATION))
    print("mode     : {}\n".format("APPLY" if args.apply else "dry run"))

    try:
        existing = {d.dataset_id for d in client.list_datasets()}
    except gexc.Forbidden as exc:
        sys.exit("FAIL cannot list datasets. Is the BigQuery API enabled, and are the roles "
                 "granted at project level?\n  {}".format(str(exc).splitlines()[0]))
    except gexc.NotFound as exc:
        sys.exit("FAIL project not found or BigQuery API not enabled.\n  {}"
                 .format(str(exc).splitlines()[0]))

    created, kept, problems = [], [], []

    for name, description in DATASETS.items():
        if name in existing:
            ds = client.get_dataset("{}.{}".format(client.project, name))
            if ds.location != LOCATION:
                problems.append(
                    "{} exists in {} but must be {}. Location cannot be changed; this dataset "
                    "has to be dropped and recreated. Not doing that automatically."
                    .format(name, ds.location, LOCATION))
            elif ds.default_table_expiration_ms is not None:
                problems.append(
                    "{} has a default table expiration of {} days set. Clear it, or models "
                    "will silently vanish later.".format(
                        name, round(int(ds.default_table_expiration_ms) / 86400000, 1)))
            else:
                kept.append(name)
            continue

        if not args.apply:
            created.append(name)
            continue

        ds = bigquery.Dataset("{}.{}".format(client.project, name))
        ds.location = LOCATION
        ds.description = description
        # Left explicitly at None. A default expiration is the setting that makes tables
        # disappear 60 days later, which presents as "dbt built nothing" long after the cause.
        ds.default_table_expiration_ms = None
        try:
            client.create_dataset(ds)
            created.append(name)
        except gexc.Forbidden as exc:
            problems.append("{}: cannot create - needs roles/bigquery.dataEditor or "
                            "user: {}".format(name, str(exc).splitlines()[0]))
        except gexc.Conflict:
            kept.append(name)          # created by someone else between list and create

    for name in kept:
        print("  KEEP   {} (already correct)".format(name))
    for name in created:
        print("  {}{}".format("CREATE " if args.apply else "WOULD CREATE ", name))
    for msg in problems:
        print("  PROBLEM {}".format(msg))

    extra = sorted(existing - set(DATASETS))
    if extra:
        print("\n  note: also present, not touched: {}".format(", ".join(extra)))

    print("\n{} correct, {} {}, {} problems".format(
        len(kept), len(created), "created" if args.apply else "to create", len(problems)))

    if problems:
        sys.exit(1)
    if not args.apply and created:
        print("\nRe-run with --apply to create them.")
    elif not created:
        print("\nAll 8 datasets present and correct. Run verify_phase1.py to confirm "
              "end to end.")


if __name__ == "__main__":
    main()
