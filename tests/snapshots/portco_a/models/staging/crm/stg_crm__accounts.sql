-- Generated staging model for source crm.accounts (entity: customer).
-- Renames to canonical fields, casts types, applies reviewed transforms, hashes or drops PII,
-- and flags (never deletes) rows excluded by reviewed row filters.
-- owner_email -> owner_email_hash: PII hashed with sha256
-- created_dt -> created_date: reviewed transform parse_mixed_date
with source as (
    select * from {{ source('crm', 'accounts') }}
)

select
    cast("acct_id" as varchar) as crm_account_id,
    cast("acct_nm" as varchar) as customer_name,
    cast("industry" as varchar) as industry,
    sha256(cast("owner_email" as varchar)) as owner_email_hash,
    cast(coalesce(try_strptime(cast("created_dt" as varchar), '%Y-%m-%d'), try_strptime(cast("created_dt" as varchar), '%m/%d/%Y')) as date) as created_date,
    cast("is_deleted" as boolean) as is_deleted,
    (coalesce(regexp_matches(cast("acct_nm" as varchar), '^(TEST|Test|test)\b'), false) or coalesce(cast("is_deleted" as boolean), false)) as _excluded
from source
