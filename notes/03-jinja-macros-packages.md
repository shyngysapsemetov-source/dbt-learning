# 03 — Jinja, Macros & Packages

**Status:** not started

## What this course covers

Jinja syntax, writing macros, using packages (`dbt_utils`), `dbt_project.yml` variables.

## Key concepts

### Jinja delimiters

| Syntax | Meaning |
|---|---|
| `{{ ... }}` | expression — renders a value into the SQL |
| `{% ... %}` | statement — control flow, no output |
| `{# ... #}` | comment — stripped before compilation |

The mental model: dbt compiles Jinja → plain SQL, *then* sends it to the warehouse. When something looks wrong, read `target/compiled/` — that's the actual SQL that ran.

### Macros

```sql
{% macro cents_to_dollars(column_name, decimal_places=2) %}
    round({{ column_name }} / 100, {{ decimal_places }})
{% endmacro %}
```

Called in a model as `{{ cents_to_dollars('amount') }}`.

## Commands used

```bash
dbt compile                        # render Jinja without running
dbt run-operation <macro_name>     # execute a macro standalone
```

## Gotchas hit

## Open questions
