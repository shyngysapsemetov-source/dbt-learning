# 05 — Refactoring SQL for Modularity

**Status:** complete

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

```bash
dbt show --inline "select ..."      # ad-hoc query without leaving the CLI
```

## Gotchas hit

### Replacing the self-join with a window changed nothing here, but it could

The legacy query computed running CLV by joining `paid_orders` to itself on
`customer_id and order_id >= order_id` and summing. A `sum(...) over (... rows
unbounded preceding)` does the same thing in one pass. That part is a safe swap.

`nvsr` is not. Legacy tagged an order `'new'` when its date equalled the
customer's `min(order_date)` — a date comparison, so **every** order placed on a
customer's first day comes back `'new'`. The refactor uses
`rank() over (partition by customer_id order by order_placed_at, order_id) = 1`,
and because `order_id` breaks the tie, exactly one order per customer is `'new'`.

Verified against jaffle_shop: 0 customers have more than one order on their first
order date, so the two definitions agree on all 99 rows and the audit comes back
clean. The divergence is latent, not absent — it appears the first time a customer
orders twice in a day. The one-`'new'`-per-customer version is the one worth
keeping: under the legacy rule, `count(*) where nvsr = 'new'` silently stops
equalling the number of customers.

### Auditing a legacy query is easier if you make it a model

The course reaches for `adapter.get_relation()` because the legacy table usually
predates the project. Once the legacy SQL is committed as a model, `ref()` is
strictly better: it follows `target.schema` between environments, shows up in the
DAG, and resolves at parse time — no `{% raw %}{% if execute %}{% endraw %}` guard
needed, which `adapter.get_relation()` does need, since it returns `None` during
parsing and `audit_helper` then fails trying to read columns off it.

### Jinja does not respect SQL comments

`-- {% raw %}{% if execute %}{% endraw %}` in an analysis is still a Jinja tag.
Commenting out a block does not disable it; it produces `unexpected end of input,
expected endif`.

## Open questions
