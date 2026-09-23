-- Generated staging model for source hr.employees (entity: employee).
-- Renames to canonical fields, casts types, applies reviewed transforms, hashes or drops PII,
-- and flags (never deletes) rows excluded by reviewed row filters.
-- full_name -> full_name_hash: PII hashed with sha256
-- ssn -> national_id: excluded (PII, never materialized)
-- dob -> date_of_birth: excluded (PII, never materialized)
with source as (
    select * from {{ source('hr', 'employees') }}
)

select
    cast("emp_id" as varchar) as employee_id,
    sha256(cast("full_name" as varchar)) as full_name_hash,
    cast("dept" as varchar) as department,
    cast("hire_date" as date) as hire_date,
    cast("term_date" as date) as termination_date,
    cast("salary" as decimal(18, 2)) as salary,
    false as _excluded
from source
