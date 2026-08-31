#!/usr/bin/env python
"""Typed row-level export of every derived object: Parquet + an explicit type contract.

Why this exists on top of `export_derived.py`: CSV carries no types. Every value in those
files is a string produced by `sf_query.render()`, so `12.50` and `12.5` are different bytes
for the same NUMBER(38,2), and a Phase 7 row diff has to re-guess the type of every column
before it can compare anything. That re-guessing is the whole problem the parity work is
supposed to eliminate.

Parquet fixes it at the source. It is columnar, self-describing and typed: a Snowflake
NUMBER(38,2) lands as Arrow `decimal128(38, 2)` and is stored as a fixed-length byte array
with precision and scale in the file's own schema. Nothing is ever rendered to text, so
nothing has to be parsed back.

The important framing: Parquet's type system is a *third* type system, not Snowflake's and
not BigQuery's. That is exactly what makes it useful — it is a defined, portable contract
sitting between the two, rather than "whatever str() happened to do on the source side".
It is also the real-world answer: `COPY INTO @stage FILE_FORMAT=(TYPE=PARQUET)` on one side
and an external/native table on the other is how warehouse migrations actually move a
reference dataset, because both engines can then read the same bytes.

Two artifacts are written:
  * <schema>__<table>.parquet  - the rows, typed
  * SCHEMA.csv                 - the type contract: Snowflake's declared type (with
                                 precision/scale/length) beside the Arrow type it mapped to
                                 and the Parquet physical type it was stored as. This is the
                                 translation table Phase 7 compares BigQuery against, and it
                                 is the thing a CSV export cannot give you at all.

Usage (needs ~/.dbt/sf_query.py for credential loading, which lives outside the repo):
    python _migration/export_derived_parquet.py -o _migration/snowflake-export-derived-20260831/parquet

Deliberate choices:
  * Rows are sorted inside Arrow on every column, ascending, nulls last — deterministic file
    bytes, so sha256 is meaningful and a re-export is reproducible. Unlike the CSV exporter
    this sorts on *typed* values, so numeric order is numeric rather than lexicographic.
  * Compression is snappy, not gzip: the point is a reference artifact that reads fast and
    diffs reproducibly, and snappy is the format default most readers assume.
  * ANALYTICS.PUBLIC excluded and both ORDERS_SNAPSHOT tables skipped, matching
    make_fingerprint.py and export_derived.py.
"""

import argparse
import csv
import hashlib
import importlib.util
import os
import sys

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

HELPER = os.path.expanduser("~/.dbt/sf_query.py")

SCHEMAS = ("DBT_LEARNING", "PROD", "MESH_DEV")
SKIP = {("DBT_LEARNING_SNAPSHOTS", "ORDERS_SNAPSHOT"), ("PROD_SNAPSHOTS", "ORDERS_SNAPSHOT")}


def load_helper():
    spec = importlib.util.spec_from_file_location("sf_query", HELPER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def connect_exact(sf):
    """Connect with arrow_number_to_decimal=True.

    This matters more than it looks. The connector's default is False, which converts any
    fixed-point NUMBER with a non-zero scale to a float64 on the way into Arrow. A first
    version of this script used the default and silently wrote NUMBER(38,2) columns as
    DOUBLE — the exact precision loss Parquet was chosen to prevent. Casting after the fact
    cannot repair it, because by then 0.1 is already the nearest binary double. The flag has
    to be set before the fetch.
    """
    import snowflake.connector
    t = sf.load_target("default", None)
    kwargs = dict(
        account=t["account"], user=t["user"], role=t.get("role"),
        warehouse=t.get("warehouse"), database=t.get("database"), schema=t.get("schema"),
        arrow_number_to_decimal=True,
    )
    if t.get("private_key_path"):
        kwargs["private_key"] = sf.private_key_bytes(t["private_key_path"])
    elif t.get("password"):
        kwargs["password"] = t["password"]
    else:
        sys.exit("target has neither private_key_path nor password")
    return snowflake.connector.connect(**{k: v for k, v in kwargs.items() if v})


def snowflake_types(cur):
    """Declared type per column, with precision/scale/length — the contract to cast to."""
    in_list = ", ".join("'{}'".format(s) for s in SCHEMAS)
    cur.execute(
        "select table_schema, table_name, column_name, data_type, "
        "  numeric_precision, numeric_scale, character_maximum_length, is_nullable, "
        "  data_type || coalesce('(' || numeric_precision || ',' || numeric_scale || ')', "
        "                        '(' || character_maximum_length || ')', '') as full_type "
        "from analytics.information_schema.columns "
        "where table_schema in ({}) order by table_schema, table_name, ordinal_position"
        .format(in_list)
    )
    out = {}
    for schema, table, col, dtype, prec, scale, clen, nullable, full_type in cur.fetchall():
        out[(schema, table, col)] = {
            "data_type": dtype, "precision": prec, "scale": scale,
            "full_type": full_type, "nullable": nullable,
        }
    return out


def target_arrow_type(meta):
    """Arrow type this column *should* be, derived from Snowflake's declaration.

    Never from the driver's inference, which narrows to whatever the observed values happen
    to fit — it turned NUMBER(38,0) into int8 because no customer_id exceeded 127. That is
    fine as data and wrong as a contract: it encodes this snapshot's values, not the column.

    Two judgment calls, both deliberate:

    * scale == 0 maps to int64, not decimal128(p, 0). The declared NUMBER(38,0) cannot fit
      in int64 in principle, but INT64 is what the *BigQuery* side of these models will
      actually produce, and matching the destination is what makes the Phase 7 diff
      apples-to-apples. Snowflake's true declared type is preserved separately in SCHEMA.csv
      and in PARITY-BASELINE, so nothing is lost by not encoding it here. Overflow is
      asserted against rather than assumed: p > 18 falls back to decimal128.
    * TIMESTAMP_* maps to microseconds, matching BigQuery's DATETIME/TIMESTAMP resolution
      rather than Snowflake's nanosecond default. Lossless for this data (millisecond
      precision at most) and verified as such by the value round-trip against the CSVs.
    """
    dtype, prec, scale = meta["data_type"], meta["precision"], meta["scale"]
    if dtype in ("NUMBER", "DECIMAL", "NUMERIC"):
        if scale and int(scale) > 0:
            return pa.decimal128(int(prec), int(scale))
        return pa.int64() if int(prec or 0) <= 18 else pa.decimal128(int(prec), 0)
    if dtype == "FLOAT":
        return pa.float64()
    if dtype == "BOOLEAN":
        return pa.bool_()
    if dtype == "DATE":
        return pa.date32()
    if dtype.startswith("TIMESTAMP") or dtype == "DATETIME":
        return pa.timestamp("us")
    if dtype == "TIME":
        return pa.time64("us")
    return pa.string()


def sort_table(tbl):
    """Deterministic row order on typed values, so the file bytes are reproducible."""
    if tbl.num_rows == 0 or tbl.num_columns == 0:
        return tbl
    # null_placement is left at its "at_end" default: passing it explicitly is deprecated
    # as of pyarrow 25 in favour of per-sort-key placement, and the default is what we want.
    keys = [(name, "ascending") for name in tbl.column_names]
    try:
        idx = pc.sort_indices(tbl, sort_keys=keys)
    except pa.ArrowNotImplementedError:
        return tbl                      # unsortable type present; leave source order
    return tbl.take(idx)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out", required=True)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    sf = load_helper()
    conn = connect_exact(sf)
    cur = conn.cursor()

    declared = snowflake_types(cur)

    in_list = ", ".join("'{}'".format(s) for s in SCHEMAS)
    cur.execute(
        "select table_schema, table_name, table_type from analytics.information_schema.tables "
        "where table_schema in ({}) order by table_schema, table_name".format(in_list)
    )
    objects = [(s, t, ty) for s, t, ty in cur.fetchall() if (s, t) not in SKIP]

    manifest, schema_rows = [], []
    for schema, table, table_type in objects:
        fqn = 'ANALYTICS."{}"."{}"'.format(schema, table)
        try:
            cur.execute("select * from {}".format(fqn))
            tbl = cur.fetch_arrow_all()
            if tbl is None:                                   # empty result set
                names = [d[0] for d in cur.description]
                tbl = pa.table({n: pa.array([], type=pa.string()) for n in names})
        except Exception as exc:                              # noqa: BLE001
            print("  !! {}: {}".format(fqn, str(exc).splitlines()[0]), file=sys.stderr)
            continue

        tbl = tbl.rename_columns([c.lower() for c in tbl.column_names])

        # Cast to the asserted contract. `safe=True` is the point: pyarrow raises rather than
        # silently truncating, so a mapping that would lose data fails loudly here instead of
        # producing a plausible-looking reference file.
        fields, drivers = [], {}
        for field in tbl.schema:
            meta = declared.get((schema, table, field.name.upper()))
            drivers[field.name] = str(field.type)
            fields.append(pa.field(field.name,
                                   target_arrow_type(meta) if meta else field.type))
        try:
            tbl = tbl.cast(pa.schema(fields))
        except (pa.ArrowInvalid, pa.ArrowNotImplementedError) as exc:
            print("  !! {} cast: {}".format(fqn, str(exc).splitlines()[0]), file=sys.stderr)
            continue

        tbl = sort_table(tbl)

        name = "{}__{}.parquet".format(schema.lower(), table.lower())
        path = os.path.join(args.out, name)
        pq.write_table(tbl, path, compression="snappy")

        pf = pq.ParquetFile(path)
        parquet_phys = {c: pf.schema.column(i).physical_type
                        for i, c in enumerate(pf.schema.names)}

        for i, field in enumerate(tbl.schema):
            meta = declared.get((schema, table, field.name.upper()), {})
            schema_rows.append({
                "schema": schema.lower(), "table": table.lower(),
                "ordinal": i + 1, "column": field.name,
                "snowflake_type": meta.get("full_type", "(unknown)"),
                "snowflake_nullable": meta.get("nullable", ""),
                "driver_arrow_type": drivers.get(field.name, ""),
                "arrow_type": str(field.type),
                "parquet_physical_type": parquet_phys.get(field.name, ""),
            })

        with open(path, "rb") as fh:
            digest = hashlib.sha256(fh.read()).hexdigest()

        manifest.append({
            "schema": schema.lower(), "table": table.lower(),
            "table_type": "view" if table_type == "VIEW" else "table",
            "n_rows": tbl.num_rows, "n_cols": tbl.num_columns,
            "file": name, "bytes": os.path.getsize(path), "sha256": digest,
        })
        print("  {:<44} {:>6} rows x {:>2} cols  {:>7} B".format(
            "{}.{}".format(schema.lower(), table.lower()),
            tbl.num_rows, tbl.num_columns, os.path.getsize(path)), file=sys.stderr)

    conn.close()

    with open(os.path.join(args.out, "MANIFEST.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, lineterminator="\n", fieldnames=[
            "schema", "table", "table_type", "n_rows", "n_cols", "file", "bytes", "sha256"])
        w.writeheader()
        w.writerows(manifest)

    with open(os.path.join(args.out, "SCHEMA.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, lineterminator="\n", fieldnames=[
            "schema", "table", "ordinal", "column", "snowflake_type", "snowflake_nullable",
            "driver_arrow_type", "arrow_type", "parquet_physical_type"])
        w.writeheader()
        w.writerows(schema_rows)

    print("\n{} objects, {} rows, {} column definitions, {:.0f} KiB total".format(
        len(manifest), sum(m["n_rows"] for m in manifest), len(schema_rows),
        sum(m["bytes"] for m in manifest) / 1024), file=sys.stderr)


if __name__ == "__main__":
    main()
