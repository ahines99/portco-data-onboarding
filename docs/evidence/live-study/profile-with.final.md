Onboarding of `fixture:portco_a` is complete through the mapping stage and now paused at the **mapping_review** gate (22 pending items). Here's what profiling and inference found, with evidence.

## Connection & scope
- Read-only connection verified: 4 schemas, 11 tables visible; a write probe was rejected (`duckdb://portco_a#probe=connection`).

## Data quality findings
- **Duplicate customers**: `billing.customers.cust_name` — 4 of 127 values (3.15%) collide after normalizing case/punctuation, suggesting the same real-world customer has multiple records.
- **Test records**: 3 rows in `billing.customers.cust_name` and 2 rows in `crm.accounts.acct_nm` start with "TEST". Both are proposed as row-filter exclusions pending your approval.
- **Soft-delete flag**: `crm.accounts.is_deleted` — 5 rows flagged deleted, also proposed for exclusion.
- **Multi-currency exposure**: `billing.customers`, `billing.invoices`, and `billing.subscriptions` each hold EUR/GBP/USD in their `currency` column with no FX table present — amounts are never summed across currencies, but any canonical metric spanning these tables needs currency-aware handling.
- **Unit mismatch**: `billing.invoice_lines.amount` looks like it's stored in cents — its mean is 93x the median of decimal money columns in the same schema (ratio 93.12). A `cents_to_major` transform is suggested.
- **Join orphans**: `billing.customers.crm_account_ref -> crm.accounts.acct_id` is N:1 with only 91.8% containment — 7.9% of billing customers reference a CRM account that doesn't exist. Flagged for review (ENTITY_OVERLAP + ORPHANS) rather than auto-approved, unlike the other 100%-containment joins (invoice_lines↔invoices, invoices↔customers, payments↔invoices, subscriptions↔customers, contacts↔accounts, opportunities↔accounts, journal_lines↔gl_accounts).
- **Entity overlap**: both `billing.customers` and `crm.accounts` describe "customer"; `billing.customers` is treated as system of record, with `crm.accounts` enriching it via the reviewed join above.
- **Semantic trap flagged**: `crm.opportunities.rev -> opportunity.amount` mapping is low-confidence — "rev" naming risks conflating opportunity/pipeline value with recognized revenue.

## PII handling
10 columns were classified as PII during profiling. Per the server's read-only design, **only aggregate stats and category labels were computed — no PII values ever left the source adapter**. Classified columns:

| Column | PII class |
|---|---|
| `billing.customers.billing_email` | email |
| `billing.payments.card_number` | payment_card |
| `crm.accounts.owner_email` | email |
| `crm.contacts.email` | email |
| `crm.contacts.first_name` / `last_name` | person_name |
| `crm.contacts.phone` | phone |
| `hr.employees.dob` | date_of_birth |
| `hr.employees.full_name` | person_name |
| `hr.employees.ssn` | national_id |

All 10 are queued as individual mapping-review items (reason code `PII_FIELD`) — each needs an explicit reviewer decision (approve / reject / override with a `pii_handling` treatment such as masking or exclusion) before they can be mapped into the canonical model. Notably `hr.employees.ssn` (national ID) and `billing.payments.card_number` (payment card) are the most sensitive and warrant particular scrutiny on handling/masking strategy.

## Full pending review list (22 items, gate = mapping_review)
- 10 PII field mappings (table above)
- 6 metric-bearing mappings: `billing.invoices.total_amt`, `billing.payments.amount`, `billing.subscriptions.mrr_amt`, `erp.journal_lines.debit`, `erp.journal_lines.credit`, plus the unit-mismatch `billing.invoice_lines.amount`
- 1 transform-required mapping: `crm.accounts.created_dt` (mixed date formats, suggest `parse_mixed_date`)
- 1 low-confidence/semantic-trap mapping: `crm.opportunities.rev`
- 3 row-filter proposals: test records in `billing.customers`/`crm.accounts`, soft-deleted `crm.accounts` rows
- 1 join needing review: `billing.customers.crm_account_ref -> crm.accounts.acct_id` (orphans + entity overlap)

The run is stopped here awaiting a human reviewer to submit decisions via `submit_mapping_review` (I cannot approve, reject, or override any of these as the agent principal). Let me know if you'd like me to walk through specific items in more depth before a reviewer decides.
