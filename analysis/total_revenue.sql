with payments as (
    select * from {{ref('stg_stripe_payment')}}
    where payment_status = 'success'
)

select sum(payment_amount) as total_revenue
from payments