-- Month-end MRR snapshot per customer and currency. A subscription is active at a month end
-- when start_date <= month_end < end_date (end dates are exclusive; null means active).
with subs as (
    select * from {{ ref('fct_subscription') }}
),

months as (
    select cast(month_start + interval 1 month - interval 1 day as date) as month_end
    from (
        select unnest(generate_series(
            cast(date_trunc('month', (select min(start_date) from subs)) as timestamp),
            cast('{{ var("as_of_month") }}' as timestamp),
            interval 1 month
        )) as month_start
    )
)

select
    cast(s.customer_id as varchar) || '|' || s.currency || '|' || cast(m.month_end as varchar) as mrr_snapshot_id,
    m.month_end,
    s.customer_id,
    s.currency,
    cast(sum(s.mrr) as decimal(18, 2)) as mrr
from months as m
inner join subs as s
    on s.start_date <= m.month_end
    and (s.end_date is null or s.end_date > m.month_end)
group by 1, 2, 3, 4
