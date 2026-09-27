"""Exercise the deployment probe against the authenticated MCP app locally."""

from pathlib import Path

import httpx2
import pytest
from pydantic import SecretStr

from scripts.smoke_container import check
from src.mcp_server import build_server
from tests.conftest import make_service, make_settings


@pytest.mark.anyio
async def test_container_probe_checks_auth_and_persisted_run(tmp_path: Path, fixtures_dir: Path, monkeypatch) -> None:
    settings = make_settings(
        tmp_path, http_tokens=SecretStr("probe=agent:smoke:agent:portco_a"), http_base_url="http://localhost:8000"
    )
    app = build_server(settings, service=make_service(tmp_path), with_auth=True).streamable_http_app()
    original_client = httpx2.AsyncClient

    def client(**kwargs):
        return original_client(transport=httpx2.ASGITransport(app=app), **kwargs)

    monkeypatch.setattr(httpx2, "AsyncClient", client)
    async with app.router.lifespan_context(app):
        before = await check("http://localhost:8000", "probe")
        after = await check("http://localhost:8000", "probe", before["run_id"])
    assert before["gate"] == "mapping_review"
    assert after == before
