# Private timing, assistance and deviation records

Prepare a fresh session from a checkout containing the recorder:

```text
uv run python -m scripts.pilot_session prepare var/operator-pilot/PILOT_ID --pilot-id PILOT_ID
```

Use an opaque identifier, not a participant or company name. Inside the repository the tool only
permits records under ignored `var/`; approved private storage outside the checkout also works.
It refuses an existing directory. Protect that storage and its backups according to intake.

The tool creates:

- `pilot.json`: the existing unexecuted record template, with consent/results still null.
- `baseline.json`: source commit, dirty-worktree flag, lock/protocol/recorder hashes and environment.
- `intervals.csv`: blank activity intervals; exact header order is required.
- `notes.csv`: blank assistance/deviation references. Detailed notes stay in approved private files.

A dirty-worktree flag means the experiment is not pinned. Resolve it and prepare a fresh baseline
before measurement; do not simply edit the flag. If application and recorder use separate checkouts,
record both revisions and the application environment explicitly in the freeze sheet.

At each activity boundary, obtain a timestamp:

```text
uv run python -m scripts.pilot_session stamp
```

Record a row with `attempt_id,task_id,arm,actor,role,phase,activity,started_at_utc,ended_at_utc`.
The stamp command only prints time; it does not automatically observe work. Participants or the
agreed facilitator must record and confirm actual activity. Use ISO 8601 timestamps with timezone.

| Field | Values/rule |
| --- | --- |
| attempt_id | Unique opaque attempt; a retest gets a new ID |
| task_id | Frozen task identifier |
| arm | `manual` or `assisted` |
| actor | Opaque stable actor ID; do not change identities to hide overlap |
| role | `operator`, `reviewer`, `developer` or `machine`; a person cannot occupy two roles in the pilot |
| phase | `setup`, `training` or `task` |
| activity | Opaque label such as `mapping`, `review`, `correction` or `compute` |
| started_at_utc / ended_at_utc | Actual observed boundaries; no estimated fill-in for missing data |

Pause active-time intervals during breaks or unattended compute. Record compute under a machine
actor. Record developer assistance separately and reference it in notes, even if the operator's
own active interval continues. Simultaneous people produce person-time, not wall-clock time.
Never drop failures, retries or correction time. Track first-use setup/training separately.

For notes, use `at_utc,attempt_id,kind,private_reference`; kinds include `assistance`, `deviation`,
`interruption`, `failure` and `withdrawal`. Record requested help, what changed and its effect in
the referenced private note. The timing tool does not interpret or redact narrative notes.

```text
uv run python -m scripts.pilot_session summarize var/operator-pilot/PILOT_ID
```

The tool rejects missing timestamps, timezone ambiguity, inconsistent attempts/roles and overlapping
intervals for the same actor. It writes `timing-summary.json` with sums per attempt, role and phase.
Missing categories remain null, not zero. Resolve mistakes against the original event log and
document corrections; do not alter times merely to pass validation.

This summary is explicitly unattested. It proves neither consent nor completion, correctness,
independence or permission to publish. It calculates no savings percentage. Use the protocol to
record wall-clock completion, reviewer corrections, failed tasks and actual attestations in
`pilot.json`, preserving raw records. A separately confirmed absence can be recorded as zero in
the final pilot record with its evidence; an unmeasured category must remain null.
