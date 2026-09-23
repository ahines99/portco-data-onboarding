-- Generated mart fct_invoice_line for entity invoice_line (system of record: billing.invoice_lines).
select
    p.invoice_line_id,
    p.invoice_id,
    p.sku,
    p.quantity,
    p.amount,
    true as _in_scope
from {{ ref('int_billing__invoice_lines') }} as p
where not p._excluded_effective
