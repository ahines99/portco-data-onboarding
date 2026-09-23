-- Scoping model for erp.journal_lines: a row is out of scope when it is excluded itself, or when the
-- parent row it references (in a different entity) is out of scope.
select
    s.*,
    (s._excluded or coalesce(p1._excluded_effective, false)) as _excluded_effective
from {{ ref('stg_erp__journal_lines') }} as s
left join (
    select account_code, bool_or(_excluded_effective) as _excluded_effective
    from {{ ref('int_erp__gl_accounts') }}
    group by 1
) as p1 on p1.account_code = s.account_code
