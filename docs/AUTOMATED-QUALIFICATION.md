# Automated roadmap execution

Owner steering, 2026-09-28: "Everything should be fully agentic or automated."
This amends the [external-validation roadmap](EXTERNAL-VALIDATION-ROADMAP.md) for the active
execution. No paid service, API calls to separately billed models or human/customer evidence is
assumed. Agents operate inside the current session; the optional mapping judge remains disabled.

The outcome is a reproducible automated qualification and integration release. Preserve the
distinction between deterministic automation, separate-agent authorship and external human use.
The prepared [human pilot kit](pilot-kit/README.md) remains available but unexecuted.

| Gate | Automated deliverable | Acceptance evidence | Current status |
| --- | --- | --- | --- |
| A0 | Pinned setup verification and recording kit | [Fresh source setup proof](evidence/pilot-kit-setup-20260928.json), [kit](pilot-kit/README.md), recording-tool integrity tests | Complete |
| A1 | Separate agent operates the documented CLI; separate delegated automated reviewer handles decisions | [Operator](evidence/agent-operator-qualification/README.md) and [reviewer](evidence/agent-reviewer-qualification/README.md): six metrics published, 38 files verified, 46-event audit intact; one unsupported mapping rejected | Complete on the pinned baseline |
| A2 | New separately authored six-case schema corpus, frozen before evaluation | [Frozen corpus and reports](../evals/agent_qualification_v2/README.md); initial safety failure preserved; entity-uncertainty repair passes safety with unchanged 42/52 correct proposals | Complete; hosted safety gate passes |
| A3 | One real read-only PostgreSQL connector | [Actual PostgreSQL acceptance](evidence/postgres-source-acceptance.json): 11 tables / 14,639 rows, nine metrics published, 59 publication files, 45 intact audit events, zero waivers; concurrency and rejection tests | Complete in hosted CI |
| A4 | Review usability improvements justified by agent observations | [Follow-up](evidence/agent-operator-qualification/FOLLOWUP.md): evidence links and neutral reviewer wording verified; premature certification link discovered, corrected and retested; self-approval and stale hash denied | Complete |
| A5 | Integrated release and honest portfolio narrative | [v0.2.0-rc.3 release record](https://github.com/ahines99/portco-data-onboarding/releases/tag/v0.2.0-rc.3): exact commit, CI results, PostgreSQL acceptance, package/evidence assets and SHA256 checksums | Complete; exact verified source and assets in linked record |

Implementation CI [36443092813](https://github.com/ahines99/portco-data-onboarding/actions/runs/36443092813)
verified the new integration and both benchmark safety gates. The release record is authoritative for
the final source commit, its fresh full CI run and attached evidence. Historical operator/setup
reports retain baseline `03c4fb3`; they are not relabeled as exercises of the release commit.

The original v1 benchmark also remains safety-passing with 32/33 correct proposals, but this
entity-uncertainty change raises review to 17/33 from the historical 7/33. V2 remains 42/52 correct,
with 48/52 requiring review. Increased routing is a safety tradeoff, not a mapping-accuracy gain.
The free local/CI roadmap needs no further owner action. Optional human research and live production
acceptance remain separate, unverified scopes.

The PostgreSQL source will run in an isolated test environment under our control, using synthetic
business records and optionally permitted public historical data. This verifies a real database
protocol and connector; it does not claim access to a customer's production system. A source role
must be read-only, while source seeding is a separate test-administrator operation.

A1 records agent command time and observed behavior, not human active time. It has no invented
manual baseline and produces no analyst-savings percentage. Reviewers are explicitly delegated
automated identities, and their decisions remain content-bound and separate from the run starter.

A2's author does not inspect mapper/scoring implementation or previous labels/results. The worker
receives inputs and blocks reads of the selected labels directory with the documented Python
regression guard. This is not an OS sandbox or external human evaluation. Preserve first outcomes
even if they fail. New evidence must not overwrite the original 0/10 probe or v1 results.

If A1 reveals no issue warranting a new interface, A4 can conclude with documented evidence that
the existing CLI satisfies the automated task; do not invent a human usability result or build a
browser application merely to check a box. Any actual fix requires a new labeled retest.

Remote hosting remains optional and is not part of this automated local/CI qualification. The
public presentation stays on GitHub Pages. A production acceptance claim still requires actual
hosting, identity, runtime and coordinated recovery evidence under a viable authorized plan.
