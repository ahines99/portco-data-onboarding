# Remaining personal review

**Update:** The assistant has collected all six real model sessions, prepared the 22 mapping
decisions and transcript annotations, produced a 3:51 captioned synthetic-voice demo, and verified
the automated fresh-checkout path. You do not need to perform those steps again.

Start with the [prepared acceptance packet](ASSISTED-ACCEPTANCE.md). What remains is confirming
your personal paragraph, inspecting decisions before they are attributed to you, and confirming
draft annotations if you want human-reviewed study scores. An independent person's usability
feedback remains external validation. Personal narration is now optional.

The procedures below are retained for a future personal walkthrough or a new study. The existing
[six sessions and review material](evidence/live-study/README.md) already cover model execution.

## Original procedures for a personal walkthrough

Scripted reviewer roles do not count as your personal review.
There is no paid judge study or public backend to configure. The public repository and MIT choice
are already approved. Do not paste API tokens into source, transcripts or chat.

## 1. Real agent session and approvals

Claude Code was located and its existing sign-in used successfully. Follow [agent walkthrough](agent_walkthrough.md)
and [operations](operations.md). Start with `fixture:portco_a` as the agent role. Inspect the 22
mapping items, especially cents-to-major units and CRM bookings versus recognized revenue. Submit
your decisions from the reviewer terminal as `alex`. At certification, inspect all metric statuses,
reconciliation and exclusions before deciding. Export the full transcript including tool arguments,
results and evidence reads. No replacement transcript should be invented if the session fails.

## 2. Six-session Skill study

Collection is complete; review the existing transcripts rather than rerunning them. For a new study,
the [protocol](skill_comparison.md) defines three exact prompts in six fresh sessions, with and without
Skills. Run `uv run python scripts/compare_skills.py prepare var/skill-comparison` once, then use the
generated `comparison.json`. Keep model/settings/tools and prompts constant; alternate condition
order. Record failures as well as successes. Inspect all transcripts and fill the reviewer metadata
and line-anchored annotations. A second person can independently check a subset. Then run:

```text
uv run python scripts/compare_skills.py score var/skill-comparison/comparison.json
```

No improvement is an acceptable result. Three pairs do not establish general statistical efficacy.

## 3. Personal narrative and recording

Recommended personal wording is ready in the [acceptance packet](ASSISTED-ACCEPTANCE.md). Read
[case study](portfolio_case_study.md). Confirm your actual motivation, design decisions and
contribution; do not sign first-person authorship claims merely because they sound strong. Optionally record
three-to-four minutes of narration using [demo script](demo_script.md), including your real approval
moment from step 1. The existing site replay is a labeled automated demo, not that human recording.

## 4. Independent first-use review

From a fresh checkout/environment, follow only README instructions. Record setup time, errors,
unclear steps and whether you can explain the result. Ideally ask someone else to do this. Check
the public project page and links while logged out. This feedback closes a different gap than CI.

Once these artifacts exist, the candidate release can be promoted and the acceptance ledger updated.
Optional paid judge work remains deferred; it requires a separate spending ceiling and secret setup.
