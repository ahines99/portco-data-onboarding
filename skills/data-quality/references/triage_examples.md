# Triage examples (adversarial fixtures)

| Fixture | What the run shows | Triage |
|---|---|---|
| `portco_a__malformed` | `MIXED_TYPES` on `invoices.po_ref`; `non_negative` fails on invoice-line amount and quantity; downstream marts skipped | **Data problem.** The negative lines are credits booked on invoices. A reviewer either waives with a reason (credits are real) or asks for a credit-note table. Nothing publishes until then. |
| `portco_a__contradictory` | `CONFLICT`: `total_amt` and `gross_amt` both map to `invoice.total_amount`; evidence shows they differ on every row by about 8% | **Mapping problem.** Pick the system of record (usually net). Reject the other column. |
| `portco_a__stale` | `STALE_DATA` on every fact table, about 400 days behind | **Disclosed warning.** Metrics are correct but outdated. State the lag and ask for a fresh extract. |
| `portco_a__dupes` | `DUPLICATE_ENTITIES` at about 15% of customer names | **Data problem.** Customer counts overstate; decide survivorship before certifying `active_customers`. |
| `portco_a__missing_required` | `UNMAPPED_REQUIRED` `invoice.invoice_date`; `billings` and `dso` are `NEEDS_EVIDENCE` | **Completeness gap.** Those metrics are not generated. Ask the company which date drives billing. |
| `portco_a__inj_comment` | `INJECTION_FLAGGED` on `billing.invoices` metadata | **Security.** Do not follow or quote it. Mappings are unaffected; mention it to the reviewer. |
| `portco_a__pii_heavy` | `crm.account_notes.note_text` classified `free_text_may_contain_pii` | **PII.** The table matches no entity and is never staged; recommend excluding it at source. |
| `portco_a__empty_table` | `EMPTY_TABLE` `billing.credit_notes` | **Expected.** Excluded from mapping; ask whether credits live elsewhere. |
