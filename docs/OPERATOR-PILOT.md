# Operator pilot: protocol and evidence requirements

**Status: protocol prepared; no participant, consent, completed trial or measured benefit.**
The [blank record](evidence/operator-pilot/TEMPLATE.json) contains null measurements deliberately.
Public retail data and synthetic demonstrations are not evidence of customer adoption or savings.
This protocol describes a small feasibility pilot, not a statistically powered impact study.

## Decision the pilot should support

Determine whether a real operator can onboard a bounded, authorized extract into a reviewed data
product using this workflow, and whether the observed effort and error burden justify a broader
trial. The comparison is the operator's usual documented manual workflow against this project's
assisted workflow. Agree the common output contract before either arm starts.

Start with one company, one frozen extract, one operator and a separate reviewer. Select a limited
set of supported entities/metrics; do not promise that arbitrary sources will yield all nine metrics.
An ingestion/profile-only trial is valid if predeclared, but cannot be reported as a certified
financial onboarding. Record unsupported tasks and failures instead of changing the task mid-study.

## Prerequisites and consent

1. The data owner authorizes the named purpose, source fields, operator, reviewer, storage location,
   retention period, deletion method and permitted outputs in a private record. Record only its
   opaque reference in the shareable report. Permission to access a system is not permission to
   publish its data, transmit it to a model provider, or identify the company publicly.
2. Inventory the extract and minimize it before import. Remove unnecessary free text, direct
   personal identifiers, secrets, sensitive notes and precise dates that are unnecessary to the
   task. Use stable private-key pseudonyms when joins require identity; keep any key/mapping
   separately under the data owner's control. Pseudonymization does not guarantee anonymity.
3. Have the owner inspect the deidentified sample, manifest, approved category domains and proposed
   public outputs. Aggregate profiles can still disclose sensitive small groups. Obtain permission
   for the residual disclosure risk; withhold public outputs until separately reviewed.
4. Restrict filesystem and database access; use approved encrypted storage and coordinated backups.
   Do not commit extracts, snapshots, participant names or approval documents to Git. Follow the
   owner's retention and deletion decision for backups too.
5. Keep LLM calls disabled for the initial pilot. If a real agent client is used, separately approve
   its provider and the exact metadata/aggregate disclosure. It must not receive reviewer tokens.
   The local operator remains trusted; static development tokens are not a hosted customer boundary.
6. For a hosted pilot, complete the actual identity, isolation, vulnerability, restart and recovery
   checks in [LIVE-DEPLOYMENT.md](LIVE-DEPLOYMENT.md) first. A local authorized pilot does not validate
   the hosted service. The initial proposed live deployment still uses only synthetic data.

The data owner may withdraw before publication. Record withdrawal and follow the agreed deletion
procedure; never replace missing consent or a withdrawn result with an assumed approval.

## Freeze the task and acceptance criteria

Before running either arm, record:

- Source/extract hashes, reference date, manifest, intended company, selected entities and metrics.
- Shared deliverables: mapping, declared units/joins, transformations, quality checks, reconciled
  outputs and review packet. Both arms must meet the same definition of done.
- Reference answers prepared by a domain owner/reviewer without looking at assisted proposals.
  Distinguish agreed business policy from an independently verified numerical reference.
- All required mapping decisions, monetary comparisons, row-retention checks and expected exclusions.
- Software commit/lock hashes, environment, model/client/version if used, operator experience,
  training time and access boundaries. Record whether the operator helped build the software.
- Order and allocation of tasks, maximum active time per arm, stopping rules and missing-data policy.
  Do not choose the time cap after seeing which arm is slower.
- Which party will authorize sharing the final aggregate findings and permitted quotations.

Safety acceptance is fixed: no unauthorized disclosure, no agent/self-approval, no waivers hiding
failed financial controls, current content-bound certification for publication, and a verified bundle
and audit chain. Task completion thresholds must be agreed before execution. Time improvement is
exploratory in a one-operator pilot; there is no promised savings threshold.

## Comparison design

Prefer at least two matched tasks and counterbalance order: manual then assisted for one task,
assisted then manual for the other. Use disjoint comparable extracts or schemas so the operator
cannot merely copy the first solution. Record differences in task size and complexity. If only one
extract exists, the second arm benefits from prior exposure; disclose the order and learning effect
rather than attributing the entire difference to the tool. Never give one arm a cleaned source or
completed mapping that the other did not receive.

Allow a short training exercise on unrelated synthetic data. Record training/setup effort separately
and report it alongside recurring task effort. Keep the comparison at the same output scope; count
manual tests/reconciliation and assisted preparation/review, not just model or dbt execution time.

## Measurement dictionary

Use a timer/event log with UTC start/end, pseudonymous actor, task, arm and activity. Retain the
private raw record; publish aggregates only after owner approval. Missing values remain null.

| Measure | Definition and denominator |
|---|---|
| Wall-clock completion time | Seconds from release of the frozen task/input to accepted final output; include waiting and report its causes |
| Operator active time | Sum of nonoverlapping operator intervals for extraction/preparation, mapping, implementation, checking and corrections; exclude reviewer and unattended compute |
| Reviewer active time | Sum of reviewer inspection, decision and reinspection intervals; never merge with operator time without labeling combined person-time |
| Machine elapsed time | Recorded process duration, including retries; concurrent durations are not human labor |
| Setup/training | Separate person-time for initial install, permissions, source adaptation and familiarization; include in first-use total |
| Review burden | Unique decisions requiring review / all required decisions, plus reviewer minutes and number of revision cycles; deduplicate the same decision across retries |
| First-pass correction rate | Decisions rejected or materially changed by the reviewer / decisions assessed in the first submitted packet; use null if none assessed |
| Final correctness | Correct decisions / required labeled decisions, with missing decisions counted as incomplete; report mappings, joins, units and metrics separately |
| Completion | Number meeting the frozen definition of done / all started tasks, including timeouts, withdrawals and unsupported cases with separate reasons |
| Publication integrity | Certification subject matches published content; file hashes and audit chain verify; boolean plus evidence reference |
| Cost | Actual invoiced or measured compute/model/hosting charges, currency and allocation method; unknown is null, not zero |

A material correction changes target entity/field, unit/transform, join/retention policy, business
meaning, test outcome or required disclosure. Cosmetic wording is tracked separately. Report raw
numerators and denominators with rates. A failed task has no successful completion time; report its
elapsed time to failure and reason. Do not average only the successful assisted tasks against all
manual tasks.

For matched completed tasks, report raw paired differences and, if useful, medians. A percentage
reduction is `(manual - assisted) / manual * 100`, only when the manual denominator is positive and
both scopes match. Show negative values and first-use setup cost. With a small sample, describe the
result as observed in this pilot; do not extrapolate annual dollars, adoption, ROI or causation.

## Run, review and close

1. Execute the frozen plan. Log interruptions, retries, support from the developer and deviations.
2. For assisted tasks, retain source fingerprints, run IDs, review packet hashes, findings, actual
   reviewer decisions, reconciliation reports and publication verification. Do not auto-approve the
   pilot as a substitute for the named reviewer. Distinguish assistance from independent review.
3. Stop on access violations, suspected disclosure, unexplained financial discrepancies or breached
   time caps. Preserve diagnostics privately, notify the owner through an agreed channel, and count
   the outcome. Starting over does not erase the original failed attempt.
4. Reviewer signs the task result, with rejected/changed decisions and any unresolved limitation.
   Operator confirms time logs and usability observations; owner signs the sharing/redaction decision.
   These are distinct attestations. Repo ownership or a passing test is not participant signoff.
5. Complete the [record template](evidence/operator-pilot/TEMPLATE.json), link private evidence by
   opaque reference, and write an aggregate report with failures, missing values and limitations.
6. If public release is authorized, inspect for sensitive fields, paths and small-group disclosure.
   Publish only the approved aggregate report. Execute and record retention/deletion decisions.

## What a completed pilot could support

A completed record may support a scoped statement such as: "In a consented two-task pilot with one
operator, observed assisted active time was X versus Y minutes for the specified deliverables."
It must include sample size, review effort, corrections, failures and design limitations. Those
variables are not current project results. Broader customer value needs repeated independent
operators/tasks and stronger controls; a pilot does not establish enterprise readiness.
