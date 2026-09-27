Onboarding for `fixture:portco_b` (run `6da283d4-d580-4810-b0fa-b36550b5c84f`) is paused at the **mapping_review** gate with **9 pending items**, requiring a human reviewer to decide before I can resume. Here's the full breakdown with evidence:

## Pending review items (9)

**Metric-bearing GL amounts (SAP FI)**
1. `sap.BSEG.DMBTR_S` → `gl_entry.debit_amount` — flagged `METRIC_BEARING`. Alternatives offered: `credit_amount`, `line_number`, `entity_code`.
2. `sap.BSEG.DMBTR_H` → `gl_entry.credit_amount` — flagged `METRIC_BEARING`. Alternatives: `debit_amount`, `line_number`, `entity_code`.
   - SAP convention: `DMBTR_S` (Soll/debit) and `DMBTR_H` (Haben/credit) are standard debit/credit amount fields in local currency — mapping looks sound, but flagged for review purely because it feeds financial metrics, not because of ambiguity. Joined via `sap.BSEG.HKONT -> sap.SKA1.SAKNR` (score 1.00, 100% containment, high confidence, no review needed on the join itself).

**PII fields (SAP HR/PA0001)**
3. `sap.PA0001.ENAME` → `employee.full_name` — flagged `PII_FIELD`. Alternatives: `employee_id`, `national_id`, `department`.
4. `sap.PA0001.GBDAT` → `employee.date_of_birth` — flagged `PII_FIELD`. Alternatives: `hire_date`, `termination_date`, `department`.
   - Profiling classified these as PII (`person_name`, `dob` categories) — values never left the adapter; only category labels were exposed as evidence.

**Low-confidence billing mappings (SAP SD, VBRK/VBRP)**
5. `sap.VBRK.KUNAG` → `invoice.customer_id` — `LOW_CONFIDENCE`, `JOIN_INFERRED`. The underlying join `VBRK.KUNAG -> KNA1.KUNNR` scored 0.81 (100% containment) — lower confidence than the other joins (which scored 1.00), which is likely why this mapping itself needs review even though the join was auto-accepted.
6. `sap.VBRK.NETWR` → `invoice.total_amount` — `LOW_CONFIDENCE`, `METRIC_BEARING`. This is the **revenue semantics question**: `NETWR` in VBRK is net invoice value at header level — the reviewer needs to confirm this is really "total_amount" (net vs. gross, currency/unit assumptions unverified) rather than assume it.
7. `sap.VBRK.FKART` → `invoice.status` — `LOW_CONFIDENCE`. `FKART` is actually the SAP **billing document type** (e.g., invoice vs. credit memo vs. debit memo), not a status field per se — this mapping is questionable and worth scrutiny; it may need `pii_handling`/transform overrides or a different canonical target.
8. `sap.VBRP.NETWR` → `invoice_line.amount` — `LOW_CONFIDENCE`. Line-level net value; no evidence yet distinguishing whether this is unit price × quantity or a rolled-up line amount — units/semantics unverified.

**Row filter**
9. `filter:sap.KNA1.LOEVM:exclude_true` — excludes 2 customer rows flagged as soft-deleted (`LOEVM` = deletion flag in SAP customer master, high confidence, 2 rows affected).

## Metrics that cannot be derived (informational, not gated)
The canonical mapping step also found **10 SaaS-style metrics have no approved source mapping** and will not be generated or estimated (per `METRIC_NEEDS_EVIDENCE`, all high confidence in that determination): `active_customers`, `arpa`, `arr`, `churned_arr`, `contraction_arr`, `dso`, `expansion_arr`, `grr`, `mrr`, `new_arr`, `nrr`. This makes sense — portco_b's source data is SAP FI/SD/HR (GL entries, invoices, customers, employees), not a subscription billing system, so there's no basis for ARR/MRR-style recurring-revenue metrics here.

## Summary of revenue-semantics uncertainty
The two biggest open questions for revenue semantics are:
- **VBRK.NETWR → invoice.total_amount**: is this gross or net, and in what currency/unit — needs confirmation before trusting it as "total."
- **VBRP.NETWR → invoice_line.amount**: line-level net value semantics also unconfirmed (could represent extended price, not unit price).

I can't approve, override, or waive any of these — a reviewer principal needs to call `submit_mapping_review` with decisions on all 9 items (and optionally override canonical_field/transform/pii_handling) before I can `resume_run`. Let me know if you'd like me to proceed once you've made those calls, or if you want more detail on any specific item.
