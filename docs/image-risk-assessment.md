# Deployment candidate: residual image vulnerability assessment

Assessed 2026-09-28 UTC. Decision: **live exposure remains pending runtime evidence**.
This is a source and advisory review, not an exploit test or an independent security certification.

## Evidence and scope

- Source: `116a9165102dab20c1cc6bcef5704e35d633ede2`, release `v0.2.0-rc.1`.
- [Hosted CI](https://github.com/ahines99/portco-data-onboarding/actions/runs/36365229540): all ten jobs passed.
- [Complete scan](https://github.com/ahines99/portco-data-onboarding/releases/download/v0.2.0-rc.1/container-audit.json), SHA-256 `6afa1adf94bcce0784d4e915bdd107d49a3a1a571462f1e8025670970fc1a936`.
- Image ID: `sha256:ffc300edad2a660bac4a5dd69f5790dd3138a71785ac4d46e32db43a618fc2b0`.
  This identifies the scanned CI image, not a future Render rebuild.
- Debian 13.7: 44 HIGH package/advisory entries, eight distinct CVEs, zero CRITICAL entries,
  and zero fixable HIGH/CRITICAL entries according to that scan. No findings are suppressed.

The application subprocess entry in `src/services/sandbox.py:run_dbt` launches a fixed dbt command
with an argument list, a filtered environment and a timeout. A search of `src` for subprocess,
shell execution and archive extraction found no direct invocation of mount, nsenter, ACL tools,
infocmp, systemd-homed, Perl or Archive::Tar. This is a limited source inspection: dependencies,
native extensions, a compromised process and privileged operator actions are not ruled out.

The Dockerfile sets the application user to UID 10001. The audit-gap changes also retain root
ownership of `/app` and strip SUID/SGID bits from regular files in the final image's root filesystem.
This reduces application code mutation and privilege-helper exposure; it does **not** patch the
flagged packages or remove the requirement for a fresh unfiltered scan. Those changes postdate the
release scan above and must be proved by the new image's CI evidence before relying on them.
For the audit-response candidate, use the exact `v0.2.0-rc.2` release's `container-audit.json`,
`runtime-evidence.json` and `verification.json` together. The earlier image ID and scan counts
above remain historical; a rebuilt image needs its own evidence even when the counts match.
The local Compose service additionally
drops all capabilities, sets `no-new-privileges`, and binds the host port to loopback. **Those
Compose settings are not declared by the Render Blueprint and must not be attributed to Render.**
The production service is intended to be reachable through Render's HTTPS proxy.

## Per-CVE disposition

All rows remain open for live deployment. The links are Debian's primary package status records,
checked on the assessment date. Their stable-release status is not a claim that fixes do not exist
upstream or in Debian testing/unstable. Do not mix unstable packages into the production image to
make a scanner count smaller.

| CVE | Exploit condition described by advisory | Repository evidence and remaining check |
| --- | --- | --- |
| [CVE-2026-76642](https://security-tracker.debian.org/tracker/CVE-2026-76642) | A privileged mount helper fails but privileged post-mount hooks still execute. | No application mount workflow. Verify effective UID/capabilities, privilege escalation restrictions, helper permissions and provider mount boundaries. |
| [CVE-2026-78408](https://security-tracker.debian.org/tracker/CVE-2026-78408) | A privileged operator invokes `nsenter --join-cgroup` on an attacker-controlled target, leaking cgroup authority. | No application nsenter workflow. Do not use this operator pattern; provider host tooling and cgroup isolation need provider evidence. Non-root application UID alone does not prove provider isolation. |
| [CVE-2026-78409](https://security-tracker.debian.org/tracker/CVE-2026-78409) | An authorized `X-mount.subdir` operation follows an intermediate symlink outside the intended tree. | No application fstab or mount configuration. Verify no user-authorized mounts or host-path exposure; check the provider's actual isolation rather than infer it from the source. |
| [CVE-2026-78410](https://security-tracker.debian.org/tracker/CVE-2026-78410) | A local user changes a bind-mount source path used by a SUID mount operation and ownership/mode hooks. | Application runs as UID 10001, but the image review does not establish the absence of SUID helpers. Inspect their permissions and the live process's privilege restrictions. |
| [CVE-2026-54369](https://security-tracker.debian.org/tracker/CVE-2026-54369) | A privileged caller processes attacker-controlled path components through affected libacl pathname operations. | No direct application ACL call. Verify there is no privileged runtime component processing `/data` paths; dependency/native paths remain a limitation of this source review. |
| [CVE-2025-69720](https://security-tracker.debian.org/tracker/CVE-2025-69720) | The infocmp command processes crafted input and overflows a buffer. | No direct application infocmp call or terminal-description input feature. Keep user-controlled terminal processing outside the service and verify the rebuilt image's inventory. Presence of ncurses libraries alone is not evidence that infocmp executes. |
| [CVE-2026-16742](https://security-tracker.debian.org/tracker/CVE-2026-16742) | A local user managed by systemd-homed reaches the vulnerable home-record/group handling. | The Dockerfile starts Python, not systemd-homed; the scan flags systemd libraries. Verify the live process tree and absence of homed-managed login facilities. A library package finding does not by itself prove the daemon is active. |
| [CVE-2026-9538](https://security-tracker.debian.org/tracker/CVE-2026-9538) | Perl Archive::Tar reads a crafted oversized tar entry and exhausts memory. | No application Perl archive ingestion. Verify whether the module is installed in the rebuilt image and keep arbitrary archive processing outside the service. Container memory limits reduce impact, but do not fix the parser. |

## Deployment decision record still required

### Collecting measured container evidence

Run `python -m src.runtime_evidence --assert-image` in an operator session inside the actual
Linux application container and retain its JSON output alongside the deployed source SHA, provider
image identity and fresh scan. The collector is read-only and does not read environment variables,
process arguments, mount sources or mount options. Its output still includes filesystem paths and
process names; review it before publishing as an operational artifact.

The image profile fails on root UID, missing identity evidence, SUID/SGID files in the inspected
executable/application directories, non-root ownership or group/other writability in `/app`, or
unreadable inventory paths. Its inventory is explicitly scoped to `/usr/bin`, `/usr/sbin`,
`/usr/local` and `/app`; it does not claim to enumerate a provider's host or arbitrary mounted data.
Symlink targets are checked, but linked directories are not recursively followed. The Docker build
strips privilege bits across the image root filesystem, independently of this narrower runtime check.

Container CI additionally invokes `--assert-compose`, requiring zero capability masks,
`NoNewPrivs=1`, and the declared cgroup v2 limits (2 GiB memory, one CPU, 256 PIDs) for the local
Compose service. CI retains the `runtime-evidence` artifact. These stronger assertions describe
Compose only. Render must be inspected separately; unavailable cgroup fields or provider restrictions
remain unknown, never assumed safe. Neither profile certifies CVE exploitability, host isolation,
application integrity after compromise, nor a successful live deployment.

Before exposing the actual service, record its source SHA, image identity, fresh unfiltered scan,
effective UID, process tree, Linux capability fields, `NoNewPrivs`, SUID/SGID inventory and mounted
filesystem boundaries. A read-only operator inspection of `/proc/self/status` and the container
filesystem can establish some of these facts. Provider isolation and host-side operator behavior
also require provider documentation or confirmation; a container cannot attest to its host.

For each row, retain one of: remediation verified by a fresh scan; evidence that the affected
component/exploit prerequisite is absent; or an explicit time-limited residual-risk decision for
this restricted synthetic service, with compensating controls and a next review date. Do not
mark all rows accepted merely because the fixable-vulnerability gate passed. Missing runtime
evidence remains an open deployment gate. Reassess after any base image, dependency, startup,
provider or workload change and when a stable-package fix becomes available.

The account and billing prerequisites, authentication tests, persistence checks and coordinated
recovery rehearsal in [LIVE-DEPLOYMENT.md](LIVE-DEPLOYMENT.md) also remain necessary.
