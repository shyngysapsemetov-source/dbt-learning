#!/usr/bin/env python
"""Prove Phase 1 actually landed, instead of assuming it did.

Phase 1 is console work, and three of its steps fail *later* rather than at the time:
a dataset created in the wrong location only breaks when a model tries to join across
regions; a default table expiration only bites 60 days in; a missing IAM role only shows up
as a 403 on the first dbt run. All three are cheap to check now and expensive to discover
in Phase 3.

    python _migration/verify_phase1.py

Reads the project id from the keyfile rather than taking it as an argument, so the real
GCP project id never has to be typed into a command that lands in shell history — and never
into this public repo.

The permission probe creates and immediately drops one table named `_dbt_permission_probe`
in `dbt_learning`. That is the only way to prove BigQuery Data Editor actually works before
dbt depends on it. It touches nothing else.
"""

import json
import os
import sys

from google.api_core import exceptions as gexc
from google.cloud import bigquery
from google.oauth2 import service_account

KEYFILE = os.path.expanduser("~/.dbt/keys/bq_dbt_sa.json")
LOCATION = "EU"
PROBE = "_dbt_permission_probe"

EXPECTED = [
    "raw_jaffle_shop",
    "raw_stripe",
    "raw_mesh_jaffle_shop",
    "dbt_learning",
    "dbt_learning_snapshots",
    "prod",
    "prod_snapshots",
    "mesh_dev",
]

ok, fail = [], []


def check(cond, good, bad):
    (ok if cond else fail).append(good if cond else bad)
    print("  {} {}".format("PASS" if cond else "FAIL", good if cond else bad))


def main():
    print("\n== keyfile ==")
    if not os.path.exists(KEYFILE):
        sys.exit("FAIL no keyfile at {} - step 5 of Phase 1 is incomplete".format(KEYFILE))
    with open(KEYFILE) as fh:
        info = json.load(fh)
    project = info.get("project_id")
    check(info.get("type") == "service_account",
          "keyfile is a service-account key", "keyfile is not a service-account key")
    check(bool(project), "project_id present in keyfile", "keyfile has no project_id")
    print("  .. service account: {}".format(info.get("client_email")))

    creds = service_account.Credentials.from_service_account_file(KEYFILE)
    client = bigquery.Client(project=project, credentials=creds, location=LOCATION)

    print("\n== datasets ==")
    try:
        found = {d.dataset_id: d for d in client.list_datasets()}
    except gexc.Forbidden as exc:
        sys.exit("FAIL cannot list datasets - check the API is enabled and roles are "
                 "granted at project level:\n  {}".format(str(exc).splitlines()[0]))
    for name in EXPECTED:
        check(name in found, "dataset {} exists".format(name),
              "dataset {} MISSING".format(name))
    extra = sorted(set(found) - set(EXPECTED))
    if extra:
        print("  .. also present (not an error): {}".format(", ".join(extra)))

    print("\n== location (irreversible; cross-location joins are rejected) ==")
    for name in EXPECTED:
        if name not in found:
            continue
        loc = client.get_dataset(found[name].reference).location
        check(loc == LOCATION,
              "{} is in {}".format(name, loc),
              "{} is in {} - must be {}; recreate it".format(name, loc, LOCATION))

    print("\n== default table expiration (must be unset, or models vanish later) ==")
    for name in EXPECTED:
        if name not in found:
            continue
        ms = client.get_dataset(found[name].reference).default_table_expiration_ms
        check(ms is None,
              "{} has no default expiration".format(name),
              "{} expires tables after {} days - clear it".format(
                  name, round(int(ms) / 86400000, 1) if ms else "?"))

    print("\n== BigQuery Job User (can run queries) ==")
    try:
        got = list(client.query("select 1 as ok", location=LOCATION).result())[0].ok
        check(got == 1, "query job succeeded", "query returned {}".format(got))
    except gexc.Forbidden as exc:
        check(False, "", "cannot run jobs - grant roles/bigquery.jobUser: {}".format(
            str(exc).splitlines()[0]))

    print("\n== BigQuery Data Editor (can create and drop tables) ==")
    if "dbt_learning" in found:
        fq = "{}.dbt_learning.{}".format(project, PROBE)
        try:
            client.query("create or replace table `{}` as select 1 as probe".format(fq),
                         location=LOCATION).result()
            client.query("drop table `{}`".format(fq), location=LOCATION).result()
            check(True, "created and dropped {}".format(PROBE), "")
        except gexc.Forbidden as exc:
            check(False, "", "cannot write - grant roles/bigquery.dataEditor: {}".format(
                str(exc).splitlines()[0]))
    else:
        check(False, "", "skipped write probe: dbt_learning does not exist")

    print("\n{} passed, {} failed".format(len(ok), len(fail)))
    if fail:
        print("\nPhase 1 is NOT complete. Fix the FAIL lines above and re-run.")
        sys.exit(1)
    print("Phase 1 verified. Safe to start Phase 2 (load raw data).")


if __name__ == "__main__":
    main()
