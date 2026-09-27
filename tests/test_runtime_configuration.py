from pathlib import Path

from src.settings import PROJECT_ROOT, Settings
from src.workflows.versioning import configuration_fingerprint, pipeline_version


def test_example_environment_is_valid() -> None:
    settings = Settings(_env_file=PROJECT_ROOT / ".env.example")
    assert settings.step_timeout_seconds > settings.dbt_timeout_seconds + 60


def test_pipeline_version_covers_adapter_settings_and_lock(tmp_path: Path) -> None:
    for relative in ("src/adapters/source.py", "src/settings.py", "uv.lock"):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        before = pipeline_version.__wrapped__(tmp_path)
        target.write_text("changed", encoding="utf-8")
        assert pipeline_version.__wrapped__(tmp_path) != before


def test_configuration_version_tracks_semantics_without_credentials(tmp_path: Path) -> None:
    base = Settings(_env_file=None, var_root=tmp_path)
    initial = configuration_fingerprint(base)
    assert configuration_fingerprint(base.model_copy(update={"llm_enabled": True})) != initial
    assert configuration_fingerprint(base.model_copy(update={"fiscal_year_start_month": 3})) != initial
    assert configuration_fingerprint(base.model_copy(update={"approval_ttl_hours": 1})) != initial
    assert configuration_fingerprint(base.model_copy(update={"var_root": tmp_path / "elsewhere"})) == initial
    other = Settings(_env_file=None, var_root=tmp_path, anthropic_api_key="secret", http_tokens="secret")
    assert configuration_fingerprint(other) == initial


def test_replay_cache_content_changes_configuration_version(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, var_root=tmp_path, llm_enabled=True)
    before = configuration_fingerprint(settings)
    settings.llm_cassette_dir.mkdir(parents=True)
    cassette = settings.llm_cassette_dir / "response.json"
    cassette.write_text('{"choice":"ABSTAIN"}', encoding="utf-8")
    assert configuration_fingerprint(settings) != before


def test_engine_invalidates_reuse_when_connection_policy_changes(service) -> None:
    spec = service.connections.resolve("fixture:portco_a")
    with service.store.tx() as tx:
        run = tx.runs.create(company_id=spec.company_id, connection_id=spec.connection_id, requested_by="agent")
    step = service.engine.steps[0]
    original = service.engine.input_hash(step, {}, run)
    service.connections.register(spec.model_copy(update={"schemas": ["billing"], "category_domains": {}}))
    assert service.engine.input_hash(step, {}, run) != original
