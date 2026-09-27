Now I have the full picture. Here's the onboarding status for **fixture:portco_b** (run_id `cfb53406-a43d-4e4a-a729-ba7d2062c1af`) — this is a SAP-derived source (BSEG/KNA1/MARA/PA0001/SKA1/VBRK/VBRP), currently **paused at the mapping_review gate with 9 pending items**. I cannot approve/reject these — only a reviewer principal can — but here's the evidence for each.

## Revenue semantics (important context first)

This source has **two independent amount signals that must not be conflated**:

- **`sap.BSEG` (GL journal lines) → `gl_entry.debit_amount`/`credit_amount`**: this is the system of record for `revenue_recognized` (credit − debit on revenue-type GL accounts, per `gl_account.account_type`). This is the correct source for recognized revenue.
- **`sap.VBRK`/`VBRP` (billing documents) → `invoice.total_amount`/`invoice_line.amount`**: these are **billings**, not revenue. The ontology's `billings` metric explicitly notes: *"Billings include prepaid annual invoices; do not present them as recognized revenue."* Since a GL exists in this source, revenue_recognized should always be computed from BSEG, never from VBRK/VBRP.

No SaaS subscription table is present in this source, so `mrr`, `arr`, `arpa`, `new_arr`, `expansion_arr`, `contraction_arr`, `churned_arr`, `grr`, `nrr` are all marked **NEEDS_EVIDENCE** and will not be generated or estimated — there's simply no `subscription` entity here. `active_customers` and `dso` are also NEEDS_EVIDENCE (dso additionally needs a `payment` table, which doesn't exist in this source either).

## The 9 pending review items

**1–2. `sap.BSEG.DMBTR_S` → `gl_entry.debit_amount`, `sap.BSEG.DMBTR_H` → `gl_entry.credit_amount`**
- Reason: `METRIC_BEARING` (score 1.00, high confidence)
- Evidence: `sap.BSEG#stat=profile`
- These feed `revenue_recognized`, `cogs`, `opex`, `ebitda` directly. SAP convention `DMBTR_S` = debit, `DMBTR_H` = credit (Soll/Haben) — the name match is unambiguous, but because these values flow straight into certified P&L metrics, sign convention and units should be double-checked (are these already in major currency units, or could there be a minor-unit trap? No `UNIT_MISMATCH` code was raised, so no cents-to-major transform was suggested — worth a sanity check against a known GL total).
- Alternatives offered are just other gl_entry fields (credit_amount/line_number/entity_code) — nothing suggests these are mis-mapped, review is procedural given the metric impact.
- Recommendation: approve — mapping is high-confidence and standard SAP naming.

**3. `sap.PA0001.ENAME` → `employee.full_name`**
- Reason: `PII_FIELD` (person_name), proposed handling: **hash** in staging.
- Evidence: `sap.PA0001#stat=profile`
- Recommendation: approve if hashing satisfies your PII policy for this field's use (e.g., headcount reporting doesn't need names at all — consider `exclude` instead of `hash` if names aren't needed downstream).

**4. `sap.PA0001.GBDAT` → `employee.date_of_birth`**
- Reason: `PII_FIELD` (dob), proposed handling: **exclude** entirely from staging.
- Recommendation: approve — DOB isn't needed for any certified metric (headcount only needs hire/termination dates).

**5. `sap.VBRK.KUNAG` → `invoice.customer_id`**
- Reason: `LOW_CONFIDENCE` (score 0.75) + `JOIN_INFERRED`
- Evidence: join `sap.VBRK.KUNAG->sap.KNA1.KUNNR`, N:1, containment 100%, name_score only 0.625 (KUNAG vs KUNNR aren't exact synonyms — KUNAG is SAP's "sold-to party" field).
- The join is solid (100% containment, no orphans), so semantically this is correct — SAP's `KUNAG` genuinely represents the sold-to customer. Low confidence is a naming artifact, not a join-quality problem.
- Recommendation: approve.

**6. `sap.VBRK.NETWR` → `invoice.total_amount`**
- Reason: `LOW_CONFIDENCE` (score 0.62) + `METRIC_BEARING`
- Evidence: `sap.VBRK#stat=profile`
- This is a **semantic trap candidate**: `NETWR` in SAP billing documents is "net value" — it feeds `billings`, and must never be treated as revenue (see semantics note above). The low confidence score reflects that NETWR isn't a strong lexical match for `total_amount`, but semantically it is the standard SAP billing net-value field. Confirm whether tax/discounts are included or excluded in NETWR before treating it as "total."
- Recommendation: approve as `total_amount` (billings), but flag downstream users that this is billings, not revenue.

**7. `sap.VBRK.FKART` → `invoice.status`**
- Reason: `LOW_CONFIDENCE` (score 0.47, lowest of all proposals)
- This is the weakest mapping. `FKART` in SAP is actually the **billing document type** (e.g., invoice vs credit memo vs debit memo), not a status field (open/paid/void). Mapping it to `status` is likely a category error — it doesn't distinguish "credit note" from "status," which matters for the "credit notes and refunds" pitfall (they should be netted, not double-counted).
- Recommendation: **reject or override**. Consider leaving it unmapped, or if a true status field doesn't exist in VBRK, note that FKART could still be useful for identifying credit memos (to net them against billings) rather than as a generic status.

**8. `sap.VBRP.NETWR` → `invoice_line.amount`**
- Reason: `LOW_CONFIDENCE` (score 0.52)
- Evidence: `sap.VBRP#stat=profile`
- Same NETWR pattern as item 6, at the line level. Alternatives include `unit_price` and `quantity` — worth checking whether NETWR at the line level is net-of-discount extended amount (quantity × unit_price) or something else, since VBRP also carries `FKIMG` (quantity, already mapped) separately.
- Recommendation: approve as `amount`, same billings-not-revenue caveat applies.

**9. `filter:sap.KNA1.LOEVM:exclude_true` (row filter)**
- Reason: `ROW_FILTER` — soft-delete flag, 2 rows in `sap.KNA1` (customer master) flagged `LOEVM = true`.
- Evidence: `sap.KNA1#stat=profile`
- Proposal excludes these 2 deleted/marked-for-deletion customer records from the canonical `customer` entity.
- Recommendation: approve — standard SAP soft-delete handling; verify the 2 rows aren't referenced by any un-filtered invoices (would create orphans) before confirming.

## Summary for the reviewer
- **Straightforward approvals**: items 1, 2, 4, 5, 9 (and 3 if hash handling is acceptable).
- **Needs scrutiny**: item 7 (`FKART`→`status` is likely a category mismatch — recommend reject/override), and items 6, 8 (`NETWR` fields are legitimate but must be labeled/used as billings, never revenue).
- **11 metrics cannot be generated** for lack of subscription/payment data: `active_customers, arpa, arr, churned_arr, contraction_arr, dso, expansion_arr, grr, mrr, new_arr, nrr`.

Let me know the reviewer's decisions and I'll submit them via `submit_mapping_review` and resume the run.
