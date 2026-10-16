"""Release publication verifies content and provenance before any remote mutation."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import shutil
import tarfile
import zipfile
from pathlib import Path

import pytest

from scripts import publish_audit_release as release

pytestmark = pytest.mark.unit


def make_archive(path: Path) -> None:
    root = release.TARBALL.removesuffix(".tar.gz")
    with tarfile.open(path, "w:gz") as archive:
        for name, body in {
            "README.md": b"original source\r\n",
            "src/retained.py": b"value = 1\n",
            ".config/auth0/config.json": b'{"local_only": true}',
        }.items():
            member = tarfile.TarInfo(f"{root}/{name}")
            member.size = len(body)
            member.mode = 0o640
            member.mtime = 1730000000
            member.uid, member.gid = 17, 23
            member.uname, member.gname = "builder", "release"
            member.pax_headers = {"comment": "retained metadata"}
            archive.addfile(member, io.BytesIO(body))
        link = tarfile.TarInfo(f"{root}/readme-link")
        link.type = tarfile.SYMTYPE
        link.linkname = "README.md"
        archive.addfile(link)


@pytest.fixture
def rc3_bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    make_archive(downloads / release.TARBALL)
    (downloads / "evidence.json").write_bytes(b'{"unchanged": true}\r\n')
    (downloads / "original.whl").write_bytes(b"original wheel bytes")
    sums = "".join(f"{release.digest(path)}  {path.name}\r\n" for path in sorted(downloads.iterdir())).encode()
    (downloads / "SHA256SUMS.txt").write_bytes(sums)
    clean = tmp_path / "clean.tar.gz"
    release.sanitize_archive(downloads / release.TARBALL, clean)
    monkeypatch.setattr(release, "ORIGINAL_TARBALL_SHA", release.digest(downloads / release.TARBALL))
    monkeypatch.setattr(release, "CLEAN_TARBALL_SHA", release.digest(clean))
    monkeypatch.setattr(release, "RETAINED_ARCHIVE_FINGERPRINT", release.archive_fingerprint(clean))
    monkeypatch.setattr(release, "ORIGINAL_CHECKSUMS_SHA", hashlib.sha256(sums).hexdigest())
    return downloads, clean


def test_rc3_sanitization_retains_every_other_asset_and_checksum(rc3_bundle, tmp_path: Path):
    downloads, _ = rc3_bundle
    original_sums = (downloads / "SHA256SUMS.txt").read_bytes()
    output = tmp_path / "corrected"
    result = release.prepare_rc3(downloads, output)
    assert result["upload_required"] is True
    assert result["removed_paths"] == [release.TARBALL.removesuffix(".tar.gz") + "/.config/auth0/config.json"]
    assert result["original_assets_verified"] == 3
    assert (output / "SHA256SUMS.txt").read_bytes() == original_sums.replace(
        release.ORIGINAL_TARBALL_SHA.encode(), release.CLEAN_TARBALL_SHA.encode()
    )
    with tarfile.open(output / release.TARBALL) as archive:
        assert not any(".config" in name for name in archive.getnames())
        assert archive.getmember(release.TARBALL.removesuffix(".tar.gz") + "/readme-link").issym()
    # The replacement operation exposes only the two authorized files for upload.
    assert {path.name for path in output.iterdir()} == {release.TARBALL, "SHA256SUMS.txt"}


@pytest.mark.parametrize("updated_checksum", [False, True])
def test_rc3_rerun_recovers_partial_upload_and_does_not_repack_clean_tarball(
    rc3_bundle, tmp_path: Path, updated_checksum
):
    downloads, clean = rc3_bundle
    shutil.copyfile(clean, downloads / release.TARBALL)
    if updated_checksum:
        sums = downloads / "SHA256SUMS.txt"
        sums.write_bytes(
            sums.read_bytes().replace(release.ORIGINAL_TARBALL_SHA.encode(), release.CLEAN_TARBALL_SHA.encode())
        )
    output = tmp_path / "rerun"
    result = release.prepare_rc3(downloads, output)
    assert result["upload_required"] is not updated_checksum
    assert (output / release.TARBALL).read_bytes() == clean.read_bytes()
    assert (
        release.parse_checksums((output / "SHA256SUMS.txt").read_bytes())[release.TARBALL] == release.CLEAN_TARBALL_SHA
    )


def test_rc3_retry_accepts_different_gzip_bytes_with_identical_retained_members(rc3_bundle, tmp_path: Path):
    downloads, clean = rc3_bundle
    recompressed = gzip.compress(gzip.decompress(clean.read_bytes()), compresslevel=1, mtime=1)
    assert hashlib.sha256(recompressed).hexdigest() != release.digest(clean)
    (downloads / release.TARBALL).write_bytes(recompressed)
    output = tmp_path / "recompressed"
    result = release.prepare_rc3(downloads, output)
    assert result["sanitized_tarball_sha256"] == hashlib.sha256(recompressed).hexdigest()
    assert (output / release.TARBALL).read_bytes() == recompressed


def test_rc3_retry_rejects_changed_retained_metadata(rc3_bundle, tmp_path: Path):
    downloads, clean = rc3_bundle
    with tarfile.open(clean) as original, tarfile.open(downloads / release.TARBALL, "w:gz") as altered:
        for member in original.getmembers():
            member.mode = 0o777
            altered.addfile(member, original.extractfile(member) if member.isfile() else None)
    with pytest.raises(ValueError, match="original retained members"):
        release.prepare_rc3(downloads, tmp_path / "metadata-rejected")


@pytest.mark.parametrize("tamper", ["asset", "checksums", "extra", "tarball"])
def test_rc3_rejects_unrelated_changes_before_preparing_uploads(rc3_bundle, tmp_path: Path, tamper: str):
    downloads, _ = rc3_bundle
    if tamper == "asset":
        (downloads / "evidence.json").write_bytes(b"altered")
    elif tamper == "checksums":
        sums = downloads / "SHA256SUMS.txt"
        sums.write_bytes(sums.read_bytes().replace(b"evidence.json", b"different.json"))
    elif tamper == "extra":
        (downloads / "unlisted.txt").write_bytes(b"extra")
    else:
        (downloads / release.TARBALL).write_bytes(b"not the verified tarball")
    output = tmp_path / "rejected"
    with pytest.raises((ValueError, tarfile.ReadError)):
        release.prepare_rc3(downloads, output)
    assert not output.exists()


@pytest.mark.parametrize("name", ["../outside", "nested/file", "SHA256SUMS.txt", ".."])
def test_checksums_reject_unsafe_or_recursive_names(name: str):
    with pytest.raises(ValueError):
        release.parse_checksums(("a" * 64 + "  " + name + "\n").encode())


def test_rc3_disclosure_appends_once_and_preserves_original_notes():
    original = "Historical rc.3 release notes.\n"
    corrected = release.rc3_notes(original)
    assert corrected.startswith(original)
    assert "source tag and wheel are unchanged" in corrected
    assert release.rc3_notes(corrected) == corrected


def test_publication_requires_exact_actions_main_checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    sha = "a" * 40
    monkeypatch.setattr(release, "command", lambda *args, **kwargs: "" if "status" in args else sha)
    context = {
        "GITHUB_ACTIONS": "true",
        "GITHUB_REPOSITORY": release.REPOSITORY,
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_SHA": sha,
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_RUN_ID": "12345",
        "CI_JOB_RESULTS": json.dumps({name: {"result": "success"} for name in release.REQUIRED_CI_JOBS}),
    }
    for key, value in context.items():
        monkeypatch.setenv(key, value)
    assert release.publication_context(True, tmp_path) == (
        sha,
        f"https://github.com/{release.REPOSITORY}/actions/runs/12345",
    )
    for key, invalid in {
        "GITHUB_ACTIONS": "false",
        "GITHUB_REF": "refs/heads/test",
        "GITHUB_SHA": "b" * 40,
        "GITHUB_EVENT_NAME": "pull_request",
    }.items():
        monkeypatch.setenv(key, invalid)
        with pytest.raises(ValueError):
            release.publication_context(True, tmp_path)
        monkeypatch.setenv(key, context[key])
    monkeypatch.setattr(release, "command", lambda *args, **kwargs: " M README.md" if "status" in args else sha)
    with pytest.raises(ValueError, match="modified source"):
        release.publication_context(True, tmp_path)


@pytest.mark.parametrize("broken", ["missing", "failed", "cancelled", "skipped", "invalid", "extra_failure"])
def test_publication_ci_gate_rejects_missing_or_unsuccessful_jobs(monkeypatch: pytest.MonkeyPatch, broken: str):
    needs = {name: {"result": "success"} for name in release.REQUIRED_CI_JOBS}
    if broken == "missing":
        del needs["production-smoke"]
    elif broken == "extra_failure":
        needs["additional-check"] = {"result": "failure"}
    else:
        needs["production-smoke"]["result"] = broken
    monkeypatch.setenv("CI_JOB_RESULTS", "invalid json" if broken == "invalid" else json.dumps(needs))
    with pytest.raises(ValueError):
        release.ci_job_results(required=True)


@pytest.mark.parametrize("hosted", [False, True])
def test_rc4_manifest_and_checksums_cover_only_verified_distribution_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, hosted: bool
):
    monkeypatch.delenv("CI_JOB_RESULTS", raising=False)
    if hosted:
        monkeypatch.setenv(
            "CI_JOB_RESULTS", json.dumps({name: {"result": "success"} for name in release.REQUIRED_CI_JOBS})
        )
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text('[project]\nversion = "0.2.0rc4"\n', encoding="utf-8")
    output = tmp_path / "rc4"

    def build(*args, **kwargs):
        assert args[:2] == ("uv", "build")
        with tarfile.open(output / "portco_data_onboarding-0.2.0rc4.tar.gz", "w:gz") as archive:
            archive.addfile(tarfile.TarInfo("portco_data_onboarding-0.2.0rc4/README.md"))
        with zipfile.ZipFile(output / "portco_data_onboarding-0.2.0rc4-py3-none-any.whl", "w") as archive:
            archive.writestr("src/__init__.py", "")
        return ""

    monkeypatch.setattr(release, "command", build)
    release.prepare_rc4(repo, output, "a" * 40, "https://example.test/ci/1", {"source_tag_unchanged": True})
    verification = json.loads((output / "verification.json").read_text())
    assert verification["source_commit"] == "a" * 40
    assert len(verification["package_sha256"]) == 2
    assert verification["ci_job_results"] == ({name: "success" for name in release.REQUIRED_CI_JOBS} if hosted else {})
    assert ("All required CI jobs passed" if hosted else "hosted CI success is not established") in verification[
        "validation"
    ]
    checksums = release.parse_checksums((output / "SHA256SUMS.txt").read_bytes())
    assert set(checksums) == {path.name for path in output.iterdir()} - {"SHA256SUMS.txt"}
    assert all(release.digest(output / name) == value for name, value in checksums.items())
