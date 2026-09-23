"""Step 7 — sandbox test execution and reconciliation (POD-308, ADR-0008).

The generated project is built with dbt in a subprocess against a disposable copy of the
source, attached read-only. The original source file is never opened for writing. Results are
cached per (bundle manifest, source fingerprint), so resuming or rerunning is cheap.

Reconciliation recomputes metrics in Python from the sandbox copy of the source, using the
reviewed mapping and filters but none of the generated SQL, and compares them with the marts.
Tolerance for money is exactly zero.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

from src.domain import metrics_reference as ref
from src.domain.errors import DependencyFailed, PolicyViolation, ValidationFailed
from src.domain.hashing import content_hash
from src.domain.models import Confidence, Finding, FindingType, ReviewDecision, ReviewGate, StepName
from src.domain.pii_guard import PiiGuard
from src.domain.project_models import (
    AcceptedMapping,
    ArtifactBundle,
    ConnectionCheck,
    DbtResult,
    ReconciliationCheck,
    ResolvedMapping,
    ReviewItem,
    TestReport,
)
from src.services.approvals import effective_decisions
from src.workflows.contracts import StepContext, StepResult, make_evidence

_GUARD = PiiGuard()


def _sanitize(message: str | None) -> str | None:
    if not message:
        return message
    text = re.sub(r"'[^']*'", "'…'", message.splitlines()[0])[:240]
    return "[redacted: message contained sensitive-looking data]" if _GUARD.scan_text(text) else text


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


# --------------------------------------------------------------------------- dbt


def materialize(ctx: StepContext, bundle: ArtifactBundle, dest: Path) -> None:
    for f in bundle.files:
        target = dest / f.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(ctx.blobs.get_bytes(f.sha256))


def run_dbt(ctx: StepContext, workdir: Path, source_copy: Path) -> tuple[int, list[DbtResult]]:
    faults = ctx.services.get("faults")
    if faults is not None and faults.active:
        faults.check("dbt.build")
    sandbox_root = ctx.settings.sandbox_root
    warehouse = workdir / "warehouse.duckdb"
    if not (_inside(warehouse, sandbox_root) and _inside(source_copy, sandbox_root)):
        raise PolicyViolation("dbt may only target files inside the sandbox directory")
    project = workdir / "project"
    env = {
        **os.environ,
        "PORTCO_DBT_WAREHOUSE": str(warehouse),
        "PORTCO_DBT_SOURCE": str(source_copy),
        "DBT_SEND_ANONYMOUS_USAGE_STATS": "false",
        "DO_NOT_TRACK": "1",
        "PYTHONIOENCODING": "utf-8",
    }
    exe = Path(sys.executable).parent / ("dbt.exe" if os.name == "nt" else "dbt")
    launcher = [str(exe)] if exe.exists() else [sys.executable, "-m", "dbt.cli.main"]
    cmd = [
        *launcher,
        "build",
        "--project-dir",
        str(project),
        "--profiles-dir",
        str(project),
        "--target-path",
        str(workdir / "target"),
        "--log-path",
        str(workdir / "logs"),
        "--no-partial-parse",
        "--no-use-colors",
    ]
    try:
        proc = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=ctx.settings.dbt_timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise DependencyFailed("dbt build exceeded its time budget") from exc
    (workdir / "dbt_stdout.log").write_text(proc.stdout + "\n" + proc.stderr, encoding="utf-8")
    results_path = workdir / "target" / "run_results.json"
    if not results_path.exists():
        if proc.returncode >= 2:
            raise DependencyFailed("dbt crashed before producing results (see sandbox logs)")
        raise ValidationFailed("dbt could not parse the generated project (see sandbox logs)")
    data = json.loads(results_path.read_text(encoding="utf-8"))
    results = [
        DbtResult(
            unique_id=r["unique_id"],
            resource_type=r["unique_id"].split(".", 1)[0],
            status=r["status"],
            failures=r.get("failures"),
            message=_sanitize(r.get("message")),
        )
        for r in data.get("results", [])
    ]
    return proc.returncode, sorted(results, key=lambda r: r.unique_id)


# --------------------------------------------------------------------------- reference inputs


class SourceRows:
    """Reads the sandbox COPY of the source. Used only for reconciliation, never exposed."""

    def __init__(self, path: Path, resolved: ResolvedMapping) -> None:
        self.con = duckdb.connect(str(path), read_only=True)
        self.r = resolved
        self._excluded: dict[str, set[str]] = {}

    def close(self) -> None:
        self.con.close()

    def _cols(self, table: str, cols: list[str]) -> list[dict[str, Any]]:
        schema, name = table.split(".", 1)
        sel = ", ".join(f'"{c}"' for c in cols) or "1 AS _row"
        rows = self.con.execute(f'SELECT {sel} FROM "{schema}"."{name}"').fetchall()
        return [dict(zip(cols, row, strict=False)) for row in rows]

    def own_excluded(self, table: str, row: dict[str, Any]) -> bool:
        for f in self.r.filters:
            if f.table != table:
                continue
            v = row.get(f.column)
            if f.kind == "exclude_true" and v is True:
                return True
            if f.kind == "exclude_prefix" and isinstance(v, str) and v.startswith(f.value or ""):
                return True
        return False

    def _parent_edges(self, table: str) -> list[tuple[str, str, str]]:
        ent = self.r.entity_tables
        mapped = {(m.source_table, m.source_column) for m in self.r.accepted if m.pii_handling != "exclude"}
        return [
            (j.left_columns[0], j.right_table, j.right_columns[0])
            for j in self.r.joins
            if j.left_table == table
            and ent.get(j.right_table)
            and ent.get(j.right_table) != ent.get(table)
            and j.cardinality in {"N:1", "1:1"}
            and (table, j.left_columns[0]) in mapped
            and (j.right_table, j.right_columns[0]) in mapped
        ]

    def excluded_keys(self, table: str, key: str, _stack: frozenset[str] = frozenset()) -> set[str]:
        cache_key = f"{table}.{key}"
        if cache_key in self._excluded:
            return self._excluded[cache_key]
        rows = self.scoped(table, [key], _stack | {table})
        out = {str(r[key]) for r in rows if not r["_in_scope"] and r[key] is not None}
        self._excluded[cache_key] = out
        return out

    def scoped(self, table: str, cols: list[str], _stack: frozenset[str] = frozenset()) -> list[dict[str, Any]]:
        edges = [e for e in self._parent_edges(table) if e[1] not in _stack]
        filter_cols = [f.column for f in self.r.filters if f.table == table]
        need = sorted(set(cols) | set(filter_cols) | {e[0] for e in edges})
        rows = self._cols(table, need)
        parents = {e: self.excluded_keys(e[1], e[2], _stack | {table}) for e in edges}
        for row in rows:
            out = self.own_excluded(table, row)
            for (fk, _pt, _pk), keys in parents.items():
                if row.get(fk) is not None and str(row[fk]) in keys:
                    out = True
            row["_in_scope"] = not out
        return rows


def _field(r: ResolvedMapping, entity: str, name: str) -> AcceptedMapping | None:
    m = r.field_source(entity, name)
    if m is None or m.source_table != r.primary_tables.get(entity) or m.pii_handling == "exclude":
        return None
    return m


def _value(m: AcceptedMapping, raw: Any) -> Any:
    if raw is None:
        return None
    if m.transform == "cents_to_major":
        return (Decimal(raw) / 100).quantize(Decimal("0.01"))
    if m.transform == "parse_mixed_date":
        for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
            try:
                return datetime.strptime(str(raw), fmt).date()
            except ValueError:
                continue
        return None
    if isinstance(raw, datetime):
        return raw.date()
    return raw


def _records(src: SourceRows, r: ResolvedMapping, entity: str, fields: list[str]) -> list[dict[str, Any]] | None:
    maps = {f: _field(r, entity, f) for f in fields}
    if any(m is None for m in maps.values()):
        return None
    table = r.primary_tables[entity]
    rows = src.scoped(table, sorted({m.source_column for m in maps.values() if m}))
    return [{f: _value(m, row[m.source_column]) for f, m in maps.items() if m} for row in rows if row["_in_scope"]]


# --------------------------------------------------------------------------- reconciliation


def _mart_dict(wh: duckdb.DuckDBPyConnection, sql: str) -> dict[str, Any]:
    return {str(k): v for k, v in wh.execute(sql).fetchall()}


def _compare(name: str, expected: dict[str, Any], actual: dict[str, Any], detail: str) -> ReconciliationCheck:
    keys = sorted(set(expected) | set(actual))
    diffs = [k for k in keys if str(expected.get(k, "0")) != str(actual.get(k, "0"))]
    return ReconciliationCheck(
        name=name,
        passed=not diffs,
        detail=(
            f"{detail}: {len(keys)} periods compared exactly"
            if not diffs
            else f"{detail}: {len(diffs)} of {len(keys)} periods differ (first: {diffs[0]})"
        ),
        expected={k: str(expected.get(k, "0")) for k in diffs[:5]} if diffs else {"periods": len(keys)},
        actual={k: str(actual.get(k, "0")) for k in diffs[:5]} if diffs else {"periods": len(keys)},
    )


def reconcile(
    src: SourceRows,
    wh: duckdb.DuckDBPyConnection,
    r: ResolvedMapping,
    bundle: ArtifactBundle,
    as_of: date | None,
    model_tables: dict[str, str],
) -> list[ReconciliationCheck]:
    checks: list[ReconciliationCheck] = []
    models = set(bundle.models)

    for table, stg in sorted(model_tables.items()):
        src_n = src.con.execute(f'SELECT count(*) FROM "{table.split(".")[0]}"."{table.split(".", 1)[1]}"').fetchone()
        stg_n, stg_x = wh.execute(f"SELECT count(*), count(*) FILTER (WHERE _excluded) FROM {stg}").fetchone()  # type: ignore[misc]
        rows = src.scoped(table, [])
        py_x = sum(1 for row in rows if src.own_excluded(table, row))
        checks.append(
            ReconciliationCheck(
                name=f"rowcount:{table}",
                passed=src_n is not None and int(src_n[0]) == int(stg_n) and py_x == stg_x,
                detail=f"source {src_n[0] if src_n else '?'} rows, staging {stg_n}; filtered {stg_x} (ref {py_x})",
                expected={"rows": int(src_n[0]) if src_n else None, "excluded": py_x},
                actual={"rows": int(stg_n), "excluded": int(stg_x)},
            )
        )

    if "fct_invoice" in models and "billings" in bundle.generated_metrics:
        recs = _records(src, r, "invoice", ["invoice_id", "customer_id", "invoice_date", "total_amount", "currency"])
        if recs is not None:
            invs = [
                ref.InvoiceRec(
                    str(x["invoice_id"]),
                    str(x["customer_id"]),
                    x["invoice_date"],
                    Decimal(x["total_amount"]),
                    str(x["currency"]),
                )
                for x in recs
            ]
            exp = {f"{m}|{c}": v for (m, c), v in ref.billings(invs).items()}
            act = _mart_dict(
                wh,
                "SELECT strftime(invoice_date, '%Y-%m') || '|' || currency, "
                "cast(sum(total_amount) AS DECIMAL(18,2)) FROM fct_invoice GROUP BY 1",
            )
            checks.append(_compare("metric:billings", exp, act, "billings by month and currency"))

    if "fct_mrr_monthly" in models and "arr" in bundle.generated_metrics:
        recs = _records(src, r, "subscription", ["customer_id", "mrr", "currency", "start_date", "end_date"])
        if recs is not None and recs:
            subs = [
                ref.SubscriptionRec(
                    str(x["customer_id"]), Decimal(x["mrr"]), str(x["currency"]), x["start_date"], x["end_date"]
                )
                for x in recs
            ]
            first = min(s.start_date for s in subs)
            last = as_of or date.today()
            months = ref.month_range(ref.month_key(first), ref.month_key(last))
            exp = {f"{m}|{c}": v for (m, c), v in ref.arr(subs, months).items()}
            act = _mart_dict(
                wh,
                "SELECT strftime(month_end, '%Y-%m') || '|' || currency, "
                "cast(sum(mrr) * 12 AS DECIMAL(18,2)) FROM fct_mrr_monthly GROUP BY 1",
            )
            checks.append(_compare("metric:arr", exp, act, "ARR by month and currency"))
            exp_ac = {m: v for m, v in ref.active_customers(subs, months).items() if v}
            act_ac = _mart_dict(
                wh,
                "SELECT strftime(month_end, '%Y-%m'), count(DISTINCT customer_id) "
                "FILTER (WHERE mrr > 0) FROM fct_mrr_monthly GROUP BY 1",
            )
            checks.append(_compare("metric:active_customers", exp_ac, act_ac, "active customers by month"))

    if "fct_gl_entry" in models and "revenue_recognized" in bundle.generated_metrics:
        lines = _records(src, r, "gl_entry", ["account_code", "posting_date", "debit_amount", "credit_amount"])
        accts = _records(src, r, "gl_account", ["account_code", "account_type"])
        if lines is not None and accts is not None:
            types = {str(a["account_code"]): str(a["account_type"]) for a in accts}
            gl = [
                ref.GlLineRec(
                    x["posting_date"],
                    types.get(str(x["account_code"]), ""),
                    Decimal(x["debit_amount"] or 0),
                    Decimal(x["credit_amount"] or 0),
                )
                for x in lines
            ]
            exp = {k: v for k, v in ref.revenue_recognized(gl).items() if v}
            act = {
                k: v
                for k, v in _mart_dict(
                    wh,
                    "SELECT strftime(posting_date, '%Y-%m'), cast(sum(CASE WHEN account_type = 'revenue' "
                    "THEN credit_amount - debit_amount ELSE 0 END) AS DECIMAL(18,2)) FROM fct_gl_entry GROUP BY 1",
                ).items()
                if v
            }
            checks.append(_compare("metric:revenue_recognized", exp, act, "recognized revenue by month"))

    if {"fct_invoice", "fct_invoice_line"} <= models:
        cols = {c[0] for c in wh.execute("DESCRIBE fct_invoice_line").fetchall()}
        icols = {c[0] for c in wh.execute("DESCRIBE fct_invoice").fetchall()}
        if {"amount", "invoice_id"} <= cols and {"total_amount", "invoice_id"} <= icols:
            total, ok = wh.execute(
                "SELECT count(*), count(*) FILTER (WHERE abs(coalesce(l.s, 0) - i.total_amount) < 0.005) "
                "FROM fct_invoice i LEFT JOIN (SELECT invoice_id, sum(amount) AS s FROM fct_invoice_line "
                "GROUP BY 1) l USING (invoice_id)"
            ).fetchone()  # type: ignore[misc]
            ratio = ok / total if total else 1.0
            checks.append(
                ReconciliationCheck(
                    name="consistency:invoice_lines_sum_to_header",
                    passed=ratio >= 0.999,
                    detail=f"{ok} of {total} invoices have line amounts summing to the header total ({ratio:.1%})",
                    expected={"match_ratio": ">= 0.999"},
                    actual={"match_ratio": round(ratio, 4)},
                )
            )

    for j in r.joins:
        if j.orphan_rate <= 0 or j.left_table not in model_tables:
            continue
        rows = src._cols(j.left_table, [j.left_columns[0]])
        right = {str(v[j.right_columns[0]]) for v in src._cols(j.right_table, [j.right_columns[0]])}
        vals = [str(x[j.left_columns[0]]) for x in rows if x[j.left_columns[0]] is not None]
        actual = round(sum(1 for v in vals if v not in right) / len(vals), 4) if vals else 0.0
        checks.append(
            ReconciliationCheck(
                name=f"orphans:{j.join_id}",
                passed=abs(actual - j.orphan_rate) <= 0.001,
                blocking=False,
                detail=f"orphan rate {actual:.2%} (reviewed at {j.orphan_rate:.2%})",
                expected={"orphan_rate": j.orphan_rate},
                actual={"orphan_rate": actual},
            )
        )
    return checks


# --------------------------------------------------------------------------- step


def build_and_test(ctx: StepContext, bundle: ArtifactBundle, resolved: ResolvedMapping, fingerprint: str) -> TestReport:
    key = f"{bundle.manifest_hash[:16]}-{fingerprint[:12]}"
    workdir = (ctx.settings.sandbox_root / str(ctx.run.run_id) / key).resolve()
    report_path = workdir / "report.json"
    if report_path.exists():
        cached = TestReport.model_validate_json(report_path.read_text(encoding="utf-8"))
        return cached.model_copy(update={"cached": True})
    started = time.monotonic()
    if workdir.exists():
        shutil.rmtree(workdir)
    (workdir / "project").mkdir(parents=True)
    materialize(ctx, bundle, workdir / "project")
    spec = ctx.adapter().spec
    ctx.close()  # release the source handle before copying
    source_copy = workdir / "source.duckdb"
    shutil.copyfile(spec.path, source_copy)
    exit_code, results = run_dbt(ctx, workdir, source_copy)

    checks: list[ReconciliationCheck] = []
    warehouse = workdir / "warehouse.duckdb"
    model_tables = {}
    if exit_code in (0, 1) and warehouse.exists():
        stg_models = {
            f.path.rsplit("/", 1)[1][:-4]
            for f in bundle.files
            if f.path.startswith("models/staging") and f.path.endswith(".sql")
        }
        for m in resolved.accepted:
            schema, name = m.source_table.split(".", 1)
            stg = f"stg_{re.sub(r'[^a-z0-9_]+', '_', schema.lower())}__{re.sub(r'[^a-z0-9_]+', '_', name.lower())}"
            if stg in stg_models:
                model_tables[m.source_table] = stg
        wh = duckdb.connect(str(warehouse), read_only=True)
        wh.execute(f"ATTACH '{source_copy.as_posix()}' AS src (READ_ONLY)")
        src = SourceRows(source_copy, resolved)
        try:
            ok_models = {
                r.unique_id.rsplit(".", 1)[1] for r in results if r.resource_type == "model" and r.status == "success"
            }
            usable = bundle.model_copy(update={"models": [m for m in bundle.models if m in ok_models]})
            checks = reconcile(
                src, wh, resolved, usable, spec.as_of, {t: s for t, s in model_tables.items() if s in ok_models}
            )
        finally:
            wh.close()
            src.close()
    failing = [r.unique_id for r in results if r.status in {"fail", "error"}]
    failing += [c.name for c in checks if not c.passed and c.blocking]
    report = TestReport(
        manifest_hash=bundle.manifest_hash,
        source_fingerprint=fingerprint,
        passed=exit_code == 0 and not failing,
        dbt_exit_code=exit_code,
        dbt_results=results,
        reconciliation=checks,
        failing_checks=sorted(failing),
        duration_seconds=round(time.monotonic() - started, 2),
    )
    report_path.write_text(report.model_dump_json(indent=1), encoding="utf-8")
    _prune(ctx.settings.sandbox_root / str(ctx.run.run_id), keep=ctx.settings.sandbox_keep_attempts)
    return report


def _prune(root: Path, keep: int) -> None:
    dirs = sorted((d for d in root.iterdir() if d.is_dir()), key=lambda d: d.stat().st_mtime, reverse=True)
    for d in dirs[keep:]:
        shutil.rmtree(d, ignore_errors=True)


def run_automated_tests(ctx: StepContext) -> StepResult:
    bundle = ctx.get(StepName.ARTIFACT_GENERATION, ArtifactBundle)
    resolved = ctx.get(StepName.MAPPING_REVIEW, ResolvedMapping)
    check = ctx.get(StepName.CONNECTION_VALIDATION, ConnectionCheck)
    report = build_and_test(ctx, bundle, resolved, check.source_fingerprint)

    payload = {
        "manifest_hash": report.manifest_hash,
        "passed": report.passed,
        "exit_code": report.dbt_exit_code,
        "results": [(r.unique_id, r.status, r.failures) for r in report.dbt_results],
        "reconciliation": [(c.name, c.passed) for c in report.reconciliation],
    }
    ev = make_evidence(ctx, f"sandbox://{ctx.run.run_id}/{report.manifest_hash[:16]}", "sandbox_test_report", payload)
    n_tests = sum(1 for r in report.dbt_results if r.resource_type == "test")
    findings = [
        Finding(
            code="SANDBOX_TESTS",
            title="Sandbox build and reconciliation",
            finding_type=FindingType.CALCULATION,
            statement=(
                f"dbt exit {report.dbt_exit_code}; {n_tests} data tests; "
                f"{sum(c.passed for c in report.reconciliation)}/{len(report.reconciliation)} reconciliation "
                f"checks passed; {len(report.failing_checks)} failing."
            ),
            confidence=Confidence.HIGH,
            evidence=[ev.ref()],
            metadata={"passed": report.passed, "cached": report.cached, "failing": report.failing_checks},
        )
    ]
    if report.passed:
        return StepResult(
            output=report,
            evidence=[ev],
            findings=findings,
            audit=[
                (
                    "sandbox_passed",
                    {
                        "manifest_hash": report.manifest_hash,
                        "cached": report.cached,
                        "duration_seconds": report.duration_seconds,
                    },
                )
            ],
        )

    subject = content_hash({"manifest": report.manifest_hash, "failing": report.failing_checks})
    decisions = effective_decisions(ctx.approvals, ReviewGate.TEST_FAILURES, subject)
    rejected = [k for k, d in decisions.items() if d.decision is ReviewDecision.REJECT]
    if rejected:
        raise ValidationFailed(
            "reviewer declined to waive failing sandbox checks; fix the mapping and rerun",
            checks=[k.removeprefix("test:") for k in rejected],
        )
    items = [
        ReviewItem(
            item_key=f"test:{name}",
            gate=ReviewGate.TEST_FAILURES,
            kind="test_failure",
            summary=f"Failing check {name}",
            reason_codes=["TEST_FAILED"],
            subject_hash=subject,
            evidence_ids=[ev.evidence_id],
        )
        for name in report.failing_checks
    ]
    pending = [i for i in items if i.item_key not in decisions]
    if pending:
        findings.append(
            Finding(
                code="SANDBOX_FAILED",
                title="Generated artifacts failed in the sandbox",
                statement=f"{len(report.failing_checks)} checks failed; nothing publishes unless a reviewer waives.",
                confidence=Confidence.HIGH,
                evidence=[ev.ref()],
                metadata={"failing": report.failing_checks},
            )
        )
        return StepResult(
            status="needs_review",
            output=report,
            evidence=[ev],
            findings=findings,
            gate=ReviewGate.TEST_FAILURES,
            pending_items=pending,
            subject_hash=subject,
            audit=[("sandbox_failed", {"failing": len(report.failing_checks)})],
        )
    waived = sorted(k.removeprefix("test:") for k in decisions)
    report = report.model_copy(update={"waived_checks": waived})
    return StepResult(
        output=report,
        evidence=[ev],
        findings=findings,
        subject_hash=subject,
        audit=[("sandbox_failures_waived", {"waived": waived})],
    )
