-- Generated staging model for source erp.journal_lines (entity: gl_entry).
-- Renames to canonical fields, casts types, applies reviewed transforms, hashes or drops PII,
-- and flags (never deletes) rows excluded by reviewed row filters.
with source as (
    select * from {{ source('erp', 'journal_lines') }}
)

select
    cast("je_id" as varchar) as journal_id,
    cast("line_no" as bigint) as line_number,
    cast("acct_code" as varchar) as account_code,
    cast("posting_date" as date) as posting_date,
    cast("debit" as decimal(18, 2)) as debit_amount,
    cast("credit" as decimal(18, 2)) as credit_amount,
    cast("entity_code" as varchar) as entity_code,
    false as _excluded
from source
