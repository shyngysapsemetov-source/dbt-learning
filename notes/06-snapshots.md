# 06 — Snapshots

**Status:** complete

## What this course covers

Capturing how a mutable source row changed over time — slowly changing dimensions, Type 2.

## Key concepts

Sources get overwritten in place. A row's current state is all the warehouse has; the history is gone unless something captured it. Snapshots are that something.

`raw.jaffle_shop.orders` is the textbook case. An order moves `placed` → `shipped` → `completed`, and the table only ever holds the current status. "How long did orders sit in `shipped` before completing?" is permanently unanswerable without a snapshot — you cannot backfill history that was never written down.

### The YAML format

dbt 1.9 moved snapshots out of `{% snapshot %}` blocks in `.sql` files and into `.yml`. Fusion supports only the YAML form, so `snapshots/snapshots.yml` here is:

```yaml
snapshots:
  - name: orders_snapshot
    relation: source('jaffle_shop', 'orders')
    config:
      schema: snapshots
      database: analytics
      unique_key: id
      strategy: check
      check_cols: ['id', 'user_id', 'order_date', 'status']
      hard_deletes: ignore
      dbt_valid_to_current: "to_date('9999-12-31')"
```

Older course material and most blog posts show the block form with `target_schema`. Same behaviour, deprecated syntax.

### Two strategies

- `timestamp` — needs a reliable `updated_at`. Cheaper, since it compares one column.
- `check` — compares the columns in `check_cols`. Use when there's no trustworthy timestamp, or `check_cols: all`.

`check` is the right call for this table. `_etl_loaded_at` looks like a usable `updated_at`, but nothing forces a writer to bump it — an `UPDATE` that changes `status` and forgets the timestamp would be **invisible** to a `timestamp` snapshot. No error, just a silently missed version. `check` compares the values themselves, so it catches the change regardless.

### Metadata columns

`dbt_valid_from` / `dbt_valid_to` bound each version. The current row normally has `dbt_valid_to is null`; `dbt_valid_to_current` replaces that null with a sentinel, which makes "current" filterable with `=` instead of `is null` and avoids null-handling in every downstream join.

`hard_deletes: ignore` (the default) means a row disappearing from the source is left untouched in the snapshot — it stays looking current forever. The alternatives are `invalidate` (close it off) and `new_record` (write a tombstone row).

## Built here

`orders_snapshot` over `source('jaffle_shop', 'orders')`, plus `analysis/snapshot_test.sql` to inspect it.

Rows 100–104 were inserted into the source specifically to have records safe to mutate, rather than editing the 99 original course rows. They went in as `placed`; 100–103 were then promoted to `shipped`, with **104 deliberately left alone** as a control.

Result — 9 rows for 5 orders:

| id | status | dbt_valid_from | dbt_valid_to |
|---|---|---|---|
| 100 | placed | 14:36:38 | 14:37:16 |
| 100 | shipped | 14:37:16 | 9999-12-31 |
| 101–103 | *same two-version shape* | | |
| 104 | placed | 14:36:38 | 9999-12-31 |

104 staying single-versioned is the proof that the snapshot only writes rows that actually changed.

## Commands used

```bash
dbt snapshot                 # also runs as part of dbt build
dbt compile --select snapshot_test
```

## Gotchas hit

### Sequencing: snapshot before you mutate, or there is no history

The snapshot only knows what it has seen. Insert and update *before* the first `dbt snapshot`, and the initial load captures the end state as version one — a single row per id, no versioning, nothing learned. The baseline run is the exercise.

### A custom `schema:` is a suffix, not an absolute name

Config says `schema: snapshots`, so the table looks like it should be `analytics.snapshots.orders_snapshot`. It isn't. dbt's default `generate_schema_name` **appends** the custom schema to the target schema, so under target `dbt_learning` it lands at:

```
analytics.dbt_learning_snapshots.orders_snapshot
```

Querying the literal `analytics.snapshots.orders_snapshot` fails with `Schema 'ANALYTICS.SNAPSHOTS' does not exist`, which reads like the snapshot was never built. `{{ ref('orders_snapshot') }}` resolves the real name, so anything going through `ref` was fine — only hand-written paths broke. Override `generate_schema_name` if absolute schema names are wanted.

### `dbt show` misrenders the far-future sentinel

The `9999-12-31` sentinel displays as `1816-03-29T05:56:08.066277376`:

```
│ 100 ┆ shipped ┆ 2026-08-20T14:37:16.994 ┆ 1816-03-29T05:56:08.066277376 │
```

The stored value is correct — Arrow's nanosecond timestamps are int64 counts from the epoch, which top out around **2262-04-11**, so 9999 overflows and wraps on the way to the terminal. Verify server-side instead of trusting the render:

```sql
select dbt_valid_to::varchar, dbt_valid_to = to_date('9999-12-31') as matches_sentinel
```

Both confirm the real value. Worth knowing before "fixing" a config that isn't broken.

### No semicolons in dbt SQL

`analysis/snapshot_test.sql` ending in `;` failed with `syntax error line 8 at position 2 unexpected 'limit'`. dbt wraps analyses in `select * from ( ... ) limit N` for previewing, and the terminator lands inside the parentheses. The line number refers to the wrapped query, not the file. Same reason models can't contain semicolons — everything gets embedded in a CTE, a `create table as`, or a `merge`.

### Snowflake does not enforce primary keys

Relevant when setting up the source rows. Snowflake accepts `PRIMARY KEY` / `UNIQUE` / `FOREIGN KEY` declarations but only enforces `NOT NULL` — the rest are optimizer metadata. `orders` has no declared constraints at all; `id` is a primary key purely as a dbt `unique` + `not_null` test, which is an assertion checked after the data lands.

So an `INSERT` with an existing `id` appends a duplicate rather than overwriting. That breaks the snapshot's own MERGE with `Duplicate row detected during DML action` — but only on the *second* run, since the initial load is a plain insert-select that swallows duplicates silently. `MERGE` is the way to make a re-runnable load.

Also note `INSERT OVERWRITE INTO` is not a row-level upsert: it truncates the **whole table** and inserts, with no key matching. It's `TRUNCATE` + `INSERT` made atomic, useful for full-refresh reloads that need to preserve grants, and catastrophic if mistaken for an upsert.

### `_etl_loaded_at` has a DEFAULT but does not auto-update

It's an ordinary column, not Snowflake metadata — Snowflake's real pseudo-columns are `METADATA$FILENAME` on staged files and `METADATA$ACTION` / `METADATA$ISUPDATE` on streams. A regular table has no built-in modified timestamp.

It does carry `DEFAULT CURRENT_TIMESTAMP()`, so an `INSERT` that omits the column gets stamped automatically (an explicit `NULL` does not — defaults only fire when the column is absent). But there is no `ON UPDATE CURRENT_TIMESTAMP` in Snowflake, so an `UPDATE` leaves it stale unless set by hand. Since it's the `loaded_at_field` for source freshness, a pipeline that updates rows without bumping it reports the source as fresh-but-stale.

## Open questions

- `hard_deletes: new_record` writes a tombstone row — what does it put in the non-key columns, and how does that interact with `check_cols`?
- Snapshots are the one dbt object whose output can't be rebuilt from source. What's the actual backup story — Time Travel, a `create table clone`, or a copy into an audit schema?
