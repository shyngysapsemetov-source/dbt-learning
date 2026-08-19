with

orders as(
    select * from {{ref('stg_jaffle_shop_orders')}}
),

payments as(
    select * from {{ref('stg_stripe_payment')}}
    where payment_status <> 'fail'
),

total_order_amounts as(
    select order_id
         , max(payment_created_at) as payment_finalized_date
         , sum(payment_amount)     as total_order_amount
    from payments
    group by 1
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
        
    left join total_order_amounts as toa 
    on orders.order_id = toa.order_id

)

select * from paid_orders