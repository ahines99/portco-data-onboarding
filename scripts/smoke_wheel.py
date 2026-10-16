"""Build/install the wheel with locked dependencies, then run it outside the checkout.

Usage: python scripts/smoke_wheel.py [--offline]
All environments and outputs are isolated in a temporary directory.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path


def verify_distribution_hygiene(dist: Path) -> None:
    """Inspect both published formats, including builds made without a Git checkout."""
    source = next(dist.glob("*.tar.gz"))
    wheel = next(dist.glob("*.whl"))
    with tarfile.open(source) as archive:
        source_names = archive.getnames()
    with zipfile.ZipFile(wheel) as archive:
        wheel_names = archive.namelist()
    for artifact, names in ((source, source_names), (wheel, wheel_names)):
        leaked = [name for name in names if ".config" in Path(name).parts]
        if leaked:
            raise RuntimeError(f"Machine-local configuration included in {artifact.name}: {leaked}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    uv_exe = shutil.which("uv")
    uv = [uv_exe] if uv_exe else [shutil.which("python") or sys.executable, "-m", "uv"]
    offline = ["--offline"] if args.offline else []
    # Leave diagnostic artifacts on failure; no source state is modified.
    root = Path(tempfile.mkdtemp(prefix="pw-"))
    print(f"Wheel smoke workspace: {root}", flush=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith("PORTCO_") and k != "PYTHONPATH"}
    env.update(PORTCO_ENV="test", PORTCO_LOG_LEVEL="WARNING", PORTCO_VAR_ROOT=str(root / "v"))
    venv = root / "env"
    env["UV_PROJECT_ENVIRONMENT"] = str(venv)

    def run(command: list[str], cwd: Path = repo) -> None:
        subprocess.run(command, cwd=cwd, env=env, check=True)

    run([*uv, "build", "--out-dir", str(root / "dist"), *offline])
    # uv build without --wheel builds the wheel from the sdist, checking both distributions.
    verify_distribution_hygiene(root / "dist")
    run([*uv, "sync", "--frozen", "--no-dev", "--no-install-project", *offline])
    python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    wheel = next((root / "dist").glob("*.whl"))
    run([*uv, "pip", "install", "--python", str(python), "--no-deps", str(wheel), *offline])
    outside = root / "outside"
    outside.mkdir()
    run([str(python), "-c", "from src.paths import IN_CHECKOUT; assert not IN_CHECKOUT"], outside)
    run([str(python), "-c", "import importlib.util; assert importlib.util.find_spec('pytest') is None"], outside)
    run([str(python), "-m", "src.cli", "fixtures", "generate", "--fixture", "a"], outside)
    run([str(python), "-m", "src.cli", "demo"], outside)
    # Minimal installed stdio MCP, with no project or test imports supplied by the checkout.
    entry = venv / ("Scripts/portco-mcp.exe" if os.name == "nt" else "bin/portco-mcp")
    code = """
import asyncio, sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
async def main():
    async with stdio_client(StdioServerParameters(command=sys.argv[1])) as streams:
        async with ClientSession(*streams) as session:
            await session.initialize()
            result = await session.call_tool('healthcheck', {})
            assert not result.is_error
            assert result.structured_content['database'] == 'ok'
asyncio.run(main())
"""
    run([str(python), "-c", code, str(entry)], outside)
    print("PASS: installed wheel, fixture generation, and all demo paths outside the checkout", flush=True)


if __name__ == "__main__":
    main()
