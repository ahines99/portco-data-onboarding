"""Step 9 — publish (POD-310). Fail-closed, idempotent, human-approved.

The MVP target is a versioned local directory: `var/published/<company>/<version>/`. It holds
the certified dbt project and semantic layer (minus rejected metrics and everything derived
from them) plus `certification.json`. Publishing the same manifest again returns the original
receipt rather than creating a second version.
"""

from __future__ import annotations

import json
import shutil

from sqlalchemy.exc import IntegrityError

from src.domain.errors import ApprovalRequired, PolicyViolation
from src.domain.models import AuditEvent, Confidence, Finding, FindingType, ReviewDecision, ReviewGate, StepName
from src.domain.policies import check_action
from src.domain.project_models import ArtifactBundle, CertificationPacket, PublishReceipt
from src.services.approvals import effective_decisions, is_valid
from src.workflows.contracts import StepContext, StepResult, make_evidence


def publish_bundle(ctx: StepContext) -> StepResult:
    bundle = ctx.get(StepName.ARTIFACT_GENERATION, ArtifactBundle)
    packet = ctx.get(StepName.HUMAN_CERTIFICATION, CertificationPacket)
    subject = bundle.manifest_hash
    if packet.manifest_hash != subject:
        raise PolicyViolation("certification packet does not match the bundle being published")
    certs = [
        a
        for a in ctx.approvals
        if a.gate == ReviewGate.CERTIFICATION
        and is_valid(a, subject)
        and any(d.item_key == f"bundle:{subject}" and d.decision is not ReviewDecision.REJECT for d in a.decisions)
    ]
    decision = check_action("publish", has_approval=bool(certs))
    if not decision.allowed:
        with ctx.store.tx() as tx:
            tx.audit.append(
                AuditEvent(
                    run_id=ctx.run.run_id,
                    step=StepName.PUBLISH.value,
                    actor="system",
                    event_type="policy_denied",
                    payload={"action": "publish", "reason": decision.reason},
                )
            )
        raise ApprovalRequired("publish requires a valid certification bound to this bundle")
    certification = sorted(certs, key=lambda a: a.created_at)[-1]
    decisions = effective_decisions(ctx.approvals, ReviewGate.CERTIFICATION, subject)
    rejected = {
        k.removeprefix("metric:")
        for k, d in decisions.items()
        if k.startswith("metric:") and d.decision is ReviewDecision.REJECT
    }
    excluded = set(rejected)
    for m in rejected:
        excluded |= ctx.ontology.metric_dependents(m)
    published_metrics = sorted(m for m in bundle.generated_metrics if m not in excluded)
    company = ctx.run.company_id

    with ctx.store.tx() as tx:
        existing = tx.publications.by_hash(company, subject)
        version = tx.publications.next_version(company)
    if existing:
        receipt = PublishReceipt.model_validate(existing).model_copy(update={"reused": True})
    else:
        dest = ctx.settings.published_root / company / version
        tmp = dest.with_name(dest.name + ".tmp")
        shutil.rmtree(tmp, ignore_errors=True)
        for f in bundle.files:
            if f.path.startswith("models/semantic/metrics/") and f.path.rsplit("/", 1)[1][:-4] in excluded:
                continue
            target = tmp / f.path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(ctx.blobs.get_bytes(f.sha256))
        receipt = PublishReceipt(
            company_id=company,
            version=version,
            manifest_hash=subject,
            certification_id=certification.approval_id,
            publisher=certification.reviewer,
            path=str(dest),
            published_metrics=published_metrics,
            excluded_metrics=sorted(excluded),
        )
        (tmp / "certification.json").write_text(
            json.dumps(
                {
                    "receipt": receipt.model_dump(mode="json"),
                    "packet": packet.model_dump(mode="json"),
                    "approvals": [str(a.approval_id) for a in certs],
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        try:
            with ctx.store.tx() as tx:
                tx.publications.insert(company, subject, version, ctx.run.run_id, receipt.model_dump(mode="json"))
            if dest.exists():
                shutil.rmtree(dest)
            tmp.rename(dest)
        except IntegrityError:
            shutil.rmtree(tmp, ignore_errors=True)
            with ctx.store.tx() as tx:
                existing = tx.publications.by_hash(company, subject)
            assert existing is not None
            receipt = PublishReceipt.model_validate(existing).model_copy(update={"reused": True})

    ev = make_evidence(
        ctx,
        f"publish://{company}/{receipt.version}",
        "publish_receipt",
        receipt.model_dump(mode="json", exclude={"reused", "published_at"}),
    )
    finding = Finding(
        code="PUBLISHED",
        title=f"Published {company} {receipt.version}",
        finding_type=FindingType.OBSERVATION,
        statement=(
            f"{len(receipt.published_metrics)} certified metrics published"
            + (f"; excluded {', '.join(receipt.excluded_metrics)}" if receipt.excluded_metrics else "")
            + ("; identical bundle was already published, receipt reused" if receipt.reused else "")
            + "."
        ),
        confidence=Confidence.HIGH,
        evidence=[ev.ref()],
        metadata={"version": receipt.version},
    )
    return StepResult(
        output=receipt,
        evidence=[ev],
        findings=[finding],
        audit=[
            (
                "publish_completed",
                {
                    "version": receipt.version,
                    "manifest_hash": subject,
                    "reused": receipt.reused,
                    "certification_id": str(receipt.certification_id),
                },
            )
        ],
    )
