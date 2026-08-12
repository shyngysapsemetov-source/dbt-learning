# 01 — dbt Fundamentals

**Status:** in progress
**Started:** 2026-08-12

## What this course covers

Project setup, sources, models, `ref()`/`source()`, tests, documentation, deployment basics.

## Key concepts

<!-- Add as you go. Suggested shape: the concept, why it exists, and the gotcha you hit. -->

### `ref()` vs `source()`

- `source('name', 'table')` — raw data landed by EL tooling; declared in a `.yml`, not built by dbt.
- `ref('model_name')` — another dbt model. This is what builds the DAG; dbt infers run order from it.
- Never hardcode a table name in a model. That breaks the DAG and the environment swap between dev/prod.

### Materializations

| Type | Builds as | Use when |
|---|---|---|
| `view` | `CREATE VIEW` | cheap, always fresh, staging layer |
| `table` | `CREATE TABLE AS` | expensive query read often |
| `incremental` | inserts/merges new rows only | large append-mostly fact tables |
| `ephemeral` | inlined as a CTE, no object | small reusable logic, not queried directly |

## Commands used

```bash
dbt debug          # verify the connection + profile wiring
dbt deps           # install packages from packages.yml
dbt seed           # load seeds/*.csv into the warehouse
dbt run            # build models
dbt test           # run tests
dbt build          # seed + run + test + snapshot, in DAG order
dbt docs generate  # build the docs site
```

## Gotchas hit

<!-- Log the things that cost you time. These are the highest-value notes later. -->

## Open questions

<!-- Anything unresolved — revisit before the exam. -->
