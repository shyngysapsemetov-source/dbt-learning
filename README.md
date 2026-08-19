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
| 2 | Materialization Fundamentals | 🟢 Complete | [notes](notes/02-materialization-fundamentals.md) |
| 3 | Jinja, Macros & Packages | ⚪ Not started | [notes](notes/03-jinja-macros-packages.md) |
| 4 | Advanced Testing | ⚪ Not started | [notes](notes/04-advanced-testing.md) |
| 5 | Refactoring SQL for Modularity | 🟢 Complete | [notes](notes/05-refactoring-sql-for-modularity.md) |
| 6 | Analyses, Seeds & Snapshots | ⚪ Not started | [notes](notes/06-analyses-seeds-snapshots.md) |
| 7 | Advanced Materializations | ⚪ Not started | [notes](notes/07-advanced-materializations.md) |
| 8 | Certification exam prep | ⚪ Not started | [notes](notes/08-exam-prep.md) |

Legend: ⚪ not started · 🟡 in progress · 🟢 complete

## What's in here

```
models/
  staging/    stg_* — 1:1 with source tables, renaming and casting only
  marts/      dim_* / fct_* — business-facing, tested and documented
  legacy/     pre-refactor queries, kept as audit baselines
functions/    SQL UDFs, callable with {{ function('name') }}
analysis/     compiled but never run — audit queries to paste into Snowflake
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
| `fct_orders` | marts/dbt_fundamentals | table | Order fact: payment totals per order, plus customer order sequencing and running lifetime value |
| `dim_customers` | marts/dbt_fundamentals | table | Customer dimension: order dates, order count, lifetime value |
| `fct_customer_orders` | marts/refactoring_sql | table | Orders enriched with customer attributes — the modular replacement for the legacy query |
| `customer_orders_legacy` | legacy | table | The pre-refactor query, untouched, as the baseline the audit analyses compare against |

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
dbt show --inline "select ..."   # ad-hoc query against the warehouse
dbt compile --select audit_all_columns    # render an audit query for pasting into Snowflake
dbt compile --write-catalog      # Fusion: write target/catalog.json, then open the dbt Core index.html viewer
```
