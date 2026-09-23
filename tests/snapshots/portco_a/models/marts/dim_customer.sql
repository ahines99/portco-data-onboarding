-- Generated mart dim_customer for entity customer (system of record: billing.customers).
select
    p.customer_id,
    p.crm_account_id,
    p.customer_name,
    p.billing_email_hash,
    p.country,
    p.currency,
    e1.industry,
    e1.owner_email_hash,
    e1.created_date,
    e1.is_deleted,
    true as _in_scope
from {{ ref('int_billing__customers') }} as p
left join {{ ref('int_crm__accounts') }} as e1
    on e1.crm_account_id = p.crm_account_id and not e1._excluded_effective
where not p._excluded_effective
