#!/usr/bin/env python
"""Prove Phase 1 actually landed, instead of assuming it did.

Phase 1 is console work, and three of its steps fail *later* rather than at the time:
a dataset created in the wrong location only breaks when a model tries to join across
regions; a default table expiration only bites 60 days in; a missing IAM role only shows up
as a 403 on the first dbt run. All three are cheap to check now and expensive to discover
in Phase 3.

    python _migration/verify_phase1.py

Reads the project id from the credential file rather than taking it as an argument, so the
real GCP project id never has to be typed into a command that lands in shell history - and
never into this public repo.

Authentication goes through `bq_creds`, which accepts either a service-account keyfile or a
user OAuth refresh token. This script does not care which: the point is to prove the *project*
is configured correctly, and both credentials exercise the same API surface. What differs is
what a FAIL on the IAM checks means - see the note printed with the credential source.

The permission probe creates and immediately drops one table named `_dbt_permission_probe`
in `dbt_learning`. That is the only way to prove BigQuery Data Editor actually works before
dbt depends on it. It touches nothing else.
"""

import os
import sys

from google.api_core import exceptions as gexc
from google.cloud import bigquery

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bq_creds  # noqa: E402

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
    print("\n== credential ==")
    # load() rather than client(): the Storage Read API probe below needs the raw
    # credential object, which a bigquery.Client does not hand back.
    creds, project, source = bq_creds.load()
    client = bigquery.Client(credentials=creds, project=project, location=LOCATION)
    check(bool(project), "project id resolved from credential",
          "credential has no project id")
    print("  .. source: {}".format(source))
    if source.startswith("user OAuth"):
        print("  .. note: this is your own identity (Owner), so the two IAM checks below")
        print("     prove the *project* works, not that a least-privilege role was granted.")
        print("     Re-run under a service-account key if the org policy is ever lifted.")

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

    # dbt Fusion 2.0 fetches query results through the BigQuery Storage Read API rather
    # than the REST API that dbt Core used, so it needs a THIRD role that the two above
    # do not imply: roles/bigquery.readSessionUser. Without it every command fails at
    # connection time with "There was a problem connecting to the BigQuery Storage API",
    # which names the API and not the missing permission -- so it reads like a disabled
    # API. It is not. The two are distinguishable only by the underlying error: a disabled
    # API returns SERVICE_DISABLED, a missing role returns 403 on
    # bigquery.readsessions.create. This probe surfaces that directly.
    print("\n== BigQuery Read Session User (Fusion 2.0 result fetching) ==")
    try:
        from google.cloud import bigquery_storage_v1 as bqs
    except ImportError:
        check(False, "", "pip install google-cloud-bigquery-storage to probe this")
    else:
        table = "projects/{}/datasets/raw_stripe/tables/payment".format(project)
        try:
            session = bqs.BigQueryReadClient(credentials=creds).create_read_session(
                request=bqs.types.CreateReadSessionRequest(
                    parent="projects/{}".format(project),
                    read_session=bqs.types.ReadSession(
                        table=table, data_format=bqs.types.DataFormat.ARROW),
                    max_stream_count=1))
            check(len(session.streams) > 0, "read session created", "no streams returned")
        except gexc.NotFound:
            check(False, "", "raw_stripe.payment missing - run Phase 2 loader first")
        except gexc.Forbidden as exc:
            check(False, "", "grant roles/bigquery.readSessionUser: {}".format(
                str(exc).splitlines()[0]))

    print("\n{} passed, {} failed".format(len(ok), len(fail)))
    if fail:
        print("\nPhase 1 is NOT complete. Fix the FAIL lines above and re-run.")
        sys.exit(1)
    print("Phase 1 verified. Safe to start Phase 2 (load raw data).")


if __name__ == "__main__":
    main()
