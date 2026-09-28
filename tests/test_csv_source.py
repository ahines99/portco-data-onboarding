"""Operator ingestion, snapshot integrity, tenant and error boundaries."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path

import anyio
import duckdb
import pytest
from typer.testing import CliRunner

from src.adapters.csv_source import import_csv, resolve_csv
from src.adapters.external import ConnectionRegistry
from src.cli import app
from src.domain.errors import Conflict, Forbidden, ValidationFailed
from src.domain.models import Principal, Role
from tests.conftest import make_service


def write_input(tmp_path: Path, **updates: object) -> Path:
    doc = {
        "source_id": "extract-v1",
        "company_id": "external_co",
        "as_of": "2025-12-31",
        "tables": [
            {
                "schema_name": "billing",
                "table_name": "invoices",
                "file": "invoices.csv",
                "columns": {"id": "VARCHAR", "amount": "DECIMAL(18,2)", "due": "DATE"},
            }
        ],
    }
    doc.update(updates)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(doc), encoding="utf-8")
    (tmp_path / "invoices.csv").write_text(
        "id,amount,due\n001,1234567890123456.78,2025-12-31\n002,\\N,\\N\n", encoding="utf-8"
    )
    return manifest


def test_import_exact_values_restart_readonly_and_immutable(tmp_path: Path) -> None:
    manifest = write_input(tmp_path)
    store = tmp_path / "sources"
    receipt = import_csv(manifest, tmp_path, store)
    assert receipt["inputs"][0]["rows"] == 2
    spec = resolve_csv("csv:extract-v1", store)
    with duckdb.connect(spec.path, read_only=True) as con:
        assert con.execute("select id, amount from billing.invoices order by id").fetchall() == [
            ("001", Decimal("1234567890123456.78")),
            ("002", None),
        ]
    adapter = ConnectionRegistry(tmp_path / "fixtures", store).open("csv:extract-v1")
    assert adapter.verify_read_only()
    adapter.close()
    (tmp_path / "invoices.csv").write_text("changed upstream", encoding="utf-8")
    assert resolve_csv("csv:extract-v1", store) == spec
    with pytest.raises(Conflict):
        import_csv(manifest, tmp_path, store)
    with Path(spec.path).open("ab") as stream:
        stream.write(b"tampered")
    with pytest.raises(ValidationFailed, match="integrity"):
        resolve_csv("csv:extract-v1", store)


@pytest.mark.parametrize(
    "path", ["../secret.csv", "C:/secret.csv", "//host/share/a.csv", "a/../invoices.csv", "a\\x.csv"]
)
def test_import_rejects_path_escape(tmp_path: Path, path: str) -> None:
    manifest = write_input(tmp_path)
    doc = json.loads(manifest.read_text())
    doc["tables"][0]["file"] = path
    manifest.write_text(json.dumps(doc))
    with pytest.raises(ValidationFailed):
        import_csv(manifest, tmp_path, tmp_path / "sources")
    assert not list((tmp_path / "sources").iterdir())


@pytest.mark.parametrize("value", ["1.001", "NaN", "Infinity", "10000000000000000.00", "email@example.test"])
def test_no_rounding_overflow_or_sensitive_diagnostics(tmp_path: Path, value: str) -> None:
    manifest = write_input(tmp_path)
    (tmp_path / "invoices.csv").write_text(f"id,amount,due\n001,{value},2025-12-31\n", encoding="utf-8")
    with pytest.raises(ValidationFailed) as exc:
        import_csv(manifest, tmp_path, tmp_path / "sources")
    assert value not in str(exc.value)
    assert not list((tmp_path / "sources").iterdir())


def test_invalid_header_and_manifest_do_not_register(tmp_path: Path) -> None:
    manifest = write_input(tmp_path)
    (tmp_path / "invoices.csv").write_text("id,amount,unexpected\n", encoding="utf-8")
    with pytest.raises(ValidationFailed, match="header"):
        import_csv(manifest, tmp_path, tmp_path / "sources")
    manifest.write_text('{"password":"private-value"}')
    with pytest.raises(ValidationFailed) as exc:
        import_csv(manifest, tmp_path, tmp_path / "sources")
    assert "private-value" not in str(exc.value)


def test_tenant_scope_and_cli_restart(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = write_input(tmp_path)
    runtime = tmp_path / "runtime"
    from src.settings import Settings

    monkeypatch.setattr("src.cli.get_settings", lambda: Settings(env="test", var_root=runtime))
    result = CliRunner().invoke(app, ["sources", "import-csv", str(manifest), "--root", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["connection_id"] == "csv:extract-v1"
    service = make_service(runtime)
    intruder = Principal(principal_id="other", role=Role.AGENT, company_ids=("other_co",))
    with pytest.raises(Forbidden):
        anyio.run(lambda: service.start_run(intruder, "csv:extract-v1"))


def test_symlink_input_rejected(tmp_path: Path) -> None:
    manifest = write_input(tmp_path)
    path = tmp_path / "invoices.csv"
    target = tmp_path / "original.csv"
    path.rename(target)
    try:
        path.symlink_to(target)
    except OSError:
        pytest.skip("OS account cannot create symbolic links")
    with pytest.raises(ValidationFailed, match="links"):
        import_csv(manifest, tmp_path, tmp_path / "sources")


def test_csv_limits_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = write_input(tmp_path)
    monkeypatch.setattr("src.adapters.csv_source.MAX_ROWS", 1)
    with pytest.raises(ValidationFailed, match="row limit"):
        import_csv(manifest, tmp_path, tmp_path / "sources")
    monkeypatch.setattr("src.adapters.csv_source.MAX_BYTES", 10)
    with pytest.raises(ValidationFailed, match="byte limit"):
        import_csv(manifest, tmp_path, tmp_path / "sources")


@pytest.mark.parametrize("dtype", ["DOUBLE", "DECIMAL(39,2)", "DECIMAL(4,5)", "VARCHAR); DROP TABLE x; --"])
def test_rejects_unsafe_or_lossy_declared_types(tmp_path: Path, dtype: str) -> None:
    manifest = write_input(tmp_path)
    doc = json.loads(manifest.read_text())
    doc["tables"][0]["columns"]["amount"] = dtype
    manifest.write_text(json.dumps(doc))
    with pytest.raises(ValidationFailed):
        import_csv(manifest, tmp_path, tmp_path / "sources")
    assert not (tmp_path / "sources" / "extract-v1").exists()


def test_competing_imports_do_not_overwrite_registration(tmp_path: Path) -> None:
    manifest = write_input(tmp_path)
    store = tmp_path / "sources"

    def attempt() -> str:
        try:
            import_csv(manifest, tmp_path, store)
        except Conflict:
            return "conflict"
        return "registered"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: attempt(), range(2)))
    assert sorted(outcomes) == ["conflict", "registered"]
    assert resolve_csv("csv:extract-v1", store).company_id == "external_co"
    assert [p.name for p in store.iterdir()] == ["extract-v1"]


@pytest.mark.integration
@pytest.mark.slow
def test_imported_csv_publishes_after_restart_and_separate_reviews(tmp_path: Path) -> None:
    from scripts.smoke_csv_source import exercise

    result = anyio.run(exercise, tmp_path)
    assert result["status"] == "complete"
    assert result["input_tables"] > 1
    assert result["publication"]
    summary = result["shareable_summary"]
    assert summary["test_report_passed"] and summary["audit_chain_valid"]
    assert len(summary["published_metrics"]) == 9
    assert summary["generated_file_hashes_verified"] == summary["published_file_count"] - 1
    assert summary["audit_event_count"] > 0
    assert all(check["passed"] for check in summary["reconciliation"])
    assert str(tmp_path) not in json.dumps(summary)
