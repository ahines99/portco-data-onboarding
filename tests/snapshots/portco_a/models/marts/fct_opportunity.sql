-- Generated mart fct_opportunity for entity opportunity (system of record: crm.opportunities).
select
    p.opportunity_id,
    p.crm_account_id,
    p.amount,
    p.stage,
    p.close_date,
    true as _in_scope
from {{ ref('int_crm__opportunities') }} as p
where not p._excluded_effective
