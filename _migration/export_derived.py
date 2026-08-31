#!/usr/bin/env python
"""Row-level export of every *derived* object, so Phase 7 can diff rows, not just aggregates.

Why this exists: `make_fingerprint.py` captured portable aggregates for 49 objects because
the trial looked like it had hours left. Aggregates are diagnostic but lossy — they cannot
catch a compensating error (two rows swapping a value keeps count, nonnull, distinct and sum
all identical), and they leave TEXT/TIMESTAMP columns thinly covered, since those get only
min..max plus n_distinct rather than a sum.

The raw sources were already exported row-for-row on 2026-08-29. The derived layer was not,
and there is no technical reason it could not be: staging views, intermediates and marts are
materialized (or queryable) in Snowflake exactly like the raw tables. This closes that gap
while the account is still reachable.

With this file, Phase 7 gains a second, stronger check: for any BigQuery object whose
aggregates disagree with PARITY-BASELINE, the exact Snowflake rows are on disk to diff
against — so a mismatch localises to a row, not just a column, and you can see which side
is wrong instead of only that they differ.

Usage (needs ~/.dbt/sf_query.py for credential loading, which lives outside the repo):
    python _migration/export_derived.py -o _migration/snowflake-export-derived-20260831

Deliberate choices:
  * Rows are sorted in PYTHON, on the rendered string tuple, not by a SQL `order by`.
    A SQL sort on a text column is collation-dependent, so Snowflake and BigQuery can
    legitimately order the same rows differently and a line-by-line diff would misalign
    on data that matches. Sorting both sides identically in Python removes that variable.
  * Headers are lowercased, matching landmine 1 in the migration plan: Snowflake stores
    unquoted identifiers uppercase, BigQuery is case-sensitive, and every model selects
    lowercase.
  * Values are rendered by sf_query.render(), the same function that produced the raw
    CSVs — ISO timestamps (so the 9999-12-31 sentinel survives) and plain-format Decimals
    (so 12.50 does not become 1.25E+1).
  * ANALYTICS.PUBLIC is excluded, same as make_fingerprint.py: stale pre-rename copies,
    recorded as droppable. Exporting them would invite "restoring" them.
  * Both ORDERS_SNAPSHOT tables are skipped — already exported 2026-08-29/31 and they are
    Phase 6 inputs, not Phase 7 reference data.
"""

import argparse
import csv
import hashlib
import importlib.util
import os
import sys

HELPER = os.path.expanduser("~/.dbt/sf_query.py")

SCHEMAS = ("DBT_LEARNING", "PROD", "MESH_DEV")

# Already exported row-for-row; they are Phase 6 restore inputs, not Phase 7 reference.
SKIP = {("DBT_LEARNING_SNAPSHOTS", "ORDERS_SNAPSHOT"), ("PROD_SNAPSHOTS", "ORDERS_SNAPSHOT")}


def load_helper():
    spec = importlib.util.spec_from_file_location("sf_query", HELPER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out", required=True, help="output directory")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)

    sf = load_helper()
    conn = sf.connect(sf.load_target("default", None))
    cur = conn.cursor()

    in_list = ", ".join("'{}'".format(s) for s in SCHEMAS)
    cur.execute(
        "select table_schema, table_name, table_type from analytics.information_schema.tables "
        "where table_schema in ({}) order by table_schema, table_name".format(in_list)
    )
    objects = [(s, t, ty) for s, t, ty in cur.fetchall() if (s, t) not in SKIP]

    manifest = []
    for schema, table, table_type in objects:
        fqn = 'ANALYTICS."{}"."{}"'.format(schema, table)
        try:
            cur.execute("select * from {}".format(fqn))
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
        except Exception as exc:                                    # noqa: BLE001
            print("  !! {}: {}".format(fqn, str(exc).splitlines()[0]), file=sys.stderr)
            continue

        rendered = sorted(tuple(sf.render(v) for v in r) for r in rows)

        name = "{}__{}.csv".format(schema.lower(), table.lower())
        path = os.path.join(args.out, name)
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh, lineterminator="\n")
            w.writerow([c.lower() for c in cols])
            w.writerows(rendered)

        with open(path, "rb") as fh:
            digest = hashlib.sha256(fh.read()).hexdigest()

        manifest.append({
            "schema": schema.lower(), "table": table.lower(),
            "table_type": "view" if table_type == "VIEW" else "table",
            "n_rows": len(rendered), "n_cols": len(cols),
            "file": name, "sha256": digest,
        })
        print("  {:<44} {:>6} rows x {:>2} cols  -> {}".format(
            "{}.{}".format(schema.lower(), table.lower()), len(rendered), len(cols), name),
            file=sys.stderr)

    conn.close()

    mpath = os.path.join(args.out, "MANIFEST.csv")
    fields = ["schema", "table", "table_type", "n_rows", "n_cols", "file", "sha256"]
    with open(mpath, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(manifest)

    total = sum(m["n_rows"] for m in manifest)
    print("\n{} objects, {} rows -> {}".format(len(manifest), total, args.out), file=sys.stderr)


if __name__ == "__main__":
    main()
