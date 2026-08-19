-- Compare column values: legacy customer_orders vs fct_customer_orders
-- Run with:  dbt compile --select audit_all_columns
-- then paste target/compiled/.../audit_all_columns.sql into Snowflake.
--
-- The legacy query lives in the project as models/legacy/customer_orders_legacy.sql,
-- so ref() resolves it: no adapter.get_relation, no hardcoded schema, and no need for
-- an "if execute" guard, because ref() resolves at parse time in every environment.

{% set old_relation = ref('customer_orders_legacy') %}

{% set dbt_relation = ref('fct_customer_orders') %}

{{ audit_helper.compare_all_columns(
    a_relation = old_relation,
    b_relation = dbt_relation,
    primary_key = "order_id"
) }}
