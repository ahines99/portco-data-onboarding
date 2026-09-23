-- Scoping model for billing.payments: a row is out of scope when it is excluded itself, or when the
-- parent row it references (in a different entity) is out of scope.
select
    s.*,
    (s._excluded or coalesce(p1._excluded_effective, false)) as _excluded_effective
from {{ ref('stg_billing__payments') }} as s
left join (
    select invoice_id, bool_or(_excluded_effective) as _excluded_effective
    from {{ ref('int_billing__invoices') }}
    group by 1
) as p1 on p1.invoice_id = s.invoice_id
