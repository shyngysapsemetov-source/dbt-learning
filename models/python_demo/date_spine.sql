-- The cast is a migration fix, not decoration. `dbt_utils.date_spine` returns DATE on
-- Snowflake but **DATETIME** on BigQuery, even with both bounds explicitly cast to date --
-- the widening happens inside the package's BigQuery implementation, so no amount of
-- reading this file would reveal it. Caught by check_parity.py comparing against the
-- Snowflake baseline: identical 365 values, but rendered '2024-01-01 00:00:00.000'
-- instead of '2024-01-01'. Casting back keeps date_day's type stable across the migration.
select cast(date_day as date) as date_day
from (
    {{
        dbt_utils.date_spine(
            datepart   = "day",
            start_date = "cast('2024-01-01' as date)",
            end_date   = "cast('2024-12-31' as date)"
            )
    }}
)
