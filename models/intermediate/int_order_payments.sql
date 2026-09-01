with

{% if is_incremental() %}
-- Orders touched by a payment inserted or updated since the last run.
-- Deliberately NOT filtered on payment_status: a payment flipping to 'fail' has to
-- mark its order dirty too, or the order would silently keep its pre-flip total.
touched_orders as (
    select distinct order_id
    from {{ ref('stg_stripe_payment') }}
    where _batched_at >= (
        select coalesce(max(t._batched_at), cast('1900-01-01' as timestamp))
        from {{ this }} as t
    )
),
{% endif %}

-- Every payment for the orders in scope, at any status. Full history per order and
-- not just the new rows, because sum() and max() need all of an order's payments.
payments as (
    select * from {{ ref('stg_stripe_payment') }}
    {% if is_incremental() %}
    where order_id in (select order_id from touched_orders)
    {% endif %}
),

order_payments as (
    select order_id
         -- Failed payments are excluded from the money columns, but their rows still
         -- hold the group open. An order whose payments have all failed therefore
         -- merges as NULL instead of going stale, since merge cannot delete a row.
         , max(case when payment_status <> 'fail' then payment_created_at end) as payment_finalized_date
         -- Type pinned on purpose, and the reason survives the migration. Originally this
         -- was number(38,2) because Snowflake cannot ALTER a NUMBER's scale, so
         -- on_schema_change: sync_all_columns hard-failed when an upstream expression change
         -- moved it. BigQuery is no more forgiving -- ALTER COLUMN SET DATA TYPE only widens
         -- (INT64 -> NUMERIC -> BIGNUMERIC -> FLOAT64) -- so declaring the stored type is
         -- still what stops it being a by-product of however payment_amount is computed.
         -- Plain NUMERIC, not NUMERIC(38,2): the scale already comes from cents_to_dollars'
         -- round(..., 2), and a parameterised type adds a second place for the same fact to
         -- be stated and drift.
         , cast(sum(case when payment_status <> 'fail' then payment_amount end)
                as numeric)                                                   as total_order_amount
         -- Watermark for the next incremental run.
         , max(_batched_at)                                                    as _batched_at
    from payments
    group by 1
)

select * from order_payments
