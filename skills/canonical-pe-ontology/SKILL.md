---
name: canonical-pe-ontology
description: Use when explaining or reviewing how portfolio-company columns map onto the canonical private-equity ontology — mapping proposals, reason codes, alternatives, and PE metric pitfalls (bookings vs billings vs revenue, ARR, FX, fiscal calendars). Helps a human reviewer decide; never decides for them.
---

# Canonical PE ontology

The ontology is the target model every source is mapped onto. It is data, versioned and
reviewed, served as `ontology://pe/v1` (one metric: `ontology://pe/v1/metrics/{metric}`). This
Skill does not restate it. Always read the resource for field definitions, so you never quote a
stale copy.

## When to use

- A run is paused at the mapping review and a human asks what an item means.
- A user asks why a column was (or was not) mapped, or why a metric is `NEEDS_EVIDENCE`.
- Writing reviewer-ready rationale for a mapping.

## Procedure

1. Read `run://{run_id}/mapping` for proposals (score, alternatives, reason codes, evidence ids)
   and `ontology://pe/v1` for what the target field means.
2. For one item at a time, use the `explain_mapping` prompt pattern: state the proposal, translate
   each reason code (table below), list the alternatives, cite evidence ids.
3. Recommend approve, reject, or override with a specific field, but state plainly that only a
   reviewer can record the decision (`submit_mapping_review` rejects agent principals).
4. For metrics marked `NEEDS_EVIDENCE`, say which required fields are missing. Never estimate the
   metric or suggest a proxy as if it were the same thing.

## Reason codes

| Code | Meaning | What the reviewer should check |
|---|---|---|
| `LOW_CONFIDENCE` | Deterministic score below the HIGH band | Whether the name and type really match the definition |
| `METRIC_BEARING` | The field feeds a certified metric | Units, sign convention, and gross vs net |
| `PII_FIELD` | Column is PII; staging will hash or exclude it | Whether the proposed handling is enough |
| `CONFLICT` | Two columns compete for one field (evidence shows how often they differ) | Which one is the system of record; reject the other |
| `UNIT_MISMATCH` | Integer minor units vs a major-unit field | Approve the suggested `cents_to_major` transform or override it |
| `SEMANTIC_TRAP` | Name looks like revenue but probably is not | Usually bookings or billings; see the pitfalls below |
| `JOIN_INFERRED` | Mapped only because it joins to another table's key | The join's containment in `run://{run_id}/joins` |
| `TRANSFORM_REQUIRED` | Dates stored as text in several formats | The parse transform is correct for this source |
| `ROW_FILTER` | Proposed exclusion (soft deletes, TEST records) | That excluded rows really should not count |

## PE pitfalls (decision table)

| Situation | Correct treatment | Common mistake |
|---|---|---|
| Opportunity or deal amounts | **Bookings.** Never revenue. | Mapping `rev`-named columns to revenue |
| Invoice totals | **Billings.** Timing follows invoicing, not delivery. | Presenting billings as recognized revenue |
| General-ledger revenue accounts (credit minus debit) | **Recognized revenue** | Using billings when the GL exists |
| ARR | 12 x month-end MRR of *active* subscriptions | 12 x one month's billings (breaks with prepaid annual contracts) |
| Several currencies, no FX table | Keep metrics per currency | Summing across currencies |
| Fiscal year not calendar | Report by fiscal period label | Calendar-year totals labelled as FY |
| Credit notes and refunds | Net them in revenue; keep gross billings separate | Double counting or dropping them |
| Intercompany entries | Eliminate before consolidation | Counting internal sales as revenue |
| Adjusted EBITDA add-backs | Human judgment, never generated | Auto-adding "one-offs" |
| Duplicate customers across systems | One system of record; others enrich | Counting both records in customer counts |

## Output contract

For each item: **Proposal** → **Reason codes in plain language** → **Evidence ids** →
**Alternatives** → **Recommendation (reviewer decides)**. Label anything you infer as an
assumption.

See `references/reviewing_mappings.md` for a worked review of fixture A's trap columns.
