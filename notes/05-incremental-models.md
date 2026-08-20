# 05 — Incremental Models

**Status:** not started

## What this course covers

Incremental models, `is_incremental()`, full refresh, late-arriving data.

Ephemeral and the view/table trade-offs are in [04 — Materialization Fundamentals](04-materialization-fundamentals.md); snapshots have their own course, [06](06-snapshots.md).

## Key concepts

### Incremental pattern

```sql
{{ config(materialized='incremental', unique_key='id') }}

select * from {{ source('raw', 'events') }}

{% if is_incremental() %}
  -- only rows newer than what's already in the table
  where _loaded_at > (select max(_loaded_at) from {{ this }})
{% endif %}
```

- `{{ this }}` — the existing relation for this model.
- `is_incremental()` is true only when: the model is `incremental`, the table already exists, and `--full-refresh` was NOT passed.
- Without `unique_key` dbt appends. With it, dbt merges (updates matching rows).

### Late-arriving data

`max(_loaded_at)` misses rows that land with an older timestamp after the run. Mitigation: a lookback window — `where _loaded_at > (select max(_loaded_at) - interval '3 days' from {{ this }})` — combined with a `unique_key` so re-processed rows update rather than duplicate.

## Commands used

```bash
dbt run --select my_model --full-refresh
```

## Gotchas hit

## Open questions
