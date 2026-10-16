"""Alembic environment. The URL comes from PORTCO_DATABASE_URL / settings unless set on the config.

Every entry point (`alembic ...`, `poe migrate`, `facade.migrate`, the cloud launcher) runs through here:
- the URL is `%`-escaped before it enters Alembic's ConfigParser (percent-encoded passwords, `%` paths);
- the migration session has explicit connect, lock and statement deadlines (PostgreSQL), applied to
  this session only;
- a failure whose traceback would echo the URL's credentials is re-raised with them removed.
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import engine_from_config, pool

from src.adapters.db import (
    MIGRATION_LOCK_TIMEOUT_MS,
    MIGRATION_STATEMENT_TIMEOUT_MS,
    escape_alembic_url,
    metadata,
    migration_connect_args,
    redact_db_error,
    set_session_deadlines,
)
from src.settings import get_settings


class MigrationError(RuntimeError):
    """A migration failure, described without the database credentials."""


config = context.config
if (
    not config.get_main_option("sqlalchemy.url")
    or config.get_main_option("sqlalchemy.url") == "sqlite:///var/portco.db"
):
    config.set_main_option("sqlalchemy.url", escape_alembic_url(get_settings().db_url))
target_metadata = metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = config.get_main_option("sqlalchemy.url") or ""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args=migration_connect_args(url),
    )
    with connectable.connect() as connection:
        # Session-level (the NullPool connection is discarded afterwards) and committed, so the deadlines
        # survive into Alembic's own transaction(s), whatever the transaction-per-migration setting.
        set_session_deadlines(
            connection, statement_ms=MIGRATION_STATEMENT_TIMEOUT_MS, lock_ms=MIGRATION_LOCK_TIMEOUT_MS
        )
        connection.commit()
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


def _run() -> None:
    try:
        if context.is_offline_mode():
            run_migrations_offline()
        else:
            run_migrations_online()
    except Exception as exc:
        safe = redact_db_error(exc, config.get_main_option("sqlalchemy.url") or "")
        if safe is None:
            raise
        raise MigrationError(safe) from None  # `from None`: the chained original would echo the secret


_run()
