# Final portfolio acceptance

Alex approved finalization on 2026-09-27: **“Looks good to me. FINALIZE THIS. I APPROVE ALL.”**
The project is accepted as a finished synthetic-data portfolio project. No required owner action
remains for this release. Production deployment and additional research are outside its scope.

## Accepted work

- The personal statement in [the acceptance packet](ASSISTED-ACCEPTANCE.md) is approved by Alex.
- The six real model-session transcripts and assistant-prepared annotations are accepted. Their
  [scored report](evidence/live-study/scored.json) counts three approved findings in each condition.
  These are owner-approved assistant annotations, not independent blinded human coding. The list
  is non-exhaustive, and no Skill improvement is claimed.
- The 3:51 synthetic-voice video and public project page satisfy the presentation deliverable.
  The video was recorded before final acceptance; its pending-review remarks describe that date.
  Personal narration and an external usability opinion are optional future additions.
- The real profile-session run was continued after collection using explicitly delegated reviewer
  actions. Its original model transcript remains unchanged. The reviewer principal is
  `alex:delegated-via-codex`, making clear that Codex executed Alex's authorization rather than
  claiming Alex personally operated the CLI.

## Completed workflow and verification

Run `ebfcaa24-a2d9-40bd-b8ee-4de306a1253e` now has status **complete**. All 22 mapping decisions
were submitted, then its own generated bundle and reconciliation were checked before certification.
The remaining CRM issue is resolved with an explicit policy: retain in-scope billing customers,
use a left join for CRM enrichment, and allow missing CRM attributes. The warehouse query confirmed
124 input customers and 124 dimension customers, including 10 without a usable CRM match.

The run passed 26 reconciliation checks with no failed or waived checks, published nine metrics,
and verified all 58 bundle files against their expected hashes. The audit chain is intact.
See [acceptance record](evidence/owner-acceptance/acceptance.json),
[mapping approval](evidence/owner-acceptance/mapping-approval.json),
[certification approval](evidence/owner-acceptance/certification-approval.json),
[reconciliation](evidence/owner-acceptance/reconciliation.json), and
[completed run report](evidence/owner-acceptance/run-report.md).

This continuation occurred after the six-session experiment. It does not change the experiment's
observed stopping points, tool histories, response text or timing measurements. Owner acceptance
does not establish independent usability, model efficacy, production readiness or business savings.

## Release disposition

The existing v0.1.0 tag and distribution files remain immutable. Their original passing CI and
checksums still identify the shipped code. Final acceptance is an additional documentation/evidence
commit, linked from the published release, which is promoted from prerelease to **v0.1.0 portfolio release**.

Known limits remain visible: the unfamiliar-schema probe matched 0/10 targets, full MetricFlow
runtime support is deferred, the optional paid judge remains off, and the demo container retains
unfixed Debian findings. These are accepted scope limits, not unfinished release tasks.
