# Generated model conventions

- Identifiers from the source are always double-quoted; canonical names are snake_case.
- Money is `decimal(18, 2)`. `cents_to_major` is `cast(cast(col as decimal(18, 2)) / 100 as decimal(18, 2))`, which is exact.
- Text dates in mixed formats are parsed with `try_strptime` for `%Y-%m-%d` and then `%m/%d/%Y`.
- PII is hashed with `sha256(cast(col as varchar))` into `<field>_hash`, or dropped with a comment
  naming the column and the reason.
- Row filters never delete rows. Staging adds `_excluded`; intermediate adds `_excluded_effective`,
  which propagates across entities (an invoice of a TEST customer is out of scope) but never
  within an entity (a CRM soft delete does not remove a billing customer).
- `fct_mrr_monthly` has one row per customer, currency and month end. A subscription is active when
  `start_date <= month_end` and `end_date` is null or after `month_end`.
- Composite keys get a surrogate `<entity>_key` in the mart for the semantic layer's primary entity.
