"""Phase 6 -- restore snapshot SCD2 history from the Snowflake export into BigQuery.

`dbt snapshot` CANNOT produce this. It builds history going forward from whatever it finds,
so on a fresh warehouse it emits one open version per order and the record of anything that
already changed is gone. The 4 closed rows in the dev export -- orders 100-103 moving
`placed` -> `shipped` at 2026-08-20 14:37:16.994 -- are the only data in this entire
migration that cannot be regenerated from source. Everything else is a rebuild away.

Two tables, deliberately different in character:

  dbt_learning_snapshots.orders_snapshot  108 rows, 4 of them CLOSED. The real prize.
                                          OVERWRITES dbt's fresh 104-row snapshot.
  prod_snapshots.orders_snapshot          104 rows, 0 closed, so no history to lose.
                                          Table does not exist yet; created here.

**Why overwriting the dev table is safe, and was checked rather than assumed:** it currently
holds 104 rows that `dbt build` created minutes ago, every one open, every one reproducible
by re-running `dbt snapshot`. The export holds those same 104 plus 4 that are not
reproducible at all. The overwrite therefore only ever adds information. Do not generalise
this to a snapshot with real accumulated history.

The prod table is created with the schema **mirrored from the table dbt itself built** rather
than one hand-written here. A hand-written schema that differs by even one type is the way
the Phase 5 production job fails on its first append.

Column order DIFFERS between the two CSVs -- dev has `DBT_SCD_ID,_ETL_LOADED_AT` and prod has
them swapped -- so every field is mapped by header NAME, case-insensitively. Positional
mapping would silently load md5 hashes into a timestamp column.

Naive timestamps are read as UTC, the same decision Phase 2 made for the raw load. The
`9999-12-31` sentinel is inside BigQuery's TIMESTAMP range and survives the round trip.

Usage:
    python restore_snapshots.py            # dry run, writes nothing
    python restore_snapshots.py --apply    # load
"""

import csv
import datetime as dt
import io
import os
import sys

from google.cloud import bigquery

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bq_creds  # noqa: E402

EXPORT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "snowflake-export-20260829")
LOCATION = "EU"

# (csv, dataset, table, expected_rows, expected_closed)
JOBS = [
    ("snapshot_orders_snapshot.csv", "dbt_learning_snapshots", "orders_snapshot", 108, 4),
    ("prodsnapshot_orders_snapshot.csv", "prod_snapshots", "orders_snapshot", 104, 0),
]

# The dev table is the one dbt built, so its schema is the authority for both.
SCHEMA_SOURCE = ("dbt_learning_snapshots", "orders_snapshot")


def convert(value, bqtype, where):
    """CSV text -> a JSON value BigQuery will accept for `bqtype`."""
    if value == "":
        # The parity baseline proves n_nonnull == n_rows for every column in both
        # snapshots, so an empty field means a damaged CSV, not a NULL.
        raise ValueError("{}: empty field, but the baseline says this column has no "
                         "NULLs - the CSV may be damaged".format(where))
    if bqtype in ("INTEGER", "INT64"):
        return int(value)
    if bqtype == "STRING":
        return value
    if bqtype == "DATE":
        return dt.date.fromisoformat(value).isoformat()
    if bqtype == "TIMESTAMP":
        stamp = dt.datetime.fromisoformat(value)
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=dt.timezone.utc)
        return stamp.isoformat()
    raise ValueError("{}: no conversion defined for BigQuery type {}".format(where, bqtype))


def read_rows(csv_name, schema):
    """Map the CSV to `schema` by column NAME, case-insensitively."""
    path = os.path.join(EXPORT, csv_name)
    with io.open(path, encoding="utf-8-sig", newline="") as fh:
        raw = list(csv.DictReader(fh))
    if not raw:
        raise ValueError("{}: no data rows".format(csv_name))

    header = {k.lower(): k for k in raw[0]}
    want = [f.name.lower() for f in schema]
    missing = [c for c in want if c not in header]
    extra = [c for c in header if c not in want]
    if missing:
        raise ValueError("{}: CSV is missing column(s) {}".format(csv_name, missing))
    if extra:
        raise ValueError("{}: CSV has unmapped column(s) {} - refusing to guess".format(
            csv_name, extra))

    out = []
    for i, r in enumerate(raw, start=2):
        out.append({f.name: convert(r[header[f.name.lower()]], f.field_type,
                                   "{} line {} col {}".format(csv_name, i, f.name))
                    for f in schema})
    return out


def verify(client, project, dataset, table, expect_rows, expect_closed):
    fq = "{}.{}.{}".format(project, dataset, table)
    sql = """
      select count(*) as n_rows
           , countif(dbt_valid_to < timestamp '9999-12-31') as n_closed
           , count(distinct dbt_scd_id) as n_scd_ids
           , count(distinct id) as n_ids
      from `{}`
    """.format(fq)
    r = list(client.query(sql, location=LOCATION).result())[0]
    ok = True
    for label, got, want in [("rows", r.n_rows, expect_rows),
                             ("closed rows", r.n_closed, expect_closed),
                             ("distinct dbt_scd_id", r.n_scd_ids, expect_rows)]:
        flag = "PASS" if got == want else "FAIL"
        ok = ok and got == want
        print("    {} {:<22} {} (expected {})".format(flag, label, got, want))
    print("    .. {} distinct order ids, so {} carry multiple versions".format(
        r.n_ids, r.n_rows - r.n_ids))
    return ok


def main():
    apply = "--apply" in sys.argv
    client, source = bq_creds.client()
    project = client.project
    print("credential: {}".format(source))
    print("mode: {}\n".format("APPLY (writes)" if apply else "DRY RUN (writes nothing)"))

    schema = client.get_table("{}.{}.{}".format(project, *SCHEMA_SOURCE)).schema
    print("schema mirrored from {}.{}:".format(*SCHEMA_SOURCE))
    for f in schema:
        print("    {:<16} {}".format(f.name, f.field_type))
    print()

    failures = []
    for csv_name, dataset, table, exp_rows, exp_closed in JOBS:
        fq = "{}.{}.{}".format(project, dataset, table)
        print("== {} -> {} ==".format(csv_name, fq))
        try:
            rows = read_rows(csv_name, schema)
        except Exception as exc:
            print("    FAIL {}".format(exc))
            failures.append(fq)
            continue
        closed = sum(1 for r in rows
                     if not r["dbt_valid_to"].startswith("9999-12-31"))
        print("    parsed {} rows, {} closed".format(len(rows), closed))
        if len(rows) != exp_rows or closed != exp_closed:
            print("    FAIL expected {} rows / {} closed".format(exp_rows, exp_closed))
            failures.append(fq)
            continue

        try:
            existing = client.get_table(fq).num_rows
            print("    target exists with {} row(s) - will be REPLACED".format(existing))
        except Exception:
            print("    target does not exist - will be created")

        if not apply:
            print("    (dry run, nothing written)\n")
            continue

        job = client.load_table_from_json(
            rows, fq,
            job_config=bigquery.LoadJobConfig(
                schema=schema,
                write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
                autodetect=False),
            location=LOCATION)
        job.result()
        print("    loaded. verifying by re-querying:")
        if not verify(client, project, dataset, table, exp_rows, exp_closed):
            failures.append(fq)
        print()

    if failures:
        print("FAILED: {}".format(", ".join(failures)))
        sys.exit(1)
    print("All snapshot restores {}.".format("verified" if apply
                                             else "validated (dry run)"))


if __name__ == "__main__":
    main()
