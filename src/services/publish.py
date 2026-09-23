"""Step 9 — publish (POD-310). Fail-closed, idempotent, human-approved.

The MVP target is a versioned local directory: `var/published/<company>/<version>/`. It holds
the certified dbt project and semantic layer (minus rejected metrics and everything derived
from them) plus `certification.json`. Publishing the same manifest again returns the original
receipt rather than creating a second version.
"""

from __future__ import annotations

import json
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from src.domain.errors import ApprovalRequired, PolicyViolation
from src.domain.hashing import content_hash
from src.domain.models import AuditEvent, Confidence, Finding, FindingType, ReviewDecision, ReviewGate, StepName
from src.domain.policies import check_action
from src.domain.project_models import Approval, ArtifactBundle, CertificationPacket, PublishReceipt
from src.fsutil import remove_tree
from src.services.approvals import is_valid
from src.workflows.contracts import StepContext, StepResult, make_evidence

MAX_VERSION_ATTEMPTS = 5


def publish_bundle(ctx: StepContext) -> StepResult:
    bundle = ctx.get(StepName.ARTIFACT_GENERATION, ArtifactBundle)
    packet = ctx.get(StepName.HUMAN_CERTIFICATION, CertificationPacket)
    manifest = bundle.manifest_hash
    if packet.manifest_hash != manifest:
        raise PolicyViolation("certification packet does not match the bundle being published")
    subject = packet.review_hash()
    certs = [
        a
        for a in ctx.approvals
        if a.gate == ReviewGate.CERTIFICATION
        and is_valid(a, subject)
        and any(d.item_key == f"bundle:{manifest}" and d.decision is not ReviewDecision.REJECT for d in a.decisions)
    ]
    decision = check_action("publish", has_approval=bool(certs) and bool(packet.certification_ids))
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
    excluded = set(packet.excluded_metrics)
    published_metrics = sorted(m for m in bundle.generated_metrics if m not in excluded)
    company = ctx.run.company_id
    # Idempotent on what is published and under which certification: the same content under the same approval
    # reuses the receipt; a changed decision (e.g. a metric rejected on re-certification) publishes a new version.
    key = content_hash(
        {
            "manifest": manifest,
            "excluded": sorted(excluded),
            "certifications": [str(c) for c in packet.certification_ids],
        }
    )
    with ctx.store.tx() as tx:
        existing = tx.publications.by_key(company, key)
    if existing:
        receipt = PublishReceipt.model_validate(existing).model_copy(update={"reused": True})
    else:
        receipt = _publish_new(ctx, bundle, packet, certs, certification, excluded, published_metrics, key)

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
            + ("; identical publication already existed, receipt reused" if receipt.reused else "")
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
                    "manifest_hash": manifest,
                    "reused": receipt.reused,
                    "certification_id": str(receipt.certification_id),
                },
            )
        ],
    )


def _publish_new(
    ctx: StepContext,
    bundle: ArtifactBundle,
    packet: CertificationPacket,
    certs: list[Approval],
    certification: Approval,
    excluded: set[str],
    published_metrics: list[str],
    key: str,
) -> PublishReceipt:
    company = ctx.run.company_id
    for _ in range(MAX_VERSION_ATTEMPTS):
        with ctx.store.tx() as tx:
            version = tx.publications.next_version(company)
        dest = ctx.settings.published_root / company / version
        tmp = dest.with_name(f"{dest.name}.tmp-{uuid4().hex[:8]}")
        for f in bundle.files:
            if f.path.startswith("models/semantic/metrics/") and f.path.rsplit("/", 1)[1][:-4] in excluded:
                continue
            target = tmp / f.path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(ctx.blobs.get_bytes(f.sha256))
        receipt = PublishReceipt(
            company_id=company,
            version=version,
            manifest_hash=bundle.manifest_hash,
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
            newline="\n",
        )
        try:
            # Unique (company, version) and (company, key) constraints arbitrate concurrent publishers.
            with ctx.store.tx() as tx:
                tx.publications.insert(
                    company, bundle.manifest_hash, key, version, ctx.run.run_id, receipt.model_dump(mode="json")
                )
        except IntegrityError:
            remove_tree(tmp)
            with ctx.store.tx() as tx:
                existing = tx.publications.by_key(company, key)
            if existing:
                return PublishReceipt.model_validate(existing).model_copy(update={"reused": True})
            continue  # another publisher took this version number: try the next one
        if dest.exists():
            raise PolicyViolation(f"publish target {version} already exists on disk; refusing to overwrite")
        tmp.rename(dest)
        return receipt
    raise PolicyViolation("could not allocate a publication version after several attempts")
