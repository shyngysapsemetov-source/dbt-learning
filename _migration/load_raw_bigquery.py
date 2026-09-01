#!/usr/bin/env python
"""Phase 2: load the 9 raw CSVs into BigQuery with explicit types and asserted row counts.

    python _migration/load_raw_bigquery.py            # dry run: parse, type-check, count
    python _migration/load_raw_bigquery.py --apply    # load
    python _migration/load_raw_bigquery.py --only raw_stripe.payment --apply

Four decisions here, each guarding a failure that shows up somewhere other than this script:

1. **Headers are lowercased.** The CSVs carry Snowflake's `UPPERCASE` headers. Snowflake folds
   unquoted identifiers to upper and matches case-insensitively; BigQuery does not fold and
   column references are case-sensitive. Every staging model selects lowercase, so loading
   `ID` would fail on the first `dbt run` with "Name ID not found" - one phase later, in a
   place that looks like a model bug.

2. **Types are declared, never autodetected.** Autodetect samples rows and guesses. It happens
   to get `payment.amount` right (INT64 cents) but can read `order_date` as STRING, and a
   STRING date compares lexicographically without erroring - `'2018-1-9' > '2018-01-10'` is
   true. Types come from `SOURCE-TYPES.md`, captured from Snowflake's information_schema.

3. **TIMESTAMP_NTZ maps to TIMESTAMP, not DATETIME** - deliberately the *less* faithful choice.
   DATETIME is the exact equivalent of a zone-less Snowflake timestamp, but two things compare
   these columns against `current_timestamp()`: source freshness (`loaded_at_field:
   _batched_at` / `_etl_loaded_at`) and `int_order_payments`'s incremental watermark. Mixing
   DATETIME with a tz-aware `current_timestamp()` makes dbt's freshness calculation subtract a
   naive datetime from an aware one, which surfaces as a Python TypeError inside dbt rather
   than as a data problem. The values are naive wall-clock and are read as UTC; that assumption
   is uniform, so ordering, diffs and aggregates are unaffected. Phase 7 must compare these
   zone-stripped, since the Snowflake baseline rendered them without a zone.

4. **Row counts are asserted against `PARITY-BASELINE-20260831.csv`, twice** - once on the
   parsed rows before upload, once by querying BigQuery afterwards. A truncated CSV that loads
   "successfully" is silent data loss, and Phase 7 would surface it as an unexplained parity
   miss with the cause four phases behind.

Also asserted: **no field may be empty.** The baseline shows n_nonnull == n_rows for every
column of every raw table, so there are no NULLs to preserve. That makes an empty CSV field
unrepresentable rather than ambiguous - the CSV writer emitted '' for None, so without this
check a NULL and an empty string would be indistinguishable and silently conflated.

Idempotent: WRITE_TRUNCATE replaces table contents, so re-running converges instead of
appending duplicates.
"""

import argparse
import csv
import datetime as dt
import os
import sys
from decimal import Decimal, InvalidOperation

from google.api_core import exceptions as gexc
from google.cloud import bigquery

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bq_creds  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
EXPORT = os.path.join(HERE, "snowflake-export-20260829")
BASELINE = os.path.join(HERE, "PARITY-BASELINE-20260831.csv")

# csv file -> (bigquery dataset, table, source identity in the baseline, columns)
# Columns are (name, bigquery type) in file order. Names are the lowercase targets.
TABLES = [
    ("raw_jaffle_shop__customers.csv", "raw_jaffle_shop", "customers",
     ("RAW", "JAFFLE_SHOP", "CUSTOMERS"), [
         ("id", "INT64"), ("first_name", "STRING"), ("last_name", "STRING")]),

    ("raw_jaffle_shop__orders.csv", "raw_jaffle_shop", "orders",
     ("RAW", "JAFFLE_SHOP", "ORDERS"), [
         ("id", "INT64"), ("user_id", "INT64"), ("order_date", "DATE"),
         ("status", "STRING"), ("_etl_loaded_at", "TIMESTAMP")]),

    ("raw_stripe__payment.csv", "raw_stripe", "payment",
     ("RAW", "STRIPE", "PAYMENT"), [
         ("id", "INT64"), ("orderid", "INT64"), ("paymentmethod", "STRING"),
         ("status", "STRING"), ("amount", "INT64"), ("created", "DATE"),
         ("_batched_at", "TIMESTAMP")]),

    ("rawmesh_jaffle_shop__customers.csv", "raw_mesh_jaffle_shop", "customers",
     ("RAW_MESH", "JAFFLE_SHOP", "CUSTOMERS"), [
         ("id", "STRING"), ("name", "STRING")]),

    ("rawmesh_jaffle_shop__items.csv", "raw_mesh_jaffle_shop", "items",
     ("RAW_MESH", "JAFFLE_SHOP", "ITEMS"), [
         ("id", "STRING"), ("order_id", "STRING"), ("sku", "STRING")]),

    ("rawmesh_jaffle_shop__orders.csv", "raw_mesh_jaffle_shop", "orders",
     ("RAW_MESH", "JAFFLE_SHOP", "ORDERS"), [
         ("id", "STRING"), ("customer", "STRING"), ("ordered_at", "TIMESTAMP"),
         ("store_id", "STRING"), ("subtotal", "INT64"), ("tax_paid", "INT64"),
         ("order_total", "INT64")]),

    ("rawmesh_jaffle_shop__products.csv", "raw_mesh_jaffle_shop", "products",
     ("RAW_MESH", "JAFFLE_SHOP", "PRODUCTS"), [
         ("sku", "STRING"), ("name", "STRING"), ("type", "STRING"),
         ("price", "INT64"), ("description", "STRING")]),

    ("rawmesh_jaffle_shop__stores.csv", "raw_mesh_jaffle_shop", "stores",
     ("RAW_MESH", "JAFFLE_SHOP", "STORES"), [
         ("id", "STRING"), ("name", "STRING"), ("opened_at", "TIMESTAMP"),
         # NUMBER(38,4). NUMERIC, not FLOAT64: tax_rate multiplies money, and 0.075 has no
         # exact binary representation. BigQuery NUMERIC is decimal with scale 9.
         ("tax_rate", "NUMERIC")]),

    ("rawmesh_jaffle_shop__supplies.csv", "raw_mesh_jaffle_shop", "supplies",
     ("RAW_MESH", "JAFFLE_SHOP", "SUPPLIES"), [
         ("id", "STRING"), ("name", "STRING"), ("cost", "INT64"),
         ("perishable", "BOOL"), ("sku", "STRING")]),
]

# Deliberately absent: snapshot_orders_snapshot.csv and prodsnapshot_orders_snapshot.csv.
# Those are Phase 6. Loading them here would hand dbt a pre-existing snapshot table it
# believes it built, and the next `dbt snapshot` would extend history it did not create -
# with `dbt_scd_id` hashes computed by a different warehouse.
SKIP = {"snapshot_orders_snapshot.csv", "prodsnapshot_orders_snapshot.csv"}


def expected_counts():
    """Row counts Snowflake reported on 2026-08-31, keyed by (database, schema, table)."""
    counts = {}
    with open(BASELINE, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            counts[(r["database"], r["schema"], r["table"])] = int(r["n_rows"])
    return counts


def convert(value, bqtype, where):
    """CSV text -> a JSON-loadable Python value of the declared type. Raises, never coerces."""
    if value == "":
        # Justified by the baseline: n_nonnull == n_rows for every raw column, so there is
        # nothing NULL to represent. An empty field means the export or the file is damaged.
        raise ValueError("{}: empty field, but the baseline says this column has no NULLs "
                         "- the CSV may be damaged".format(where))
    if bqtype == "STRING":
        return value
    if bqtype == "INT64":
        return int(value)                     # ValueError on anything non-integral
    if bqtype == "NUMERIC":
        try:
            return str(Decimal(value))        # as a string: exact, no float round-trip
        except InvalidOperation:
            raise ValueError("{}: {!r} is not a decimal".format(where, value))
    if bqtype == "BOOL":
        # The exporter wrote Python repr, so 'True'/'False'. Accept the usual spellings but
        # nothing else - a silent default here would invert `perishable` for a whole column.
        low = value.strip().lower()
        if low in ("true", "t", "1"):
            return True
        if low in ("false", "f", "0"):
            return False
        raise ValueError("{}: {!r} is not a boolean".format(where, value))
    if bqtype == "DATE":
        return dt.date.fromisoformat(value).isoformat()
    if bqtype == "TIMESTAMP":
        # Exported as ISO 8601, e.g. 2026-08-02T01:25:11.485, naive. Parsed to validate, then
        # re-emitted with an explicit +00:00 so BigQuery is not left to infer the zone.
        stamp = dt.datetime.fromisoformat(value)
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=dt.timezone.utc)
        return stamp.isoformat()
    raise ValueError("{}: unhandled type {}".format(where, bqtype))


def read_table(path, columns):
    """Parse and type-convert one CSV. Returns a list of dicts ready for a JSON load."""
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        header = next(reader)
        lowered = [h.strip().lower() for h in header]
        declared = [c for c, _ in columns]
        if lowered != declared:
            raise ValueError(
                "header mismatch in {}\n  file    : {}\n  declared: {}"
                .format(os.path.basename(path), lowered, declared))

        rows = []
        for lineno, raw in enumerate(reader, start=2):
            if len(raw) != len(columns):
                raise ValueError("{} line {}: {} fields, expected {}".format(
                    os.path.basename(path), lineno, len(raw), len(columns)))
            rows.append({
                name: convert(val, bqtype, "{} line {} col {}".format(
                    os.path.basename(path), lineno, name))
                for (name, bqtype), val in zip(columns, raw)})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="load; default is a dry run")
    ap.add_argument("--only", help="one target as dataset.table, e.g. raw_stripe.payment")
    args = ap.parse_args()

    unknown = {f for f in os.listdir(EXPORT) if f.endswith(".csv")} - \
              {t[0] for t in TABLES} - SKIP
    if unknown:
        sys.exit("FAIL unmapped CSVs in the export dir, refusing to guess: {}\n"
                 "  Add them to TABLES or to SKIP explicitly."
                 .format(", ".join(sorted(unknown))))

    client, source = bq_creds.client()
    counts = expected_counts()
    print("project   : {}".format(client.project))
    print("credential: {}".format(source))
    print("mode      : {}\n".format("APPLY" if args.apply else "dry run"))

    total, failures = 0, []

    for filename, dataset, table, ident, columns in TABLES:
        target = "{}.{}".format(dataset, table)
        if args.only and args.only != target:
            continue
        label = "{:<34}".format(target)
        try:
            rows = read_table(os.path.join(EXPORT, filename), columns)
        except (ValueError, OSError) as exc:
            failures.append("{}: {}".format(target, exc))
            print("  FAIL  {} {}".format(label, exc))
            continue

        want = counts.get(ident)
        if want is None:
            failures.append("{}: no baseline row count for {}".format(target, ident))
            print("  FAIL  {} no baseline entry for {}".format(label, ".".join(ident)))
            continue
        if len(rows) != want:
            failures.append("{}: parsed {} rows, baseline says {}".format(
                target, len(rows), want))
            print("  FAIL  {} parsed {} rows, Snowflake had {}".format(
                label, len(rows), want))
            continue

        if not args.apply:
            print("  OK    {} {:>5} rows parsed and typed".format(label, len(rows)))
            total += len(rows)
            continue

        schema = [bigquery.SchemaField(name, bqtype) for name, bqtype in columns]
        job_config = bigquery.LoadJobConfig(
            schema=schema,
            # Explicit: never let the API infer a schema from the JSON payload.
            autodetect=False,
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        )
        fq = "{}.{}.{}".format(client.project, dataset, table)
        try:
            client.load_table_from_json(rows, fq, job_config=job_config).result()
            landed = list(client.query(
                "select count(*) as n from `{}`".format(fq)).result())[0].n
        except (gexc.GoogleAPIError, gexc.RetryError) as exc:
            failures.append("{}: {}".format(target, str(exc).splitlines()[0]))
            print("  FAIL  {} {}".format(label, str(exc).splitlines()[0]))
            continue

        if landed != want:
            failures.append("{}: loaded {} rows but BigQuery reports {}".format(
                target, want, landed))
            print("  FAIL  {} BigQuery reports {} rows, expected {}".format(
                label, landed, want))
            continue
        print("  LOAD  {} {:>5} rows, verified in BigQuery".format(label, landed))
        total += landed

    print("\n{} rows across {} tables. {} failures.".format(
        total, len([t for t in TABLES if not args.only or args.only == "{}.{}".format(t[1], t[2])]),
        len(failures)))
    if failures:
        print("\nPhase 2 is NOT complete:")
        for f in failures:
            print("  - {}".format(f))
        sys.exit(1)
    if args.apply:
        print("Phase 2 loaded and row-count verified. Next: Phase 3, profiles + dialect fixes.")
    else:
        print("Dry run clean. Re-run with --apply to load.")


if __name__ == "__main__":
    main()
