"""Build inputs stay pinned and the image's port stays configurable in one place (audit DEL-03, DEL-04)."""

from __future__ import annotations

import re

import pytest
import yaml

from src.settings import PROJECT_ROOT

pytestmark = pytest.mark.unit

WORKFLOWS = sorted((PROJECT_ROOT / ".github" / "workflows").glob("*.yml"))
DOCKERFILE = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")
COMPOSE = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
DIGEST = r"@sha256:[0-9a-f]{64}"


def test_workflows_parse_and_pin_every_action_to_a_commit_with_its_release_tag():
    assert WORKFLOWS
    for path in WORKFLOWS:
        text = path.read_text(encoding="utf-8")
        assert isinstance(yaml.safe_load(text), dict), path.name
        uses = re.findall(r"^\s*-?\s*uses:\s*(.+)$", text, re.MULTILINE)
        assert uses, path.name
        for ref in uses:
            if ref.startswith("./"):
                continue  # a local action is versioned with the repository
            assert re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40} # v\d+\.\d+\.\d+", ref.strip()), ref


def test_container_images_are_pinned_to_digests():
    references = re.findall(r"^FROM\s+(\S+)", DOCKERFILE, re.MULTILINE)
    references += re.findall(r"COPY --from=(\S+/\S+)", DOCKERFILE)
    references += re.findall(r"^# syntax=(\S+)", DOCKERFILE, re.MULTILINE)
    references += re.findall(r"^\s*image:\s*(\S+)", COMPOSE, re.MULTILINE)
    for path in WORKFLOWS:
        text = path.read_text(encoding="utf-8")
        references += re.findall(r"^\s*image:\s*(\S+)", text, re.MULTILINE)
        references += re.findall(r"(aquasec/trivy\S*)", text)
        references += re.findall(r"SMOKE_POSTGRES_IMAGE:\s*(\S+)", text)
    assert len(references) >= 8
    for ref in references:
        assert re.search(rf":[\w.-]+{DIGEST}$", ref), f"{ref} must keep its tag and pin a digest"


def test_ci_uv_matches_the_image_build_tool():
    uv_tag = re.search(r"ghcr\.io/astral-sh/uv:([\d.]+)@", DOCKERFILE)
    assert uv_tag
    for path in WORKFLOWS:
        text = path.read_text(encoding="utf-8")
        blocks = re.findall(r"setup-uv@\S+ # v[\d.]+\n\s+with: \{([^}]*)\}", text)
        assert len(blocks) == text.count("astral-sh/setup-uv@"), path.name
        for block in blocks:
            assert f'version: "{uv_tag.group(1)}"' in block, path.name


def test_dependabot_covers_the_pinned_ecosystems():
    config = yaml.safe_load((PROJECT_ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8"))
    ecosystems = {update["package-ecosystem"] for update in config["updates"]}
    assert {"github-actions", "docker", "docker-compose", "uv"} <= ecosystems


def test_image_server_and_health_check_share_one_configurable_port():
    cmd = re.search(r"^CMD (.+)$", DOCKERFILE, re.MULTILINE)
    health = re.search(r"^HEALTHCHECK .+$", DOCKERFILE, re.MULTILINE)
    assert cmd and health
    assert "${PORT:-8000}" in cmd.group(1) and "--port 8000" not in cmd.group(1)
    assert "os.environ.get('PORT','8000')" in health.group(0)


def test_ci_boots_the_production_entry_point():
    ci = yaml.safe_load((PROJECT_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    steps = ci["jobs"]["production-smoke"]["steps"]
    commands = " ".join(str(step.get("run", "")) for step in steps)
    assert "python -m scripts.smoke_production" in commands and "--port 18080" in commands
    assert "ssl=on" in commands
