# 04 — Refactoring SQL for Modularity

**Status:** not started

## What this course covers

Migrating a legacy stored-procedure-style query into modular dbt models: CTE groupings, staging layer, splitting out marts, auditing the refactor.

## Key concepts

### The refactoring sequence

1. Move the legacy query into dbt as-is (one model, still one blob).
2. Translate hardcoded table refs → `source()` / `ref()`.
3. Choose a CTE-first structure: imports at top, logic in the middle, one final `select`.
4. Break the import CTEs out into staging models.
5. Split business logic into intermediate/mart models.
6. Audit old vs new with `dbt_utils.equality` or the `audit_helper` package.

### Layer conventions

| Layer | Prefix | Purpose |
|---|---|---|
| staging | `stg_` | 1:1 with a source table — rename, cast, light cleanup only |
| intermediate | `int_` | joins and reshaping, not exposed to BI |
| marts | `fct_` / `dim_` | business-facing, tested and documented |

## Commands used

```bash
dbt run --select stg_customers+     # model and everything downstream
dbt run --select +fct_orders        # model and everything upstream
dbt run --select @stg_customers     # upstream AND downstream
```

## Gotchas hit

## Open questions
