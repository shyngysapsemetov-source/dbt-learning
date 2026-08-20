# Python Models

**Status:** complete

A standalone video on the certification path rather than a numbered course.

## What it covers

Writing a dbt model in Python instead of SQL. The model is a `.py` file defining one function, `model(dbt, session)`, that returns a dataframe; dbt wraps it in a stored procedure and runs it in the warehouse.

## Key concepts

### The shape of a Python model

```python
def model(dbt, session):
    dbt.config(materialized="table", packages=["pandas", "pyarrow", "holidays"])
    df = dbt.ref("date_spine").to_pandas()
    ...
    return df
```

- No Jinja. `{{ ref() }}` becomes `dbt.ref()`, `{{ config() }}` becomes `dbt.config()`, both as real Python calls.
- Must be materialized as `table` or `incremental` — a Python model can't be a view, since there's no SQL to put in one.
- Third-party imports have to be declared in `packages`, and on Snowflake must exist in its Anaconda channel. The code runs in the warehouse, not on your machine, so your local environment is irrelevant.
- `dbt.ref()` returns a Snowpark dataframe. `.to_pandas()` converts it, which is also the moment the whole relation is pulled into the warehouse's Python memory.

### When it's the right tool

For anything expressible in SQL, it isn't — a Python model costs a stored procedure round trip and hides logic from the SQL-literate. It earns its place when the transformation genuinely has no SQL form: a library like `holidays` encoding external domain knowledge, statistical fitting, or calling out to a model.

Built here: `is_holiday_2024`, flagging each day of a 2024 date spine against `holidays.US()`. The holiday calendar is the justification — there is no reasonable SQL for "is this a US federal holiday", so the alternative is a hand-maintained seed that goes stale every year.

## Commands used

```bash
dbt run --select is_holiday_2024
```

## Gotchas hit

### `to_pandas()` needs pyarrow, and says pandas is missing when it's absent

First run failed with a wall of Snowflake traceback ending in:

```
255002: Optional dependency: 'pandas' is not installed
```

`pandas` *was* declared in `packages`, and the `import pandas` at the top of the file had already succeeded — the failure was inside `to_pandas()`. Arrow is what actually materializes a Snowflake result set into a dataframe, so the connector's "can I use pandas" check fails when **pyarrow** is missing, and reports the missing dependency as pandas.

Fix: `packages=['pandas', 'pyarrow', 'holidays']`. Worth knowing the error names the wrong library, because the obvious reading sends you off checking your pandas declaration, which is already correct.

### Snowflake hands back upper-case column names

```python
df['is_holiday'] = df['date_day'].apply(...)   # KeyError: 'date_day'
```

The upstream model selects an unquoted `date_day`, which Snowflake stores as `DATE_DAY`. Snowpark preserves that case into pandas, so lowercase lookups miss. Named the new column `IS_HOLIDAY` to match, which also keeps the output table's column unquoted — a lowercase `is_holiday` would arrive as `"is_holiday"` and need quoting in every downstream query forever.

The general rule: identifier case is the warehouse's, not Python's, the moment data crosses that boundary.

### `to_pandas()` moves the whole table into memory

Fine for 366 rows. On a real table it's the thing that breaks, since the sproc gets the warehouse node's memory and nothing more. The alternative is to stay in Snowpark and push the comparison down —

```python
df.with_column('IS_HOLIDAY', F.col('DATE_DAY').isin(holiday_dates))
```

— which computes in the warehouse and never materializes a dataframe. Only the small holiday list crosses into Python.

## Open questions

- Where does a Python model's `packages` list get pinned? Nothing here pins versions, so a Snowflake Anaconda channel update could change behaviour between runs.
