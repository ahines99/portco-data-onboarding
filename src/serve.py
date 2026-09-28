"""Single-instance cloud entry point, with bounded HTTP work and explicit startup migration.

Deployment operators run this module; it is not exposed as an MCP capability.
"""

import os

import uvicorn
from sqlalchemy.engine import make_url

from src.fixtures.generate import ensure_fixture
from src.settings import Settings
from src.workflows.facade import migrate


def prepare_environment() -> Settings:
    # Render supplies a standard Postgres URL; SQLAlchemy needs the installed psycopg driver.
    if not os.environ.get("PORTCO_DATABASE_URL") and os.environ.get("DATABASE_URL"):
        url = make_url(os.environ["DATABASE_URL"])
        if url.drivername not in ("postgres", "postgresql", "postgresql+psycopg"):
            raise RuntimeError("deployment requires PostgreSQL")
        url = url.set(drivername="postgresql+psycopg")
        if "sslmode" not in url.query:
            url = url.update_query_dict({"sslmode": "require"})
        os.environ["PORTCO_DATABASE_URL"] = url.render_as_string(hide_password=False)
    settings = Settings()
    if settings.env != "production":
        raise RuntimeError("cloud entry point requires PORTCO_ENV=production")
    return settings


def main() -> None:
    settings = prepare_environment()
    settings.var_root.mkdir(parents=True, exist_ok=True)
    migrate(settings.db_url)
    if os.environ.get("PORTCO_SEED_SYNTHETIC") == "true":
        for fixture in ("portco_a", "portco_b"):
            ensure_fixture(fixture, settings.fixtures_dir)
    uvicorn.run(
        "src.mcp_server:app",
        host="0.0.0.0",  # noqa: S104 -- container port is served through the hosting provider's HTTPS proxy
        port=int(os.environ.get("PORT", "8000")),
        workers=1,
        limit_concurrency=32,
        timeout_keep_alive=5,
        timeout_graceful_shutdown=30,
        proxy_headers=False,
        access_log=False,
    )


if __name__ == "__main__":
    main()
