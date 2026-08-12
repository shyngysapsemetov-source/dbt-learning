# 05 — Analyses, Seeds & Snapshots

**Status:** not started

## What this course covers

The `analyses/` directory, loading static data via seeds, capturing slowly changing dimensions with snapshots.

## Key concepts

### Seeds

CSVs in `seeds/`, loaded with `dbt seed`. For small, static, version-controllable data — country code mappings, exclusion lists, test fixtures. Not for anything large or frequently changing.

### Snapshots

Capture how a mutable source row changed over time (SCD Type 2).

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

### Analyses

SQL in `analyses/` gets compiled by `dbt compile` but never materialized. Good for ad-hoc queries you still want version-controlled and Jinja-templated.

## Commands used

```bash
dbt seed
dbt seed --full-refresh
dbt snapshot
```

## Gotchas hit

## Open questions
