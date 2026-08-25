{#
    Convert an integer cents column to dollars.

    `round(..., decimal_places)` fixes the result's scale, which a bare `/ 100` does not.
    That is a schema decision, not just a formatting one: any incremental model that
    stores the result inherits the scale, and Snowflake cannot ALTER a NUMBER's scale
    afterwards. See notes/05-incremental-models.md.
#}
{%- macro cents_to_dollars(column_name, decimal_places=2) -%}
   round({{ column_name }} * 1.0 / 100, {{ decimal_places }})
{%- endmacro -%}
