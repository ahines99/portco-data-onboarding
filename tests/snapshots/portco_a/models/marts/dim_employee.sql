-- Generated mart dim_employee for entity employee (system of record: hr.employees).
select
    p.employee_id,
    p.full_name_hash,
    p.department,
    p.hire_date,
    p.termination_date,
    p.salary,
    true as _in_scope
from {{ ref('int_hr__employees') }} as p
where not p._excluded_effective
