"""Prepare audited release assets; --publish uploads them from a gated main-branch Actions job.

Run as ``uv run python -m scripts.publish_audit_release --publish``. Authentication is
inherited by gh. This script never reads or persists credentials. Without --publish,
it only downloads, verifies and builds artifacts in var/release-publication/.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import tomllib
from pathlib import Path, PurePosixPath
from typing import Any

from scripts.smoke_wheel import verify_distribution_hygiene

REPOSITORY = "ahines99/portco-data-onboarding"
OLD_TAG = "v0.2.0-rc.3"
NEW_TAG = "v0.2.0-rc.4"
TARBALL = "portco_data_onboarding-0.2.0rc3.tar.gz"
ORIGINAL_TARBALL_SHA = "964d1a317bc1214f6ef4c0d075aca6fa2f9409d9a7a604308a36ef9cf573f7b7"
CLEAN_TARBALL_SHA = "92886c0eb632303dfdfd08b68d273d7b31ce74793c2149cab2dd94ef3db7868d"
ORIGINAL_CHECKSUMS_SHA = "e26f4c076e10f2e85d1b9e2c7614f97b975b27b45e7fec28d3f64e7f116a25b4"
NOTICE_MARKER = "<!-- october-2026-package-hygiene -->"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_checksums(data: bytes) -> dict[str, str]:
    checksums: dict[str, str] = {}
    for line in data.decode("utf-8").splitlines():
        match = re.fullmatch(r"([a-f0-9]{64})  ([A-Za-z0-9_.-]+)", line)
        if not match or match[2] in checksums or match[2] in {".", "..", "SHA256SUMS.txt"}:
            raise ValueError("Invalid or duplicate release checksum entry")
        checksums[match[2]] = match[1]
    if not checksums:
        raise ValueError("Release checksums are empty")
    return checksums


def sanitize_archive(source: Path, destination: Path) -> list[str]:
    """Remove only root .config members; retain every other member's bytes and metadata."""
    removed: list[str] = []
    with tarfile.open(source) as archive, destination.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w|", format=tarfile.PAX_FORMAT) as output:
                for member in archive.getmembers():
                    parts = PurePosixPath(member.name).parts
                    if len(parts) >= 2 and parts[1] == ".config":
                        removed.append(member.name)
                        continue
                    output.addfile(member, archive.extractfile(member) if member.isfile() else None)
    with tarfile.open(source) as before, tarfile.open(destination) as after:
        if after.getnames() != [name for name in before.getnames() if name not in removed]:
            raise ValueError("Sanitization changed retained archive membership")
        for current in after.getmembers():
            previous = before.getmember(current.name)
            fields = ("name", "mode", "uid", "gid", "size", "mtime", "type", "linkname", "uname", "gname", "pax_headers")
            if any(getattr(previous, field) != getattr(current, field) for field in fields):
                raise ValueError(f"Sanitization changed member metadata: {current.name}")
            if current.isfile():
                old_data = before.extractfile(previous)
                new_data = after.extractfile(current)
                if old_data is None or new_data is None or old_data.read() != new_data.read():
                    raise ValueError(f"Sanitization changed member bytes: {current.name}")
    return removed


def prepare_rc3(downloads: Path, output: Path) -> dict[str, Any]:
    """Validate the complete original asset set and recover an interrupted two-file upload."""
    original_sums = (downloads / "SHA256SUMS.txt").read_bytes()
    checksums = parse_checksums(original_sums)
    listed_tarball = checksums.get(TARBALL)
    if listed_tarball not in {ORIGINAL_TARBALL_SHA, CLEAN_TARBALL_SHA}:
        raise ValueError("rc.3 tarball does not match the original or sanitized release")
    baseline = original_sums.replace(listed_tarball.encode(), ORIGINAL_TARBALL_SHA.encode())
    if hashlib.sha256(baseline).hexdigest() != ORIGINAL_CHECKSUMS_SHA:
        raise ValueError("The original rc.3 checksum list changed beyond the tarball correction")
    names = {path.name for path in downloads.iterdir() if path.is_file()}
    if names != {*checksums, "SHA256SUMS.txt"}:
        raise ValueError("Downloaded rc.3 assets differ from the complete checksum list")
    for name, expected in checksums.items():
        actual = digest(downloads / name)
        allowed = {expected}
        if name == TARBALL:
            # A retry after uploading the tarball but before uploading its checksum is safe.
            allowed |= {ORIGINAL_TARBALL_SHA, CLEAN_TARBALL_SHA}
        if actual not in allowed:
            raise ValueError(f"rc.3 checksum mismatch: {name}")
    output.mkdir(parents=True, exist_ok=True)
    original_hash = digest(downloads / TARBALL)
    removed = []
    if original_hash == ORIGINAL_TARBALL_SHA:
        removed = sanitize_archive(downloads / TARBALL, output / TARBALL)
    else:
        shutil.copyfile(downloads / TARBALL, output / TARBALL)
    if digest(output / TARBALL) != CLEAN_TARBALL_SHA:
        raise ValueError("Sanitized rc.3 archive differs from the independently verified correction")
    corrected_sums = baseline.replace(ORIGINAL_TARBALL_SHA.encode(), CLEAN_TARBALL_SHA.encode())
    (output / "SHA256SUMS.txt").write_bytes(corrected_sums)
    return {
        "source_tag": OLD_TAG,
        "source_tag_unchanged": True,
        "original_tarball_sha256": ORIGINAL_TARBALL_SHA,
        "sanitized_tarball_sha256": CLEAN_TARBALL_SHA,
        "removed_paths": removed,
        "original_assets_verified": len(checksums),
        "upload_required": original_hash != CLEAN_TARBALL_SHA or original_sums != corrected_sums,
    }


def rc3_notes(body: str) -> str:
    if NOTICE_MARKER in body:
        return body
    return body.rstrip() + (
        f"\n\n{NOTICE_MARKER}\n"
        "Packaging correction (2026-10-16): the attached source tarball was replaced to remove "
        "`.config/auth0/config.json`, which contained local Auth0 development metadata and no tokens. "
        "All retained files and their archive metadata are unchanged; the rc.3 source tag and wheel "
        "are unchanged. `SHA256SUMS.txt` now records the corrected tarball; all other checksums are "
        "preserved. The October application fixes ship separately in v0.2.0-rc.4.\n"
    )


def command(*args: str, cwd: Path | None = None, missing_ok: bool = False) -> str | None:
    result = subprocess.run(list(args), cwd=cwd, check=False, capture_output=True, text=True)
    if result.returncode:
        if missing_ok and "(HTTP 404)" in result.stderr:
            return None
        raise RuntimeError(f"Command failed ({args[0]} {args[1]}): {result.stderr.strip()}")
    return result.stdout


def github_json(endpoint: str, *, missing_ok: bool = False) -> Any:
    output = command("gh", "api", f"repos/{REPOSITORY}/{endpoint}", missing_ok=missing_ok)
    return json.loads(output) if output is not None else None


def tag_commit(tag: str) -> str | None:
    reference = github_json(f"git/ref/tags/{tag}", missing_ok=True)
    if reference is None:
        return None
    obj = reference["object"]
    for _ in range(5):
        if obj["type"] == "commit":
            return str(obj["sha"])
        if obj["type"] != "tag":
            break
        obj = github_json(f"git/tags/{obj['sha']}")["object"]
    raise ValueError(f"Cannot resolve release tag {tag} to a commit")


def publication_context(publish: bool, repo: Path) -> tuple[str, str]:
    source_sha = (command("git", "rev-parse", "HEAD", cwd=repo) or "").strip()
    if not re.fullmatch(r"[a-f0-9]{40}", source_sha):
        raise ValueError("Cannot identify release source commit")
    if publish:
        expected = {
            "GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": REPOSITORY,
            "GITHUB_REF": "refs/heads/main", "GITHUB_SHA": source_sha,
        }
        if any(os.environ.get(key) != value for key, value in expected.items()):
            raise ValueError("Publication requires the exact main-branch GitHub Actions checkout")
        if os.environ.get("GITHUB_EVENT_NAME") not in {"push", "workflow_dispatch"}:
            raise ValueError("Publication is permitted only on main push or explicit dispatch")
        if command("git", "status", "--porcelain", "--untracked-files=no", cwd=repo).strip():
            raise ValueError("Refusing to publish a modified source checkout")
        if not os.environ.get("GITHUB_RUN_ID", "").isdigit():
            raise ValueError("Publication requires a GitHub Actions run identity")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    ci_url = f"https://github.com/{REPOSITORY}/actions/runs/{run_id}" if run_id else "local preparation only"
    return source_sha, ci_url


def prepare_rc4(repo: Path, output: Path, source_sha: str, ci_url: str, correction: dict[str, Any]) -> None:
    config = tomllib.loads((repo / "pyproject.toml").read_text(encoding="utf-8"))
    if config["project"]["version"] != "0.2.0rc4":
        raise ValueError("rc.4 publication requires package version 0.2.0rc4")
    output.mkdir(parents=True, exist_ok=True)
    command("uv", "build", "--out-dir", str(output), cwd=repo)
    verify_distribution_hygiene(output)
    packages = sorted(path for path in output.iterdir() if path.is_file())
    if {path.name for path in packages} != {
        "portco_data_onboarding-0.2.0rc4.tar.gz", "portco_data_onboarding-0.2.0rc4-py3-none-any.whl",
    }:
        raise ValueError("Unexpected rc.4 package filenames")
    verification = {
        "release": NEW_TAG, "package_version": "0.2.0rc4", "source_commit": source_sha,
        "ci_run": ci_url,
        "validation": "Publication is gated on all required CI jobs; distribution contents were inspected again.",
        "package_sha256": {path.name: digest(path) for path in packages},
        "rc3_packaging_correction": {key: value for key, value in correction.items() if key != "upload_required"},
        "scope": "Synthetic/local and CI validation; no live customer deployment or human pilot is claimed.",
    }
    (output / "verification.json").write_text(json.dumps(verification, indent=2) + "\n", encoding="utf-8")
    sums = "".join(f"{digest(path)}  {path.name}\n" for path in sorted(output.iterdir()) if path.is_file())
    (output / "SHA256SUMS.txt").write_text(sums, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publish", action="store_true", help="Upload from a gated GitHub Actions main-branch job")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    source_sha, ci_url = publication_context(args.publish, repo)
    output_root = repo / "var/release-publication"
    output_root.mkdir(parents=True, exist_ok=True)
    workspace = Path(tempfile.mkdtemp(prefix="audit-release-", dir=output_root))
    old_tag_sha = tag_commit(OLD_TAG)
    if old_tag_sha is None:
        raise ValueError("The historical rc.3 tag is missing")
    existing_new_tag = tag_commit(NEW_TAG)
    if existing_new_tag not in {None, source_sha}:
        raise ValueError("Existing rc.4 tag points at different source; refusing to replace it")
    old_release = github_json(f"releases/tags/{OLD_TAG}")
    downloads = workspace / "rc3-downloads"
    downloads.mkdir()
    command("gh", "release", "download", OLD_TAG, "--repo", REPOSITORY, "--dir", str(downloads))
    corrected = workspace / "rc3-corrected"
    correction = prepare_rc3(downloads, corrected)
    rc4 = workspace / "rc4"
    prepare_rc4(repo, rc4, source_sha, ci_url, correction)
    old_notes = workspace / "rc3-notes.md"
    old_notes.write_text(rc3_notes(old_release.get("body") or ""), encoding="utf-8")
    new_notes = workspace / "rc4-notes.md"
    new_notes.write_text(
        "October audit remediation: 23 findings addressed, including revenue categories that previously "
        "produced zero revenue while every check passed. Regression coverage includes parallel workflows, "
        "mid-run cancellation, source packaging and fresh-clone audit checksums.\n\n"
        "The demo now shows 28 review items and 27/27 reconciliation checks. Production-entry-point, "
        "PostgreSQL, container PORT, Linux/Windows packaging, evaluation and security CI gates passed "
        f"before publication. [Exact CI run]({ci_url}); source commit `{source_sha}`.\n\n"
        "The rc.3 source tarball was separately sanitized without changing its tag or retained files. "
        "`verification.json` records this release's provenance and package hashes; `SHA256SUMS.txt` "
        "covers every attached asset except itself.\n\n"
        "Scope: reproducible synthetic/local and CI validation. No live customer deployment, accepted "
        "production hosting or demonstrated human time savings is claimed.\n",
        encoding="utf-8",
    )
    print(f"Verified release assets prepared in {workspace}", flush=True)
    if not args.publish:
        return
    if correction["upload_required"]:
        command("gh", "release", "upload", OLD_TAG, str(corrected / TARBALL), "--repo", REPOSITORY, "--clobber")
        command("gh", "release", "upload", OLD_TAG, str(corrected / "SHA256SUMS.txt"), "--repo", REPOSITORY, "--clobber")
    if old_notes.read_text(encoding="utf-8") != (old_release.get("body") or ""):
        command("gh", "release", "edit", OLD_TAG, "--repo", REPOSITORY, "--notes-file", str(old_notes))
    if tag_commit(OLD_TAG) != old_tag_sha:
        raise ValueError("Historical rc.3 tag changed during publication")
    existing_release = github_json(f"releases/tags/{NEW_TAG}", missing_ok=True)
    assets = [str(path) for path in sorted(rc4.iterdir())]
    if existing_release is None:
        command(
            "gh", "release", "create", NEW_TAG, *assets, "--repo", REPOSITORY,
            "--target", source_sha, "--prerelease", "--title", "v0.2.0-rc.4 — October audit remediation",
            "--notes-file", str(new_notes),
        )
    else:
        if tag_commit(NEW_TAG) != source_sha:
            raise ValueError("Existing rc.4 release tag differs from the verified source")
        expected_names = {path.name for path in rc4.iterdir()}
        if any(asset["name"] not in expected_names for asset in existing_release["assets"]):
            raise ValueError("Existing rc.4 release contains unexpected assets")
        command("gh", "release", "upload", NEW_TAG, *assets, "--repo", REPOSITORY, "--clobber")
        command("gh", "release", "edit", NEW_TAG, "--repo", REPOSITORY, "--prerelease", "--notes-file", str(new_notes))
    if tag_commit(NEW_TAG) != source_sha:
        raise ValueError("Published rc.4 tag does not identify the verified source")
    for tag, expected in ((OLD_TAG, corrected), (NEW_TAG, rc4)):
        published = workspace / f"verify-{tag}"
        published.mkdir()
        command("gh", "release", "download", tag, "--repo", REPOSITORY, "--dir", str(published))
        sums = parse_checksums((published / "SHA256SUMS.txt").read_bytes())
        if {path.name for path in published.iterdir()} != {*sums, "SHA256SUMS.txt"}:
            raise ValueError(f"Published {tag} assets differ from their checksum list")
        if any(digest(published / name) != sha for name, sha in sums.items()):
            raise ValueError(f"Published {tag} asset checksum verification failed")
        if any(digest(published / path.name) != digest(path) for path in expected.iterdir()):
            raise ValueError(f"Published {tag} assets differ from the prepared files")
    print(f"Published and downloaded both releases for final checksum verification: {NEW_TAG}", flush=True)


if __name__ == "__main__":
    main()
