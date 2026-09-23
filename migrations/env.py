"""Alembic environment. The URL comes from PORTCO_DATABASE_URL / settings unless set on the config."""

from __future__ import annotations

from alembic import context
from sqlalchemy import engine_from_config, pool

from src.adapters.db import metadata
from src.settings import get_settings

config = context.config
if (
    not config.get_main_option("sqlalchemy.url")
    or config.get_main_option("sqlalchemy.url") == "sqlite:///var/portco.db"
):
    config.set_main_option("sqlalchemy.url", get_settings().db_url)
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
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
