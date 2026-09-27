The run has profiled and mapped the source, and is now paused at the **mapping_review gate** with 22 pending items. I have not approved anything — that requires a reviewer principal. Here's the summary:

## Data quality findings

**PII (10 columns, aggregate-only, never left the adapter):**
- `billing.customers.billing_email`, `crm.accounts.owner_email` — emails
- `billing.payments.card_number` — payment card (high sensitivity)
- `crm.contacts.first_name/last_name/email/phone` — contact PII
- `hr.employees.full_name`, `ssn` (→ national_id), `dob` — HR PII, SSN especially sensitive

**Unit/metric issues:**
- `billing.invoice_lines.amount` looks like **cents** (mean is 89.65x the median of decimal money columns elsewhere) — proposed `cents_to_major` transform needs confirmation, not just acceptance.
- `crm.opportunities.rev` mapped to `opportunity.amount` with **LOW_CONFIDENCE + SEMANTIC_TRAP** — classic bookings/revenue naming trap, needs a human to confirm what "rev" actually represents before trusting it as a metric.
- Multiple metric-bearing fields (`invoices.total_amt`, `payments.amount`, `subscriptions.mrr_amt`, GL `debit`/`credit`) flagged simply because they drive financial metrics and need reviewer sign-off.

**Currency:** `billing.customers`, `billing.invoices`, `billing.subscriptions` each hold EUR/GBP/USD with **no FX table** — amounts must never be summed across currencies without conversion.

**Row-level quality:**
- 3 test records in `billing.customers.cust_name` (names starting "TEST") — proposed exclusion filter
- 2 test records in `crm.accounts.acct_nm` — proposed exclusion filter
- 5 soft-deleted rows in `crm.accounts.is_deleted` — proposed exclusion filter
- Probable duplicate customers in `billing.customers.cust_name` (4/127 collide after normalization)
- `billing.invoices.po_ref` mixes numeric and text values (490/1962 numeric)
- `crm.accounts.created_dt` needs a `parse_mixed_date` transform (mixed date formats)

**Referential integrity:**
- `billing.customers.crm_account_ref → crm.accounts.acct_id`: only 91.8% containment, **7.9% orphan rate** — some customers reference nonexistent CRM accounts. This join needs review before being relied on.
- All other joins (invoice_lines→invoices, invoices→customers, payments→invoices, subscriptions→customers, contacts/opportunities→accounts, journal_lines→gl_accounts) are 100% containment, no review needed.

## Safe next steps
1. A reviewer should go through the 22 pending items (10 PII mappings, 6 metric-bearing mappings, 1 low-confidence/semantic-trap mapping, 1 transform, 3 row filters, 1 orphaned join) via `submit_mapping_review`.
2. Particular attention should go to: the SSN/card_number PII handling policy, the `cents_to_major` transform on invoice_lines.amount, the `rev`→`amount` semantic trap, and whether the 7.9% orphaned customer→CRM join rows should be dropped, nulled, or investigated as a data issue upstream.
3. Once reviewed and approved, `resume_run` continues to artifact generation → sandbox tests → certification → publish — each with its own gate.

I have not made any approve/reject decisions — that's for you or another reviewer principal to do.
