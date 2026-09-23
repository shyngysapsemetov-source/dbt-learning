# 03 — Jinja, Macros & Packages

**Status:** complete

## What this course covers

The templating layer that sits above the SQL — Jinja delimiters, macros with arguments and
defaults, `run_query()` for talking to the warehouse from Jinja, and packages as the way to
stop writing the same macro in every project.

The recurring theme: Jinja is compiled away before the warehouse sees anything, so every
question about "what did it do" is answered by reading `target/compiled/`.

## Key concepts

### Jinja delimiters

| Syntax | Meaning |
|---|---|
| `{{ ... }}` | expression — renders a value into the SQL |
| `{% ... %}` | statement — control flow, no output |
| `{# ... #}` | comment — stripped before compilation |

The mental model: dbt compiles Jinja → plain SQL, *then* sends it to the warehouse. When
something looks wrong, read `target/compiled/` — that's the actual SQL that ran.

### Whitespace control

`{%-` strips whitespace before the tag, `-%}` after it. On a macro definition that is the
difference between the call site rendering inline and rendering with a leading newline plus
the macro file's own indentation:

```sql
{%- macro cents_to_dollars(column_name, decimal_places=2) -%}
   round({{ column_name }} * 1.0 / 100, {{ decimal_places }})
{%- endmacro -%}
```

Cosmetic as far as the warehouse cares, but compiled SQL is something you actually read
when debugging, and a select list broken across random lines is harder to diff.

### Macros take defaults, and calls can be positional or keyword

```sql
{{ cents_to_dollars('amount') }}                      -- decimal_places defaults to 2
{{ cents_to_dollars('amount', decimal_places=4) }}    -- keyword, self-documenting
```

Keyword form is worth the extra characters on anything with more than one argument —
`clean_stale_models(days=7, dry_run=False)` reads unambiguously, `clean_stale_models(7, False)`
does not.

### A macro's return type is a schema decision

`round(x, 2)` doesn't just format — it fixes the result's *scale*, and any model that
materializes the result inherits that scale as a stored column type. Extracting
`cents_to_dollars` was supposed to be a pure refactor and instead broke the build. Full
story in the gotchas.

### The two compile phases, and why `execute` exists

dbt renders model SQL **twice**: once at parse time to discover `ref()` and `source()` and
build the DAG, then again at run time to produce the SQL it sends. During the parse pass
`execute` is `False` and `run_query()` returns `None`.

So a macro called *from a model* that queries the warehouse must guard:

```sql
{% if execute %}
    {% set results = run_query(sql) %}
{% endif %}
```

Without the guard, the parse pass reaches `None.columns` and the whole project fails to
parse — before anything runs. Macros invoked only through `run-operation` never render at
parse time, so they get away without it, but the guard costs nothing.

### `run_query()` and result shapes

`run_query()` is the friendly wrapper over a `statement` block. It hands back a result table
object (agate, in dbt Core) rather than a list of dicts, so you pull data out by column:

```sql
{% set drop_queries = run_query(sql).columns[1].values() %}
```

`.columns[1]` is *positional*. Add a column to the query's select list and it silently starts
returning the wrong one — see the gotchas.

### `log()`, `target`, and DML

- `log(msg, info=True)` prints to the console; without `info=True` it only reaches the log file.
- `target` carries the active profile: `target.name`, `target.schema`, `target.database`,
  `target.role`, `target.type`. Defaulting a macro's arguments to `target.*` is what keeps an
  operational macro from ever being pointed at the wrong environment by accident.
- Models compile to a `SELECT`. Anything that mutates — `grant`, `drop`, `insert` — has to go
  through `dbt run-operation`.

### Loops, and where the list should live

```sql
{%- set payment_methods = ['credit_card', 'coupon', 'bank_transfer', 'gift_card'] -%}
...
       {% for method in payment_methods %}
     , sum(case when payment_method = '{{ method }}' then payment_amount end) as {{ method }}_amount
       {% endfor %}
```

The **leading comma** is doing real work: it removes the need for
`{% if not loop.last %},{% endif %}`. Commas before each item mean the loop body is identical
on every iteration, which is the whole point of writing it as a loop.

Three places the list could live, in increasing order of coupling:

| Where | Trade-off |
|---|---|
| `{% set %}` in the model | Local and obvious. Right when one model needs it. |
| `vars:` in `dbt_project.yml` | Shared across models, overridable per-invocation with `--vars`. |
| `dbt_utils.get_column_values()` | Read from the data at compile time — no maintenance, but the model's **schema** now depends on the data. A method appearing or disappearing silently adds or drops a column. |

This project keeps the list in the model: only one model pivots, and a stable column list is
worth more here than never touching the file again.

### Packages

`packages.yml` declares them, `dbt deps` installs into `dbt_packages/` (gitignored), and the
resolved versions land in `package-lock.yml` (committed) so every environment installs
identically. `dbt deps --upgrade` is what re-resolves the lock.

Three sources:

| Source | Declaration |
|---|---|
| dbt Hub | `package: dbt-labs/dbt_utils` + `version: 1.4.1` |
| git | `git: https://...` + `revision:` (tag or commit, never a branch) |
| local | `local: ../shared_macros` |

Package macros are namespaced — `dbt_utils.date_spine(...)` — while your own are called bare.
A project-local macro whose name collides with a package's wins, which is the supported way
to override package behaviour.

Installed here:

| Package | Used for |
|---|---|
| `dbt_utils` 1.4.1 | `date_spine` in `models/python_demo/date_spine.sql`; the cross-database standard library generally |
| `audit_helper` 0.14.0 | `compare_all_columns` and `compare_row_counts` in `analysis/`, refactor parity checks against the legacy model |
| `codegen` 0.14.1 | Scaffolding source and model YAML via `run-operation` |

## Built here

| Artifact | What it demonstrates |
|---|---|
| `macros/cents_to_dollars.sql` | Arguments with defaults, whitespace control. Called from `stg_stripe_payment` |
| `models/intermediate/int_orders__pivoted.sql` | `{% set %}` list + `{% for %}` loop generating one column per payment method |
| `macros/grant_select.sql` | `run-operation` DML, `target.schema` / `target.role` defaults, `run_query()` |
| `macros/clean_stale_models.sql` | Querying `information_schema` from Jinja, reading a result column, and a `dry_run=True` default |

`clean_stale_models` is the one worth re-reading later: a macro whose job is to `DROP` things
defaults to **printing** the statements instead of running them, and takes an explicit
`dry_run=False` to actually act. Anything generating destructive DDL from a query result
should be built that way round.

## Commands used

```bash
dbt deps                                   # install packages.yml into dbt_packages/
dbt deps --upgrade                         # re-resolve and rewrite package-lock.yml
dbt compile --select int_orders__pivoted    # render the loop and read target/compiled/
dbt run-operation grant_select
dbt run-operation clean_stale_models --args '{"days": 7, "dry_run": true}'
dbt run-operation generate_model_yaml --args '{"model_names": ["int_orders__pivoted"]}'
```

## Gotchas hit

### Extracting a macro changed a column's type and broke an incremental model

`amount / 100.0` became `{{ cents_to_dollars('amount') }}`, which is
`round(amount * 1.0 / 100, 2)`. Same values, and `stg_stripe_payment` is a view, so it looked
free. But the division produced NUMBER(38,6) and the `round(..., 2)` produces NUMBER(38,2), and
`int_order_payments` **stores** the sum of that column. `on_schema_change: sync_all_columns`
tried to `alter column ... set data type NUMBER(38,2)`, which Snowflake refuses because scale
changes aren't supported.

The lesson that generalises: **a macro's output type is part of its interface.** A refactor
that preserves every value can still be a breaking schema change one model downstream. Full
diagnosis, the failing DDL, and what Snowflake will and won't alter are in
[05 — Incremental Models](05-incremental-models.md).

### `.columns[1]` is positional, so the query and the accessor are silently coupled

```sql
select case when table_type = 'VIEW' then table_type else 'TABLE' end as object_type
     , 'DROP ' || object_type || ' ' || ... as drop_statement
...
{% set drop_queries = run_query(sql).columns[1].values() %}
```

Add a column anywhere before `drop_statement` and the macro starts executing whatever now sits
at index 1. Nothing errors — it just does something else. Fetching by name is the safer habit
where the API allows it, and where it doesn't, the accessor and the select list have to be
edited as one unit.

### That macro also leans on a Snowflake-only extension

`drop_statement` references `object_type`, an alias defined in the *same* select list. Snowflake
allows lateral alias references; standard SQL does not, and neither do several other
warehouses. Fine in a project pinned to one warehouse, but it is exactly the kind of thing that
makes a macro non-portable — and portability is the reason macros get extracted in the first
place. A repeated `case` expression or a subquery is the portable form.

### `dbt run-operation` hides `run_query` failures behind a parse error

A macro body that only ever runs under `run-operation` is never rendered at parse time, so a
missing `{% if execute %}` guard doesn't bite there. Move that same code into a macro a *model*
calls and the failure shows up as a project-wide parse error rather than a runtime one — the
model isn't even the thing that looks broken. Guard on `execute` whenever `run_query` could end
up on a parse path.

### `--args` can only pass strings, so a Relation has to be built inside the macro

`dbt run-operation find_datatypes --args '{"relation": "fct_orders"}'` fails with
`JinjaError (dbt1501) … invalid operation: relation must be an object`. `--args` parses YAML/JSON,
so it yields scalars, lists and dicts — never a `Relation`. But `adapter.get_columns_in_relation()`
type-checks its argument, because it needs `.database` / `.schema` / `.identifier` to build the
metadata lookup. A string has none of them, and it raises **before** any SQL is emitted.

The pattern that fixes it is a thin CLI wrapper that does the conversion:

```sql
{% macro print_datatypes(model_name) %}
    {{ log(find_datatypes(ref(model_name)), info=True) }}
{% endmacro %}
```

Generalises to: **a macro reachable from the shell takes strings; a macro reachable from Jinja
takes objects.** Keep them as two macros. Use `ref()` rather than `api.Relation.create()` for
anything in the DAG — `ref()` resolves the active target, so the same command reads dev in dev
and prod in prod, while `Relation.create()` hardcodes a dataset and silently reads the wrong
environment. Also note the error names no relation and points at a `:line:col` — that pair is
the tell for "Jinja/adapter layer", not "warehouse".

### On BigQuery, `col.data_type` drops precision and scale — on Snowflake it didn't

Verified 2026-09-08 against a scratch table, comparing `adapter.get_columns_in_relation` to
`INFORMATION_SCHEMA.COLUMNS`:

| Declared | `col.data_type` | `INFORMATION_SCHEMA` | |
|---|---|---|---|
| `NUMERIC(12, 2)` | `NUMERIC` | `NUMERIC(12, 2)` | lost |
| `BIGNUMERIC(40, 10)` | `BIGNUMERIC` | `BIGNUMERIC(40, 10)` | lost |
| `STRING(20)` | `STRING` | `STRING(20)` | lost |
| `BYTES(5)` | `BYTES` | `BYTES(5)` | lost |
| `BOOL` | `BOOLEAN` | `BOOL` | alias, not identical |
| `ARRAY<INT64>` | `ARRAY<INT64>` | same | exact |
| `STRUCT<a INT64, b STRING>` | `` STRUCT<`a` INT64, `b` STRING> `` | same, unquoted | exact |
| `JSON` `GEOGRAPHY` `DATETIME` `DATE` `TIME` `INT64` `FLOAT64` | identical | identical | exact |

Nested and repeated structure survives; **parameters do not.** The cause is an adapter
difference, not a BigQuery one. Snowflake's base `Column.data_type` reconstructs parameters from
`numeric_precision` / `numeric_scale` / `character_maximum_length`, so it returned `NUMBER(38,2)`
and `VARCHAR(16777216)`. The BigQuery column class overrides `data_type` to compose the
`ARRAY<…>` / `STRUCT<…>` wrappers and never consults precision or scale — even though the API
exposes them.

Why it matters: paste that output into a yml, set `contract: {enforced: true}`, and dbt builds the
table from the *declared* types, so `NUMERIC(12, 2)` becomes bare `NUMERIC` (38,9) and the scale
constraint is gone. The contract still passes, because it compares the declaration against a table
built from that same declaration — circular and green.

`codegen` does **not** save you here. `codegen/macros/vendored/dbt_core/format_column.sql:14-15`
reads the same `column.data_type`, so dbt Labs' own generator is equally lossy on BigQuery. The
only exact route is `INFORMATION_SCHEMA.COLUMNS`, which returns the full DDL type string.

The rule: **`col.data_type` gives the type *family*, not the type.** And the wider one — the same
macro, unchanged, returns less information after a warehouse migration. Nothing fails; the output
just quietly gets coarser. This is the class of regression a migration parity check on row counts
will never surface.

*(Measured on Fusion 2.0's Rust adapter; dbt Core's `dbt-bigquery` implements `data_type` the same
way, but that was reasoned, not run.)*

### `col.dtype` vs `col.data_type` is warehouse-dependent, and `adapter.dispatch` is why

Straight from codegen's source, `macros/vendored/dbt_core/format_column.sql`:

```sql
{% macro format_column(column) -%}
  {{ return(adapter.dispatch('format_column', 'codegen')(column)) }}
{%- endmacro %}

{% macro default__format_column(column) -%}
  {% set data_type = column.dtype %}          {# Snowflake et al. #}
  ...
{% macro bigquery__format_column(column) -%}
  {% set data_type = column.data_type %}      {# BigQuery #}
  {% if column.mode.lower() == "repeated" and column.dtype.lower() == "record" %}
    {% set data_type = "array" %}             {# codegen issue #190 #}
  {% endif %}
```

| Attribute | What it is | Right on |
|---|---|---|
| `col.dtype` | the raw type label the warehouse reported (`RECORD`, `INTEGER`) | Snowflake — already the full story there |
| `col.data_type` | the *composed* value, wrapping `ARRAY<…>` / `STRUCT<…>` around `dtype` | BigQuery |

So there is no single correct attribute — which is exactly the condition that justifies
`adapter.dispatch`. The shape to copy: one bare macro that dispatches, a `default__`
implementation, and a `<adapter>__` override. **Dispatch earns its indirection when the right
answer genuinely differs per warehouse, not merely when the syntax does** — a plain macro is
enough for anything a `case` expression can absorb.

Line 16-18 is also worth remembering on its own: a REPEATED RECORD gets special-cased down to
plain `array`, because the `ARRAY<STRUCT<…>>` the adapter composes isn't valid in a contract. That
is a maintained package absorbing an adapter wart on your behalf, and it is the strongest argument
for a package over a hand-rolled macro — stronger than "less code."

### Reading INFORMATION_SCHEMA instead of the adapter — the trade

`mesh/platform/macros/find_datatypes.sql` was switched off `adapter.get_columns_in_relation()` onto
a `run_query` against `INFORMATION_SCHEMA.COLUMNS` to recover the parameters. Verified on a scratch
table, 2026-09-08 — every type now exact, including `bool` rather than the adapter's `BOOLEAN`
alias:

```
c_num  ->  numeric(12, 2)      c_arr     ->  array<int64>
c_str  ->  string(20)          c_struct  ->  struct<a int64, b string>
```

What it costs, and why it was still the right call for a single-warehouse project:

- **Portability.** `` `project.dataset`.INFORMATION_SCHEMA.COLUMNS `` is BigQuery-shaped. The
  adapter call was warehouse-agnostic. This is the `object_type` lateral-alias mistake from the
  `clean_stale_models` gotcha above, made deliberately this time and with a comment saying so.
- **A round trip to the warehouse** instead of cached relation metadata.
- **`{% if execute %}` became mandatory.** The adapter version never needed it; the moment
  `run_query` entered the macro body, a caller from a *model* would hit `None` at parse time. Same
  lesson as the `run-operation` gotcha below, arrived at from the opposite direction: the guard is a
  property of *what the macro does*, not of how it happens to be called today.
- **Row access by name, not index** — `col['data_type']`, not `col[1]` — for the reason in the
  `.columns[1]` gotcha above. Fusion supports the named form.

## Open questions

- ~~`adapter.dispatch` is how `dbt_utils` supports many warehouses from one macro name. When is a
  plain macro genuinely enough, and at what point is dispatch worth the indirection?~~
  **Answered 2026-09-08** from codegen's `format_column` — see the `dtype` vs `data_type` gotcha
  above. Dispatch is for when the correct *answer* differs per warehouse, not just the syntax.
- `dbt_utils.pivot` does what `int_orders__pivoted` hand-rolls. Is a package dependency worth it
  for four columns, or is the explicit loop the better documentation?
- `codegen` generates YAML. Commit the output as-is, or treat it as scaffold and hand-edit? The
  YAML in this project is hand-written, and the descriptions are the reason.
- Fusion runs Jinja in Rust, not Python. Which parts of the `run_query()` / agate API are shimmed
  and which quietly differ? *Partial, 2026-09-08:* `run_query(...).rows` works, and rows support
  **named** access (`row['data_type']`) as well as positional. `adapter.dispatch`,
  `api.Relation.create`, `exceptions.raise_compiler_error` and `log(info=True)` all behave as in
  Core. Still unknown: agate's typed-column helpers (`.columns[n].values()` worked, but
  `agate.Table` methods like `.select()` / aggregations are untested).
- Sharing `cents_to_dollars` across projects means publishing it as a git package. What does that
  cost in practice versus copying twelve lines?
