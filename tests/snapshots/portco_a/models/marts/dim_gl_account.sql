-- Generated mart dim_gl_account for entity gl_account (system of record: erp.gl_accounts).
select
    p.account_code,
    p.account_name,
    p.account_type,
    true as _in_scope
from {{ ref('int_erp__gl_accounts') }} as p
where not p._excluded_effective
