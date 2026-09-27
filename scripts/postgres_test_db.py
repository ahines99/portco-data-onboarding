"""Allocate a disposable PostgreSQL database; never reset the caller's database."""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url


def drop_statement(name: str) -> str:
    if not re.fullmatch(r"portco_test_[0-9a-f]{32}", name):
        raise ValueError("refusing to drop a database outside the generated test namespace")
    return f'DROP DATABASE "{name}" WITH (FORCE)'


@contextmanager
def disposable_database(admin_url: str, *, allow_create: bool) -> Iterator[str]:
    if not allow_create:
        raise ValueError("set PORTCO_TEST_POSTGRES_ALLOW_CREATE=1 to allocate an isolated test database")
    url = make_url(admin_url)
    if url.get_backend_name() != "postgresql":
        raise ValueError("PostgreSQL administrative connection required")
    name = f"portco_test_{uuid4().hex}"
    engine = create_engine(url, isolation_level="AUTOCOMMIT")
    created = False
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql(f'CREATE DATABASE "{name}"')
            created = True
        yield url.set(database=name).render_as_string(hide_password=False)
    finally:
        try:
            if created:
                with engine.connect() as conn:
                    conn.exec_driver_sql(drop_statement(name))
        finally:
            engine.dispose()
