with

orders as(
    select * from {{ref('stg_jaffle_shop_orders')}}
),

-- Payment rollup lives in int_order_payments, which is incremental: an order's
-- total depends only on its own payments, so its group key is also its merge key.
-- The windows below cannot make that claim, which is why this model is a table.
order_payments as(
    select * from {{ref('int_order_payments')}}
),

paid_orders as (
    
    select orders.order_id
         , orders.customer_id
         , orders.order_placed_at
         , orders.order_status
         , toa.total_order_amount
         , toa.payment_finalized_date
         -- sequence of transactions in the system
         , row_number() over (
               order by orders.order_id
               )                                        as transaction_seq
         -- sequenece of transactions on customer level
         , row_number() over (
               partition by orders.customer_id 
               order by orders.order_id
               )                                        as customer_sales_seq
         -- new vs returning customers
         , case when (
                rank() over(
                    partition by orders.customer_id
                    order by orders.order_placed_at, orders.order_id
                    ) = 1
                ) then 'new'
                else 'return' 
           end                                          as nvsr
         -- first order date
         , first_value(orders.order_placed_at) over(
               partition by orders.customer_id
               order by orders.order_placed_at
               )                                        as fdos
         -- customer liftime value at the specific order
         , sum(toa.total_order_amount) over(
               partition by orders.customer_id
               order by orders.order_placed_at, orders.order_id
               rows unbounded preceding
               )                                                as running_clv
    from orders
        
    left join order_payments as toa
    on orders.order_id = toa.order_id

)

select * from paid_orders