-- Compare column values: legacy customer_orders vs fct_customer_orders
-- Run with:  dbt compile --select audit_all_columns
-- then paste target/compiled/.../audit_all_columns.sql into Snowflake.

{% set old_relation = adapter.get_relation(
      database = target.database,
      schema = "dbt_learning",
      identifier = "customer_orders_legacy"
) -%}

{% set dbt_relation = ref('fct_customer_orders') %}

{{ audit_helper.compare_all_columns(
    a_relation = old_relation,
    b_relation = dbt_relation,
    primary_key = "order_id"
) }}
