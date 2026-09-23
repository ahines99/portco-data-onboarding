"""Policy engine (POD-311). Unknown actions are denied: the registry is the allowlist.

The human-readable `project://policies` resource is rendered from this registry, so the
documentation and the enforcement cannot drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel

from src.domain.models import ReviewGate, RiskTier, Role


class ActionDecision(BaseModel):
    allowed: bool
    requires_human_approval: bool
    reason: str


@dataclass(frozen=True)
class ActionPolicy:
    risk: RiskTier
    roles: frozenset[Role]
    gate: ReviewGate | None = None
    description: str = ""


ALL = frozenset(Role)
HUMANS = frozenset({Role.REVIEWER, Role.ADMIN})

ACTIONS: dict[str, ActionPolicy] = {
    "read_run": ActionPolicy(RiskTier.LOW, ALL, description="Read run status, findings, evidence and artifacts."),
    "start_run": ActionPolicy(RiskTier.LOW, ALL, description="Start read-only discovery against a registered source."),
    "profile_schema": ActionPolicy(RiskTier.LOW, ALL, description="Aggregate-only profiling; no row values."),
    "propose_mapping": ActionPolicy(RiskTier.LOW, ALL, description="Deterministic mapping proposals."),
    "resume_run": ActionPolicy(RiskTier.LOW, ALL, description="Continue a run; gates re-check approvals."),
    "generate_artifacts": ActionPolicy(
        RiskTier.MEDIUM, ALL, ReviewGate.MAPPING_REVIEW, "Generate dbt + semantic artifacts from a reviewed mapping."
    ),
    "run_sandbox_tests": ActionPolicy(RiskTier.MEDIUM, ALL, description="Run generated SQL in a disposable sandbox."),
    "submit_review": ActionPolicy(RiskTier.HIGH, HUMANS, description="Record human review decisions."),
    "certify": ActionPolicy(RiskTier.HIGH, HUMANS, description="Certify joins and metrics for publication."),
    "waive_test_failures": ActionPolicy(RiskTier.HIGH, HUMANS, description="Waive failing sandbox checks."),
    "publish": ActionPolicy(
        RiskTier.HIGH,
        ALL,
        ReviewGate.CERTIFICATION,
        "Publish certified artifacts; requires a valid certification bound to the bundle.",
    ),
    "rerun_from": ActionPolicy(RiskTier.MEDIUM, HUMANS, description="Invalidate and recompute from a step."),
    "cancel_run": ActionPolicy(RiskTier.MEDIUM, HUMANS, description="Cancel a run."),
}


def check_action(
    action: str, risk_tier: str | None = None, has_approval: bool = False, role: Role | str = Role.AGENT
) -> ActionDecision:
    policy = ACTIONS.get(action)
    if policy is None:
        return ActionDecision(
            allowed=False, requires_human_approval=True, reason=f"Unknown action {action!r} is denied by default"
        )
    role = Role(role)
    if role not in policy.roles:
        return ActionDecision(
            allowed=False, requires_human_approval=True, reason=f"Role {role.value!r} may not perform {action!r}"
        )
    risk = RiskTier(risk_tier) if risk_tier else policy.risk
    material = risk in {RiskTier.HIGH, RiskTier.CRITICAL}
    # Gated actions need an approval, whoever performs them.
    if policy.gate is not None and not has_approval:
        return ActionDecision(
            allowed=False, requires_human_approval=True, reason="Material action requires explicit human approval"
        )
    # Ungated material actions are performed by humans themselves.
    if material and policy.gate is None and role not in HUMANS:
        return ActionDecision(
            allowed=False, requires_human_approval=True, reason="High-risk action requires a human principal"
        )
    return ActionDecision(allowed=True, requires_human_approval=False, reason="Policy satisfied")


def render_policies() -> str:
    lines = [
        "# Operating and safety policies (generated from src/domain/policies.py)",
        "",
        "Principles: read-only discovery; generated SQL runs in a sandbox first; humans certify metrics",
        "and joins; no raw PII in model context; unknown actions are denied.",
        "",
        "| action | risk | allowed roles | required approval | description |",
        "|---|---|---|---|---|",
    ]
    for name, p in sorted(ACTIONS.items()):
        roles = ", ".join(sorted(r.value for r in p.roles))
        lines.append(f"| {name} | {p.risk.value} | {roles} | {p.gate.value if p.gate else '-'} | {p.description} |")
    return "\n".join(lines) + "\n"
