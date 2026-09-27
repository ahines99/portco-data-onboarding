# Release security review

2026-09-27. Scope: synthetic-data portfolio code, dependencies and development container.

- Gitleaks 8.30.1 scanned the complete existing Git history and staged release changes with redacted
  output. No leaks were reported. This is a pattern-based scan, not proof that no sensitive material exists.
- pip-audit initially found nine advisory entries (including duplicate identifiers) affecting
  `sqlparse` 0.5.4. dbt-core 1.10.23 prevented upgrading it. The application now resolves dbt-core
  1.11.15 and sqlparse 0.6.0; local dependency scanning and the hosted dependency job report no known
  vulnerabilities in the application environment. See the [upstream dependency issue](https://github.com/dbt-labs/dbt-core/issues/15988).
- Trivy 0.74.0 scanned the actual Compose application image. The initial report identified six
  fixable entries in the unused global pip inherited from the base image. The runtime Dockerfile
  now removes that installer; application dependencies remain in the prebuilt virtual environment.
- The first image report also contained 44 HIGH package/advisory entries covering eight unique CVEs
  in Debian 13.7 packages (util-linux, ACL, ncurses, systemd and Perl). The scanner provided no fixed
  package version for these entries. Counts include the same advisory on multiple binary packages.
  These are retained as residual risk, not suppressed or described as a clean image.

The container runs as a non-root user, drops all Linux capabilities, forbids privilege escalation
and binds its HTTP port to loopback. No systemd daemon or privileged mount helper is part of the
application workflow. These constraints reduce some exposure; they do not establish that every
reported issue is unreachable. The image is a local synthetic demo artifact and is not approved
for production or untrusted public traffic. A static GitHub Pages site serves only public evidence.

The full machine-readable scan is retained in the CI `container-audit` artifact. The release status
links the verified run and records final counts after rebuilding. The scan job deliberately retains
unfixed OS findings for review; application dependency scanning is a failing gate on vulnerabilities.

Before production use: replace development tokens with verified identity, review actual data/egress
boundaries, update/rebuild the base image, remediate or independently assess remaining OS findings,
and rerun container scans and functional tests. These are explicit production prerequisites, not
claims made by this portfolio release.
