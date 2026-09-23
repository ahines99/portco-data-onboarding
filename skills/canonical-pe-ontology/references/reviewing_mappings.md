# Worked review: fixture A trap columns

**`crm.opportunities.rev`, proposed `opportunity.amount`** (`LOW_CONFIDENCE`, `SEMANTIC_TRAP`).
The column name suggests revenue, but it sits in the opportunities table and the ontology defines
`opportunity.amount` as a booking value (see `ontology://pe/v1`). Recommendation: approve as
`amount`, which is bookings. If a revenue-named override is ever requested, point out that recognized
revenue exists only in the general ledger.

**`billing.invoice_lines.amount`, proposed `invoice_line.amount` with `cents_to_major`**
(`UNIT_MISMATCH`). This is an integer column whose mean is about 30 times other money columns.
The sandbox checks that invoice lines sum to the invoice total, so if the transform is wrong the
build fails loudly rather than silently. Recommendation: approve with the transform.

**Join `billing.customers.crm_account_ref -> crm.accounts.acct_id`** (`ORPHANS`,
`ENTITY_OVERLAP`). 7.9% of billing customers reference CRM accounts that do not exist. Billing
stays the system of record; CRM only enriches (industry, owner). Recommendation: approve. The
relationship test runs at warning severity with the known orphan rate.

**Row filters: TEST prefix on customer names, and the soft-delete flag.** These exclude 3 billing
customers and 7 CRM accounts. Recommendation: approve, but confirm with the company that "TEST"
records never carry real revenue.
