#!/usr/bin/env python
"""Capture a warehouse-portable fingerprint of every relevant object.

Why this exists: the Snowflake trial expires ~2026-09-04 and the migration plan's
Phase 7 called for comparing Snowflake against BigQuery side by side. There is not
enough time left for that — GCP is not provisioned yet. So the reference side is
recorded *now* as a data artifact, and Phase 7 becomes "diff BigQuery against the
recording" instead of "diff two live warehouses". That turns a deadline into a file.

Only portable aggregates are used, so the same numbers are computable on BigQuery
with identical semantics: count(*), count(col), count(distinct col), sum(numeric),
min/max rendered as strings.

Usage (needs ~/.dbt/sf_query.py for credential loading, which is outside the repo):
    python _migration/make_fingerprint.py -o _migration/PARITY-BASELINE.csv

Known limits, both deliberate:
  * TEXT min/max depend on collation, which is not guaranteed identical between
    warehouses. Treat a text min/max mismatch as a question, not a failure.
  * FLOAT sums are order-dependent. Nothing here is FLOAT today; if that changes,
    compare rounded.
"""

import argparse
import csv
import importlib.util
import os
import sys

HELPER = os.path.expanduser("~/.dbt/sf_query.py")

# Deliberately excludes ANALYTICS.PUBLIC: stale pre-rename copies of five models,
# recorded as droppable. Fingerprinting them would invite "restoring" them.
SCOPE = [
    ("ANALYTICS", ("DBT_LEARNING", "DBT_LEARNING_SNAPSHOTS", "PROD", "PROD_SNAPSHOTS", "MESH_DEV")),
    ("RAW", ("JAFFLE_SHOP", "STRIPE")),
    ("RAW_MESH", ("JAFFLE_SHOP",)),
]

NUMERIC = {"NUMBER", "DECIMAL", "INT", "INTEGER", "BIGINT", "SMALLINT", "FLOAT", "DOUBLE", "REAL"}
TEMPORAL = {"DATE", "TIME", "TIMESTAMP_NTZ", "TIMESTAMP_LTZ", "TIMESTAMP_TZ", "DATETIME", "TIMESTAMP"}


def load_helper():
    spec = importlib.util.spec_from_file_location("sf_query", HELPER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def agg_expr(col, dtype):
    """A single portable summary value per column, rendered as text."""
    q = '"{}"'.format(col)
    if dtype in NUMERIC:
        return "to_varchar(sum({}))".format(q)
    if dtype in TEMPORAL:
        return "to_varchar(min({}))||'..'||to_varchar(max({}))".format(q, q)
    return "to_varchar(min({}))||'..'||to_varchar(max({}))".format(q, q)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out", required=True)
    args = ap.parse_args()

    sf = load_helper()
    target = sf.load_target("default", None)
    conn = sf.connect(target)
    cur = conn.cursor()

    # 1. Metadata sweep.
    columns = {}
    for db, schemas in SCOPE:
        in_list = ", ".join("'{}'".format(s) for s in schemas)
        # full_type carries precision/scale/length, which plain data_type drops —
        # and type divergence is the single most likely BigQuery difference.
        cur.execute(
            "select table_schema, table_name, column_name, data_type, table_catalog, "
            "  data_type || coalesce('(' || numeric_precision || ',' || numeric_scale || ')', "
            "                        '(' || character_maximum_length || ')', '') as full_type "
            "from {}.information_schema.columns "
            "where table_schema in ({}) order by table_schema, table_name, ordinal_position"
            .format(db, in_list)
        )
        for schema, table, col, dtype, catalog, full_type in cur.fetchall():
            columns.setdefault((catalog, schema, table), []).append((col, dtype, full_type))

    # 2. One wide scan per object, unpivoted in Python.
    rows = []
    for (db, schema, table), cols in sorted(columns.items()):
        fqn = '{}."{}"."{}"'.format(db, schema, table)
        selects = ["count(*)"]
        for col, dtype, _full in cols:
            q = '"{}"'.format(col)
            selects += ["count({})".format(q), "count(distinct {})".format(q), agg_expr(col, dtype)]
        try:
            cur.execute("select {} from {}".format(", ".join(selects), fqn))
            vals = cur.fetchone()
        except Exception as exc:                                  # noqa: BLE001
            print("  !! {}: {}".format(fqn, str(exc).splitlines()[0]), file=sys.stderr)
            continue
        n_rows = vals[0]
        for i, (col, dtype, full_type) in enumerate(cols):
            nn, nd, agg = vals[1 + i * 3], vals[2 + i * 3], vals[3 + i * 3]
            rows.append({
                "database": db, "schema": schema, "table": table,
                "column": col, "data_type": dtype, "full_type": full_type,
                "n_rows": n_rows,
                "n_nonnull": nn, "n_distinct": nd,
                "agg": "" if agg is None else str(agg),
            })
        print("  {:<52} {:>6} rows x {:>2} cols".format(
            "{}.{}".format(schema, table), n_rows, len(cols)), file=sys.stderr)

    conn.close()

    fields = ["database", "schema", "table", "column", "data_type", "full_type",
              "n_rows", "n_nonnull", "n_distinct", "agg"]
    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    objs = len({(r["schema"], r["table"]) for r in rows})
    print("\n{} objects, {} column rows -> {}".format(objs, len(rows), args.out), file=sys.stderr)


if __name__ == "__main__":
    main()
