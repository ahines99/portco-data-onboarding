"""Minimal deployment readiness: migrated database and writable persistent storage.

The probe is bounded (audit DEL-02). PostgreSQL is checked on its own unpooled connection with a connect
timeout and transaction-local statement/lock timeouts inside `READINESS_BUDGET_S`, so a stalled database or
an exclusive schema lock turns into "not ready" instead of a thread blocked indefinitely. At most one check
runs at a time: a probe that arrives while another is in flight gets the last fresh answer (or "not ready")
instead of queueing more database work behind it.
"""

from __future__ import annotations

import shutil
import tempfile
import threading
import time
import weakref
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine import Engine

from src.adapters.db import make_probe_engine, set_session_deadlines
from src.settings import PROJECT_ROOT
from src.workflows.facade import OnboardingService

_CONNECT_BUDGET_S = 2  # libpq's minimum effective connect_timeout
_QUERY_BUDGET_MS = 2_000  # statement and lock timeout for the readiness transaction
# Worst-case database time of one probe (connect + query); Render requires an answer within 5 s.
READINESS_BUDGET_S = _CONNECT_BUDGET_S + _QUERY_BUDGET_MS / 1000

_inflight = threading.Lock()
_last: tuple[Any, float, bool] | None = None  # (weakref to the service, monotonic time, result)
_probe_engines: dict[str, Engine] = {}
_engines_lock = threading.Lock()


def _probe_engine(service: OnboardingService) -> Engine:
    engine = service.store.engine
    if engine.dialect.name == "sqlite":  # in-process file (or memory) database: no network, no server locks
        return engine
    key = engine.url.render_as_string(hide_password=False)
    with _engines_lock:
        if key not in _probe_engines:
            _probe_engines[key] = make_probe_engine(key, connect_timeout_s=_CONNECT_BUDGET_S)
        return _probe_engines[key]


def _schema_current(service: OnboardingService) -> bool:
    config = Config()
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    expected = set(ScriptDirectory.from_config(config).get_heads())
    with _probe_engine(service).connect() as conn, conn.begin():
        set_session_deadlines(conn, statement_ms=_QUERY_BUDGET_MS, lock_ms=_QUERY_BUDGET_MS, local=True)
        actual = set(conn.execute(text("SELECT version_num FROM alembic_version")).scalars())
    return actual == expected


def _check(service: OnboardingService) -> bool:
    try:
        if not _schema_current(service):
            return False
        root = service.settings.var_root
        if shutil.disk_usage(root).free < 100 * 1024 * 1024:
            return False
        with tempfile.TemporaryFile(dir=root) as probe:
            probe.write(b"ready")
            probe.flush()
        return True
    except Exception:
        return False


def check_ready(service: OnboardingService) -> bool:
    global _last
    if not _inflight.acquire(blocking=False):
        last = _last
        fresh = last is not None and last[0]() is service and time.monotonic() - last[1] <= READINESS_BUDGET_S
        return bool(fresh and last is not None and last[2])
    try:
        result = _check(service)
        _last = (weakref.ref(service), time.monotonic(), result)
        return result
    finally:
        _inflight.release()
