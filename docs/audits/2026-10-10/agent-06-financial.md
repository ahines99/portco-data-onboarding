# Agent 6/10 — financial and data correctness audit

Audit date: 2026-10-10. Scope: generated dbt models, semantic execution, independent reconciliation, ontology and metric reference calculators. No tracked source changes. Synthetic probes only.

## Results

Two high-priority findings reproduced using the real `resolve()`, `Generator.build()` and `build_and_test()` code, including actual dbt builds. Both reports pass without waivers. A third precision inconsistency was reproduced with the exact generated cast expression and independent reference calculator; it fails closed when money reconciliation runs.

Reproduce the two full sandbox probes from the repository root:

```powershell
.venv/Scripts/python.exe var/audit-2026-10-10/agent-06-probe.py
```

Probe: `var/audit-2026-10-10/agent-06-probe.py`. Compact preserved results: `var/audit-2026-10-10/agent-06-probe-results.json`. Initial detailed generated projects, dbt logs, warehouse, source, reports and immutable blobs: `var/audit-2026-10-10/financial-1d5b59/`. The probe uses typed synthetic profiles and explicit decisions rather than testing inference or authorization. It tests actual gate resolution and actual dbt/sandbox behavior. It does not publish or claim to have run a complete authorized service workflow.

## FIN-01 — P1 — generated ontology lookups resurrect a rejected relationship

Primary location: `src/services/generation.py:385`–`:401` (`build_marts()` ontology lookup loop). Supporting locations: `src/services/gates.py:167`–`:181`; `templates/dbt/mart.sql.j2:21`; `src/services/sandbox.py:382` and `:502`; `src/services/certification.py:74`; `src/services/publish.py:172`.

`resolve()` correctly removes a rejected GL-entry→GL-account relationship and records its key in `rejected_keys`. Generation then independently adds an account-code join whenever the ontology lookup exists and the account table has a one-column key. It never checks `resolved.joins` or the rejection. The reference calculators independently reconstitute the same unauthorized relationship using an account-code dictionary, so reconciliation cannot detect this governance error.

Concrete reproduction: one journal line, `account_code='4000'`, credit 100.00, debit 0; one account `4000`, `account_type='revenue'`. Approve all column mappings, explicitly reject `join:erp.journal_lines.account_code->erp.gl_accounts.account_code`. Observed:

- `accepted_join_count=0`, with the exact rejection retained.
- Generated `fct_gl_entry.sql` still contains `left join {{ ref('int_erp__gl_accounts') }} as l1 on l1.account_code = p.account_code`.
- dbt exit 0; all eight reconciliation checks pass; `metric:revenue_recognized` is 100.00 and EBITDA is 100.00.
- Certification's `joins` is copied from `resolved.joins`, so the packet describes zero joins while generated SQL executes one. Publication copies mart files as generated; no later relationship rejection check exists in that path. Publication behavior is traced, not executed in this probe.

Impact: an explicitly disallowed relationship can influence certified financial figures. An incorrect account-code association or filtered dimension row can still classify journal money after relationship rejection.

Fix: authorize each ontology lookup against the exact accepted source join, including tables, fields, direction and compatible cardinality. If absent/rejected, omit lookup and mark dependent metrics `NEEDS_EVIDENCE` rather than generating an expression whose classification has no approved lineage. Make the reference build use the same *approval contract* while keeping independent arithmetic. Certification should expose every relationship actually used by generated SQL.

Independent regression: approve vs reject the identical relationship, keeping all column mappings unchanged. Rejection must remove the generated lookup and block/withhold GL metrics; no passing report or published artifact may silently reintroduce it. Also cover no inferred join at all and mismatched account-code namespaces.

## FIN-02 — P1 — unsupported account-type labels produce passing zero financial results

Primary location: `src/services/generation.py:264`–`:265`; supporting `ontology/pe_canonical_v1.yaml:144`, `:374`, `:382`, `:389`; `src/domain/metrics_reference.py:257`–`:261`; `src/services/sandbox.py:502`–`:521`; `src/services/approvals.py:65`–`:74`.

The ontology says account types are one of `revenue`, `cogs`, `opex`, `da`, `asset`, `liability`, `equity`, but the runtime field contract is unrestricted string. Generated accepted-values tests use the observed/source-approved labels instead of the canonical domain. All financial SQL and the independent calculator recognize only exact lowercase strings and silently skip others. Available mapping overrides cannot translate categorical values (only field choice, cents/date transform or PII handling).

Concrete reproduction: same 100.00 credit, with account type `Revenue` and an accepted relationship. The generated dbt accepted-values test permits `Revenue`. dbt exit 0 and all eight reconciliation checks pass, while recognized revenue and EBITDA both equal 0.00; gross margin is null. The mart revenue check even reports zero periods compared exactly, because it removes zero results on both sides. This is not a request to infer accounting classifications automatically: noncanonical classification should stop financial certification instead of being treated as financially zero.

Category-domain boundary was checked: `src/adapters/external.py:447`–`:467` allows source labels only when operator-approved and safe to expose; that approval is a privacy/disclosure allowlist, not conversion to the ontology's canonical accounting values. An operator can approve `Revenue` for disclosure, or omit the category-domain allowlist and receive no category test at all. Neither path enforces canonical financial meaning.

Fix: represent canonical value constraints in `FieldDef`, validate/aggregate unknown and null account types independent of whether labels may be exposed, and block affected metrics until a reviewer provides an explicit translation. A narrowly documented case/whitespace normalizer may cover `Revenue`, but arbitrary ERP codes require an approved crosswalk. Unknown account codes/types must remain unknown rather than defaulting to a legitimate zero measure.

Independent regression: use `Revenue`, `REVENUE`, trailing spaces, an unknown ERP code, and NULL. Until explicitly normalized/mapped, none may produce a passing zero-valued GL metric. Canonical asset/liability rows must still remain valid and contribute zero to revenue. Validate source-domain disclosure and canonical-value validation separately.

Research: dbt documents that `accepted_values` checks membership in the supplied list; the generator must therefore supply the intended canonical domain, not merely repeat observed labels. See [dbt data tests property](https://docs.getdbt.com/reference/resource-properties/data-tests) and [dbt built-in data tests](https://docs.getdbt.com/docs/build/data-tests). This is a code/validation finding, not a conclusion about accounting standards.

## FIN-03 — P2 — money staging disagrees with the reference's documented rounding policy

Primary location: `src/services/generation.py:41` and `:137`; related `:129`; `src/domain/metrics_reference.py:7`, `:29`, `:139`; `docs/CSV-SOURCE.md:43`–`:46`.

CSV ingestion accepts exact `DECIMAL(p,s)` with scales beyond two. Generation casts every canonical decimal to `DECIMAL(18,2)` at the individual-row stage, while `billings()` aggregates full-precision source values and then applies `ROUND_HALF_EVEN`. These differ by both rounding mode and rounding point.

Verified two synthetic invoice values 1.005 and 1.005 (`DECIMAL(18,3)`): exact generated staging expression `sum(cast(v as decimal(18,2)))` returns 2.02; reference `billings()` returns 2.01. A single 1.005 yields 1.01 in the generated cast versus 1.00 under the documented reference banker-rounding rule. This causes legitimate higher-precision imports to fail reconciliation; the normal reconciliation path prevents silent publication unless a reviewer waives the discrepancy. No full invoice dbt build was needed for this arithmetic proof.

Fix: define supported money precision/scale and rounding point as a reviewed contract. Either preserve adequate decimal precision through aggregation and round consistently at the metric boundary, or reject unsupported precision at mapping review with a precise reason. Do not silently choose row-level rounding and then invite a waiver of the disagreement. Treat `cents_to_major` separately: DuckDB decimal division returns approximate floating point, so use an exact scaling construction or prove bounds if large minor-unit integers are allowed.

Independent regression: positive/negative half-cent ties, several subcent rows, three-decimal currencies, large integer minor amounts, sum overflow and explicit approved scaling. Expect exact agreement or an explicit unsupported-input status before generation.

Research: [DuckDB numeric types](https://duckdb.org/docs/current/sql/data_types/numeric) documents exact fixed-point storage and approximate floating-point decimal division; [DuckDB casts](https://duckdb.org/docs/current/sql/expressions/cast) documents cast-related rounding implications. Runtime probe establishes behavior of this installed version rather than assuming current docs match every historical version.

## Other observations and bounded improvement opportunities

- Positive: each generated semantic metric is now executed from generated YAML and compared against independent Python inputs; expression mutation is covered in `tests/test_semantic_execution.py`. The previous audit's missing coverage issue is materially improved.
- Positive: invoice-line/header consistency is blocking by default, includes NULL/unknown differences, and reports mismatch counts and magnitude.
- Supported scope matters: month-end exclusive subscription end dates, annualized ARR, calendar-month grouping, reference-only retention/DSO/headcount and the explicitly bounded local semantic executor are documented behavior. Do not report lack of MetricFlow compatibility or missing generated reference-only metrics as newly discovered bugs.
- GL money has no currency field in the canonical ontology. Before supporting real multi-ledger inputs, require explicit single reporting-currency evidence or add currency/FX contracts. The synthetic fixture's ledger normalization does not prove arbitrary GL sources are comparable. This is a scope-hardening recommendation, not a demonstrated current financial misstatement.
- Performance: `SourceRows._cols()` repeatedly fetches complete tables, and the mart + semantic paths load the same invoice/subscription/GL fields again. `mrr()`, `arr()` and `active_customers()` repeatedly rebuild an O(months × subscriptions) snapshot. Cache a scoped source projection and one independent customer/month snapshot per reconciliation run; preserve source-SQL independence. Measure peak memory as well as runtime on the CSV limit of 250,000 rows and long subscription histories before raising limits.
- Composite join fields are represented as lists but inference currently skips composite target keys. Generation/reference use only index zero. Because the normal inference path does not produce composite joins, this was not elevated to a reachable end-to-end defect; validate unsupported cardinality/key shapes explicitly if introducing manual join editing.

## Suggested order

1. Stop rejected ontology relationships from reappearing; make certification lineage match generated behavior.
2. Add canonical financial category validation and preserve unknown classifications as blocking evidence gaps.
3. Establish the precision contract and test independent rounding invariants.
4. Optimize repeated source reads/snapshot construction using measured larger synthetic datasets.
