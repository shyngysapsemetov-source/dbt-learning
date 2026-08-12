# 03 — Advanced Testing

**Status:** not started

## What this course covers

Generic vs singular tests, custom generic tests, test severity/thresholds, `dbt_utils` tests, source freshness.

## Key concepts

### Two kinds of test

- **Generic** — parameterized, declared in `.yml`, reused across columns (`not_null`, `unique`, `accepted_values`, `relationships`).
- **Singular** — a `.sql` file in `tests/` containing a query. Test passes when it returns **zero rows**.

### Severity

```yaml
tests:
  - not_null:
      config:
        severity: warn        # or error
        error_if: ">100"
        warn_if: ">0"
```

### Freshness

```yaml
sources:
  - name: raw
    freshness:
      warn_after: {count: 12, period: hour}
      error_after: {count: 24, period: hour}
    loaded_at_field: _loaded_at
```

## Commands used

```bash
dbt test --select model_name
dbt test --select source:raw
dbt source freshness
dbt build --fail-fast
```

## Gotchas hit

## Open questions
