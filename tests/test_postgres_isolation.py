"""The test harness cannot reset an existing source database."""

from contextlib import contextmanager

import pytest

from scripts.postgres_test_db import disposable_database, drop_statement


@pytest.mark.parametrize("name", ["postgres", "portco", "public", "portco_test_", 'x"; DROP SCHEMA public; --'])
def test_drop_refuses_non_generated_names(name: str) -> None:
    with pytest.raises(ValueError):
        drop_statement(name)


def test_without_explicit_opt_in_no_connection_is_opened(monkeypatch) -> None:
    def fail(*args, **kwargs):
        raise AssertionError("must not connect")

    monkeypatch.setattr("scripts.postgres_test_db.create_engine", fail)
    with (
        pytest.raises(ValueError, match="ALLOW_CREATE"),
        disposable_database("postgresql://localhost/source", allow_create=False),
    ):
        pass


def test_cleanup_only_drops_the_created_database_even_on_failure(monkeypatch) -> None:
    statements = []

    class Engine:
        @contextmanager
        def connect(self):
            yield self

        def exec_driver_sql(self, sql):
            statements.append(sql)

        def dispose(self):
            pass

    monkeypatch.setattr("scripts.postgres_test_db.create_engine", lambda *a, **k: Engine())
    with pytest.raises(RuntimeError), disposable_database("postgresql://localhost/keep_me", allow_create=True) as url:
        name = url.rsplit("/", 1)[1]
        assert name.startswith("portco_test_") and name != "keep_me"
        raise RuntimeError("simulated test failure")
    assert statements == [f'CREATE DATABASE "{name}"', drop_statement(name)]
