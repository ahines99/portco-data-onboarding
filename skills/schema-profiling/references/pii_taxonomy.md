# PII taxonomy and handling

Classification happens inside the source adapter: the server counts regex and checksum matches
in SQL and only the counts leave the source. The classifier is conservative: when name signals
and value signals disagree, the column is flagged.

| Class | Detected by | Staging handling | Why |
|---|---|---|---|
| `email` | >= 80% of values match an email pattern, or the name contains `email`/`mail` | sha256 hash | Joinable for dedup, not readable |
| `phone` | >= 80% phone pattern with separators, or phone-like name | sha256 hash | Same |
| `person_name` | column name (`first_name`, `full_name`, `ename`, ...) | sha256 hash | Needed only for dedup |
| `national_id` | >= 80% `NNN-NN-NNNN`, or `ssn`-like name | **excluded** | Hashing is brute-forceable (10^9 space) |
| `payment_card` | >= 80% Luhn-valid 13-19 digit strings | **excluded** | PCI scope; never materialized |
| `dob` | date column with a birth-date name | **excluded** | Quasi-identifier |
| `free_text_may_contain_pii` | > 2% of values contain an email or national id | **excluded** | Cannot be scrubbed reliably |
| `address`, `ip_address` | name or pattern | reviewer decides | Rare in PE reporting |

A reviewer can override `pii_handling` on a mapping item, for example to exclude an email that
the portfolio company considers sensitive. The override is part of the audited approval.

The PII guard also scans every MCP response. If anything PII-shaped ever reaches an output, the
response is blocked with `POLICY_VIOLATION`; it is never silently cleaned.
