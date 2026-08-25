{%- set payment_methods = ['credit_card', 'coupon', 'bank_transfer', 'gift_card'] -%}

with payments as (
    select * from {{ref('stg_stripe_payment')}}
    where payment_status = 'success'
),

pivoted as (
    select order_id
           {% for method in payment_methods %}
         , sum(case when payment_method = '{{method}}' then payment_amount end) as {{method}}_amount
           {% endfor %}
    from payments
    group by 1
)

select *
from pivoted