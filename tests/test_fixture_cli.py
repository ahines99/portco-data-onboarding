"""Runtime fixture generation must not mutate packaged/read-only ground truth."""

from types import SimpleNamespace

import yaml
from typer.testing import CliRunner

from src.cli import app


def test_fixture_cli_preserves_ground_truth_unless_explicitly_refreshed(tmp_path, monkeypatch):
    truth_root = tmp_path / "resources"
    truth = truth_root / "portco_a" / "ground_truth.yaml"
    truth.parent.mkdir(parents=True)
    truth.write_text("sentinel: preserve-me\n", encoding="utf-8")
    runtime = tmp_path / "runtime"
    monkeypatch.setattr("src.fixtures.generate.GROUND_TRUTH_DIR", truth_root)
    monkeypatch.setattr("src.fixtures.generate.IN_CHECKOUT", True)
    monkeypatch.setattr("src.cli.get_settings", lambda: SimpleNamespace(fixtures_dir=runtime))
    runner = CliRunner()

    result = runner.invoke(app, ["fixtures", "generate", "--fixture", "a"])
    assert result.exit_code == 0, result.output
    assert (runtime / "portco_a.duckdb").is_file()
    assert truth.read_text(encoding="utf-8") == "sentinel: preserve-me\n"

    result = runner.invoke(app, ["fixtures", "generate", "--fixture", "a", "--refresh-ground-truth"])
    assert result.exit_code == 0, result.output
    document = yaml.safe_load(truth.read_text(encoding="utf-8"))
    assert document["fixture"] == "portco_a"
    assert document["content_digest"]
    assert "sentinel" not in document
