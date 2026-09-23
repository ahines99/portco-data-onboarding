-- Generated staging model for source erp.gl_accounts (entity: gl_account).
-- Renames to canonical fields, casts types, applies reviewed transforms, hashes or drops PII,
-- and flags (never deletes) rows excluded by reviewed row filters.
with source as (
    select * from {{ source('erp', 'gl_accounts') }}
)

select
    cast("acct_code" as varchar) as account_code,
    cast("acct_name" as varchar) as account_name,
    cast("acct_type" as varchar) as account_type,
    false as _excluded
from source
