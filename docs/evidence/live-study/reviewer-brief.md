# Recommended decisions for the actual model run

Prepared by the implementation assistant; none has been submitted as Alex or as a human review.
Run: `ebfcaa24-a2d9-40bd-b8ee-4de306a1253e`. Source: `fixture:portco_a`. Gate: `mapping_review`.
Subject hash: `c8143be76f1cf0e929a457df83b3baa0148ae3cf720b43fd55cf3424c9e743e8`.

These recommendations apply to this synthetic fixture, not arbitrary customer data. The current
mapping artifact was read separately after the model sessions; it was not injected into the study.
The existing certified fixture evidence is a cross-check, not certification of this still-pending run.

| # | Item | Proposed decision and reason | Evidence |
|---|---|---|---|
| 1 | `mapping:billing.customers.billing_email` | Approve the existing **hash** handling for this synthetic demonstration. Hashing is pseudonymization, not a claim of anonymous production data. | `evidence://ae0c76c2-8ec8-5f9b-9c50-acbe4883f805` |
| 2 | `mapping:billing.invoice_lines.amount` | Approve **cents_to_major** for this fixture. The 93x magnitude signal supports review; the fixture definition and cent-exact reconciliation establish the intended conversion. | `evidence://f372b81c-04bd-5abf-8925-07919fec4781` |
| 3 | `mapping:billing.invoices.total_amt` | Approve the proposed financial field for the fixture; retain declared currency and sign conventions and require reconciliation before certification. | `evidence://bc950c41-245a-5204-98a8-3b08f29c14e7` |
| 4 | `mapping:billing.payments.amount` | Approve the proposed financial field for the fixture; retain declared currency and sign conventions and require reconciliation before certification. | `evidence://0c573565-9863-5cb0-9296-9bc8096676af` |
| 5 | `mapping:billing.payments.card_number` | Approve with the existing **exclude** handling; this field is not needed in published metric models. Do not preserve raw values. | `evidence://0c573565-9863-5cb0-9296-9bc8096676af` |
| 6 | `mapping:billing.subscriptions.mrr_amt` | Approve the proposed financial field for the fixture; retain declared currency and sign conventions and require reconciliation before certification. | `evidence://3ee0958c-e8ef-5171-9cb4-32105917ae7a` |
| 7 | `mapping:crm.accounts.owner_email` | Approve the existing **hash** handling for this synthetic demonstration. Hashing is pseudonymization, not a claim of anonymous production data. | `evidence://fe0fba90-3896-5e85-86e5-45d57b3d760c` |
| 8 | `mapping:crm.accounts.created_dt` | Approve **parse_mixed_date** for the fixture; require generated date tests to pass before certification. | `evidence://fe0fba90-3896-5e85-86e5-45d57b3d760c` |
| 9 | `mapping:crm.contacts.first_name` | Approve the existing **hash** handling for this synthetic demonstration. Hashing is pseudonymization, not a claim of anonymous production data. | `evidence://5a1e0e46-8c79-5126-811c-dfbffe65035c` |
| 10 | `mapping:crm.contacts.last_name` | Approve the existing **hash** handling for this synthetic demonstration. Hashing is pseudonymization, not a claim of anonymous production data. | `evidence://5a1e0e46-8c79-5126-811c-dfbffe65035c` |
| 11 | `mapping:crm.contacts.email` | Approve the existing **hash** handling for this synthetic demonstration. Hashing is pseudonymization, not a claim of anonymous production data. | `evidence://5a1e0e46-8c79-5126-811c-dfbffe65035c` |
| 12 | `mapping:crm.contacts.phone` | Approve the existing **hash** handling for this synthetic demonstration. Hashing is pseudonymization, not a claim of anonymous production data. | `evidence://5a1e0e46-8c79-5126-811c-dfbffe65035c` |
| 13 | `mapping:crm.opportunities.rev` | Approve as **opportunity.amount** only. This is pipeline/bookings context, not recognized revenue; do not feed it into the recognized-revenue metric. | `evidence://2c082058-00cf-52e6-82c3-371b20d1b3a8` |
| 14 | `mapping:erp.journal_lines.debit` | Approve the proposed financial field for the fixture; retain declared currency and sign conventions and require reconciliation before certification. | `evidence://70394bd4-5948-576b-8f6f-d235c57905e9` |
| 15 | `mapping:erp.journal_lines.credit` | Approve the proposed financial field for the fixture; retain declared currency and sign conventions and require reconciliation before certification. | `evidence://70394bd4-5948-576b-8f6f-d235c57905e9` |
| 16 | `mapping:hr.employees.full_name` | Approve the existing **hash** handling for this synthetic demonstration. Hashing is pseudonymization, not a claim of anonymous production data. | `evidence://d1227b4a-050f-5c7b-844e-df14516f7463` |
| 17 | `mapping:hr.employees.ssn` | Approve with the existing **exclude** handling; this field is not needed in published metric models. Do not preserve raw values. | `evidence://d1227b4a-050f-5c7b-844e-df14516f7463` |
| 18 | `mapping:hr.employees.dob` | Approve with the existing **exclude** handling; this field is not needed in published metric models. Do not preserve raw values. | `evidence://d1227b4a-050f-5c7b-844e-df14516f7463` |
| 19 | `filter:billing.customers.cust_name:exclude_match` | Approve the proposed exclusion for synthetic TEST/deleted records. Do not infer a general customer-record deletion policy from this fixture. | Actual pending item plus TEST_RECORDS / SOFT_DELETE_FLAG findings in the transcript. |
| 20 | `filter:crm.accounts.acct_nm:exclude_match` | Approve the proposed exclusion for synthetic TEST/deleted records. Do not infer a general customer-record deletion policy from this fixture. | Actual pending item plus TEST_RECORDS / SOFT_DELETE_FLAG findings in the transcript. |
| 21 | `filter:crm.accounts.is_deleted:exclude_true` | Approve the proposed exclusion for synthetic TEST/deleted records. Do not infer a general customer-record deletion policy from this fixture. | Actual pending item plus TEST_RECORDS / SOFT_DELETE_FLAG findings in the transcript. |
| 22 | `join:billing.customers.crm_account_ref->crm.accounts.acct_id` | **Hold for an explicit orphan policy.** 91.8% containment does not justify discarding unmatched billing customers. Decide whether CRM enrichment may remain missing and verify customer counts before acceptance. | JOIN_INFERRED / ORPHAN_KEYS: 91.8% containment, 7.9% orphan rate. |

## Certification preview

For the earlier automated reference run, nine generated metrics were certified with 26/26 passing
reconciliation checks, no failing or waived checks, and an intact audit chain. Nine other metrics
were reference-only rather than generated. See [certification](../certification.json),
[reconciliation](../reconciliation.json) and the [run report](../success-report.md).

Do not certify this new live-model run by copying that earlier certificate. After its mapping
decisions are recorded, resume it, inspect its own generated bundle and tests, then decide on its
new certification hash. The recommendation to hold the orphaned join means this packet is not a
blanket approval file. No CLI import command has been executed.
