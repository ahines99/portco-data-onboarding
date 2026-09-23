-- Generated staging model for source billing.customers (entity: customer).
-- Renames to canonical fields, casts types, applies reviewed transforms, hashes or drops PII,
-- and flags (never deletes) rows excluded by reviewed row filters.
-- billing_email -> billing_email_hash: PII hashed with sha256
with source as (
    select * from {{ source('billing', 'customers') }}
)

select
    cast("cust_id" as varchar) as customer_id,
    cast("crm_account_ref" as varchar) as crm_account_id,
    cast("cust_name" as varchar) as customer_name,
    sha256(cast("billing_email" as varchar)) as billing_email_hash,
    cast("country" as varchar) as country,
    cast("currency" as varchar) as currency,
    (coalesce(starts_with(cast("cust_name" as varchar), 'TEST'), false)) as _excluded
from source
