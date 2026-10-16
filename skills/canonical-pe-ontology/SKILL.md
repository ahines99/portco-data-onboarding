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
| `UNIT_UNCERTAIN` | Name says "minor" but not "cents"; the scale is unknown, so no transform is suggested | The source's documented unit; override with `cents_to_major` only if it really is hundredths |
| `ENTITY_UNCERTAIN` | The table's entity classification is not HIGH confidence, so even an exact column-name match is unsettled | Whether the whole table is the proposed entity (see below) |
| `STRUCTURAL_INFERENCE` | The entity or key was inferred from column structure, not the table name | The anchor columns and key evidence (see below) |
| `JUDGE_REORDERED` | The optional model judge chose an alternative over the deterministic top choice; confidence is capped at MEDIUM | Both candidates on their evidence. The judge's preference is not evidence |
| `DUPLICATE_TARGET_AFTER_REVIEW` | After the decisions, two columns resolve to one canonical field | Keep one (the system of record) and reject or re-target the other |
| `CATEGORY_NORMALIZATION` | A closed-domain field (for example an account type) has only case or whitespace variants of canonical values; `normalize_category` is suggested | The variants really are the canonical values. Approving accepts the transform |
| `NONCANONICAL_VALUES` | The column has NULL or unknown classifications for a closed-domain field. Dependent metrics stay `NEEDS_EVIDENCE` | How many rows are affected (row counts are in the proposal rationale; values are never shown). Mapping arbitrary codes needs a reviewed crosswalk or a source fix, not an approval |
| `PRECISION_EXCEEDS_CENTS` | Money values carry more decimal places than the supported precision. They are rejected, not rounded | Whether the column is really major-unit money; fix the source extract instead of approving rounding |

Join review items (`join:` keys) use their own codes. `STRUCTURAL_JOIN`: the join rests mainly on
value containment because the names are weak, so check that the two columns mean the same key.
`ORPHANS`: containment is below the review threshold, so check the orphan rate in
`run://{run_id}/joins` and whether the orphans matter. `ENTITY_OVERLAP`: both tables describe the same
entity, so decide which is the system of record before approving. `GENERIC_KEY`: both sides use a
generic surrogate name such as `id`, and two independent 1..n sequences overlap completely, so
containment alone proves nothing. Approve only with a documented relationship. `ENTITY_UNCERTAIN`
on a join means that the entity of either endpoint is uncertain. `LOW_CONFIDENCE` has its usual
meaning.

## Entity-level uncertainty: `ENTITY_UNCERTAIN` and `STRUCTURAL_INFERENCE`

These codes concern the **table**, not the column. A column named exactly like a canonical field
(`status`, `amount`) means something different in a subscription than in an invoice. These codes
cause most of the added review burden in the current qualification corpora, so explain them first
and group the items by table.

Evidence to read: the table's entry in `run://{run_id}/entities` (proposed entity, score,
confidence, `feature_breakdown`, `primary_key_columns`, alternatives); the table's columns and key
uniqueness in `run://{run_id}/profile`; its relationships in `run://{run_id}/joins`; and
`ENTITY_OVERLAP` / `NO_ENTITY_MATCH` in `run://{run_id}/findings`.

- `ENTITY_UNCERTAIN`: the table name and columns did not classify the table at HIGH confidence. Every
  proposal in that table inherits the uncertainty: a column's confidence is lowered to the entity's.
- `STRUCTURAL_INFERENCE`, LOW confidence: the table name matched no entity. At least two
  type-compatible anchor columns, one of them unique to the entity, selected it
  (`feature_breakdown.structural_anchors`). This fallback is designed to route the table to review.
- `STRUCTURAL_INFERENCE`, MEDIUM confidence: the table's single-column primary key has a name that
  matches no ontology field, and it was mapped to the entity's id field because it is the table's key.

Guidance for the reviewer (the agent recommends; only the reviewer decides):

- **Approve** when the table as a whole is the proposed entity: the anchor columns, key uniqueness and
  joins agree, and no alternative explains the table equally well. Example: a table named with a system
  code that has a unique key, a customer name and a country, and whose key invoices reference, is a
  customer master. Approve its id and name rows.
- **Reject or override** when the evidence points to another entity, for example a line-item table
  whose `amount` should not become an invoice header amount. Override with a field from the item's
  `allowed_fields` only when the right target is in the same entity. Otherwise reject the item.
- **Abstain** (recommend that the reviewer hold the packet and record no approval) when only the
  company can say what the table is, for example two plausible entities with similar evidence. The
  run stays paused at the gate and nothing is generated. Write the question in "open questions".
  Never guess to clear the queue.

Scores and confidence bands are deterministic heuristics with thresholds from `ontology/scoring.yaml`.
They are **not calibrated probabilities**: a score of 0.8 does not mean an 80% chance of being right,
and MEDIUM on one table is not comparable with MEDIUM on another. Use them to order review, not to
replace it.

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
