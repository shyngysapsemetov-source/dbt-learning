# Source column types (Snowflake, exported 2026-08-29)


## ANALYTICS.DBT_LEARNING_SNAPSHOTS.ORDERS_SNAPSHOT

| # | column | type | prec | scale | nullable |
|---|---|---|---|---|---|
| 1 | `ID` | NUMBER | 38 | 0 | YES |
| 2 | `USER_ID` | NUMBER | 38 | 0 | YES |
| 3 | `ORDER_DATE` | DATE |  |  | YES |
| 4 | `STATUS` | TEXT |  |  | YES |
| 5 | `_ETL_LOADED_AT` | TIMESTAMP_NTZ |  |  | YES |
| 6 | `DBT_SCD_ID` | TEXT |  |  | YES |
| 7 | `DBT_UPDATED_AT` | TIMESTAMP_NTZ |  |  | YES |
| 8 | `DBT_VALID_FROM` | TIMESTAMP_NTZ |  |  | YES |
| 9 | `DBT_VALID_TO` | TIMESTAMP_NTZ |  |  | YES |

## RAW.JAFFLE_SHOP.CUSTOMERS

| # | column | type | prec | scale | nullable |
|---|---|---|---|---|---|
| 1 | `ID` | NUMBER | 38 | 0 | YES |
| 2 | `FIRST_NAME` | TEXT |  |  | YES |
| 3 | `LAST_NAME` | TEXT |  |  | YES |

## RAW.JAFFLE_SHOP.ORDERS

| # | column | type | prec | scale | nullable |
|---|---|---|---|---|---|
| 1 | `ID` | NUMBER | 38 | 0 | YES |
| 2 | `USER_ID` | NUMBER | 38 | 0 | YES |
| 3 | `ORDER_DATE` | DATE |  |  | YES |
| 4 | `STATUS` | TEXT |  |  | YES |
| 5 | `_ETL_LOADED_AT` | TIMESTAMP_NTZ |  |  | YES |

## RAW.STRIPE.PAYMENT

| # | column | type | prec | scale | nullable |
|---|---|---|---|---|---|
| 1 | `ID` | NUMBER | 38 | 0 | YES |
| 2 | `ORDERID` | NUMBER | 38 | 0 | YES |
| 3 | `PAYMENTMETHOD` | TEXT |  |  | YES |
| 4 | `STATUS` | TEXT |  |  | YES |
| 5 | `AMOUNT` | NUMBER | 38 | 0 | YES |
| 6 | `CREATED` | DATE |  |  | YES |
| 7 | `_BATCHED_AT` | TIMESTAMP_NTZ |  |  | YES |

## RAW_MESH.JAFFLE_SHOP.CUSTOMERS

| # | column | type | prec | scale | nullable |
|---|---|---|---|---|---|
| 1 | `ID` | TEXT |  |  | YES |
| 2 | `NAME` | TEXT |  |  | YES |

## RAW_MESH.JAFFLE_SHOP.ITEMS

| # | column | type | prec | scale | nullable |
|---|---|---|---|---|---|
| 1 | `ID` | TEXT |  |  | YES |
| 2 | `ORDER_ID` | TEXT |  |  | YES |
| 3 | `SKU` | TEXT |  |  | YES |

## RAW_MESH.JAFFLE_SHOP.ORDERS

| # | column | type | prec | scale | nullable |
|---|---|---|---|---|---|
| 1 | `ID` | TEXT |  |  | YES |
| 2 | `CUSTOMER` | TEXT |  |  | YES |
| 3 | `ORDERED_AT` | TIMESTAMP_NTZ |  |  | YES |
| 4 | `STORE_ID` | TEXT |  |  | YES |
| 5 | `SUBTOTAL` | NUMBER | 38 | 0 | YES |
| 6 | `TAX_PAID` | NUMBER | 38 | 0 | YES |
| 7 | `ORDER_TOTAL` | NUMBER | 38 | 0 | YES |

## RAW_MESH.JAFFLE_SHOP.PRODUCTS

| # | column | type | prec | scale | nullable |
|---|---|---|---|---|---|
| 1 | `SKU` | TEXT |  |  | YES |
| 2 | `NAME` | TEXT |  |  | YES |
| 3 | `TYPE` | TEXT |  |  | YES |
| 4 | `PRICE` | NUMBER | 38 | 0 | YES |
| 5 | `DESCRIPTION` | TEXT |  |  | YES |

## RAW_MESH.JAFFLE_SHOP.STORES

| # | column | type | prec | scale | nullable |
|---|---|---|---|---|---|
| 1 | `ID` | TEXT |  |  | YES |
| 2 | `NAME` | TEXT |  |  | YES |
| 3 | `OPENED_AT` | TIMESTAMP_NTZ |  |  | YES |
| 4 | `TAX_RATE` | NUMBER | 38 | 4 | YES |

## RAW_MESH.JAFFLE_SHOP.SUPPLIES

| # | column | type | prec | scale | nullable |
|---|---|---|---|---|---|
| 1 | `ID` | TEXT |  |  | YES |
| 2 | `NAME` | TEXT |  |  | YES |
| 3 | `COST` | NUMBER | 38 | 0 | YES |
| 4 | `PERISHABLE` | BOOLEAN |  |  | YES |
| 5 | `SKU` | TEXT |  |  | YES |
