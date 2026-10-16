"""Skills must describe the implemented contract (audit DOC-02, DOC-03).

The reason-code inventory is extracted from the implementation, so a new code that reaches a
mapping review item cannot ship without reviewer guidance in the ontology Skill.
"""

from __future__ import annotations

import re

import pytest

from src.domain.models import ReviewGate, Role
from src.domain.policies import ACTIONS, HUMANS
from src.settings import PROJECT_ROOT

pytestmark = pytest.mark.unit

SKILLS = PROJECT_ROOT / "skills"
REVIEW_CODE_SOURCES = ("src/services/mapping.py", "src/services/joins.py", "src/services/gates.py")
EMITTED = (
    r'reasons\.append\("([A-Z_]+)"\)',  # mapping and join proposals
    r'reason_codes=\["([A-Z_]+)"\]',  # gate-built items
    r'reason_codes\) \| \{"([A-Z_]+)"\}',  # judge reordering
    r'\*i\.reason_codes, "([A-Z_]+)"',  # re-raised items after review
)


def _emitted_codes() -> set[str]:
    codes: set[str] = set()
    for rel in REVIEW_CODE_SOURCES:
        text = (PROJECT_ROOT / rel).read_text(encoding="utf-8")
        for pattern in EMITTED:
            codes |= set(re.findall(pattern, text))
    return codes


def test_every_mapping_gate_reason_code_is_explained_in_the_ontology_skill():
    codes = _emitted_codes()
    # Guard the extractor itself: these are known emission sites in each source.
    assert {"ENTITY_UNCERTAIN", "STRUCTURAL_INFERENCE", "JUDGE_REORDERED"} <= codes
    assert {"STRUCTURAL_JOIN", "ORPHANS", "ENTITY_OVERLAP"} <= codes
    assert {"ROW_FILTER", "DUPLICATE_TARGET_AFTER_REVIEW"} <= codes
    skill = (SKILLS / "canonical-pe-ontology" / "SKILL.md").read_text(encoding="utf-8")
    missing = sorted(code for code in codes if f"`{code}`" not in skill)
    assert not missing, f"reason codes without reviewer guidance: {missing}"
    assert "not calibrated probabilities" in skill


def test_schema_profiling_skill_states_the_actual_publication_contract():
    # The policy: humans alone approve/certify/waive; publication needs a certification approval.
    for action in ("submit_review", "certify", "waive_test_failures"):
        assert ACTIONS[action].roles == HUMANS
    assert Role.AGENT in ACTIONS["publish"].roles and ACTIONS["publish"].gate is ReviewGate.CERTIFICATION
    skill = (SKILLS / "schema-profiling" / "SKILL.md").read_text(encoding="utf-8")
    assert not re.search(r"Never approve, certify, waive or publish", skill)
    assert "Never approve, certify or waive" in skill
    assert "`publish_run`" in skill and "`certification_id`" in skill and "separate human reviewer" in skill
