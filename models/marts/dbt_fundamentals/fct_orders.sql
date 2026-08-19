with orders as (

    select * from {{ref('stg_jaffle_shop_orders')}}

),

payments as (
    select * from {{ref('stg_stripe_payment')}}
),

order_payments as (
    select order_id
         , sum(case when payment_status = 'success' then payment_amount end) as amount
    from payments
    group by order_id
),

final as (
    select o.order_id
         , o.customer_id
         , o.order_placed_at
         , coalesce(op.amount, 0) as amount
    from orders as o
    left join order_payments as op
    on o.order_id = op.order_id
)

select *
from final