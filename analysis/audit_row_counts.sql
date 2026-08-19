-- Compare row counts: legacy customer_orders vs fct_customer_orders
-- Run with:  dbt compile --select audit_row_counts
-- then paste target/compiled/.../audit_row_counts.sql into Snowflake.

{% set old_relation = ref('customer_orders_legacy') %}

{% set dbt_relation = ref('fct_customer_orders') %}

{{ audit_helper.compare_row_counts(
    a_relation = old_relation,
    b_relation = dbt_relation
) }}
