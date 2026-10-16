"""Exercise distribution hygiene and exact-byte audit evidence across actual Git checkouts."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tarfile
import tomllib
import zipfile
from pathlib import Path

import pytest

from scripts.smoke_wheel import verify_distribution_hygiene
from src.settings import PROJECT_ROOT


def assert_audit_hashes(root: Path) -> None:
    manifest = json.loads((root / "docs/audits/2026-10-10/manifest.json").read_text(encoding="utf-8"))
    for name, expected in manifest["files"].items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == expected, name


@pytest.mark.unit
def test_october_audit_recorded_bytes_match_manifest():
    assert_audit_hashes(PROJECT_ROOT)


@pytest.mark.integration
@pytest.mark.parametrize("autocrlf", ["false", "true"])
def test_october_audit_hashes_survive_commit_and_fresh_clone(tmp_path: Path, autocrlf: str):
    origin = tmp_path / "origin"
    origin.mkdir()
    manifest_path = Path("docs/audits/2026-10-10/manifest.json")
    manifest = json.loads((PROJECT_ROOT / manifest_path).read_text(encoding="utf-8"))
    for name in [".gitattributes", str(manifest_path), *manifest["files"]]:
        target = origin / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(PROJECT_ROOT / name, target)
    git = shutil.which("git")
    assert git is not None, "Git is required to verify source-release provenance"

    def run(*args: str, cwd: Path = origin) -> None:
        subprocess.run([git, *args], cwd=cwd, check=True, capture_output=True, text=True)

    run("init", "--template=")
    run("config", "core.autocrlf", "true")
    run("add", ".")
    run(
        "-c",
        "user.name=Audit Byte Check",
        "-c",
        "user.email=audit@example.invalid",
        "-c",
        "commit.gpgsign=false",
        "-c",
        "core.hooksPath=/dev/null",
        "commit",
        "-m",
        "Preserve frozen audit evidence",
    )
    clone = tmp_path / "fresh-clone"
    run("-c", f"core.autocrlf={autocrlf}", "clone", "--no-local", str(origin), str(clone), cwd=tmp_path)
    assert_audit_hashes(clone)


@pytest.mark.integration
def test_distributions_exclude_machine_configuration_without_git_ignores(tmp_path: Path):
    """Build real source/wheel artifacts with local configuration deliberately present."""
    project = tmp_path / "project"
    project.mkdir()
    config = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    build = config["tool"]["hatch"]["build"]["targets"]["wheel"]
    inputs = {"pyproject.toml", "README.md", "LICENSE", *build["packages"], *build["force-include"]}
    for name in inputs:
        source = PROJECT_ROOT / name
        target = project / name
        if source.is_dir():
            shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            shutil.copyfile(source, target)
    local_config = project / ".config/auth0/config.json"
    local_config.parent.mkdir(parents=True)
    local_config.write_text('{"local_only": "packaging-regression-sentinel"}', encoding="utf-8")
    # Neither repository nor personal Git ignores can conceal the regression here.
    assert not (project / ".gitignore").exists()
    assert not (project / ".git").exists()
    uv = shutil.which("uv")
    assert uv is not None, "uv is required to test release distribution contents"
    dist = tmp_path / "dist"
    subprocess.run([uv, "build", str(project), "--out-dir", str(dist)], check=True, capture_output=True, text=True)
    verify_distribution_hygiene(dist)
    with tarfile.open(next(dist.glob("*.tar.gz"))) as archive:
        assert any(name.endswith("/ontology/pe_canonical_v1.yaml") for name in archive.getnames())
    with zipfile.ZipFile(next(dist.glob("*.whl"))) as archive:
        assert "src/_resources/ontology/pe_canonical_v1.yaml" in archive.namelist()
