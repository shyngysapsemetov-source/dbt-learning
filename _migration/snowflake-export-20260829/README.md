# Snowflake export — 2026-08-29

Raw-layer and snapshot data pulled off the trial Snowflake account before it expires
(~2026-09-04), ahead of migrating the estate to **BigQuery**.

Purpose: make the migration a *re-point* rather than a rebuild. Everything below is
either mutated away from the dbt-labs course defaults, or accumulated state that a
fresh warehouse cannot reproduce.

## Why this directory is not `seeds/`

`seed-paths` is `seeds`, so dbt ignores `_migration/` entirely. Putting these CSVs in
`seeds/` would make them dbt seeds and change what courses 8–11 read from — a change to
course content, not to setup. They stay here as migration input; wiring sources to read
from them (if that is even the chosen approach) is a separate, later decision.

## Contents

| File | Source | Rows |
|---|---|---|
| `raw_jaffle_shop__customers.csv` | `raw.jaffle_shop.customers` | 100 |
| `raw_jaffle_shop__orders.csv` | `raw.jaffle_shop.orders` | 104 |
| `raw_stripe__payment.csv` | `raw.stripe.payment` | 122 |
| `rawmesh_jaffle_shop__customers.csv` | `raw_mesh.jaffle_shop.customers` | 939 |
| `rawmesh_jaffle_shop__orders.csv` | `raw_mesh.jaffle_shop.orders` | 899 |
| `rawmesh_jaffle_shop__items.csv` | `raw_mesh.jaffle_shop.items` | 899 |
| `rawmesh_jaffle_shop__stores.csv` | `raw_mesh.jaffle_shop.stores` | 5 |
| `rawmesh_jaffle_shop__products.csv` | `raw_mesh.jaffle_shop.products` | 10 |
| `rawmesh_jaffle_shop__supplies.csv` | `raw_mesh.jaffle_shop.supplies` | 65 |
| `snapshot_orders_snapshot.csv` | `analytics.dbt_learning_snapshots.orders_snapshot` | 108 |
| `prodsnapshot_orders_snapshot.csv` | `analytics.prod_snapshots.orders_snapshot` | 104 |

**3,355 rows total**, all 11 files verified row-for-row against the live tables on 2026-08-31,
zero mismatches. That check also corrected the count: the ten original files sum to **3,251**,
not the 3,241 first written here — an arithmetic slip, not a missing file. Column types in `SOURCE-TYPES.md`, read from `INFORMATION_SCHEMA.COLUMNS`
so the BigQuery rebuild can be faithful rather than CSV-inferred.

## The irreplaceable one

`snapshot_orders_snapshot.csv` is the only file here that is **accumulated state**. The raw
tables can in principle be re-downloaded from dbt-labs course material; the SCD2 history
cannot — it was produced by real snapshot runs over real time. 108 rows: 104 currently-open
plus 4 closed on 2026-08-20.

Its four `TIMESTAMP_NTZ` columns were cast to `varchar` **server-side** before export, on
purpose. `dbt show` renders timestamps as Arrow nanosecond int64, which overflows past
~2262-04-11, so the `dbt_valid_to_current` sentinel `9999-12-31` comes back as
`1816-03-29T05:56:08` if exported natively. Verified in the CSV: the sentinel reads
`9999-12-31`. Any future export of this table must keep the cast.

## Mutations away from course defaults — preserved here, do not "fix"

- `raw.jaffle_shop.orders` — ids 100–104 added 2026-08-20 for the snapshots exercise
  (100–103 `shipped`, 104 `placed`, all dated 2025-02-15). Originally 99 rows.
  `user_id` must stay ≤ 100 or the `relationships` test on
  `stg_jaffle_shop_orders.customer_id` fails — customers are ids 1–100 exactly.
- `raw.stripe.payment` — payments `1001` (order 100, $25) and `1002` (order 1, $15,
  a deliberate late payment) inserted 2026-08-22; payment `33` flipped `success` → `fail`
  so order 25 drops $58 → $42. Originally 120 rows.
- `raw_mesh.jaffle_shop` is deliberately a **separate database** from `raw.jaffle_shop`.
  Both hold `customers` and `orders` with different contents (939/899 vs 100/104). The
  split exists to stop them colliding. BigQuery has one fewer namespace level than
  Snowflake, so this separation needs an explicit decision during migration — it must not
  be flattened into one dataset by accident.

## Not exported

`analytics.prod.*` and `analytics.dbt_learning.*` — both are dbt build output, fully
reproducible from source once the estate runs on BigQuery. Their aggregates *are* recorded, in
`../PARITY-BASELINE-20260831.csv`, so correctness is still checkable after the trial lapses.

**Correction, 2026-08-31:** this section previously suspected
`analytics.prod.int_order_payments` of still holding `NUMBER(38,6)` and of failing the 06:00
job since 2026-08-25. **Both were wrong.** It is `NUMBER(38,2)`, and dev and prod match on
every column, type, row count and aggregate — measured, not assumed. See `../PARITY-BASELINE.md`.

## The prod snapshot holds no unique history

`prodsnapshot_orders_snapshot.csv` was added 2026-08-31 after `analytics.prod_snapshots` turned
up in an information-schema sweep, having been missed entirely by the 2026-08-29 export. All
104 of its rows are **open** (`dbt_valid_to` = the `9999-12-31` sentinel), zero closed: the
production snapshot first ran *after* the 2026-08-20 source mutation, so it never observed a
change. The 4 closed rows in the dev snapshot therefore remain the only irreplaceable SCD2
history in the estate. Exported anyway — it is 104 rows and it is the production state.
