# 05 — Incremental Models

**Status:** complete

## What this course covers

Building a table in slices instead of rebuilding it whole — `materialized: incremental`, `is_incremental()`, `{{ this }}`, merge strategies, and the question that decides everything: which models can safely be built this way at all.

Ephemeral and the view/table trade-offs are in [04 — Materialization Fundamentals](04-materialization-fundamentals.md); snapshots have their own course, [06](06-snapshots.md).

## Key concepts

### The pattern

```sql
{{ config(materialized='incremental', unique_key='id') }}

select * from {{ source('raw', 'events') }}

{% if is_incremental() %}
  where _loaded_at >= (select coalesce(max(t._loaded_at), '1900-01-01') from {{ this }} as t)
{% endif %}
```

- `{{ this }}` — the existing relation for this model.
- `is_incremental()` is true only when the model is `incremental`, the table already exists, **and** `--full-refresh` was not passed.
- Without `unique_key` dbt appends. With it, dbt merges.
- Use `>=`, not `>`. Rows in one batch can share a timestamp, and with `merge` reprocessing is idempotent, so `>=` is safe while `>` can silently skip.
- Alias `{{ this }}` and qualify the column. An unqualified reference to a column the target lacks does not error — see the first gotcha below.
- Cast columns whose type could drift. A stored column's type is fixed at creation, and `sync_all_columns` can only change it as far as the warehouse permits.

### The rule that decides whether a model can be incremental

Incremental is safe **and** profitable exactly when the computation's partition key equals the merge key.

| Computation | Merge key | Verdict |
|---|---|---|
| `sum(x) group by order_id` | `order_id` | **Key match.** An order's total depends only on its own payments. Recomputing a touched order is always correct, regardless of the order batches arrive in. |
| `sum(x) over (partition by customer_id)` | `order_id` | **Mismatch.** Correctness needs whole customers reprocessed to change a few rows. Savings shrink, staleness risk rises. |
| `row_number() over (order by order_id)` | anything | **Impossible.** No `partition by` means the partition is the entire table. No incremental scheme can ever work. |

This is why `fct_orders` fought every attempt: its five window columns are customer-partitioned or unpartitioned, but its grain — and any sensible merge key — is `order_id`.

### Where the filter goes changes what breaks

Two placements, different failure modes:

**Input filter** — scope the source CTE, so windows compute over the filtered slice:

```sql
orders as (
    select * from {{ ref('stg_orders') }}
    {% if is_incremental() %}
    where customer_id in (select customer_id from touched_customers)
    {% endif %}
)
```

Customer-partitioned windows become correct again because the window sees each touched customer's full history. Global windows stay broken.

**Output filter** — compute over everything, filter at the end:

```sql
select * from paid_orders
{% if is_incremental() %}
where _loaded_at >= (select max(_loaded_at) from {{ this }})
{% endif %}
```

All windows, global ones included, are correct **for the rows emitted**. Snowflake cannot push the predicate below the window function — that is only legal when the filter is on the `partition by` columns — so the windows genuinely see every row.

The catch: it is correct only if new rows sort to the end of every window's `order by`. Break that and rows you never re-emit go stale:

| Arrival | What goes stale |
|---|---|
| Backdated `order_date` | `running_clv` for the customer's later orders; `fdos` for **all** their rows |
| Lower `order_id` | `customer_sales_seq` later in the partition; `transaction_seq` globally |
| Order predating the customer's current first order | The old `'new'` row should now read `'return'` |
| Revised amount on an existing order | `running_clv` for every *subsequent* order of that customer |

That last one needs no backdating at all, which makes it the easiest to miss.

And the honest cost: output filtering computes the windows over full history every run, so it saves no scan and no sort — only the write. Against `materialized: table` that is a modest win carrying real correctness risk.

### A watermark's sufficiency is a property of the loader, not the column

The contract that makes a watermark valid: **every row whose visible state changes gets a timestamp strictly greater than any previously loaded.** Three mutation classes, only two of which a watermark can carry:

| Mutation | Carried? |
|---|---|
| Insert | Yes, naturally |
| Update | Yes — *only if* the loader bumps the timestamp in the same statement |
| Delete | **No, in principle.** A removed row has no timestamp left to move |

Deletes have to become soft deletes — a status change rather than a `DELETE` — or the strategy has to change to `delete+insert`.

A load timestamp like `_batched_at` records insert time. Nothing forces a writer to bump it on update, which is the same hazard that makes `check` the right snapshot strategy in [06](06-snapshots.md).

## Built here

`int_order_payments` — the project's only incremental model, and the one place where the group key is the merge key:

```yaml
    config:
      materialized: incremental
      unique_key: order_id
      incremental_strategy: merge
      on_schema_change: sync_all_columns
```

Two non-obvious choices inside it:

- **`touched_orders` is not filtered on `payment_status`.** A payment flipping to `'fail'` has to mark its order dirty too, or the order silently keeps its pre-flip total.
- **Failed payments are excluded with `case when`, not `where`.** Their rows still hold the group open, so an order whose payments have all failed merges as NULL instead of going stale — because `merge` cannot delete a row.

`fct_orders` went back to `materialized: table`, with the reasoning recorded in `_marts.yml` so it does not get "optimized" back later.

`macros/load_payment_batch.sql` is the test harness — it exercises all three mutation classes against `raw.stripe.payment` and has a paired `revert_payment_batch`.

### Test protocol

Prove the refactor is value-neutral *before* changing data, or a later difference can't be attributed to the incremental logic rather than the refactor:

```bash
dbt build --select int_order_payments fct_orders fct_customer_orders --full-refresh
dbt run --select customer_orders_legacy --full-refresh   # baseline on the same raw data
# compare vs legacy → expect zero diffs
dbt run-operation load_payment_batch
dbt run --select int_order_payments                      # a real incremental run
# compare built table vs recomputed truth → expect zero drift
dbt build --select fct_orders fct_customer_orders
dbt run --select customer_orders_legacy --full-refresh
# compare vs legacy again → expect zero diffs
```

Results:

| Case | Before | After |
|---|---|---|
| Order 1 — late payment on a 2018 order | $10.00, finalized 2018-01-01 | $25.00, finalized 2026-08-22 |
| Order 25 — payment flipped to `fail` | $58.00 | $42.00 |
| Order 100 — previously had no payments | *no row* | $25.00 |

Zero drift on 100 keys; legacy parity held at 104 keys with zero column differences both before and after.

The result that mattered: customer 1's **order 37 was never touched by the batch**, but its `running_clv` moved 33 → 48 because order 1's total rose. An orders-keyed incremental `fct_orders` would never have re-emitted that row and would still read 33. Putting the incremental boundary upstream of the windows fixes that by construction rather than by luck.

## Commands used

```bash
dbt run --select my_model --full-refresh
dbt run-operation load_payment_batch      # DML via run_query(); dbt show is SELECT-only
dbt show --inline "select ..." --limit 5
```

`equal_null()` is the NULL-safe comparison for drift checks — `=` returns NULL on NULL operands and silently undercounts differences.

## Gotchas hit

### A missing column reported as a correlated aggregate

The failure that started all of this:

```
002036 (42601): SQL compilation error:
Subquery containing correlated aggregate function [MAX(PAID_ORDERS._ETL_LOADED_AT)]
can only appear in having or select clause
```

`_etl_loaded_at` was added to the model's select list *after* the table already existed. `on_schema_change` defaults to **`ignore`**, so dbt quietly left the new column out of the insert and out of the table. The watermark subquery referenced the column unqualified:

```sql
where _etl_loaded_at >= (select coalesce(max(_etl_loaded_at),'1900-01-01') from {{ this }})
```

Snowflake resolved the inner reference against `{{ this }}`, did not find it, and — instead of erroring — fell **outward** to the enclosing query and bound it to `paid_orders._etl_loaded_at`. That made the subquery a correlated aggregate, which is legal only in `SELECT` or `HAVING`, never in `WHERE`.

Two lessons: set `on_schema_change` on every incremental model, and always qualify columns inside a `{{ this }}` subquery so a missing column fails as a missing column.

### `sync_all_columns` cannot change a NUMBER's scale

The answer to what the type-change open question was asking. Swapping `amount / 100.0` for
`{{ cents_to_dollars('amount') }}` in `stg_stripe_payment` looks like a pure refactor —
identical values, and staging is a view, so there is nothing to migrate. But `round(x, 2)`
pins a scale where the bare division did not:

| Expression | Column type | `sum()` → |
|---|---|---|
| `amount / 100.0` | NUMBER(38,6) | NUMBER(38,6) |
| `round(amount * 1.0 / 100, 2)` | NUMBER(38,2) | NUMBER(38,2) |

`int_order_payments` is the only model that *stores* that number, so it was the only one
to fail:

```
040052 (22000): SQL compilation error: cannot change column TOTAL_ORDER_AMOUNT
from type NUMBER(38,6) to NUMBER(38,2) because changing the scale of a number is not supported.
```

dbt had described both relations, logged `Schema changed: True`, and issued:

```sql
alter table "ANALYTICS"."DBT_LEARNING"."INT_ORDER_PAYMENTS"
    alter "TOTAL_ORDER_AMOUNT" set data type NUMBER(38,2)
```

So `sync_all_columns` does attempt **type** changes on existing columns, not just adds and
removes — and it inherits whatever the warehouse allows:

| Change | Snowflake |
|---|---|
| Add or drop a column | Yes |
| Widen a NUMBER's precision, lengthen a VARCHAR | Yes |
| Change a NUMBER's scale | **No** |
| Change type family (NUMBER → VARCHAR) | **No** |

No dbt setting works around the last two; `--full-refresh` is the only path, because
drop-and-recreate is the only way Snowflake will restate the column.

Three lessons:

- **A view's column type is still a contract** the moment a downstream table stores it.
  Type drift in staging is invisible until it reaches the first materialized column.
- **Cast money columns explicitly in incremental models.** `total_order_amount` is now
  `cast(... as number(38, 2))`, so the type is declared rather than inherited from
  whatever expression currently produces `payment_amount`. The describe comparison then
  matches and dbt skips the sync entirely.
- The uncomfortable one: under the default `on_schema_change: ignore` this would have
  merged NUMBER(38,2) values into the NUMBER(38,6) column and **passed silently**. The
  hardening from the gotcha above is what converted an invisible type drift into a failed
  build. That is the setting working, not misbehaving.

### `incremental_predicates` on the source side inserts duplicates

```yaml
incremental_predicates: ["DBT_INTERNAL_SOURCE._etl_loaded_at > dateadd(day, -7, current_date)"]
```

dbt appends these to the merge's `ON` clause. Re-emitting a row whose timestamp is older than the window makes the predicate false, so it does not match its existing target row, falls through to `when not matched`, and gets **inserted a second time**. Any pattern that reprocesses historical rows — the touched-keys pattern especially — collides with a source-side predicate. Prune on `DBT_INTERNAL_DEST` instead, or drop it.

### `merge` cannot delete, so a vanishing group goes stale

If the aggregate is filtered with `where payment_status <> 'fail'` and every payment on an order flips to fail, the order produces no source row at all. `merge` finds nothing to match, and the **old value stays in the target forever**. Filtering inside the aggregate with `case when` keeps the group alive so it merges to NULL.

### The audit baseline is a frozen table

`customer_orders_legacy` is `materialized: table` deliberately, so audits don't re-run the legacy SQL every time. After changing raw data it therefore reflects the *old* state, and a parity comparison shows differences that are not drift. Rebuild it before comparing.

For measuring incremental drift specifically, comparing against a full refresh of the same model is the sharper test — the legacy audit answers a different question.

### `dbt show --inline` appends its own `LIMIT`

An inner `limit N` in the inline SQL fails with `syntax error line 5 at position 2 unexpected 'limit'`. Use `--limit N`. Same root cause as the semicolon problem in [06](06-snapshots.md) — dbt wraps the query and the tail lands inside the wrapper.

### A single-valued watermark column is degenerate

`raw.stripe.payment` has 120 rows and **one** distinct `_batched_at`: the whole table was loaded once. With one distinct value, `>= max(...)` matches every row on every run and `>` matches none, forever. Neither is an incremental run. Worth profiling the watermark column before designing around it:

```sql
select count(*), count(distinct _batched_at), min(_batched_at), max(_batched_at) from ...
```

`raw.jaffle_shop.orders` has 3 distinct values, so it is the only real watermark in the project — and it feeds the one model where incremental is structurally unsafe.

### Out-of-order arrival is invisible until two rows share a partition

The orders batches loaded id 104 at 07:22 and ids 100–103 at 07:37 — `_etl_loaded_at` order inverted against `id` order. Nothing broke, but only because those five orders belong to five different customers, so no window partition saw out-of-order arrival. One shared customer and the earlier-loaded row would hold a stale `customer_sales_seq`. Passing tests here proved coincidence, not correctness.

## Open questions

- `incremental_strategy: delete+insert` is the usual answer for hard deletes. What does it cost against `merge` on Snowflake, and does it need the same `unique_key`?
- dbt 1.9's `microbatch` strategy splits the run into time-based batches with `event_time`. Does it handle the key-mismatch problem any better, or does it just automate the watermark?
- Snowflake dynamic tables solve incrementality in the warehouse rather than in dbt. Where's the line — when is a dynamic table the better answer than an incremental model?
