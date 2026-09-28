# Audit gap roadmap and implementation record

Planning baseline: `e09be37f9e99f6c805698af50b3d13b5f421a923`.
Source: owner-supplied portfolio assessment, reviewed 2026-09-28 UTC.
The owner requested five planning agents and implementation by those same five agents.
This roadmap supersedes historical planning checklists for this audit response only.

## Objective and accepted boundaries

Bridge the audit's practical gaps: unfamiliar-schema evidence and inference, an external-input
integration boundary, deployment security evidence, and a usable path to authentic operator impact.
Preserve deterministic financial calculations, privacy constraints, tenant authorization,
content-bound approvals, separate reviewer identities and crash-safe publication.

The audit's numeric portfolio rating is subjective. It is not an acceptance test or an outcome
this work promises. Real customer impact, external independent evaluation and live cloud acceptance
require evidence beyond synthetic tests and cannot be manufactured by implementation agents.

## Finalized plan

| ID | Same planning/implementation agent | Deliverable | Acceptance evidence |
| --- | --- | --- | --- |
| GAP-01 | `gap_benchmark` | Four separately authored unfamiliar-schema cases, isolated input/label files, frozen manifest, baseline and final measurements | Manifest frozen before mapper edits; inference receives no labels; report entity/mapping/join/unit results, abstention, review burden and empirical correctness by categorical confidence; preserve failures |
| GAP-02 | `gap_mapping` | Conservative structural entity/key/mapping/join fallbacks and explicit monetary-unit evidence | Ambiguous evidence abstains or requires review; unfamiliar primary/foreign-key proposals require review; date/money/PII uniqueness alone cannot define a key; existing golden behavior remains valid |
| GAP-03 | `gap_source` | Operator-only typed CSV extract import into immutable DuckDB snapshots, persistent connection registration, CLI and full workflow smoke | Reject path escapes, unsafe types/identifiers, overwrite and oversized inputs; retain source provenance; resolve after restart; enforce tenant scope; import through certified publication using labeled synthetic extracts |
| GAP-04 | `gap_security` | Root-owned application image, cleared SUID/SGID bits, safe runtime evidence collector and CI assertions | Existing container workflow passes; image control evidence is captured; full image scan retained; Compose-only controls distinguished from Render's unverified runtime |
| GAP-05 | `gap_portfolio` | Operator pilot protocol, blank measurement records, claims/resume guide and synchronized public documentation | No invented participants, consent, human review or savings; clear denominators/timers; original 0/10 probe and historical acceptance retained; current claims link to observed evidence |
| GAP-06 | Root integration | Integrate and review all changes; full relevant checks; hosted CI and reviewed publication | Clean committed worktree; reproducible commands; actual test/evaluation results; final status separates implementation from external prerequisites |
| GAP-07 | Root integration | Bounded public operational-data ingestion/profile exercise using UCI Online Retail | Official source attribution/license and archive hash; local raw files only; reproducible extract policy, preserved cancellations/missingness, aggregate evidence; no customer-impact or certified-financial-output claim |

## Execution order and ownership

1. All five agents plan before implementation. Root consolidates this document and resolves scope.
2. Benchmark agent authors and freezes the cases and records the unmodified baseline first.
   Mapping agent must not inspect new benchmark labels or tune against outcomes.
3. CSV integration and security work proceed independently while the benchmark freezes.
4. Mapping implementation begins after freeze/baseline confirmation, using general principles and
   its own regression cases. Benchmark agent runs the frozen evaluation again after integration.
5. Portfolio agent implements the pilot/claims artifacts and synchronizes claims to final observed
   outcomes. Test counts from prior releases remain explicitly historical.
6. Root reviews cross-boundary behavior and runs lint/types, relevant unit/security tests, the full
   non-PostgreSQL suite, golden evals, unfamiliar benchmark, source smoke, packaging and hosted CI.

Available concurrency is three child agents at a time. The five agents run in batches and retain
their workstreams across planning and implementation. They share the workspace, with disjoint
file ownership and root-controlled integration; agents do not commit or publish independently.

- Mapping owns `src/services/{entities,mapping,joins}.py` and structural regression tests.
- Source owns CSV importer/tests/docs/smoke and small CLI/connection registry/service wiring edits.
- Benchmark owns its input/label fixtures, harness, tests and benchmark evidence.
- Security owns Dockerfile, runtime collector/tests, container CI section and deployment-risk docs.
- Portfolio owns README, site, current status/case study/handoff and new pilot/claims documents.
- Root owns this roadmap, version/release integration and benchmark CI wiring.

## Measurement rules

Planning addition after source verification: UCI's official Online Retail page identifies a real
retail transaction dataset and CC BY 4.0 terms (https://archive.ics.uci.edu/dataset/352/online+retail).
A bounded extract can bridge the absence of any operational input without obtaining private
customer data. This is separate from the synthetic unfamiliar-schema benchmark and the unexecuted
customer pilot. It must not be used to tune the frozen benchmark or presented as an independent
financial ground truth. Large downloads and raw extracts remain under ignored `var/`.

- Preserve the original unfamiliar-schema probe as historical evidence. A new benchmark does not
  overwrite it or retroactively improve its 0/10 result.
- Separate-agent authorship is a stronger design separation, not independent external human review.
  The benchmark is synthetic and becomes public; future tuning would make it a regression dataset.
- Confidence is categorical. Report empirical correctness by confidence bucket, not probabilistic
  calibration metrics that imply the heuristic score is a probability.
- Do not require an arbitrary accuracy target or conceal abstentions to make results look better.
  Integrity, privacy, permission and mandatory-review invariants remain failing gates.
- CSV import establishes an actual operator-file ingestion boundary. Its demonstration inputs are
  synthetic; it does not establish a live SaaS connector, actual customer adoption or financial impact.
- Container privilege hardening can reduce exposure without removing package advisory findings.
  Preserve complete scans and reassess runtime preconditions for each residual CVE.

## External actions still required

| Requirement | Codex preparation/execution | Owner or external party input |
| --- | --- | --- |
| Live service (optional paid path) | Provider access and real agent-token preflight verified; deployment configuration, identity actions and acceptance procedures prepared | Owner chose free-only delivery on 2026-09-28; paid deployment is not authorized |
| Cloud acceptance | Run actual HTTPS/tenant/reviewer, persistence, isolation and coordinated recovery checks once provisioned | Account controls and access to provider operations |
| Real operating dataset | CSV intake, validation and documented data handling | Authorized dataset and permitted use; agree deidentification and retention before ingestion |
| Customer/business impact | Predefined pilot metrics, evidence forms and reporting rules | Real operator participation, manual baseline, separate review and actual signoff |
| External generalization/usability | Reproducible harness, frozen cases and logs | Independent dataset/reviewer supplied without development-team tuning |

No paid resources, customer data or messages to third parties are authorized by the preparation
alone. Existing repository implementation/publication authorization continues to apply.

## Implementation record

Planning: complete; five agents returned bounded plans before edits began.
Implementation: all five agents implemented their assigned workstreams. Root integrated the public
operational-data exercise, benchmark CI gate and source-backup requirements.

| Gap | Implemented result | Remaining boundary |
| --- | --- | --- |
| GAP-01 | Four frozen cases; baseline, first post-change and remediation reports preserved; CI enforces integrity/review safety | Small synthetic sample; separate-agent authorship is not external validation |
| GAP-02 | Conservative structural inference, explicit unit handling and review of competing monetary representations | Eight opaque fields remain unresolved; one incorrect proposal remains review-required |
| GAP-03 | Typed CSV ingestion and persistent registration; full synthetic import-to-publication smoke with nine metrics | No live SaaS synchronization or arbitrary-schema correctness claim |
| GAP-04 | Root-owned application image, privilege-bit removal, runtime collector and hosted assertions | Unfixed package findings and actual cloud runtime acceptance remain open |
| GAP-05 | Pilot protocol, null evidence template, resume/claims matrix and updated site | No participant, measured savings or independent reviewer signoff invented |
| GAP-06 | Integrated lint/type checks, regression coverage, packaging/CI gates and release evidence | Use the exact candidate release's verification assets for final hosted results |
| GAP-07 | 10,000 public historical retail rows imported/profiled; six aggregate controls passed | No approved mapping, certified financial output or customer benefit measured |

The first post-change unfamiliar benchmark did not improve over baseline: 31/33 proposals correct,
31/32 positive targets covered and 5/6 units correct. It failed safety because competing monetary
interpretations did not all require review. The generic failure class informed a subsequent repair;
the baseline and first failed report remain unchanged. The post-benchmark remediation achieves
32/33 correct proposals, 32/32 positive targets, 6/6 units and a passing safety gate, with review
burden increasing from 6/33 to 7/33 proposals. Entity decisions are 10/10 including two intentional
abstentions; joins are 3/3. This is not untouched held-out evidence or broad operating accuracy.
See the [three-stage benchmark record](../evals/unfamiliar/README.md).

The integrated first implementation passed 606 local non-PostgreSQL tests (one Windows symlink
permission skip; five PostgreSQL tests deselected), all 37 golden evaluation cases, six Auth0 Action
tests, Ruff and mypy. The monetary repair additionally passed 23 structural/golden and 58 workflow,
generation, review-binding and invoice regressions (one existing skip). The full post-remediation
Windows suite passed 608 tests, with one symlink-permission skip and five PostgreSQL tests deselected.
Hosted testing then exposed fixture generation rewriting bundled reference answers under the newly
root-owned application directory. Runtime fixture generation was separated from explicit development
reference regeneration, retaining the read-only application boundary. The release verification record
also retains the subsequent runtime assertion failure for a build-created writable virtual-environment
lock file; application-tree modes were tightened without exempting the file from the gate. The record
distinguishes the Windows run before that final CLI repair from the subsequent targeted and hosted checks.
These populations overlap; do not sum them. Final container/PostgreSQL results and distribution
hashes are recorded in the `v0.2.0-rc.2` release verification assets. Local evidence records worktree
status and implementation hashes because measurements preceded the integration commit.

The roadmap's implementable repository work is complete. Live hosting/identity acceptance,
residual cloud runtime risk decisions, authentic operator impact and independent external
generalization remain the external actions listed above. The project is still a deployment
candidate, not an accepted live production service.
