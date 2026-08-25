with

{% if is_incremental() %}
-- Orders touched by a payment inserted or updated since the last run.
-- Deliberately NOT filtered on payment_status: a payment flipping to 'fail' has to
-- mark its order dirty too, or the order would silently keep its pre-flip total.
touched_orders as (
    select distinct order_id
    from {{ ref('stg_stripe_payment') }}
    where _batched_at >= (
        select coalesce(max(t._batched_at), '1900-01-01'::timestamp)
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
         -- Scale pinned on purpose. Snowflake cannot ALTER a NUMBER's scale, so
         -- on_schema_change: sync_all_columns hard-fails when an upstream expression
         -- change moves it. Declaring it here makes the stored type a contract instead
         -- of a by-product of however payment_amount happens to be computed today.
         , cast(sum(case when payment_status <> 'fail' then payment_amount end)
                as number(38, 2))                                             as total_order_amount
         -- Watermark for the next incremental run.
         , max(_batched_at)                                                    as _batched_at
    from payments
    group by 1
)

select * from order_payments
