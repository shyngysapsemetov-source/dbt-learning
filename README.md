# dbt Learning — Certified Developer Path

Hands-on work from the dbt Labs certification path, built on Snowflake with dbt Fusion.
Every practical exercise is committed here, so the history doubles as a learning log.

**Started:** August 2026
**Warehouse:** Snowflake
**dbt version:** Fusion 2.0
**Project:** `jaffle_shop` (dbt Labs course dataset)

## Progress

| # | Course | Status | Notes |
|---|--------|--------|-------|
| 1 | dbt Fundamentals | 🟢 Complete | [notes](notes/01-dbt-fundamentals.md) |
| 2 | Jinja, Macros & Packages | ⚪ Not started | [notes](notes/02-jinja-macros-packages.md) |
| 3 | Advanced Testing | ⚪ Not started | [notes](notes/03-advanced-testing.md) |
| 4 | Refactoring SQL for Modularity | ⚪ Not started | [notes](notes/04-refactoring-sql-for-modularity.md) |
| 5 | Analyses, Seeds & Snapshots | ⚪ Not started | [notes](notes/05-analyses-seeds-snapshots.md) |
| 6 | Advanced Materializations | ⚪ Not started | [notes](notes/06-advanced-materializations.md) |
| 7 | Certification exam prep | ⚪ Not started | [notes](notes/07-exam-prep.md) |

Legend: ⚪ not started · 🟡 in progress · 🟢 complete

## What's in here

```
models/
  staging/    stg_* — 1:1 with source tables, renaming and casting only
  marts/      dim_* / fct_* — business-facing, tested and documented
seeds/        static CSVs loaded with `dbt seed`
macros/       reusable Jinja
tests/        singular tests
snapshots/    SCD Type 2 captures
notes/        one markdown file per course module
```

Current models:

| Model | Layer | Materialization | Description |
|---|---|---|---|
| `stg_jaffle_shop_customers` | staging | view | Customers from the `jaffle_shop` source, renamed |
| `stg_jaffle_shop_orders` | staging | view | Orders from the `jaffle_shop` source, renamed |
| `stg_stripe_payment` | staging | view | Stripe payments from the `stripe` source, renamed and converted from cents to dollars |
| `fct_orders` | marts/finance | table | Order fact with successful payment amount per order |
| `dim_customers` | marts | table | Customer dimension: order dates, order count, lifetime value |

## Running this locally

Requires a Snowflake account with the `raw.jaffle_shop` course dataset.

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
dbt compile --write-catalog      # Fusion: write target/catalog.json, then open the dbt Core index.html viewer
```
