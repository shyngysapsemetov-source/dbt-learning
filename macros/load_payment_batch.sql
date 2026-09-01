{#
    Test harness for the int_order_payments incremental model.

    Simulates a source batch in raw_stripe.payment covering the three mutation
    classes a watermark has to survive. Every statement sets _batched_at to
    current_timestamp(): that bump IS the loading contract. An update that forgets
    it is invisible to the incremental run and silently corrupts the target.

      (a) insert  id 1001 -> order 100, an order that had no payments at all
      (b) insert  id 1002 -> order 1, a late payment against a 2018 order
      (c) update  id 33   -> status 'fail', which must lower order 25's total

    Deletes are deliberately absent: a removed row has no timestamp left to move,
    so no watermark can carry it. Model them as status changes instead.

    Run:     dbt run-operation load_payment_batch
    Undo:    dbt run-operation revert_payment_batch
#}

{% macro load_payment_batch() %}

    {% set insert_new_order_payment %}
        insert into raw_stripe.payment
            (id, orderid, paymentmethod, status, amount, created, _batched_at)
        select 1001, 100, 'credit_card', 'success', 2500, date '2025-02-15', current_timestamp()
        from unnest([1])
        where not exists (select 1 from raw_stripe.payment where id = 1001)
    {% endset %}

    {% set insert_late_payment %}
        insert into raw_stripe.payment
            (id, orderid, paymentmethod, status, amount, created, _batched_at)
        select 1002, 1, 'coupon', 'success', 1500, date '2026-08-22', current_timestamp()
        from unnest([1])
        where not exists (select 1 from raw_stripe.payment where id = 1002)
    {% endset %}

    {% set flip_status_to_fail %}
        update raw_stripe.payment
           set status = 'fail'
             , _batched_at = current_timestamp()
         where id = 33
           and status = 'success'
    {% endset %}

    {% do log("(a) inserting payment 1001 for order 100 (previously unpaid)", info=True) %}
    {% do run_query(insert_new_order_payment) %}

    {% do log("(b) inserting payment 1002 for order 1 (late payment, 2018 order)", info=True) %}
    {% do run_query(insert_late_payment) %}

    {% do log("(c) flipping payment 33 to 'fail' (order 25 total should drop 58 -> 42)", info=True) %}
    {% do run_query(flip_status_to_fail) %}

    {% do log("batch loaded", info=True) %}

{% endmacro %}


{% macro revert_payment_batch() %}

    {% set remove_inserts %}
        delete from raw_stripe.payment where id in (1001, 1002)
    {% endset %}

    {% set unflip_status %}
        update raw_stripe.payment
           set status = 'success'
             , _batched_at = current_timestamp()
         where id = 33
           and status = 'fail'
    {% endset %}

    {% do log("removing test payments 1001, 1002", info=True) %}
    {% do run_query(remove_inserts) %}

    {% do log("restoring payment 33 to 'success'", info=True) %}
    {% do run_query(unflip_status) %}

    {% do log("reverted -- rebuild with: dbt run --select int_order_payments+ --full-refresh", info=True) %}

{% endmacro %}
