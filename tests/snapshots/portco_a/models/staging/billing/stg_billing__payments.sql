-- Generated staging model for source billing.payments (entity: payment).
-- Renames to canonical fields, casts types, applies reviewed transforms, hashes or drops PII,
-- and flags (never deletes) rows excluded by reviewed row filters.
-- card_number -> card_number: excluded (PII, never materialized)
with source as (
    select * from {{ source('billing', 'payments') }}
)

select
    cast("pmt_id" as varchar) as payment_id,
    cast("inv_no" as varchar) as invoice_id,
    cast("paid_at" as timestamp) as paid_at,
    cast("amount" as decimal(18, 2)) as amount,
    cast("method" as varchar) as method,
    cast("card_last4" as varchar) as card_last4,
    false as _excluded
from source
