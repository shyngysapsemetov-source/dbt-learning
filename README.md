# dbt Learning — Certified Developer Path

Hands-on work from the dbt Labs certification path, built on BigQuery with dbt Fusion.
Every practical exercise is committed here, so the history doubles as a learning log.

**Started:** August 2026
**Warehouse:** BigQuery (migrated from Snowflake, September 2026 — see below)
**dbt version:** Fusion 2.0
**Project:** `jaffle_shop` (dbt Labs course dataset)
**Deployment:** dbt Cloud, `dbt build` on cron `0 6 * * *` against the `prod` dataset

## Warehouse migration: Snowflake → BigQuery

The project was built on a Snowflake trial. When that trial turned out to have one day
left rather than six, the whole estate was moved to BigQuery: 8 datasets, 9 raw tables,
22 derived objects in this project plus 10 in the sibling
[dbt-mesh-platform](https://github.com/shyngysapsemetov-source/dbt-mesh-platform) repo,
and an SCD Type 2 snapshot with real history in it.

Full record — plan, findings, and verification — in
[`_migration/BIGQUERY-MIGRATION-PLAN.md`](_migration/BIGQUERY-MIGRATION-PLAN.md). The
parts worth knowing if you read the code:

- **Verification is a committed artifact, not a memory.** The Snowflake side was
  exported twice before the account lapsed — portable aggregates per column
  (`PARITY-BASELINE-20260831.csv`, 49 objects) and then row-for-row
  (`snowflake-export-derived-20260831/`, 40 objects / 11,685 rows), because aggregates
  alone are blind to compensating errors and thin on TEXT/TIMESTAMP columns.
  `_migration/check_parity.py` diffs BigQuery against those files and currently reports
  **274/274 columns across 43 objects, 0 problems**. It is re-runnable; don't trust this
  number, run it.
- **A dialect migration is verified by execution, not by grep.** Grepping for Snowflake
  syntax predicted 4 fixes. There were 14 findings. Most were only findable by running
  something —
  including `date_part`, which was missing from the grep's own pattern list. An
  enumerated denylist of "Snowflake syntax" is only as good as the enumeration.
- **The subtlest bug was silent and passed every test.** `/ 100.0` is `NUMBER(n,1)` on
  Snowflake but a `FLOAT64` literal on BigQuery, so dividing integer cents quietly turned
  money into floating point across 5 files — green build, no failing test, no error. One
  column even passed the parity check by luck, because its 10 values happened to
  round-trip; it was fixed on the mechanism rather than the symptom.
- **One capability was lost, not ported.** Snowflake ran dbt Python models natively on
  Snowpark. BigQuery has no in-warehouse Python — dbt submits the model to Dataproc
  Serverless, which needs a compute region and a staging bucket and isn't free. So
  `is_holiday_2024` is disabled rather than deleted, and `dbt_project.yml` records why.

## Progress

Numbered to match the course order in the official
[dbt Certified Developer learning path](https://learn.getdbt.com/learn/learning-path/dbt-certified-developer).

| # | Course | Status | Notes |
|---|--------|--------|-------|
| 1 | dbt Fundamentals | 🟢 Complete | [notes](notes/01-dbt-fundamentals.md) |
| 2 | Refactoring SQL for Modularity | 🟢 Complete | [notes](notes/02-refactoring-sql-for-modularity.md) |
| 3 | Jinja, Macros, and Packages | 🟢 Complete | [notes](notes/03-jinja-macros-packages.md) |
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

**Remaining:** 4 of 11 courses — Advanced Testing, Advanced Deployment, Exposures,
dbt Mesh — then the exam.

## What's in here

```
models/
  staging/      stg_* — 1:1 with source tables, renaming and casting only
  intermediate/ int_* — reusable rollups between staging and marts
  marts/        dim_* / fct_* — business-facing, tested and documented
  legacy/      pre-refactor queries, kept as audit baselines
  python_demo/ Python models — .py instead of .sql; disabled on BigQuery, see above
functions/     SQL UDFs, callable with {{ function('name') }} — a Fusion feature
analysis/      compiled but never run — audit queries to paste into the warehouse
seeds/         static CSVs loaded with `dbt seed`
macros/        reusable Jinja
tests/         singular tests
snapshots/     SCD Type 2 captures
notes/         one markdown file per course, numbered to match the path
  videos/      one per standalone video
_migration/    the Snowflake → BigQuery move: plan, exports, loaders, parity checker
```

Current models:

| Model | Layer | Materialization | Description |
|---|---|---|---|
| `stg_jaffle_shop_customers` | staging | view | Customers from the `jaffle_shop` source, renamed |
| `stg_jaffle_shop_orders` | staging | view | Orders from the `jaffle_shop` source, renamed |
| `stg_stripe_payment` | staging | view | Stripe payments from the `stripe` source, renamed and converted from cents to dollars |
| `int_order_payments` | intermediate | **incremental** | Non-failed payment totals per order. The only incremental model here — its group key is also its merge key, so a touched order recomputes correctly regardless of batch arrival order |
| `int_orders__pivoted` | intermediate | view | Successful payment amounts as one column per payment method, generated by a Jinja loop over a method list |
| `fct_orders` | marts/dbt_fundamentals | table | Order fact: payment totals per order, plus customer order sequencing and running lifetime value. Stays a table — its window columns are customer-partitioned or unpartitioned, so no `order_id`-keyed incremental scheme can keep them correct |
| `dim_customers` | marts/dbt_fundamentals | table | Customer dimension: order dates, order count, lifetime value |
| `fct_customer_orders` | marts/refactoring_sql | table | Orders enriched with customer attributes — the modular replacement for the legacy query |
| `customer_orders_legacy` | legacy | table | The pre-refactor query, untouched, as the baseline the audit analyses compare against |
| `date_spine` | python_demo | view | One row per day across 2024, built with `dbt_utils.date_spine` |
| `is_holiday_2024` | python_demo | ~~table~~ | Python model: the date spine with each day flagged against `holidays.US()`. **Disabled on BigQuery** — no in-warehouse Python, and paying for Dataproc Serverless to look up US public holidays is the wrong trade. The `.py` file is untouched; removing two lines from `dbt_project.yml` restores it |

Seeds:

| Seed | Description |
|---|---|
| `employees` | Employee emails and the customer account each one orders under |

Snapshots:

| Snapshot | Strategy | Description |
|---|---|---|
| `orders_snapshot` | `check` | SCD Type 2 history of `raw_jaffle_shop.orders`, preserving each order's status transitions that the source overwrites in place |

Materializes to `<project>.dbt_learning_snapshots.orders_snapshot` — a custom `schema:`
is **appended** to the target dataset, not used as an absolute name. That suffixing is
dbt's own `generate_schema_name`, not warehouse behaviour, so it survived the migration
unchanged; getting the target dataset wrong would silently build a second, empty history
somewhere else.

This snapshot is also the one thing in the repo that a rebuild cannot recreate. `dbt
snapshot` builds history *forward* from whatever it finds, so on a fresh warehouse it
emits one open row per order and any past transition is simply gone — the source has
already overwritten it. Its 4 closed rows were restored from the Snowflake export by
`_migration/restore_snapshots.py`.

Macros:

| Macro | Kind | Description |
|---|---|---|
| `cents_to_dollars` | SQL helper | Integer cents → dollars at a fixed scale. Note that the scale is part of its interface — see `notes/05` |
| `grant_select` | `run-operation` | Grants usage + select on the target schema to a role. **Snowflake-only, kept as course work** — `target.role` has no BigQuery equivalent and neither does `grant usage on schema`, where access is IAM. Harmless: nothing invokes it, and Jinja evaluates macro defaults at call time, so it can't break parsing |
| `clean_stale_models` | `run-operation` | Generates `DROP` statements for objects untouched for N days. Defaults to `dry_run=True` — prints, doesn't drop. Portable: BigQuery maps `target.database` to the project |
| `load_payment_batch` / `revert_payment_batch` | `run-operation` | Mutates `raw_stripe.payment` to exercise the incremental model, and undoes it |

## Running this locally

Requires a GCP project with the BigQuery API enabled and the course data loaded into
the `raw_jaffle_shop` and `raw_stripe` datasets. `_migration/` has the loaders and the
source CSVs if you want to reproduce them exactly.

Note that the source data here has been deliberately mutated by the exercises, so a
fresh copy of the course dataset will not reproduce every result:
`raw_jaffle_shop.orders` gained rows 100–104 for the snapshots course, and
`raw_stripe.payment` gained payments 1001–1002 plus a status flip on payment 33 for the
incremental-models course. See `macros/load_payment_batch.sql` for the latter, and
`revert_payment_batch` to undo it.

```bash
# 1. Credentials — copy the template to ~/.dbt/profiles.yml and set env vars.
#    profiles.yml is gitignored; no secret belongs in this repo.
#    Auth is a service-account keyfile. See profiles.yml.example for the GCP setup,
#    including the third IAM role that Fusion needs and dbt Core does not.
cp profiles.yml.example ~/.dbt/profiles.yml

export BIGQUERY_PROJECT="your-gcp-project-id"
export BIGQUERY_KEYFILE="$HOME/.dbt/keys/bq_dbt_sa.json"
export BIGQUERY_LOCATION="EU"     # must match where the datasets were created

# 2. Verify the connection
dbt debug

# 3. Build everything
dbt build

# 4. Optional — check the warehouse against the committed Snowflake baseline
python _migration/check_parity.py
```

## Command reference

```bash
dbt debug                        # check profile + warehouse connection
dbt build                        # seed + run + test + snapshot, in DAG order
dbt run --select stg_jaffle_shop_orders+  # a model and everything downstream
dbt test --select dim_customers
dbt show --inline "select ..." --limit 5  # ad-hoc query; SELECT-only, and it appends its own LIMIT
dbt run-operation load_payment_batch      # DML via run_query() — writes to raw, has a revert
dbt compile --select audit_all_columns    # render an audit query for pasting into BigQuery
                                          # (needs both relations to already exist — audit_helper
                                          #  introspects them at COMPILE time, so run dbt build first)
dbt compile --write-catalog      # Fusion: write target/catalog.json, then open the dbt Core index.html viewer
```
