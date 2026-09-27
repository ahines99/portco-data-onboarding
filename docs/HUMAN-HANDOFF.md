# Remaining actions requiring Alex

Everything here depends on your participation; scripted reviewer roles do not count as your review.
There is no paid judge study or public backend to configure. The public repository and MIT choice
are already approved. Do not paste API tokens into source, transcripts or chat.

## 1. Real agent session and approvals

Make your authenticated Claude Code session available. Follow [agent walkthrough](agent_walkthrough.md)
and [operations](operations.md). Start with `fixture:portco_a` as the agent role. Inspect the 22
mapping items, especially cents-to-major units and CRM bookings versus recognized revenue. Submit
your decisions from the reviewer terminal as `alex`. At certification, inspect all metric statuses,
reconciliation and exclusions before deciding. Export the full transcript including tool arguments,
results and evidence reads. No replacement transcript should be invented if the session fails.

## 2. Six-session Skill study

The [protocol](skill_comparison.md) defines three exact prompts in six fresh sessions, with and without
Skills. Run `uv run python scripts/compare_skills.py prepare var/skill-comparison` once, then use the
generated `comparison.json`. Keep model/settings/tools and prompts constant; alternate condition
order. Record failures as well as successes. Inspect all transcripts and fill the reviewer metadata
and line-anchored annotations. A second person can independently check a subset. Then run:

```text
uv run python scripts/compare_skills.py score var/skill-comparison/comparison.json
```

No improvement is an acceptable result. Three pairs do not establish general statistical efficacy.

## 3. Personal narrative and recording

Read [case study](portfolio_case_study.md). Supply your actual motivation, design decisions and
contribution; do not sign first-person authorship claims merely because they sound strong. Record
three-to-four minutes of narration using [demo script](demo_script.md), including your real approval
moment from step 1. The existing site replay is a labeled automated demo, not that human recording.

## 4. Independent first-use review

From a fresh checkout/environment, follow only README instructions. Record setup time, errors,
unclear steps and whether you can explain the result. Ideally ask someone else to do this. Check
the public project page and links while logged out. This feedback closes a different gap than CI.

Once these artifacts exist, the candidate release can be promoted and the acceptance ledger updated.
Optional paid judge work remains deferred; it requires a separate spending ceiling and secret setup.
