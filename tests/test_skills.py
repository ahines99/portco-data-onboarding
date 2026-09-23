"""Skill lint and cross-checks against the live MCP server (POD-606)."""

from __future__ import annotations

import re
from itertools import combinations
from pathlib import Path

import pytest
import yaml
from mcp import Client

from src.domain.ontology import load_ontology
from src.mcp_server import build_server
from src.settings import PROJECT_ROOT

pytestmark = pytest.mark.unit
SKILLS = sorted((PROJECT_ROOT / "skills").glob("*/SKILL.md"))
TOOL_PREFIXES = ("start_", "get_", "resume_", "list_", "submit_", "certify_", "profile_", "propose_", "generate_",
                 "run_", "publish_", "explain_", "review_", "onboarding_", "healthcheck")
NOT_TOOLS = {"run_id"}
SECRET = re.compile(r"(sk-[A-Za-z0-9]{10,}|api[_-]?key\s*[:=]\s*\S+|password\s*[:=]\s*\S+)", re.I)
ABS_PATH = re.compile(r"([A-Za-z]:\\|/Users/|/home/)")


def _split(path: Path) -> tuple[dict[str, str], str]:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), path
    _, front, body = text.split("---\n", 2)
    return yaml.safe_load(front), body


@pytest.fixture(scope="module")
def surface() -> dict[str, set[str]]:
    import anyio

    async def collect() -> dict[str, set[str]]:
        async with Client(build_server(with_auth=False)) as c:
            return {
                "tools": {t.name for t in (await c.list_tools()).tools},
                "prompts": {p.name for p in (await c.list_prompts()).prompts},
                "resources": {str(r.uri) for r in (await c.list_resources()).resources},
                "templates": {t.uri_template for t in (await c.list_resource_templates()).resource_templates},
            }

    return anyio.run(collect)


def _template_regex(template: str) -> re.Pattern[str]:
    parts = re.split(r"(\{\+?[a-z_]+\})", template)
    out = "".join((".+" if p.startswith("{+") else "[^/]+") if p.startswith("{") else re.escape(p) for p in parts)
    return re.compile(f"^{out}$")


def test_there_are_five_skills() -> None:
    assert {p.parent.name for p in SKILLS} == {"schema-profiling", "canonical-pe-ontology", "dbt-modeling",
                                                 "semantic-layer-generation", "data-quality"}


@pytest.mark.parametrize("path", SKILLS, ids=lambda p: p.parent.name)
def test_frontmatter_and_hygiene(path: Path) -> None:
    front, body = _split(path)
    assert front["name"] == path.parent.name
    assert 40 < len(front["description"]) < 1024
    text = path.read_text(encoding="utf-8")
    assert len(text.splitlines()) < 500
    assert not SECRET.search(text) and not ABS_PATH.search(text)
    for ref in re.findall(r"`references/([^`]+)`", body):
        assert (path.parent / "references" / ref).exists(), ref


@pytest.mark.parametrize("path", SKILLS, ids=lambda p: p.parent.name)
def test_every_referenced_tool_prompt_and_resource_exists(path: Path, surface: dict[str, set[str]]) -> None:
    text = path.read_text(encoding="utf-8")
    for ref_file in (path.parent / "references").glob("*.md"):
        text += "\n" + ref_file.read_text(encoding="utf-8")
    tokens = set(re.findall(r"`([^`\s]+)`", text))
    templates = [_template_regex(t) for t in surface["templates"]]
    for tok in tokens:
        name = tok.split("(")[0]
        if "://" in tok:
            uri = tok.replace("{run_id}", "r1").replace("{evidence_id}", "e1").replace("{metric}", "arr") \
                .replace("{finding_id}", "f1").replace("{path}", "a/b.sql")
            assert uri in surface["resources"] or any(t.match(uri) for t in templates), f"{path.parent.name}: {tok}"
        elif name.startswith(TOOL_PREFIXES) and name not in NOT_TOOLS and re.fullmatch(r"[a-z_]+", name):
            assert name in surface["tools"] | surface["prompts"], f"{path.parent.name} mentions unknown tool {name}"


def test_skills_are_not_duplicates_of_each_other() -> None:
    bodies = {p.parent.name: {ln.strip() for ln in _split(p)[1].splitlines() if ln.strip()} for p in SKILLS}
    for a, b in combinations(bodies, 2):
        shared = len(bodies[a] & bodies[b]) / min(len(bodies[a]), len(bodies[b]))
        assert shared < 0.6, (a, b, shared)


def test_ontology_skill_references_rather_than_copies_the_ontology() -> None:
    ont = load_ontology()
    field_refs = {f"{e}.{f}" for e, d in ont.entities.items() for f in d.fields}
    body = _split(PROJECT_ROOT / "skills" / "canonical-pe-ontology" / "SKILL.md")[1]
    mentioned = {r for r in field_refs if r in body}
    assert len(mentioned) <= 5, mentioned
    assert "ontology://pe/v1" in body
