"""Record real scripted demo stdout and timing for the read-only portfolio replay.

This is an automated fixture run, not a live model session or human approval recording.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from src.settings import PROJECT_ROOT


def main() -> None:
    root = Path(tempfile.mkdtemp(prefix="pr-"))
    env = {k: v for k, v in os.environ.items() if not k.startswith("PORTCO_")}
    env.update(PORTCO_VAR_ROOT=str(root), PORTCO_ENV="test", PORTCO_LOG_LEVEL="WARNING", PYTHONUNBUFFERED="1")
    frames = []
    start = time.monotonic()
    with (root / "stderr.log").open("w", encoding="utf-8") as errors:
        proc = subprocess.Popen(
            [sys.executable, "-m", "src.cli", "demo", "--out", str(root / "demo")],
            cwd=PROJECT_ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=errors,
            text=True,
            encoding="utf-8",
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.replace(str(root), "<private-workspace>").replace(root.as_posix(), "<private-workspace>")
            frames.append({"seconds": round(time.monotonic() - start, 3), "text": line.rstrip()})
        if proc.wait() != 0:
            raise RuntimeError(f"demo failed; private diagnostics at {root}")
    out = PROJECT_ROOT / "docs/evidence"
    out.mkdir(exist_ok=True, parents=True)
    recording = {
        "label": "Actual scripted fixture demo; reviewer approvals are automated, not Alex's live decisions",
        "recorded_at": datetime.now(UTC).isoformat(),
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "duration": round(time.monotonic() - start, 3),
        "frames": frames,
    }
    (out / "demo-replay.json").write_text(json.dumps(recording, indent=2) + "\n", encoding="utf-8")
    (out / "demo-transcript.txt").write_text("\n".join(f["text"] for f in frames) + "\n", encoding="utf-8")
    print(f"Recorded {len(frames)} stdout lines in {recording['duration']} seconds; no model calls")


if __name__ == "__main__":
    main()
