-- Daily time spine required by the semantic layer.
select cast(d as date) as date_day
from (
    select unnest(generate_series(timestamp '2015-01-01', timestamp '2035-12-31', interval 1 day)) as d
)
