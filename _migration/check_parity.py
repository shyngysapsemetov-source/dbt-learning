#!/usr/bin/env python
"""Phase 7: diff BigQuery against the recorded Snowflake fingerprint.

    python _migration/check_parity.py                       # everything the baseline covers
    python _migration/check_parity.py --database RAW RAW_MESH
    python _migration/check_parity.py --verbose              # print matches too

Snowflake is gone, so this compares live BigQuery against `PARITY-BASELINE-20260831.csv`,
produced by `make_fingerprint.py` while the trial was alive. Objects the baseline knows about
but BigQuery does not yet have are reported as "not built" rather than as failures - before
Phase 3 that is every derived model, and the same command becomes a full parity run afterwards
with no changes.

**The hard part is not the aggregates, it is rendering.** The baseline recorded Snowflake's
`to_varchar()` output, so equality only means something if BigQuery is asked to render the same
way. The three that actually differ:

  * TIMESTAMP - Snowflake's default is `YYYY-MM-DD HH:MI:SS.FF3`; BigQuery's `cast(x as string)`
    yields `2026-08-02 01:25:11.485000+00`. Compared via
    `format_timestamp('%Y-%m-%d %H:%M:%E3S', x, 'UTC')`. The UTC is not cosmetic: the loader
    read naive Snowflake wall-clock as UTC, so rendering in any other zone would shift every
    value by the offset and fail everything.
  * NUMERIC - trailing zeros differ by declared scale. Compared as trimmed decimals, since
    `0.2775` and `0.277500` are the same number and a string compare would call them different.
  * FLOAT64 - none exist today. If any appear, sums are order-dependent and must be compared
    rounded, not exactly.

Two limits inherited from the baseline, both deliberate and both meaning "investigate", not
"fail": TEXT min/max depends on collation, which is not guaranteed identical across warehouses;
and `count(distinct)` on TEXT is exact in both, but BigQuery's `APPROX_COUNT_DISTINCT` is not -
this uses exact `count(distinct)` on purpose, which costs more and is the right trade at this
data volume.
"""

import argparse
import csv
import os
import sys
from decimal import Decimal, InvalidOperation

from google.api_core import exceptions as gexc

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bq_creds  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
BASELINE = os.path.join(HERE, "PARITY-BASELINE-20260831.csv")

# Snowflake database.schema -> BigQuery dataset. BigQuery is one level shallower, so the
# three-part Snowflake name collapses into a prefixed dataset (Phase 0's namespace model).
DATASET = {
    ("RAW", "JAFFLE_SHOP"): "raw_jaffle_shop",
    ("RAW", "STRIPE"): "raw_stripe",
    ("RAW_MESH", "JAFFLE_SHOP"): "raw_mesh_jaffle_shop",
    ("ANALYTICS", "DBT_LEARNING"): "dbt_learning",
    ("ANALYTICS", "DBT_LEARNING_SNAPSHOTS"): "dbt_learning_snapshots",
    ("ANALYTICS", "PROD"): "prod",
    ("ANALYTICS", "PROD_SNAPSHOTS"): "prod_snapshots",
    ("ANALYTICS", "MESH_DEV"): "mesh_dev",
}

NUMERIC_SF = {"NUMBER", "DECIMAL", "INT", "INTEGER", "BIGINT", "SMALLINT",
              "FLOAT", "DOUBLE", "REAL"}

# `SchemaField.field_type` returns BigQuery's **legacy** type names, not the standard-SQL ones
# the docs and DDL use: INT64 comes back as INTEGER, FLOAT64 as FLOAT, BOOL as BOOLEAN. NUMERIC,
# TIMESTAMP, DATE and STRING happen to be spelled identically, which makes this a nasty bug --
# the first version of this script matched only standard names, so decimals and timestamps
# compared correctly while every integer column silently fell through to a min..max comparison
# and "failed" against a sum. Both spellings are accepted rather than one canonicalised, because
# which one the API returns is not something to rely on.
NUMERIC_BQ = {"INT64", "INTEGER", "NUMERIC", "BIGNUMERIC", "FLOAT64", "FLOAT"}


def render_agg(bq_type, col):
    """BigQuery SQL producing the same text the Snowflake baseline recorded."""
    q = "`{}`".format(col)
    if bq_type in NUMERIC_BQ:
        return "cast(sum({}) as string)".format(q)
    if bq_type == "TIMESTAMP":
        fmt = "format_timestamp('%Y-%m-%d %H:%M:%E3S', {}, 'UTC')"
        return "concat({}, '..', {})".format(fmt.format("min({})".format(q)),
                                             fmt.format("max({})".format(q)))
    if bq_type == "DATETIME":
        fmt = "format_datetime('%Y-%m-%d %H:%M:%E3S', {})"
        return "concat({}, '..', {})".format(fmt.format("min({})".format(q)),
                                             fmt.format("max({})".format(q)))
    # DATE, STRING, BOOL: Snowflake's to_varchar and BigQuery's cast agree.
    return "concat(cast(min({}) as string), '..', cast(max({}) as string))".format(q, q)


def same_number(a, b):
    """Decimal equality, so 0.2775 == 0.277500 and scale differences are not failures."""
    try:
        return Decimal(a) == Decimal(b)
    except (InvalidOperation, ValueError, TypeError):
        return False


def same_agg(expected, actual, sf_type):
    if expected == actual:
        return True
    if sf_type in NUMERIC_SF:
        return same_number(expected, actual)
    # A min..max pair of decimals, e.g. dates are strings but numerics could be ranged.
    if ".." in expected and ".." in actual:
        e_lo, _, e_hi = expected.partition("..")
        a_lo, _, a_hi = actual.partition("..")
        if sf_type in NUMERIC_SF:
            return same_number(e_lo, a_lo) and same_number(e_hi, a_hi)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--database", nargs="*", help="limit to these Snowflake databases")
    ap.add_argument("--verbose", action="store_true", help="print matching columns too")
    args = ap.parse_args()

    client, source = bq_creds.client()
    print("project   : {}".format(client.project))
    print("credential: {}".format(source))
    print("baseline  : {}\n".format(os.path.basename(BASELINE)))

    with open(BASELINE, newline="", encoding="utf-8") as fh:
        baseline = list(csv.DictReader(fh))
    if args.database:
        wanted = {d.upper() for d in args.database}
        baseline = [r for r in baseline if r["database"].upper() in wanted]

    # Group the baseline by object, preserving column order.
    objects = {}
    for r in baseline:
        objects.setdefault((r["database"], r["schema"], r["table"]), []).append(r)

    # What actually exists in BigQuery, and with what types.
    live = {}
    for dataset in sorted(set(DATASET.values())):
        try:
            for t in client.list_tables("{}.{}".format(client.project, dataset)):
                tbl = client.get_table(t.reference)
                live[(dataset, t.table_id)] = {f.name: f.field_type for f in tbl.schema}
        except gexc.NotFound:
            continue

    checked = matched = 0
    problems, notbuilt = [], []

    for (db, schema, table), cols in sorted(objects.items()):
        dataset = DATASET.get((db, schema))
        if dataset is None:
            problems.append("{}.{}.{}: no dataset mapping".format(db, schema, table))
            continue
        key = (dataset, table.lower())
        if key not in live:
            notbuilt.append("{}.{} (from {}.{}.{})".format(dataset, table.lower(),
                                                           db, schema, table))
            continue

        bq_cols = live[key]
        fq = "`{}.{}.{}`".format(client.project, dataset, table.lower())

        # Column presence, before any aggregate: a missing column is a different failure from
        # a wrong value, and reporting it as a value mismatch would be misleading.
        missing = [c["column"] for c in cols if c["column"].lower() not in bq_cols]
        if missing:
            problems.append("{}.{}: columns missing in BigQuery: {}".format(
                dataset, table.lower(), ", ".join(sorted(missing))))
            continue
        extra = sorted(set(bq_cols) - {c["column"].lower() for c in cols})

        selects = ["count(*)"]
        for c in cols:
            col = c["column"].lower()
            bq_type = bq_cols[col]
            selects += ["count(`{}`)".format(col),
                        "count(distinct `{}`)".format(col),
                        render_agg(bq_type, col)]
        try:
            vals = list(client.query("select {} from {}".format(
                ", ".join(selects), fq)).result())[0]
        except gexc.GoogleAPIError as exc:
            problems.append("{}.{}: query failed: {}".format(
                dataset, table.lower(), str(exc).splitlines()[0]))
            continue

        obj_problems = []
        n_rows = vals[0]
        if str(n_rows) != cols[0]["n_rows"]:
            obj_problems.append("  n_rows: BigQuery {} vs Snowflake {}".format(
                n_rows, cols[0]["n_rows"]))

        for i, c in enumerate(cols):
            col = c["column"].lower()
            nn, nd, agg = vals[1 + i * 3], vals[2 + i * 3], vals[3 + i * 3]
            checked += 1
            issues = []
            if str(nn) != c["n_nonnull"]:
                issues.append("n_nonnull {} vs {}".format(nn, c["n_nonnull"]))
            if str(nd) != c["n_distinct"]:
                issues.append("n_distinct {} vs {}".format(nd, c["n_distinct"]))
            actual = "" if agg is None else str(agg)
            if not same_agg(c["agg"], actual, c["data_type"]):
                issues.append("agg {!r} vs {!r}".format(actual, c["agg"]))
            if issues:
                obj_problems.append("  {}: {}".format(col, "; ".join(issues)))
            else:
                matched += 1
                if args.verbose:
                    print("    ok  {}.{}.{}".format(dataset, table.lower(), col))

        status = "FAIL" if obj_problems else "PASS"
        print("  {}  {:<40} {:>5} rows x {:>2} cols".format(
            status, "{}.{}".format(dataset, table.lower()), n_rows, len(cols)))
        for line in obj_problems:
            print("  " + line)
        if extra:
            print("    note: extra columns in BigQuery, not in baseline: {}".format(
                ", ".join(extra)))
        if obj_problems:
            problems.append("{}.{}: {} column issue(s)".format(
                dataset, table.lower(), len(obj_problems)))

    if notbuilt:
        print("\nNot built in BigQuery yet ({}):".format(len(notbuilt)))
        for n in notbuilt:
            print("  - {}".format(n))
        print("  (expected before Phase 3 for derived models; Phase 6 for snapshots)")

    print("\n{}/{} columns match across {} objects. {} problems.".format(
        matched, checked, len(objects) - len(notbuilt), len(problems)))
    if problems:
        print("\nParity NOT clean:")
        for p in problems:
            print("  - {}".format(p))
        sys.exit(1)
    print("Parity clean for every object present.")


if __name__ == "__main__":
    main()
