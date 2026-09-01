{#
    Convert an integer cents column to dollars.

    `round(..., decimal_places)` fixes the result's scale, which a bare `/ 100` does not.
    That is a schema decision, not just a formatting one: any incremental model that
    stores the result inherits the scale, and neither Snowflake nor BigQuery can widen a
    decimal's scale afterwards. See notes/05-incremental-models.md.

    The `cast(... as numeric)` is a BigQuery requirement, not decoration. This macro used
    to read `{{ column_name }} * 1.0 / 100`, which is exact in Snowflake because `1.0` is
    NUMBER(2,1) there -- but `1.0` is a **FLOAT64 literal** in BigQuery, so the whole
    expression, and every money column derived from it, silently became floating point.
    Verified rather than assumed: `select round(2500 * 1.0 / 100, 2)` reports type FLOAT
    on BigQuery. Casting the cents to NUMERIC first keeps the division exact decimal.
#}
{%- macro cents_to_dollars(column_name, decimal_places=2) -%}
   round(cast({{ column_name }} as numeric) / 100, {{ decimal_places }})
{%- endmacro -%}
