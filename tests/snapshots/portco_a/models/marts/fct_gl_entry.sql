-- Generated mart fct_gl_entry for entity gl_entry (system of record: erp.journal_lines).
select
    p.journal_id,
    p.line_number,
    p.account_code,
    p.posting_date,
    p.debit_amount,
    p.credit_amount,
    p.entity_code,
    l1.account_type,
    cast(p.journal_id as varchar) || '|' || cast(p.line_number as varchar) as gl_entry_key,
    true as _in_scope
from {{ ref('int_erp__journal_lines') }} as p
left join {{ ref('int_erp__gl_accounts') }} as l1
    on l1.account_code = p.account_code
where not p._excluded_effective
