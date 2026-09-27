Onboarding for `fixture:portco_a` has run read-only through connection validation, profiling, entity/join inference, and canonical mapping, and is now paused at the **mapping_review** gate with 22 pending items. I cannot approve/reject these — that requires a reviewer principal — but here's what the profile found, with evidence.

## Connection & schema
- Read-only connection verified: 4 schemas (billing, crm, erp, hr), 11 tables; a write probe was correctly rejected (`duckdb://portco_a#probe=connection`).

## Data quality findings
- **Duplicate customers**: 4 of 127 `billing.customers.cust_name` values collide after normalizing case/punctuation (3.15% dup ratio) — likely the same entity recorded multiple times.
- **Test records**: 3 rows in `billing.customers.cust_name` and 2 rows in `crm.accounts.acct_nm` start with "TEST" — proposed as row-exclusion filters, not yet applied.
- **Soft-deletes**: `crm.accounts.is_deleted` flags 5 rows — proposed exclusion filter pending.
- **Multi-currency**: `billing.customers`, `billing.invoices`, and `billing.subscriptions` each hold EUR/GBP/USD with no FX table present, so amounts are never summed cross-currency (flagged, not blocking).
- **Unit mismatch**: `billing.invoice_lines.amount` has a mean 93x the median of decimal money columns elsewhere in the schema — likely stored in cents. System suggests a `cents_to_major` transform.
- **Orphan keys**: `billing.customers.crm_account_ref -> crm.accounts.acct_id` has only 91.8% containment (7.9% orphan rate) — some customers reference a CRM account that doesn't exist. Flagged as a join needing review (also flagged as `ENTITY_OVERLAP` since both tables represent "customer"; `billing.customers` is treated as system of record).
- **Semantic trap**: `crm.opportunities.rev -> opportunity.amount` mapping is low confidence — worth double-checking that "rev" really means opportunity amount and not something else (e.g. recognized revenue).
- **Date parsing**: `crm.accounts.created_dt` needs a `parse_mixed_date` transform (mixed date formats in source).

## PII handling
The profiler classified **10 columns as PII** across 5 tables — values themselves never left the adapter; only aggregates and category labels were retrieved (per governance policy):

| Table.Column | PII class |
|---|---|
| billing.customers.billing_email | email |
| billing.payments.card_number | payment_card |
| crm.accounts.owner_email | email |
| crm.contacts.email | email |
| crm.contacts.first_name / last_name | person_name |
| crm.contacts.phone | phone |
| hr.employees.full_name | person_name |
| hr.employees.ssn | national_id |
| hr.employees.dob | dob |

Notably, `billing.payments.card_number` (raw PAN, payment_card class) and `hr.employees.ssn` (national_id) are the most sensitive — these are proposed for direct mapping into canonical fields (`payment.card_number`, `employee.national_id`) with no masking/tokenization transform suggested yet, which a reviewer should scrutinize before approving.

## Pending review gate (22 items)
- 10 PII field mappings (emails, names, phone, card number, SSN, DOB)
- 6 metric-bearing mappings (invoice/payment/subscription/GL amounts)
- 1 low-confidence/semantic-trap mapping (`crm.opportunities.rev`)
- 1 transform-required mapping (mixed date parsing)
- 3 row-filter proposals (test records x2, soft-deletes x1)
- 1 join requiring review (orphan keys, entity overlap)

**Next action**: a human reviewer needs to call `submit_mapping_review` with decisions on these 22 items (approve / reject / approve_with_override), then `resume_run`. I'm stopping here for that review.
