# Parity baseline — Snowflake, captured 2026-08-31

`PARITY-BASELINE-20260831.csv` — 49 objects, 306 column rows. Produced by
`make_fingerprint.py` against the live trial account.

## Why this replaces migration Phase 7

Phase 7 originally said: keep Snowflake targets in `profiles.yml`, migrate, then compare the
two warehouses side by side while the trial is still alive. **That plan died when the trial
window shrank to one day.** GCP is not provisioned yet, and Phases 1–3 are ~3.5 hours of work
before a single BigQuery model exists to compare against.

So the reference side was recorded instead. Phase 7 is now **"diff BigQuery against this
file"**, which can happen calmly next week. The deadline became an artifact.

## What is in it

One row per column, per object, in `ANALYTICS.{DBT_LEARNING, DBT_LEARNING_SNAPSHOTS, PROD,
PROD_SNAPSHOTS, MESH_DEV}`, `RAW.{JAFFLE_SHOP, STRIPE}` and `RAW_MESH.JAFFLE_SHOP`:

| Field | Meaning |
|---|---|
| `full_type` | `data_type` plus precision/scale/length — plain `data_type` drops these, and type divergence is the most likely BigQuery difference |
| `n_rows` | `count(*)` for the object |
| `n_nonnull` | `count(col)` — catches NULL-handling changes |
| `n_distinct` | `count(distinct col)` — catches silent fan-out from a bad join |
| `agg` | `sum()` for numerics, `min..max` for everything else |

Only aggregates with identical semantics on BigQuery were used, deliberately. No `HASH_AGG`,
no `md5` over concatenated rows: both are warehouse-specific and would produce a fingerprint
that is impossible to reproduce on the other side — a check that can only ever fail is worse
than no check.

`ANALYTICS.PUBLIC` is **excluded** — stale pre-rename copies of five models, already recorded
as droppable. Including them would invite someone to "restore" them on BigQuery.

## Two things this already established, while Snowflake was alive to ask

**1. Dev and prod are identical. Zero drift.** All 12 objects in `DBT_LEARNING` and `PROD`
match on every field — same columns, same types, same row counts, same aggregates. Nothing to
reconcile at migration time.

**2. The `NUMBER(38,6)` production worry is closed on evidence.**
`PROD.INT_ORDER_PAYMENTS.TOTAL_ORDER_AMOUNT` is `NUMBER(38,2)`, matching dev exactly. The
suspicion recorded in `snowflake-export-20260829/README.md` — that prod might still hold
`NUMBER(38,6)` from an unconfirmed restatement, and might have been failing the 06:00 job
since 2026-08-25 — was wrong. The job was healthy and the type is right.

## One observation, deliberately not changed

`CUSTOMER_ORDERS_LEGACY.RUNNING_CLV` and `.TOTAL_AMOUNT_PAID` are `NUMBER(38,6)`, while the
refactored `FCT_CUSTOMER_ORDERS` equivalents are `NUMBER(38,2)`. The legacy model is course 2's
un-refactored original, so a type difference between the pair is expected rather than broken —
values compare equal numerically (`1696.00` = `1696.000000`), which is why `audit_helper`
passes. **This is course content and was left alone.** Worth knowing before BigQuery, where
`NUMERIC` is fixed at precision 38 / scale 9 and this distinction simply disappears.

## How to use it at Phase 7

Run the equivalent aggregates on BigQuery, join on
`(schema, table, column)` after lowercasing, and diff. Expect and accept:

- **`full_type` will differ everywhere.** `NUMBER(38,0)` → `INT64`, `NUMBER(38,2)` →
  `NUMERIC`, `TEXT(n)` → `STRING`, `TIMESTAMP_NTZ` → `DATETIME` (or `TIMESTAMP`). Compare
  *type families*, not strings.
- **Text `min`/`max` depend on collation**, which is not guaranteed identical between
  warehouses. Treat a mismatch there as a question, not a failure.
- **`n_rows`, `n_nonnull`, `n_distinct` and numeric `sum` must match exactly.** These are the
  real check. A `sum` that differs in the last decimal is a scale problem; a `n_distinct` that
  differs is a join fan-out.
- The snapshot tables will differ by design — see the migration plan's Phase 6 on the
  `dbt_scd_id` hash, which is expected to add one cosmetic version row per order.

## Reproducing

Needs `~/.dbt/sf_query.py` (outside every repo, since its job is reading credentials) plus
`snowflake-connector-python` and `pyyaml`, both installed 2026-08-31. Once the trial lapses
this is no longer reproducible — which is the entire point of having committed the output.
