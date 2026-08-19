with
-- Import CTEs

customers as(
    select * from {{ref('dim_customers')}}
),

orders as (
    select * from {{ref('fct_orders')}}
),

-- Final CTE
final_cte as (
    
    select orders.order_id
         , orders.customer_id
         , orders.order_placed_at
         , orders.order_status
         , orders.total_order_amount as total_amount_paid
         , orders.payment_finalized_date
         , customers.customer_first_name
         , customers.customer_last_name
         , orders.transaction_seq
         , orders.customer_sales_seq
         , orders.nvsr
         , orders.running_clv
         , orders.fdos
    from orders
        
    left join customers
    on orders.customer_id = customers.customer_id
)

-- Final select statement
select * from final_cte