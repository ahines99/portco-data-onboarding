# Four-minute narrated demonstration

Status: script and automated replay prepared; Alex's live session and narration remain pending.
Use a readable terminal font and hide unrelated windows/credentials. Generate fixtures first with
`uv sync --all-extras --frozen` and `uv run poe fixtures`. Use a fresh, explicitly chosen demo output
folder with `uv run portco demo --out var/recording-demo`; that command resets its demo directory.
For the actual human beat, use a separate live run following [operations](operations.md).

| Time | On screen | Suggested narration |
|---|---|---|
| 0:00–0:25 | Project page and workflow | “A source schema can look plausible and still represent the wrong financial meaning. This prototype makes evidence, review and calculation explicit.” |
| 0:25–0:50 | Profile and mapping review | “These are synthetic records. Profiling exposes aggregates and approved category domains; it doesn't send source rows to the model.” |
| 0:50–1:15 | Cents trap and `rev` finding | “Invoice lines use cents; CRM `rev` describes bookings. The proposed mapping and transform need review.” |
| 1:15–1:45 | Agent denied; Alex's separate review terminal | “The agent principal cannot approve. Here I inspect the items and make the reviewer decisions.” Use a real session for this beat; label any scripted substitute. |
| 1:45–2:10 | Test report | “All nine generated monthly metrics are executed. This fixture passes 26 reconciliation checks, including structural and mart checks; monetary comparisons are exact to the cent.” |
| 2:10–2:35 | Certification and publication | “Certification binds this content and the metric decisions. Publication reserves a version and verifies its files, including on retry.” |
| 2:35–3:00 | Failure/injection replay | “A transient timeout retries. Malformed lines stop publication. A planted instruction does not authorize an action.” |
| 3:00–3:25 | Audit and recovery result | “The audit chain and artifact hashes are checked. Hosted tests recreate the stack; the local rehearsal upgrades and restores populated state.” |
| 3:25–3:50 | CI, held-out probe and scope | “CI passes, but this unfamiliar-schema probe makes no correct mappings. This is a governed fixture-backed prototype, not proof of arbitrary-schema accuracy.” |
| 3:50–4:00 | Repository/evidence links | “The code, reproducible demo and supporting reports are linked here.” |

The [recorded replay](index.html) and [transcript](evidence/demo-transcript.txt) show an actual automated
fixture run. They are a fallback visual, not a substitute for Alex's live approval or model-session
evidence. Caption narration, review the final cut and retain failed live-session evidence in the study.
