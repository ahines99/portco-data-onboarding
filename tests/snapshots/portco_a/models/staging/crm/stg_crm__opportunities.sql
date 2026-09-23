-- Generated staging model for source crm.opportunities (entity: opportunity).
-- Renames to canonical fields, casts types, applies reviewed transforms, hashes or drops PII,
-- and flags (never deletes) rows excluded by reviewed row filters.
with source as (
    select * from {{ source('crm', 'opportunities') }}
)

select
    cast("opp_id" as varchar) as opportunity_id,
    cast("acct_id" as varchar) as crm_account_id,
    cast("rev" as decimal(18, 2)) as amount,
    cast("stage" as varchar) as stage,
    cast("close_date" as date) as close_date,
    false as _excluded
from source
