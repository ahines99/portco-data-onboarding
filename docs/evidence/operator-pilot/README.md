# Operator pilot evidence (not yet collected)

[TEMPLATE.json](TEMPLATE.json) is a blank collection aid, not a completed observation or executable
validator. Follow the [protocol](../../OPERATOR-PILOT.md) before filling it. It is deliberately
unpopulated: no participant, consent, outcome or signoff has been fabricated.

Copy the template into a private study directory. Assign an opaque pilot ID and freeze the agreed
protocol before the trial. Add one attempt object per arm/task using `attempt_record_fields` as the
field dictionary; that dictionary is not itself a completed attempt. Keep missing measurements null.
Store timer logs, approvals, names, source data and detailed diagnostics privately. Reference them
with opaque IDs, not public URLs or sensitive filesystem paths.

Preserve failed and abandoned attempts; reconcile denominators against all started tasks. Review
all computed rates against their raw counts. Do not treat `false`, `null` and zero as interchangeable.
Participant attestations must come from the named operator, reviewer and owner, not the assistant.

Before sharing an aggregate record, remove unused template fields, record the applicable code and
input hashes, obtain the owner's publication decision, and inspect the complete output for privacy
risks. Add a report explaining scope, order effects, developer assistance and excluded/missing values.
An external operator pilot remains outstanding until that evidence exists.
