-- Scoping model for erp.gl_accounts: a row is out of scope when it is excluded itself, or when the
-- parent row it references (in a different entity) is out of scope.
select
    s.*,
    (s._excluded) as _excluded_effective
from {{ ref('stg_erp__gl_accounts') }} as s
