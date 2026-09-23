-- Generated staging model for source crm.contacts (entity: contact).
-- Renames to canonical fields, casts types, applies reviewed transforms, hashes or drops PII,
-- and flags (never deletes) rows excluded by reviewed row filters.
-- first_name -> first_name_hash: PII hashed with sha256
-- last_name -> last_name_hash: PII hashed with sha256
-- email -> email_hash: PII hashed with sha256
-- phone -> phone_hash: PII hashed with sha256
with source as (
    select * from {{ source('crm', 'contacts') }}
)

select
    cast("contact_id" as varchar) as contact_id,
    cast("acct_id" as varchar) as crm_account_id,
    sha256(cast("first_name" as varchar)) as first_name_hash,
    sha256(cast("last_name" as varchar)) as last_name_hash,
    sha256(cast("email" as varchar)) as email_hash,
    sha256(cast("phone" as varchar)) as phone_hash,
    false as _excluded
from source
