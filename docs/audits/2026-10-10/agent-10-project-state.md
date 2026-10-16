# Agent 10/10 — project state, documentation, operator experience and roadmap

Audit date: 2026-10-10. Reviewed checkout `e1f8e369`; no tracked implementation changes or external writes. The parent independently verified that local/main match, stable release is v0.1.1, latest candidate is v0.2.0-rc.3, all ten exact-commit CI jobs passed, and fresh golden/wheel checks pass. Those verification results are parent-supplied, not duplicate runs by this agent.

## Assessment

The project is a released, unusually well-evidenced synthetic portfolio workflow with a later automated qualification candidate. It is not an accepted production application. That boundary is already explicit and sensible: free Pages presentation plus reproducible local/CI execution, no deployed backend, no measured human savings. The strongest portfolio value is inspectable deterministic calculations, persistent state, separate review authority and retained negative experimental results. More hosting or integrations will not resolve the audit's actual correctness issues.

README, public Pages, case study, claims guide and automated qualification ledger carefully distinguish the original 0/10 probe, initial frozen benchmark failures, feedback-informed remediation and source-informed automated reviewer exercise. Existing historical reports must remain immutable. Old acceptance counts are dated historical observations, not automatic defects. The current v1 review burden is 17/33 (51.5%); v2 is 48/52 (92.3%), with 42/52 correct proposals and ten wrong reviewed proposals. These are useful guardrails but do not demonstrate low review effort or trustworthy autonomous generalization. Correct proposal counts and target recall should remain separate from review effort and financial end-to-end correctness.

## DOC-01 — P2: PostgreSQL quickstart switches out of the environment it just installed

References: `docs/POSTGRES-SOURCE.md:19`, `:32-33`, `:170`, `:200`; compare `README.md:137` onward and `docs/pilot-kit/setup-and-training.md:13,28-37`.

The installation command uses `python -m uv sync --extra postgres --frozen`, which installs the project into `.venv`. Subsequent commands use bare `python -m src.cli`, `python -m pytest` and `python -m scripts.smoke_postgres_source`, with no activation instruction. Bare Python need not select that interpreter or its psycopg dependency. In this session `Get-Command python` resolves to `C:\Python314\python.exe`, while the project environment is Python 3.12. The global interpreter happens to have enough installed dependencies for CLI help, so this is a demonstrated interpreter-selection defect and fresh-machine portability risk, not a falsely reported local import crash.

Fix the documented source and smoke paths to use `python -m uv run --frozen --extra postgres portco ...` / `python -m uv run --frozen --extra postgres python -m ...`, or consistently use `uv run` as the rest of the quickstart does. Run the documented sequence once with an isolated base interpreter containing only uv, so ambient global packages cannot mask the mistake. Avoid invoking `uv sync` here merely to validate prose because it mutates the active environment.

Primary research: [uv running commands](https://docs.astral.sh/uv/concepts/projects/run/) explicitly states that the project `.venv` is isolated from the current shell and recommends `uv run` for project commands. Retrieved 2026-10-10.

## DOC-02 — P2: installed Skill contradicts the actual agent publication contract

References: `skills/schema-profiling/SKILL.md:68`; `src/domain/policies.py:46-51`; `src/capabilities/tools.py:344-346`; `skills/semantic-layer-generation/SKILL.md:40-41`; `docs/agent_walkthrough.md:34`.

Schema profiling instructs an agent to never publish and says those tools reject agent principals. The policy explicitly permits `publish` for all roles once certification exists, and the semantic Skill/walkthrough direct the agent to publish after separate reviewer certification. An agent loading multiple Skills receives incompatible instructions about the final workflow action. This is instruction drift, not an authorization bypass.

Fix by preserving the absolute prohibition on agent approval/certification/waiver and describing publication as allowed only with the current separate reviewer's valid certification. If schema-profiling is intentionally discovery-only, say it stops at mapping review because of that Skill's scope; do not misdescribe the server permission. A small policy/document contract check is appropriate; a new live paid model experiment is unnecessary for this text correction.

## DOC-03 — P3: reviewer explanation Skill omits the reason codes responsible for the current safety tradeoff

References: `skills/canonical-pe-ontology/SKILL.md:30-44`; `src/services/mapping.py:216-222`; `docs/AUTOMATED-QUALIFICATION.md:30-33`.

The reason-code explanation table omits `STRUCTURAL_INFERENCE` and `ENTITY_UNCERTAIN`. The latter is the current repair that raises v2 review to 48/52. An operator following the Skill is told to translate each code using the table but lacks the central explanation: even an exact field-name match cannot settle the enclosing table's business entity. This weakens review guidance precisely where measured review burden is highest.

Add source/table evidence, entity alternatives, confidence limitations and clear approve/reject/abstain examples for both codes. Explain that heuristic scores are not calibrated probabilities. Prefer generating the enumerated code inventory from implementation/contracts while keeping hand-written domain rationale. Validate a current exported v2 packet against that inventory; do not fabricate human usability outcomes.

## DOC-04 — P3: historical roadmap entry points still point readers to superseded active work

References: `docs/ROADMAP.md:3-5`; `docs/PORTFOLIO-ROADMAP.md:8`; `docs/EXTERNAL-VALIDATION-ROADMAP.md:3-15`; `docs/AUTOMATED-QUALIFICATION.md:13-27`; `docs/RELEASE-STATUS.md:83-85`.

ROADMAP's opening calls PORTFOLIO-ROADMAP the current remaining-work plan. PORTFOLIO-ROADMAP instead says it is historical and delegates current completion to release status; the external-validation roadmap delegates active execution to the automated ledger. Release status also retains a transition paragraph saying the owner subsequently requested a live service and the expanded requirement is not closed, although its current section records the later free-only decision. Each historical decision is traceable, but a new maintainer must follow multiple redirects and dated amendments to determine that automated qualification is complete and hosting is optional.

Keep historical plans and evidence unchanged below their banners. Update only entry-point banners/transition context so every old roadmap points directly to one current status/next-work index, explicitly dated and linked to the exact candidate. A compact current-state table should identify stable release, latest candidate, supported source types, current known defects and next remediation batch. Do not rewrite old failed experiments to look successful.

## Static presentation and documentation verification

- Checked relative Markdown/HTML file targets in 44 root/first-level documentation and Skill/reference documents: zero missing local targets. This was a bounded path-existence check, not a complete Markdown-anchor checker or exhaustive remote link crawl.
- Direct HTTPS GET of `https://ahines99.github.io/portco-data-onboarding/` returned 200. Content exactly matches local `docs/index.html` after CRLF/LF normalization. The web-search fetcher could not access the page, so normal HTTP was used to verify it.
- Reviewed the HTML, replay controls, transcript fallback, responsive CSS, visible focus styling and accessible control labels. No browser/assistive-technology pass was performed; historical browser screenshots are not presented as a new October visual test.
- The static replay is clearly identified as recorded output; automated decisions and synthetic voice are disclosed. No tracking SDK, runtime model call, or backend is present in the inspected HTML. The perpetual idle `requestAnimationFrame` loop is a minor energy improvement opportunity, not an important performance bottleneck relative to source extraction and workflow execution findings elsewhere.
- The above-the-fold story is clear, but current qualification evidence sits in a dense lower section. A short current-result card linking the candidate and mixed benchmark outcomes would help hiring reviewers without adding claims or a live app.

## Proposed next roadmap

This is an audit recommendation, not authorization to change scope, spend money, deploy or claim new acceptance. Existing free-only and automated execution preferences remain suitable.

1. **Correctness and authority repair batch first.** Close the separately reproduced stale-authority/cache and worker-identity defects, rejected-join resurrection, noncanonical financial labels passing as zero, and exception telemetry leaks before adding integrations. Their consequences directly undermine the project's strongest claims. Use the other agents' exact reproducers as acceptance cases; test composed workflows and negative decisions, not only isolated helpers. Record the current audit as a new evidence layer and retain earlier release evidence.
2. **Performance batch with preserved semantics.** Implement the bounded PostgreSQL cursor batching and repeat-insert improvements proposed by the performance/ingestion agents. Benchmark input growth and network latency separately, record rows/bytes/query counts and peak memory, and require unchanged snapshot, metric and review contracts. The public portfolio does not need a scale claim; useful evidence is a before/after comparison on declared synthetic inputs. Do not introduce more workers until lease/authority behavior is fixed.
3. **Operator path and release coherence.** Fix DOC-01/02/03, provide a single current work index, and replay the documented CSV/PostgreSQL path with separate delegated operator and reviewer identities. Keep per-item decisions explicit; do not reduce review counts using bulk default approval. Re-run the required release gates against the exact repaired commit, then publish a new candidate only under the user's eventual publishing authorization. Existing root audit work is not an authorization to publish.
4. **Reduce wrong proposals before trying to reduce review flags.** On a new frozen, separately authored corpus, measure wrong unreviewed decisions, proposal precision, positive-target coverage, abstention and review count together. Report review-reason mix, corrections, evidence lookups and agent command effort separately from human time. Prioritize canonical value translation contracts and entity uncertainty: current v2 needs review on 92.3% of proposals, so merely routing more items is close to saturated. A defensible improvement is fewer wrong proposals or more justified abstentions with preserved coverage/safety, followed by narrower evidence-backed review routing. Keep first-run failures even after remediation.
5. **Portfolio maintenance versus product development is an explicit fork.** For a hiring portfolio, one repaired candidate, a concise engineering case study and periodic dependency refresh may be enough. For a product, identify a real supported business task and authorized source, validate the operator/reviewer workflow and definitions, and only then prioritize value crosswalk UI, connector expansion or hosted identity/recovery. Real human usability/customer savings remain unverified unless actual participants and measurements exist; an agent-only roadmap can continue without pretending to establish either.

## Limitations

No customer extract, production account, human participant or hosted service was tested. This agent did not re-execute the parent-owned full suite, golden corpora, wheel smoke or dependency audit, and did not visually test the browser. Cross-agent defects above refer to their dedicated reports/probes; they are not independently duplicated findings or ten separate versions of the same bug. Test success is strong regression evidence but cannot establish invariants that the current assertions omit.
