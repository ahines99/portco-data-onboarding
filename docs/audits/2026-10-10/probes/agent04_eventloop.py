import sys
from pathlib import Path

sys.path.insert(
    0, str(next(parent for parent in Path(__file__).resolve().parents if (parent / "pyproject.toml").is_file()))
)
(
    next(parent for parent in Path(__file__).resolve().parents if (parent / "pyproject.toml").is_file())
    / "var"
    / "audit-2026-10-10"
).mkdir(parents=True, exist_ok=True)
import asyncio
import json
import sqlite3
import tempfile
import threading
import time
from src.adapters.db import make_engine
from src.adapters.repositories import Store
from src.adapters.artifact_store import ArtifactStore


async def main(root):
    db = root / "audit.sqlite"
    engine = make_engine(f"sqlite:///{db.as_posix()}")
    store = Store(engine, ArtifactStore(root / "blobs"))
    with store.tx():
        pass
    blocker = sqlite3.connect(db, check_same_thread=False)
    blocker.execute("BEGIN IMMEDIATE")

    def release():
        blocker.rollback()

    timer = threading.Timer(0.35, release)
    timer.start()
    ticks = []

    async def heartbeat():
        for _ in range(8):
            ticks.append(time.perf_counter())
            await asyncio.sleep(0.02)

    task = asyncio.create_task(heartbeat())
    await asyncio.sleep(0.01)
    started = time.perf_counter()
    with store.tx():
        pass
    blocked = time.perf_counter() - started
    await task
    timer.join()
    blocker.close()
    engine.dispose()
    out = {
        "injected_writer_lock_seconds": 0.35,
        "sync_transaction_wait_seconds": blocked,
        "heartbeat_max_gap_seconds": max(b - a for a, b in zip(ticks, ticks[1:])),
        "method": "Actual Store.tx()/make_engine with 350 ms writer hold; async caller invokes Store.tx synchronously as current async MCP/workflow code does; synthetic contention, not a remote network measurement.",
    }
    (
        next(parent for parent in Path(__file__).resolve().parents if (parent / "pyproject.toml").is_file())
        / "var"
        / "audit-2026-10-10"
        / "agent04_eventloop.json"
    ).write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out), flush=True)


with tempfile.TemporaryDirectory(prefix="loop04-", dir=Path(__file__).parent) as td:
    asyncio.run(main(Path(td)))
