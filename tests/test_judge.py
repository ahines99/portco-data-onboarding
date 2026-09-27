"""The optional LLM mapping judge is boxed in (POD-607, ADR-0010). No network: stub client + cassettes."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.domain.models import Confidence, RunStatus, StepName
from src.domain.ontology import load_ontology
from src.domain.project_models import ColumnProfile, MappingProposal, ScoredTarget, SemanticType, TableProfile
from src.services.judge import ClaudeJudge
from src.services.mapping import _apply_judge
from src.workflows.facade import OnboardingService
from tests.conftest import AGENT, make_settings

pytestmark = pytest.mark.unit


class StubMessages:
    def __init__(self, answer: dict[str, Any], stop_reason: str = "end_turn") -> None:
        self.answer, self.stop_reason, self.requests = answer, stop_reason, []

    def create(self, **kwargs: Any) -> Any:
        self.requests.append(kwargs)
        return SimpleNamespace(
            stop_reason=self.stop_reason,
            model=kwargs["model"],
            content=[SimpleNamespace(type="text", text=json.dumps(self.answer))],
            usage=SimpleNamespace(input_tokens=1200, output_tokens=80),
        )


def _case() -> tuple[MappingProposal, ColumnProfile, TableProfile]:
    col = ColumnProfile(
        table="sap.VBRK",
        column="KUNAG",
        ordinal=2,
        dtype="VARCHAR",
        row_count=100,
        non_null_count=100,
        null_pct=0.0,
        distinct_count=80,
        uniqueness_ratio=0.8,
        inferred_semantic_type=SemanticType.ID,
    )
    table = TableProfile(schema_name="sap", table_name="VBRK", row_count=100, columns=[col])
    ev = "6f1c2a9e-3b7d-4c55-9a51-0d2f7e1b8c44"
    proposal = MappingProposal(
        mapping_key="sap.VBRK.KUNAG",
        source_table="sap.VBRK",
        source_column="KUNAG",
        source_field="sap.VBRK.KUNAG",
        canonical_entity="invoice",
        canonical_field="status",
        confidence=Confidence.MEDIUM,
        score=0.6,
        rationale="r",
        requires_review=True,
        reason_codes=["LOW_CONFIDENCE"],
        alternatives=[ScoredTarget(entity="invoice", field="customer_id", score=0.58)],
        evidence_ids=[ev],
    )
    return proposal, col, table


def _judge(tmp_path: Path, answer: dict[str, Any], mode: str = "live", **kw: Any) -> tuple[ClaudeJudge, StubMessages]:
    stub = StubMessages(answer, **kw)
    return ClaudeJudge(SimpleNamespace(messages=stub), "claude-opus-5", mode, tmp_path), stub  # type: ignore[arg-type]


def test_request_is_schema_constrained_to_candidates_and_value_free(tmp_path: Path) -> None:
    proposal, col, table = _case()
    judge, stub = _judge(
        tmp_path,
        {"choice": "customer_id", "rationale": "joins to KNA1", "cited_evidence_ids": [str(proposal.evidence_ids[0])]},
    )
    judge.judge(proposal, col, table, load_ontology())
    req = stub.requests[0]
    enum = req["output_config"]["format"]["schema"]["properties"]["choice"]["enum"]
    assert enum == ["customer_id", "status", "ABSTAIN"]
    assert req["model"] == "claude-opus-5" and req["fallbacks"] == "default"
    assert "server-side-fallback-2026-07-01" in req["betas"]
    assert "min_value" not in json.dumps(req) and "category_values" not in json.dumps(req)


def test_judge_can_reorder_but_never_clears_review(tmp_path: Path) -> None:
    proposal, col, table = _case()
    judge, _ = _judge(
        tmp_path,
        {
            "choice": "customer_id",
            "rationale": "sold-to party is the customer",
            "cited_evidence_ids": [str(proposal.evidence_ids[0])],
        },
    )
    out = _apply_judge(judge, proposal, col, table, load_ontology())
    assert out.canonical_field == "customer_id" and out.requires_review
    assert out.confidence is Confidence.MEDIUM and "JUDGE_REORDERED" in out.reason_codes
    assert out.judge and out.judge["usage"]["cost_usd"] is None
    assert out.judge["usage"]["cost_status"] == "unknown_price"


def test_invented_targets_and_uncited_answers_are_rejected(tmp_path: Path) -> None:
    proposal, col, table = _case()
    judge, _ = _judge(tmp_path, {"choice": "revenue_recognized", "rationale": "x", "cited_evidence_ids": []})
    assert judge.judge(proposal, col, table, load_ontology())["choice"] == "ABSTAIN"
    judge, _ = _judge(tmp_path, {"choice": "customer_id", "rationale": "x", "cited_evidence_ids": ["made-up"]})
    assert judge.judge(proposal, col, table, load_ontology())["choice"] == "ABSTAIN"


def test_refusal_becomes_abstain(tmp_path: Path) -> None:
    proposal, col, table = _case()
    judge, _ = _judge(tmp_path, {}, stop_reason="refusal")
    out = _apply_judge(judge, proposal, col, table, load_ontology())
    assert out.canonical_field == "status" and out.judge and out.judge["applied"] is False


def test_pii_in_prompt_is_withheld(tmp_path: Path) -> None:
    proposal, col, table = _case()
    col = col.model_copy(update={"column": "contact a.b@c.io"})
    judge, stub = _judge(tmp_path, {"choice": "customer_id", "rationale": "x", "cited_evidence_ids": []})
    assert judge.judge(proposal, col, table, load_ontology())["choice"] == "ABSTAIN"
    assert stub.requests == []


def test_unknown_cost_is_preserved_in_comparison() -> None:
    from evals.judge_eval import total_cost

    assert total_cost([]) == 0
    assert total_cost([{"usage": {"cost_usd": 0.01}}, {"usage": {"cost_usd": None}}]) is None
    assert total_cost([{"usage": {"cost_usd": 0.01}}, {"usage": {"cost_usd": 0.02}}]) == 0.03


def test_record_then_replay_without_network(tmp_path: Path) -> None:
    proposal, col, table = _case()
    answer = {"choice": "customer_id", "rationale": "r", "cited_evidence_ids": [str(proposal.evidence_ids[0])]}
    recorder, _ = _judge(tmp_path, answer, mode="record")
    recorder.judge(proposal, col, table, load_ontology())
    assert list(tmp_path.glob("*.json"))
    replayer = ClaudeJudge(None, "claude-opus-5", "replay", tmp_path)
    out = replayer.judge(proposal, col, table, load_ontology())
    assert out and out["choice"] == "customer_id" and out["replayed"]
    assert (
        ClaudeJudge(None, "claude-opus-5", "replay", tmp_path / "empty").judge(proposal, col, table, load_ontology())[
            "choice"
        ]
        == "ABSTAIN"
    )


@pytest.mark.anyio
async def test_llm_enabled_in_replay_mode_changes_nothing_without_cassettes(tmp_path: Path, fixtures_dir: Path) -> None:
    svc = OnboardingService.build(make_settings(tmp_path, llm_enabled=True, llm_mode="replay"))
    assert "judge" in svc.services
    run = await svc.start_run(AGENT, "fixture:portco_b")
    assert run.status is RunStatus.NEEDS_REVIEW
    ms = svc.artifact(AGENT, run.run_id, StepName.CANONICAL_MAPPING)
    judged = [p for p in ms.proposals if p.judge]
    assert judged and all(p.judge["applied"] is False for p in judged)
