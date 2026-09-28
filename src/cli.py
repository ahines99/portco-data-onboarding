"""`portco` command-line interface (POD-407).

The CLI is the human's console: `review` records decisions as a reviewer principal, while
`run`/`resume` act as the agent principal. Separation of duties is enforced server-side either
way — the principal that started a run cannot approve it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

import anyio
import typer
import yaml

from src.domain.errors import Conflict, DomainError, ValidationFailed
from src.domain.models import Principal, ReviewDecision, ReviewGate, Role, StepName
from src.domain.project_models import ItemDecision
from src.settings import get_settings

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Portfolio-company data onboarding.")
fixtures_app = typer.Typer(no_args_is_help=True, help="Synthetic fixture databases.")
app.add_typer(fixtures_app, name="fixtures")
sources_app = typer.Typer(no_args_is_help=True, help="Operator-managed external source snapshots.")
app.add_typer(sources_app, name="sources")


@sources_app.command("import-csv")
def sources_import_csv(
    manifest: Path,
    root: Annotated[Path, typer.Option(help="Directory containing declared CSV extracts")],
) -> None:
    """Import explicit typed CSV extracts; local operator only, never a remote capability."""
    from src.adapters.csv_source import import_csv

    try:
        receipt = import_csv(manifest, root, get_settings().var_root / "sources")
    except DomainError as exc:
        _fail(exc)
        return
    typer.echo(json.dumps(receipt, indent=2))


def _service() -> Any:
    from src.workflows.facade import OnboardingService

    return OnboardingService.build()


def _principal(spec: str, default_role: Role) -> Principal:
    pid, _, role = spec.partition(":")
    if role in {r.value for r in Role}:
        return Principal(principal_id=pid, role=Role(role))
    return Principal(principal_id=spec, role=default_role)


def _fail(exc: DomainError) -> None:
    typer.secho(f"{exc.code.value}: {exc.message}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code=2)


def _print_run(run: Any) -> None:
    colors = {"complete": typer.colors.GREEN, "needs_review": typer.colors.YELLOW, "failed": typer.colors.RED}
    color = colors.get(run.status.value)
    typer.secho(
        f"run {run.run_id}  status={run.status.value}  step={run.current_step or '-'}  "
        f"gate={run.gate or '-'}  pending={len(run.pending_items)}",
        fg=color,
    )
    if run.error:
        typer.secho(f"  error: {run.error.get('code')}: {run.error.get('message')}", fg=typer.colors.RED)
    if run.pending_items:
        typer.echo(f"  next: portco review {run.run_id} --export review.yaml")


@fixtures_app.command("generate")
def fixtures_generate(
    fixture: Annotated[str, typer.Option(help="a, b, all, or a fixture name")] = "all",
    refresh_ground_truth: Annotated[
        bool, typer.Option(help="Explicitly refresh ground-truth resources in a writable development checkout")
    ] = False,
) -> None:
    """Generate runtime fixture databases; ground-truth resources are unchanged by default."""
    from src.fixtures.generate import fixture_names, generate

    names = {"a": ["portco_a"], "b": ["portco_b"], "all": fixture_names()}.get(fixture, [fixture])
    for name in names:
        path = generate(name, get_settings().fixtures_dir, write_truth=refresh_ground_truth)
        typer.echo(f"generated {name} -> {path}")


@app.command()
def run(
    fixture: Annotated[str, typer.Option(help="fixture name, e.g. portco_a")] = "portco_a",
    connection: Annotated[str | None, typer.Option(help="connection id (overrides --fixture)")] = None,
    stop_after: Annotated[StepName | None, typer.Option(help="pause after this step")] = None,
    as_: Annotated[str, typer.Option("--as", help="principal id, optionally id:role")] = "agent:cli",
) -> None:
    """Start an onboarding run; it proceeds until the first review gate."""
    svc = _service()
    principal = _principal(as_, Role.AGENT)
    try:
        result = anyio.run(lambda: svc.start_run(principal, connection or f"fixture:{fixture}", None, stop_after))
    except DomainError as exc:
        _fail(exc)
        return
    _print_run(result)


@app.command()
def status(run_id: UUID) -> None:
    """Show a run's steps, attempts and pending review items."""
    svc = _service()
    admin = Principal(principal_id="cli:status", role=Role.ADMIN)
    try:
        r = svc.get_run(admin, run_id)
        _print_run(r)
        for s in svc.steps(admin, run_id):
            typer.echo(f"  {s['step']:22} {s['status']:13} attempts={s['attempts']}")
        for item in r.pending_items:
            typer.echo(f"  [review] {item.item_key}  {','.join(item.reason_codes)}")
    except DomainError as exc:
        _fail(exc)


@app.command()
def review(
    run_id: UUID,
    export: Annotated[Path | None, typer.Option(help="write pending items to this YAML file")] = None,
    import_: Annotated[Path | None, typer.Option("--import", help="read decisions from this YAML")] = None,
    reviewer: Annotated[str, typer.Option(help="reviewer principal id")] = "reviewer:cli",
    default: Annotated[str | None, typer.Option(help="decision for items left blank (approve|reject)")] = None,
    comment: Annotated[str | None, typer.Option(help="comment stored with the approval")] = None,
) -> None:
    """Export pending review items, or import a reviewer's decisions."""
    svc = _service()
    admin = Principal(principal_id="cli:review", role=Role.ADMIN)
    try:
        r = svc.get_run(admin, run_id)
        if export:
            doc = {
                "run_id": str(run_id),
                "gate": r.gate,
                "subject_hash": r.pending_items[0].subject_hash if r.pending_items else None,
                "instructions": "Set decision to approve | reject | approve_with_override for each item. "
                "Overrides: {canonical_field, transform, pii_handling}.",
                "items": [
                    {
                        "item_key": i.item_key,
                        "summary": i.summary,
                        "reason_codes": i.reason_codes,
                        "options": i.options,
                        "decision": None,
                        "override": None,
                        "comment": None,
                    }
                    for i in r.pending_items
                ],
            }
            export.write_text(yaml.safe_dump(doc, sort_keys=False, width=120), encoding="utf-8", newline="\n")
            typer.echo(f"wrote {len(r.pending_items)} items to {export}")
            return
        if not import_:
            typer.echo("use --export or --import")
            raise typer.Exit(1)
        doc = yaml.safe_load(import_.read_text(encoding="utf-8"))
        if not isinstance(doc, dict) or not isinstance(doc.get("items"), list):
            raise ValidationFailed("review file must contain packet metadata and an items list")
        try:
            packet_run = UUID(str(doc["run_id"]))
            packet_gate = ReviewGate(doc["gate"])
            subject_hash = doc["subject_hash"]
        except (KeyError, ValueError, TypeError) as exc:
            raise ValidationFailed(
                "review file requires a valid run_id, gate and subject_hash; export it again"
            ) from exc
        if not isinstance(subject_hash, str) or not subject_hash:
            raise ValidationFailed("review file requires a nonempty subject_hash")
        if packet_run != run_id or packet_gate.value != r.gate:
            raise Conflict("review file is for a different run or gate; export the current packet")
        decisions = []
        for item in doc.get("items", []):
            decision = item.get("decision") or default
            if not decision:
                continue
            decisions.append(
                ItemDecision(
                    item_key=item["item_key"],
                    decision=ReviewDecision(decision),
                    override=item.get("override"),
                    comment=item.get("comment"),
                )
            )
        principal = _principal(reviewer, Role.REVIEWER)
        if packet_gate is ReviewGate.CERTIFICATION:
            approval = svc.certify(principal, run_id, subject_hash, decisions, comment)
        else:
            approval = svc.submit_review(
                principal, run_id, decisions, comment, subject_hash=subject_hash, gate=packet_gate
            )
        typer.secho(
            f"recorded approval {approval.approval_id} ({len(decisions)} decisions) for gate {approval.gate.value}",
            fg=typer.colors.GREEN,
        )
        typer.echo(f"next: portco resume {run_id}")
    except DomainError as exc:
        _fail(exc)


@app.command()
def resume(run_id: UUID, as_: Annotated[str, typer.Option("--as")] = "agent:cli") -> None:
    """Resume a paused or failed run. Gates re-check approvals; completed steps are not recomputed."""
    svc = _service()
    try:
        _print_run(anyio.run(lambda: svc.resume(_principal(as_, Role.AGENT), run_id)))
    except DomainError as exc:
        _fail(exc)


@app.command()
def rerun(
    run_id: UUID,
    from_: Annotated[StepName, typer.Option("--from")],
    as_: Annotated[str, typer.Option("--as")] = "reviewer:cli",
) -> None:
    """Invalidate a step and everything after it, then run again (reused where inputs are unchanged)."""
    svc = _service()
    try:
        _print_run(anyio.run(lambda: svc.rerun_from(_principal(as_, Role.REVIEWER), run_id, from_)))
    except DomainError as exc:
        _fail(exc)


@app.command()
def cancel(
    run_id: UUID, reason: str = "cancelled from CLI", as_: Annotated[str, typer.Option("--as")] = "reviewer:cli"
) -> None:
    """Cancel a run."""
    svc = _service()
    try:
        _print_run(svc.cancel(_principal(as_, Role.REVIEWER), run_id, reason))
    except DomainError as exc:
        _fail(exc)


@app.command()
def findings(run_id: UUID, code: str | None = None) -> None:
    """List current findings (observations, calculations, assumptions, recommendations)."""
    svc = _service()
    admin = Principal(principal_id="cli:findings", role=Role.ADMIN)
    for f in svc.findings(admin, run_id, code):
        typer.echo(f"{f.code:24} {f.confidence.value:6} {f.status.value:14} {f.title}")


@app.command()
def audit(run_id: UUID, verify: bool = False) -> None:
    """Print the audit log; --verify checks the hash chain."""
    svc = _service()
    events, ok = svc.audit(Principal(principal_id="cli:audit", role=Role.ADMIN), run_id)
    if verify:
        typer.secho(
            f"audit chain {'intact' if ok else 'BROKEN'} ({len(events)} events)",
            fg=typer.colors.GREEN if ok else typer.colors.RED,
        )
        raise typer.Exit(0 if ok else 3)
    for e in events:
        typer.echo(
            f"{e.created_at:%H:%M:%S} {e.step:22} {e.event_type:24} {e.actor:16} "
            f"{json.dumps(e.payload, default=str)[:100]}"
        )


@app.command()
def lineage(finding_id: UUID) -> None:
    """Show the evidence tree behind a finding."""
    svc = _service()
    typer.echo(json.dumps(svc.lineage(Principal(principal_id="cli", role=Role.ADMIN), finding_id), indent=2))


@app.command()
def report(run_id: UUID, out: Annotated[Path | None, typer.Option(help="write Markdown here")] = None) -> None:
    """Render the run report / certification packet as Markdown."""
    from src.reporting import render_run_report

    svc = _service()
    text = render_run_report(svc, Principal(principal_id="cli:report", role=Role.ADMIN), run_id)
    if out:
        out.write_text(text, encoding="utf-8", newline="\n")
        typer.echo(f"wrote {out}")
    else:
        typer.echo(text)


@app.command()
def demo(out: Annotated[Path, typer.Option(help="where to write demo reports")] = Path("var/demo")) -> None:
    """One-command demo: a happy path and a controlled failure/review path."""
    from src.demo import run_demo

    raise typer.Exit(run_demo(out))


if __name__ == "__main__":
    app()
