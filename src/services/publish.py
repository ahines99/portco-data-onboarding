"""Step 9 — publish (POD-310). Fail-closed, idempotent, human-approved.

The MVP target is a versioned local directory: `var/published/<company>/<version>/`. It holds
the certified dbt project and semantic layer (minus rejected metrics and everything derived
from them) plus `certification.json`. Publishing the same manifest again returns the original
receipt rather than creating a second version.
"""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from src.adapters.repositories import Tx
from src.domain.errors import ApprovalRequired, PolicyViolation
from src.domain.hashing import content_hash
from src.domain.models import AuditEvent, Confidence, Finding, FindingType, ReviewDecision, ReviewGate, StepName
from src.domain.project_models import Approval, ArtifactBundle, CertificationPacket, PublishReceipt
from src.fsutil import remove_tree
from src.services.approvals import effective_decisions, is_valid
from src.workflows.contracts import StepContext, StepResult, make_evidence

MAX_VERSION_ATTEMPTS = 5


def publish_bundle(ctx: StepContext) -> StepResult:
    bundle = ctx.get(StepName.ARTIFACT_GENERATION, ArtifactBundle)
    packet = ctx.get(StepName.HUMAN_CERTIFICATION, CertificationPacket)
    manifest = bundle.manifest_hash
    if packet.manifest_hash != manifest:
        raise PolicyViolation("certification packet does not match the bundle being published")
    try:
        with ctx.store.tx() as tx:
            certs, certification, excluded, published_metrics = _certifications(ctx, tx, bundle, packet)
    except ApprovalRequired:
        with ctx.store.tx() as tx:
            tx.audit.append(
                AuditEvent(
                    run_id=ctx.run.run_id,
                    step=StepName.PUBLISH.value,
                    actor="system",
                    event_type="policy_denied",
                    payload={"action": "publish"},
                )
            )
        raise
    company = ctx.run.company_id
    key = content_hash(
        {
            "manifest": manifest,
            "excluded": sorted(excluded),
            "certifications": [str(c) for c in packet.certification_ids],
        }
    )
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


def _certifications(
    ctx: StepContext,
    tx: Tx,
    bundle: ArtifactBundle,
    packet: CertificationPacket,
) -> tuple[list[Approval], Approval, set[str], list[str]]:
    subject = packet.review_hash()
    # Reload from storage: a context snapshot is not proof that approval remains valid.
    approvals = tx.approvals.for_run(ctx.run.run_id, ReviewGate.CERTIFICATION.value, lock=True)
    certs = [a for a in approvals if is_valid(a, subject)]
    decisions = effective_decisions(approvals, ReviewGate.CERTIFICATION, subject)
    required = {f"bundle:{bundle.manifest_hash}", *(f"metric:{m}" for m in bundle.generated_metrics)}
    valid_ids = {a.approval_id for a in certs}
    if (
        not ctx.approvals
        or not packet.certification_ids
        or not set(packet.certification_ids).issubset(valid_ids)
        or not required.issubset(decisions)
        or decisions[f"bundle:{bundle.manifest_hash}"].decision is not ReviewDecision.APPROVE
    ):
        raise ApprovalRequired("publish requires current certification for the bundle and every generated metric")
    excluded: set[str] = set()
    for metric in bundle.generated_metrics:
        d = decisions[f"metric:{metric}"]
        if d.decision is ReviewDecision.REJECT:
            excluded.add(metric)
            excluded.update(ctx.ontology.metric_dependents(metric))
        elif d.decision is not ReviewDecision.APPROVE or d.override is not None:
            raise ApprovalRequired("invalid metric certification decision")
    published = sorted(set(bundle.generated_metrics) - excluded)
    if published != sorted(packet.certified_metrics) or sorted(excluded) != sorted(packet.excluded_metrics):
        raise ApprovalRequired("effective metric decisions changed; repeat certification")
    certification = next(
        a
        for a in reversed(sorted(certs, key=lambda a: a.created_at))
        if any(d.item_key == f"bundle:{bundle.manifest_hash}" for d in a.decisions)
    )
    return certs, certification, excluded, published


def _resolved_identity(path: Path) -> PurePath:
    resolved = path.resolve()
    # Windows realpath can retain its extended prefix if a parent is created between
    # its filesystem probes. Normalize that spelling only after resolving links;
    # otherwise concurrent publishers can compare \\?\C:\... against C:\....
    if isinstance(resolved, PureWindowsPath):
        text = str(resolved)
        if resolved.drive.startswith("\\\\?\\UNC\\"):
            return PureWindowsPath("\\\\" + text[8:])
        if len(resolved.drive) == 6 and resolved.drive.startswith("\\\\?\\") and resolved.drive[-1] == ":":
            return PureWindowsPath(text[4:])
    return resolved


def _contained(root: Path, relative: str) -> Path:
    # Reject both POSIX and Windows path escapes regardless of the host platform.
    p, w = PurePosixPath(relative), PureWindowsPath(relative)
    if not relative or p.is_absolute() or w.drive or w.root or ".." in p.parts or ".." in w.parts:
        raise PolicyViolation("publication path escapes its root")
    target = root / relative
    if not _resolved_identity(target).is_relative_to(_resolved_identity(root)) or target.is_symlink():
        raise PolicyViolation("publication path escapes its root")
    return target


def _contents(
    ctx: StepContext,
    bundle: ArtifactBundle,
    packet: CertificationPacket,
    certs: list[Approval],
    receipt: PublishReceipt,
) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for f in bundle.files:
        _contained(Path(receipt.path), f.path)
        if f.path.startswith("models/semantic/metrics/") and f.path.rsplit("/", 1)[1][:-4] in receipt.excluded_metrics:
            continue
        if f.path in files or f.path == "certification.json":
            raise PolicyViolation("duplicate or reserved publication path")
        data = ctx.blobs.get_bytes(f.sha256)
        if sha256(data).hexdigest() != f.sha256:
            raise PolicyViolation("publication artifact content hash mismatch")
        files[f.path] = data
    # Approval IDs are bound to the packet, not later unrelated approval history.
    files["certification.json"] = json.dumps(
        {
            "receipt": receipt.model_dump(mode="json"),
            "packet": packet.model_dump(mode="json"),
            "approvals": [str(a) for a in packet.certification_ids],
        },
        indent=2,
        sort_keys=True,
    ).encode("utf-8")
    return files


def _verify(dest: Path, files: dict[str, bytes]) -> None:
    if not dest.is_dir() or dest.is_symlink():
        raise PolicyViolation("publication destination is missing or invalid")
    actual = {p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file()}
    if actual != set(files) or any(p.is_symlink() for p in dest.rglob("*")):
        raise PolicyViolation("publication file set has changed")
    for name, data in files.items():
        if _contained(dest, name).read_bytes() != data:
            raise PolicyViolation("publication file content has changed")


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
    company_root = _contained(ctx.settings.published_root, company)
    for _ in range(MAX_VERSION_ATTEMPTS):
        try:
            with ctx.store.tx() as tx:
                ctx.check_publication_owner(tx)
                operation = tx.publications.operation(company, key)
                if operation is None:
                    version = tx.publications.next_version(company)
                    receipt = PublishReceipt(
                        company_id=company,
                        version=version,
                        manifest_hash=bundle.manifest_hash,
                        certification_id=certification.approval_id,
                        publisher=certification.reviewer,
                        path=str(_contained(company_root, version)),
                        published_metrics=published_metrics,
                        excluded_metrics=sorted(excluded),
                    )
                    tx.publications.insert(
                        company,
                        bundle.manifest_hash,
                        key,
                        version,
                        ctx.run.run_id,
                        receipt.model_dump(mode="json"),
                        state="prepared",
                    )
                else:
                    receipt = PublishReceipt.model_validate(operation["receipt"])
            break
        except IntegrityError:
            continue
    else:
        raise PolicyViolation("could not allocate a publication version")
    dest = _contained(company_root, receipt.version)
    if dest != Path(receipt.path):
        raise PolicyViolation("publication receipt destination has changed")
    files = _contents(ctx, bundle, packet, certs, receipt)
    # Each attempt stages privately. A crash can leave an inert staging directory;
    # the durable prepared row allows retry to reconstruct and finish the same version.
    tmp = dest.with_name(f".{dest.name}.tmp-{uuid4().hex}")
    try:
        for name, data in files.items():
            if ctx.execution_cancelled.is_set():
                raise PolicyViolation("publication attempt was cancelled")
            target = _contained(tmp, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        with ctx.store.tx() as tx:
            # Cancellation, lease takeover and other finalizers serialize on these locks.
            ctx.check_publication_owner(tx)
            operation = tx.publications.operation(company, key)
            assert operation is not None
            _certifications(ctx, tx, bundle, packet)
            if dest.exists():
                # Covers a crash after rename but before the complete transaction commits.
                _verify(dest, files)
                reused = operation["state"] == "complete"
            elif operation["state"] == "complete":
                raise PolicyViolation("completed publication destination is missing")
            else:
                _verify(tmp, files)
                ctx.check_publication_owner(tx)
                tmp.rename(dest)
                try:
                    ctx.check_publication_owner(tx)
                except BaseException:
                    # A timeout during filesystem finalization must not leave published output.
                    remove_tree(dest)
                    raise
                reused = False
            tx.publications.complete(company, key)
        return receipt.model_copy(update={"reused": reused})
    finally:
        if tmp.exists():
            remove_tree(tmp)
