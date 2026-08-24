# dbt Learning — Certified Developer Path

Hands-on work from the dbt Labs certification path, built on Snowflake with dbt Fusion.
Every practical exercise is committed here, so the history doubles as a learning log.

**Started:** August 2026
**Warehouse:** Snowflake
**dbt version:** Fusion 2.0
**Project:** `jaffle_shop` (dbt Labs course dataset)

## Progress

Numbered to match the course order in the official
[dbt Certified Developer learning path](https://learn.getdbt.com/learn/learning-path/dbt-certified-developer).

| # | Course | Status | Notes |
|---|--------|--------|-------|
| 1 | dbt Fundamentals | 🟢 Complete | [notes](notes/01-dbt-fundamentals.md) |
| 2 | Refactoring SQL for Modularity | 🟢 Complete | [notes](notes/02-refactoring-sql-for-modularity.md) |
| 3 | Jinja, Macros, and Packages | ⚪ Not started | [notes](notes/03-jinja-macros-packages.md) |
| 4 | Materialization Fundamentals | 🟢 Complete | [notes](notes/04-materialization-fundamentals.md) |
| 5 | Incremental Models | 🟢 Complete | [notes](notes/05-incremental-models.md) |
| 6 | Snapshots | 🟢 Complete | [notes](notes/06-snapshots.md) |
| 7 | Analyses and Seeds | 🟢 Complete | [notes](notes/07-analyses-and-seeds.md) |
| 8 | Advanced Testing | ⚪ Not started | [notes](notes/08-advanced-testing.md) |
| 9 | Advanced Deployment | ⚪ Not started | [notes](notes/09-advanced-deployment.md) |
| 10 | Exposures | ⚪ Not started | [notes](notes/10-exposures.md) |
| 11 | dbt Mesh | ⚪ Not started | [notes](notes/11-dbt-mesh.md) |
| — | Certification exam | ⚪ Not started | [notes](notes/99-exam-prep.md) |

Standalone videos on the path, outside the numbered courses:

| Video | Status | Notes |
|---|--------|-------|
| Python Models | 🟢 Complete | [notes](notes/videos/python-models.md) |

Legend: ⚪ not started · 🟡 in progress · 🟢 complete

**Remaining:** 5 of 11 courses — Jinja/Macros/Packages, Advanced Testing,
Advanced Deployment, Exposures, dbt Mesh — then the exam.

## What's in here

```
models/
  staging/      stg_* — 1:1 with source tables, renaming and casting only
  intermediate/ int_* — reusable rollups between staging and marts
  marts/        dim_* / fct_* — business-facing, tested and documented
  legacy/      pre-refactor queries, kept as audit baselines
  python_demo/ Python models — .py instead of .sql, run as Snowflake sprocs
functions/     SQL UDFs, callable with {{ function('name') }}
analysis/      compiled but never run — audit queries to paste into Snowflake
seeds/         static CSVs loaded with `dbt seed`
macros/        reusable Jinja
tests/         singular tests
snapshots/     SCD Type 2 captures
notes/         one markdown file per course, numbered to match the path
  videos/      one per standalone video
```

Current models:

| Model | Layer | Materialization | Description |
|---|---|---|---|
| `stg_jaffle_shop_customers` | staging | view | Customers from the `jaffle_shop` source, renamed |
| `stg_jaffle_shop_orders` | staging | view | Orders from the `jaffle_shop` source, renamed |
| `stg_stripe_payment` | staging | view | Stripe payments from the `stripe` source, renamed and converted from cents to dollars |
| `int_order_payments` | intermediate | **incremental** | Non-failed payment totals per order. The only incremental model here — its group key is also its merge key, so a touched order recomputes correctly regardless of batch arrival order |
| `fct_orders` | marts/dbt_fundamentals | table | Order fact: payment totals per order, plus customer order sequencing and running lifetime value. Stays a table — its window columns are customer-partitioned or unpartitioned, so no `order_id`-keyed incremental scheme can keep them correct |
| `dim_customers` | marts/dbt_fundamentals | table | Customer dimension: order dates, order count, lifetime value |
| `fct_customer_orders` | marts/refactoring_sql | table | Orders enriched with customer attributes — the modular replacement for the legacy query |
| `customer_orders_legacy` | legacy | table | The pre-refactor query, untouched, as the baseline the audit analyses compare against |
| `date_spine` | python_demo | view | One row per day across 2024, built with `dbt_utils.date_spine` |
| `is_holiday_2024` | python_demo | table | Python model: the date spine with each day flagged against `holidays.US()` |

Seeds:

| Seed | Description |
|---|---|
| `employees` | Employee emails and the customer account each one orders under |

Snapshots:

| Snapshot | Strategy | Description |
|---|---|---|
| `orders_snapshot` | `check` | SCD Type 2 history of `raw.jaffle_shop.orders`, preserving each order's status transitions that the source overwrites in place |

Materializes to `analytics.dbt_learning_snapshots.orders_snapshot` — a custom
`schema:` is appended to the target schema, not used as an absolute name.

## Running this locally

Requires a Snowflake account with the `raw.jaffle_shop` course dataset.

Note that the source data here has been deliberately mutated by the exercises, so a
fresh copy of the course dataset will not reproduce every result: `raw.jaffle_shop.orders`
gained rows 100–104 for the snapshots course, and `raw.stripe.payment` gained payments
1001–1002 plus a status flip on payment 33 for the incremental-models course. See
`macros/load_payment_batch.sql` for the latter, and `revert_payment_batch` to undo it.

```bash
# 1. Credentials — copy the template to ~/.dbt/profiles.yml and set env vars.
#    profiles.yml is gitignored; no secret belongs in this repo.
#    Auth is key-pair: Snowflake dropped password auth on 2026-08-31.
#    See profiles.yml.example for the one-time openssl + ALTER USER key setup.
cp profiles.yml.example ~/.dbt/profiles.yml

export SNOWFLAKE_ACCOUNT="..."
export SNOWFLAKE_USER="..."
export SNOWFLAKE_PRIVATE_KEY_PATH="$HOME/.dbt/keys/snowflake_dbt_key.p8"
export SNOWFLAKE_PRIVATE_KEY_PASSPHRASE="..."

# 2. Verify the connection
dbt debug

# 3. Build everything
dbt build
```

## Command reference

```bash
dbt debug                        # check profile + warehouse connection
dbt build                        # seed + run + test + snapshot, in DAG order
dbt run --select stg_jaffle_shop_orders+  # a model and everything downstream
dbt test --select dim_customers
dbt show --inline "select ..." --limit 5  # ad-hoc query; SELECT-only, and it appends its own LIMIT
dbt run-operation load_payment_batch      # DML via run_query() — writes to raw, has a revert
dbt compile --select audit_all_columns    # render an audit query for pasting into Snowflake
dbt compile --write-catalog      # Fusion: write target/catalog.json, then open the dbt Core index.html viewer
```
