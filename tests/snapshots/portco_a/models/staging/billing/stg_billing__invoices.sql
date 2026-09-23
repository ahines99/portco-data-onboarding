-- Generated staging model for source billing.invoices (entity: invoice).
-- Renames to canonical fields, casts types, applies reviewed transforms, hashes or drops PII,
-- and flags (never deletes) rows excluded by reviewed row filters.
with source as (
    select * from {{ source('billing', 'invoices') }}
)

select
    cast("inv_no" as varchar) as invoice_id,
    cast("cust_id" as varchar) as customer_id,
    cast("inv_date" as date) as invoice_date,
    cast("due_date" as date) as due_date,
    cast("total_amt" as decimal(18, 2)) as total_amount,
    cast("currency" as varchar) as currency,
    cast("status" as varchar) as status,
    false as _excluded
from source
