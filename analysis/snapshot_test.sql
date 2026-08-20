select *
from {{ref('orders_snapshot')}}
where id between 100 and 104
order by id, dbt_valid_from