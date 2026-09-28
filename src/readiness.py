"""Minimal deployment readiness: migrated database and writable persistent storage."""

import shutil
import tempfile

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from src.settings import PROJECT_ROOT
from src.workflows.facade import OnboardingService


def check_ready(service: OnboardingService) -> bool:
    try:
        config = Config()
        config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
        expected = set(ScriptDirectory.from_config(config).get_heads())
        with service.store.engine.connect() as conn:
            actual = set(conn.execute(text("SELECT version_num FROM alembic_version")).scalars())
        if actual != expected:
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
