The run onboarded `fixture:portco_a__malformed` and is paused at the **mapping_review** gate with 22 pending items. It's read-only so far — no data has left the adapter and nothing has been approved. Here's a summary:

## Data quality findings

**Test/junk records**
- 3 rows in `billing.customers.cust_name` and 2 in `crm.accounts.acct_nm` start with `"TEST"` — proposed row filters to exclude them.
- 5 rows in `crm.accounts` are soft-deleted (`is_deleted=true`) — proposed filter to exclude.

**Likely duplicates**
- `billing.customers.cust_name`: 4 of 127 values collide after normalizing case/punctuation (medium confidence) — possible duplicate customer records.

**Currency/units issues**
- `billing.customers`, `billing.invoices`, `billing.subscriptions` all mix EUR/GBP/USD with no FX table — amounts can't be safely summed across currencies as-is.
- `billing.invoice_lines.amount` looks like it's stored in cents (mean is ~90x the median of other decimal money columns) — suggested `cents_to_major` transform.
- `billing.invoices.po_ref` mixes numeric and text values (490/1962 numeric).

**Referential integrity**
- Join `billing.customers.crm_account_ref -> crm.accounts.acct_id`: 7.9% orphan rate (containment 91.8%) — some billing customers reference nonexistent CRM accounts. Flagged for review, unlike the other 6 joins which are 100% clean and auto-accepted.

**Semantic/naming traps**
- `crm.opportunities.rev` → proposed mapping to `opportunity.amount` is flagged **LOW_CONFIDENCE + SEMANTIC_TRAP** — worth double-checking this isn't actually revenue-recognized vs. deal amount.
- `crm.accounts.created_dt` needs a `parse_mixed_date` transform (inconsistent date formats in source).

**PII (10 columns, values never left the adapter, only classified)**
- Emails: `billing.customers.billing_email`, `crm.accounts.owner_email`, `crm.contacts.email`
- Names: `crm.contacts.first_name/last_name`, `hr.employees.full_name`
- Sensitive: `hr.employees.ssn` (national_id), `hr.employees.dob`, `crm.contacts.phone`, `billing.payments.card_number` (payment card — highest sensitivity)

## Safe next steps

1. A reviewer needs to work through the 22 pending mapping/filter/join items via `submit_mapping_review` — particularly the PII fields (need explicit `pii_handling` decisions), the `card_number` field (consider masking/exclusion rather than raw mapping), the `crm.opportunities.rev` semantic trap, and the orphaned join.
2. Once reviewed, `resume_run` continues to artifact generation → sandbox tests → certification → publish.
3. I have not approved, overridden, or certified anything — that requires a reviewer principal.

Let me know if you'd like me to lay out recommended decisions for the reviewer to consider (without submitting them myself).
