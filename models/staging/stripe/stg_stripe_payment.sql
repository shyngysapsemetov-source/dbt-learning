with source as (
    select * from {{source('stripe','payment')}}
),

transformed as (
    select orderid             as order_id
         , id                  as payment_id
         , paymentmethod       as payment_method
         , status              as payment_status
         , amount / 100.0      as payment_amount
         , created             as payment_created_at
         , _batched_at
    from source
)

select * from transformed