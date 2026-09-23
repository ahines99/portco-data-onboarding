-- Generated mart fct_invoice for entity invoice (system of record: billing.invoices).
select
    p.invoice_id,
    p.customer_id,
    p.invoice_date,
    p.due_date,
    p.total_amount,
    p.currency,
    p.status,
    true as _in_scope
from {{ ref('int_billing__invoices') }} as p
where not p._excluded_effective
