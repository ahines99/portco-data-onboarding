# Local setup and unrelated training

Use Python 3.12, Git and uv on an existing workstation. No Docker, cloud subscription or API key
is required for this path. The coordinator supplies an exact committed `FROZEN_COMMIT` in the
private task sheet before the pilot; do not measure a changing main branch. The kit/tool revision
must also be recorded if different from the application revision.

```text
git clone https://github.com/ahines99/portco-data-onboarding.git
cd portco-data-onboarding
git checkout FROZEN_COMMIT
git status --short
uv sync --all-extras --frozen
```

Replace `FROZEN_COMMIT` with the agreed full SHA. Expected status output is empty. If uv is installed
as a Python module but not on PATH, replace `uv` with `python -m uv`. Record actual install time and
problems as setup effort; the automated setup proof is not the participant's measurement.

**Training uses a fresh synthetic environment, never the measured task's answers.**

Example for PowerShell:

```powershell
$env:PORTCO_ENV = 'dev'
$env:PORTCO_LLM_ENABLED = 'false'
$env:PORTCO_VAR_ROOT = Join-Path (Get-Location) 'var/pilot-training'
uv run portco fixtures generate --fixture b
uv run portco run --fixture portco_b --as training-agent
```

Record the returned run ID, then export its review packet:

```text
uv run portco review RUN_ID --export var/pilot-training/review.yaml
uv run portco report RUN_ID --out var/pilot-training/report.md
uv run portco audit RUN_ID --verify
```

The coordinator helps the participant identify the current gate, one uncertain mapping, its
evidence, and the packet's content hash. Explain why the run starter cannot approve their own
run and why edits invalidate earlier approvals. Do not give the participant the actual pilot
mapping answers during training. If the planned pilot uses this same fixture/schema, choose
another training input or explicitly disclose the exposure.

`uv run poe demo` is useful for orientation: its reviewers are automated and its failures are
scripted. Do not run it as the measured human task. Import decisions individually through the
review packet for the pilot; do not use `--default approve` to substitute for actual review.

Before the pilot, open a fresh shell and configure a different private runtime directory. Use
`PORTCO_ENV=dev`, `PORTCO_LLM_ENABLED=false`, and the coordinator-approved local database/storage
settings. A separate reviewer identity is required but the local operating-system user remains
trusted. Do not serve this setup publicly. Keep interval logs in the private session directory.

**Common problems and the next action:**

| Observation | Action |
| --- | --- |
| Wrong Python version | Use Python 3.12; do not regenerate the dependency lock to force installation |
| Fixture connection missing | Generate the named fixture in the same `PORTCO_VAR_ROOT` used by the run |
| Source import rejected | Compare the manifest's types/order and path limits with the [CSV contract](../CSV-SOURCE.md); do not relax validation |
| Run says `needs_review` | This is an expected gate; export the current packet for the separate reviewer |
| Approval says stale/conflict | Export again and inspect the current content; do not reuse an earlier signature/hash |
| Agent approval forbidden | Use the actual designated reviewer through the supported review command |
| Sandbox/reconciliation fails | Preserve findings, stop per the frozen rules, and log assistance; do not hide a failed financial control with a waiver |
| Storage or access error | Check approved local paths and access; keep private logs and stop rather than printing source data publicly |

Any workaround or developer intervention is a deviation/assistance event. A material application
fix creates a new attempt/version; it does not erase the original failure.
