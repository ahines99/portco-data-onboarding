-- Generated mart dim_contact for entity contact (system of record: crm.contacts).
select
    p.contact_id,
    p.crm_account_id,
    p.first_name_hash,
    p.last_name_hash,
    p.email_hash,
    p.phone_hash,
    true as _in_scope
from {{ ref('int_crm__contacts') }} as p
where not p._excluded_effective
