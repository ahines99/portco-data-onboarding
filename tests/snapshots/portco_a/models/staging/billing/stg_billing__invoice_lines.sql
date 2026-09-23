-- Generated staging model for source billing.invoice_lines (entity: invoice_line).
-- Renames to canonical fields, casts types, applies reviewed transforms, hashes or drops PII,
-- and flags (never deletes) rows excluded by reviewed row filters.
-- amount -> amount: reviewed transform cents_to_major
with source as (
    select * from {{ source('billing', 'invoice_lines') }}
)

select
    cast("line_id" as varchar) as invoice_line_id,
    cast("inv_no" as varchar) as invoice_id,
    cast("sku" as varchar) as sku,
    cast("qty" as bigint) as quantity,
    cast(cast("amount" as decimal(18, 2)) / 100 as decimal(18, 2)) as amount,
    false as _excluded
from source
