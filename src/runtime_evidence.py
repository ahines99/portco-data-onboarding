"""Read-only Linux container evidence; never reads environment or process arguments.

Run inside the deployed container: ``python -m src.runtime_evidence``. Supplied
source/image identifiers are operator assertions, not runtime attestation. This
collector cannot verify the provider host or replace a vulnerability scan.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

STATUS_FIELDS = frozenset({"Name", "Uid", "Gid", "CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb", "NoNewPrivs"})
INVENTORY_ROOTS = ("/usr/bin", "/usr/sbin", "/usr/local", "/app")
EXECUTABLES = ("mount", "umount", "nsenter", "infocmp", "perl", "systemd-homed")


def read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return None


def process_status(path: Path) -> dict[str, str]:
    raw = read_text(path) or ""
    return {
        key: value.strip()
        for line in raw.splitlines()
        if ":" in line
        for key, value in [line.split(":", 1)]
        if key in STATUS_FIELDS
    }


def inventory(roots: tuple[Path, ...], app_root: Path) -> dict[str, Any]:
    privileged: list[str] = []
    mutable_app: list[str] = []
    errors: list[str] = []

    def on_error(error: OSError) -> None:
        errors.append(str(error.filename))

    for root in roots:
        if not root.exists():
            errors.append(str(root))
            continue
        for current, dirs, files in os.walk(root, followlinks=False, onerror=on_error):
            for path in [Path(current), *(Path(current) / name for name in dirs + files)]:
                try:
                    info = path.stat()  # Check symlink targets too, without recursively following them.
                except OSError:
                    errors.append(str(path))
                    continue
                if stat.S_ISREG(info.st_mode) and info.st_mode & (stat.S_ISUID | stat.S_ISGID):
                    privileged.append(str(path))
                if path.is_relative_to(app_root) and (info.st_uid != 0 or info.st_mode & 0o022):
                    mutable_app.append(str(path))
    return {
        "scope": [str(root) for root in roots],
        "suid_sgid_files": sorted(set(privileged)),
        "app_ownership_or_mode_violations": sorted(set(mutable_app)),
        "unreadable_paths": sorted(set(errors)),
    }


def mounts(path: Path) -> list[dict[str, str]]:
    result = []
    for line in (read_text(path) or "").splitlines():
        fields = line.split()
        if "-" in fields and len(fields) > 6:
            separator = fields.index("-")
            if separator + 1 < len(fields):
                # Deliberately omit mount sources and options, which may contain credentials.
                result.append({"mount_point": fields[4], "filesystem": fields[separator + 1]})
    return result


def collect() -> dict[str, Any]:
    if platform.system() != "Linux":
        raise RuntimeError("Runtime evidence must be collected inside the Linux container")
    executables = {}
    for name in EXECUTABLES:
        candidates = [Path(directory) / name for directory in ("/usr/bin", "/usr/sbin", "/usr/lib/systemd")]
        executables[name] = [str(path) for path in candidates if path.is_file()]
    return {
        "schema_version": 1,
        "collected_at": datetime.now(UTC).isoformat(),
        "scope": "container-visible state; no host isolation or vulnerability attestation",
        "application_process": process_status(Path("/proc/1/status")),
        "collector_process": process_status(Path("/proc/self/status")),
        "process_names": sorted(
            {
                process_name
                for path in Path("/proc").glob("[0-9]*/comm")
                if (process_name := read_text(path)) is not None
            }
        ),
        "mounts": mounts(Path("/proc/self/mountinfo")),
        "cgroup_v2_limits": {
            name: read_text(Path("/sys/fs/cgroup") / name) for name in ("memory.max", "pids.max", "cpu.max")
        },
        "executable_presence": executables,
        "filesystem_inventory": inventory(tuple(Path(root) for root in INVENTORY_ROOTS), Path("/app")),
    }


def violations(evidence: dict[str, Any], *, compose: bool = False) -> list[str]:
    problems = []
    for label in ("application_process", "collector_process"):
        status = evidence[label]
        ids = status.get("Uid", "").split()
        if len(ids) != 4 or any(value == "0" or not value.isdecimal() for value in ids):
            problems.append(f"{label}: non-root UID not verified")
        if compose:
            for field in ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb"):
                if not re.fullmatch("0+", status.get(field, "")):
                    problems.append(f"{label}: {field} is nonzero or unavailable")
            if status.get("NoNewPrivs") != "1":
                problems.append(f"{label}: NoNewPrivs is not enabled")
    fs = evidence["filesystem_inventory"]
    for field in ("suid_sgid_files", "app_ownership_or_mode_violations", "unreadable_paths"):
        if fs[field]:
            problems.append(f"filesystem inventory: {field}")
    if compose:
        limits = evidence["cgroup_v2_limits"]
        if limits.get("memory.max") != "2147483648" or limits.get("pids.max") != "256":
            problems.append("Compose memory/PID limits missing or different")
        cpu = (limits.get("cpu.max") or "").split()
        if len(cpu) != 2 or not all(part.isdecimal() for part in cpu) or cpu[0] != cpu[1]:
            problems.append("Compose one-CPU limit missing or different")
    return problems


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assert-image", action="store_true")
    parser.add_argument("--assert-compose", action="store_true", help="Also enforce local Compose runtime restrictions")
    args = parser.parse_args()
    evidence = collect()
    errors = violations(evidence, compose=args.assert_compose) if args.assert_image or args.assert_compose else []
    evidence["assertions"] = {
        "profile": "compose" if args.assert_compose else "image" if args.assert_image else "none",
        "violations": errors,
    }
    print(json.dumps(evidence, indent=2, sort_keys=True))
    raise SystemExit(1 if errors else 0)


if __name__ == "__main__":
    main()
