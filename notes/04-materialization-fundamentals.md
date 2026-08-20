# 04 — Materialization Fundamentals

**Status:** complete

## What this course covers

How dbt turns a `select` into an object in the warehouse, and the four materializations that ship with dbt: view, table, incremental, ephemeral.

## Key concepts

### The four materializations

| Materialization | What dbt builds | Cost profile | Use when |
|---|---|---|---|
| `view` | `create view as <your select>` | Cheap to build, cost paid on every read | Light transformation, model is not queried often |
| `table` | `create table as <your select>` | Full rebuild each run, cheap to read | Downstream models or BI query it repeatedly |
| `incremental` | `create table` once, then insert/merge only new rows | Cheapest on large append-only data | Table is large and history does not change |
| `ephemeral` | Nothing — inlined into the caller as a CTE | No object, no storage | Shared logic you never want to query directly |

A model's materialization is a config, not part of the SQL. Change it and dbt drops and recreates the object on the next run — the `select` never changes.

### Where the config goes

Three places, most specific wins:

1. `{{ config(materialized='table') }}` in the model file — this model only.
2. `+materialized:` on a folder in `dbt_project.yml` — the whole subtree.
3. Nothing — dbt falls back to `view`.

This project uses the folder form: `staging` is `view`, `marts` is `table`, `legacy` is `table`.

### Ephemeral has real trade-offs

An ephemeral model has no relation in the warehouse, so it cannot be selected, tested with a stored result, or inspected. Referenced by several models, its SQL is pasted into each of them, so the work is repeated per caller instead of shared. It buys DRY-ness in the project, not efficiency in the warehouse.

### Incremental in one line

`is_incremental()` is true only when the model is incremental **and** the table already exists **and** `--full-refresh` was not passed. That third condition is what makes `dbt run --full-refresh` the escape hatch when the logic changes.

## Commands used

```bash
dbt run --select dim_customers         # rebuild one model with its current materialization
dbt run --full-refresh                 # ignore incremental logic, rebuild from scratch
```

## Gotchas hit

## Open questions
