# 07 — Analyses and Seeds

**Status:** complete

## What this course covers

The `analysis/` directory for SQL that is compiled but never run, and loading small static data into the warehouse via seeds.

## Key concepts

### Analyses

SQL in `analysis/` gets compiled by `dbt compile` but never materialized. Good for ad-hoc queries you still want version-controlled and Jinja-templated — `ref()` and macros work exactly as they do in a model. The compiled output lands in `target/compiled/` for pasting into the warehouse.

Built here: `total_revenue.sql`, summing successful Stripe payments. The two `audit_*` analyses from the refactoring course are the same idea used for a real purpose.

### Seeds

CSVs in `seeds/`, loaded with `dbt seed`. For small, static, version-controllable data — country code mappings, exclusion lists, employee rosters, test fixtures. Not for anything large or frequently changing: every row lives in git and the whole file is re-inserted on each `dbt seed`.

Seeds are first-class nodes: `ref('employees')` works, and they take `description` / `data_tests` in a YAML file just like models. `seeds/_seeds.yml` documents and tests this one.

Built here: `employees.csv` — employee emails and the customer account each one orders under, so employee orders can be excluded from customer metrics.

## Commands used

```bash
dbt seed
dbt seed --full-refresh          # drop and recreate; needed when the CSV's columns change
dbt compile --select total_revenue
```

## Gotchas hit

### dbt trims seed headers but not seed values

The course CSV is written with a space after every comma:

```csv
employee_id, email, customer_id
3425, mike@jaffleshop.com, 1
```

The *headers* come through clean — the column really is `EMAIL`. The *values* don't. `email` loaded as `" mike@jaffleshop.com"`, with the leading space intact, so every join or `=` against a real email address missed silently. Numeric columns are unaffected, because the type conversion eats the whitespace, which makes it easy to spot-check the CSV and conclude it's fine.

Nothing errors. `dbt seed` succeeds, `unique` and `not_null` both pass — a leading space is still unique and still not null. Only a comparison against data from anywhere else reveals it. Fixed by removing the spaces in the CSV.

Worth remembering that this is the general shape of a seed bug: seeds get no source freshness, no upstream tests, and no schema enforcement, so a typo in a committed CSV is indistinguishable from data until something downstream quietly returns zero rows.

## Open questions
