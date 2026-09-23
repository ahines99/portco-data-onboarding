-- Generated mart fct_payment for entity payment (system of record: billing.payments).
select
    p.payment_id,
    p.invoice_id,
    p.paid_at,
    p.amount,
    p.method,
    p.card_last4,
    true as _in_scope
from {{ ref('int_billing__payments') }} as p
where not p._excluded_effective
