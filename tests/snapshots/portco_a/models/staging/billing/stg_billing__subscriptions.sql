-- Generated staging model for source billing.subscriptions (entity: subscription).
-- Renames to canonical fields, casts types, applies reviewed transforms, hashes or drops PII,
-- and flags (never deletes) rows excluded by reviewed row filters.
with source as (
    select * from {{ source('billing', 'subscriptions') }}
)

select
    cast("sub_id" as varchar) as subscription_id,
    cast("cust_id" as varchar) as customer_id,
    cast("plan_code" as varchar) as plan_code,
    cast("mrr_amt" as decimal(18, 2)) as mrr,
    cast("currency" as varchar) as currency,
    cast("start_dt" as date) as start_date,
    cast("end_dt" as date) as end_date,
    cast("status" as varchar) as status,
    false as _excluded
from source
