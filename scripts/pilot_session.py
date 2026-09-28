"""Prepare private pilot records and summarize explicitly recorded intervals.

This tool does not attest consent, review, task completion or business impact.
Run from a source checkout: python -m scripts.pilot_session --help.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import re
import subprocess
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FIELDS = ["attempt_id", "task_id", "arm", "actor", "role", "phase", "activity", "started_at_utc", "ended_at_utc"]
ROLES = ("operator", "reviewer", "developer", "machine")
PHASES = ("setup", "training", "task")
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")


def _identifier(value: str) -> str:
    if not IDENTIFIER.fullmatch(value):
        raise ValueError("Use opaque identifiers of 1-64 letters, digits, underscores or hyphens")
    return value


def _time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.utcoffset() is None:
            raise ValueError("Timezone required")
        return parsed.astimezone(UTC)
    except ValueError as exc:
        raise ValueError("Interval timestamps must be ISO 8601 with an explicit timezone") from exc


def prepare(directory: Path, pilot_id: str) -> None:
    """Create blank records without overwriting another session or inventing observations."""
    _identifier(pilot_id)
    directory = directory.resolve()
    if directory.is_relative_to(ROOT) and not directory.is_relative_to(ROOT / "var"):
        raise ValueError("Private pilot records inside the checkout must be under ignored var/")
    if directory.exists():
        raise ValueError("Session directory already exists; choose a fresh directory")
    record = json.loads((ROOT / "docs/evidence/operator-pilot/TEMPLATE.json").read_text(encoding="utf-8"))
    record["pilot_id"] = pilot_id
    record["created_at_utc"] = datetime.now(UTC).isoformat()
    record["protocol_version"] = "docs/OPERATOR-PILOT.md"
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain"], cwd=ROOT, check=True, capture_output=True, text=True
        ).stdout.strip()
    )
    baseline = {
        "source_commit": commit,
        "worktree_dirty": dirty,
        "lock_sha256": hashlib.sha256((ROOT / "uv.lock").read_bytes()).hexdigest(),
        "recorder_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "protocol_sha256": hashlib.sha256((ROOT / "docs/OPERATOR-PILOT.md").read_bytes()).hexdigest(),
        "python": platform.python_version(),
        "platform": platform.system(),
        "warning": "Preparation only. A dirty worktree is not a pinned experiment; freeze it before running.",
    }
    record["environment"].update(source_commit=commit, lock_sha256=baseline["lock_sha256"])
    directory.mkdir(parents=True)
    for name, data in (("pilot.json", record), ("baseline.json", baseline)):
        (directory / name).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    with (directory / "intervals.csv").open("w", newline="", encoding="utf-8") as stream:
        csv.writer(stream).writerow(FIELDS)
    with (directory / "notes.csv").open("w", newline="", encoding="utf-8") as stream:
        csv.writer(stream).writerow(["at_utc", "attempt_id", "kind", "private_reference"])


def summarize(directory: Path) -> dict[str, Any]:
    """Validate intervals, reject double-counting, preserve unknown time as null."""
    with (directory / "intervals.csv").open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != FIELDS:
            raise ValueError("Interval CSV headers must match the prepared template")
        rows = list(reader)
    totals: dict[str, dict[str, Any]] = {}
    intervals: dict[str, list[tuple[datetime, datetime]]] = defaultdict(list)
    actor_roles: dict[str, str] = {}
    for number, row in enumerate(rows, 2):
        if None in row or any(value is None or not value.strip() for value in row.values()):
            raise ValueError(f"Interval row {number} is incomplete; do not estimate missing times")
        for field in ("attempt_id", "task_id", "actor", "activity"):
            _identifier(row[field])
        if row["arm"] not in ("manual", "assisted") or row["role"] not in ROLES or row["phase"] not in PHASES:
            raise ValueError(f"Interval row {number} has an invalid arm, role or phase")
        start, end = _time(row["started_at_utc"]), _time(row["ended_at_utc"])
        if end < start:
            raise ValueError(f"Interval row {number} ends before it starts")
        actor = row["actor"]
        if actor in actor_roles and actor_roles[actor] != row["role"]:
            raise ValueError("An actor cannot change roles within the recorded pilot")
        actor_roles[actor] = row["role"]
        intervals[actor].append((start, end))
        attempt = totals.setdefault(
            row["attempt_id"],
            {
                "task_id": row["task_id"],
                "arm": row["arm"],
                "seconds": {phase: dict.fromkeys(ROLES) for phase in PHASES},
                "interval_count": 0,
            },
        )
        if attempt["task_id"] != row["task_id"] or attempt["arm"] != row["arm"]:
            raise ValueError("An attempt must refer to exactly one task and comparison arm")
        values = attempt["seconds"][row["phase"]]
        values[row["role"]] = (values[row["role"]] or 0) + (end - start).total_seconds()
        attempt["interval_count"] += 1
    for spans in intervals.values():
        previous_end = None
        for start, end in sorted(spans):
            if previous_end is not None and start < previous_end:
                raise ValueError("An actor has overlapping intervals; resolve double-counting first")
            previous_end = end
    return {
        "record_type": "unattested_interval_summary",
        "interval_count": len(rows),
        "attempts": totals,
        "task_completion": None,
        "consent_verified": False,
        "human_attestations_verified": False,
        "public_release_authorized": False,
        "limitations": [
            "Recorded interval sums only; missing roles/phases are null, not zero.",
            "Machine interval sums are not wall-clock completion time or human labor.",
            "Separate actors may work concurrently; their person-time is not elapsed time.",
            "No correctness, completion, consent, savings or independence is inferred.",
            "Review assistance/deviation notes and obtain actual attestations under the pilot protocol.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("prepare", help="Create a fresh private session with blank forms")
    create.add_argument("directory", type=Path)
    create.add_argument("--pilot-id", required=True)
    report = commands.add_parser("summarize", help="Validate intervals and write a private timing summary")
    report.add_argument("directory", type=Path)
    commands.add_parser("stamp", help="Print the current UTC timestamp; no event is recorded automatically")
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            prepare(args.directory, args.pilot_id)
            print("Prepared blank private records. No consent or completed trial is represented.")
        elif args.command == "summarize":
            result = summarize(args.directory)
            (args.directory / "timing-summary.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            print(f"Validated {result['interval_count']} intervals. Private unattested summary written.")
        else:
            print(datetime.now(UTC).isoformat())
    except (ValueError, OSError, subprocess.CalledProcessError):
        # Do not print source rows, personal data, paths or Git diagnostics on failure.
        parser.exit(2, "Cannot process session. Check private paths, fields, timestamps, roles and overlaps.\n")


if __name__ == "__main__":
    main()
