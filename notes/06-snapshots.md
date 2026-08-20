# 06 — Snapshots

**Status:** not started

## What this course covers

Capturing how a mutable source row changed over time — slowly changing dimensions, Type 2.

## Key concepts

Sources get overwritten in place. A row's current state is all the warehouse has; the history is gone unless something captured it. Snapshots are that something.

```sql
{% snapshot orders_snapshot %}
{{ config(
    target_schema='snapshots',
    unique_key='id',
    strategy='timestamp',
    updated_at='updated_at'
) }}
select * from {{ source('jaffle_shop', 'orders') }}
{% endsnapshot %}
```

Two strategies:
- `timestamp` — needs a reliable `updated_at`. Preferred.
- `check` — compares listed columns (`check_cols`). Use when there's no timestamp.

Adds `dbt_valid_from` / `dbt_valid_to`; the current row has `dbt_valid_to is null`.

## Commands used

```bash
dbt snapshot
```

## Gotchas hit

## Open questions
