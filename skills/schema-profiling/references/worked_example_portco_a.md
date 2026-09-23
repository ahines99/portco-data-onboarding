# Worked example: fixture A (synthetic B2B SaaS company)

Call sequence: `start_onboarding_run(connection_id="fixture:portco_a")`, then read
`run://{run_id}/profile` and `run://{run_id}/findings`.

**Summary.** Four schemas (crm, billing, erp, hr), 11 tables, all read-only. The run is paused at
the mapping review with 22 items.

**Evidence-backed findings.**
- `POSSIBLE_MINOR_UNITS` on `billing.invoice_lines.amount`: an integer money column about 30x
  larger than other money columns, so probably cents. Expect a `UNIT_MISMATCH` item suggesting
  `cents_to_major`. (evidence: billing.invoice_lines profile)
- `DUPLICATE_ENTITIES` on `billing.customers.cust_name`: 4 of 127 names collide after
  normalization.
- `ENTITY_OVERLAP`: `crm.accounts` and `billing.customers` both describe customers; billing is
  the system of record, and CRM enriches it through a reviewed join with 7.9% orphans.
- `MULTI_CURRENCY`: USD, EUR and GBP with no FX table, so metrics stay per currency.
- `TEST_RECORDS` and `SOFT_DELETE_FLAG`: three row filters are proposed for review.
- `PII_CLASSIFIED`: 10 columns (emails, phone, names, SSN, card number, date of birth). Values
  never leave the source.

**Assumptions.** `crm.opportunities.rev` is flagged `SEMANTIC_TRAP`: the name says revenue but
the table holds opportunities, so it is most likely bookings. This is an inference; the reviewer
confirms it.

**Risks.** The cents inference rests on magnitude alone. A reviewer should confirm it against one
invoice in the source system.

**Next actions.** Review the `UNIT_MISMATCH`, `SEMANTIC_TRAP` and join items first, because they
change reported numbers. The PII items only confirm handling.

**Open questions.** Is the fiscal year really February to January? Should TEST customers be
excluded everywhere, including CRM enrichment?
