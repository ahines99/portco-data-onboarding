-- Generated mart fct_subscription for entity subscription (system of record: billing.subscriptions).
select
    p.subscription_id,
    p.customer_id,
    p.plan_code,
    p.mrr,
    p.currency,
    p.start_date,
    p.end_date,
    p.status,
    true as _in_scope
from {{ ref('int_billing__subscriptions') }} as p
where not p._excluded_effective
