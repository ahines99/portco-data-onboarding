"""Bounded audit microbenchmarks; no production data, no tracked edits."""

import sys
from pathlib import Path

ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / "pyproject.toml").is_file())
sys.path.insert(0, str(ROOT))
import csv
import hashlib
import json
import platform
import statistics
import tempfile
import time
import tracemalloc
from datetime import date
from decimal import Decimal

import duckdb
from src.adapters.csv_source import import_csv
from src.adapters.external import DuckDBAdapter
from src.domain.project_models import ConnectionSpec
from src.services import pii
from src.services.sandbox import SourceRows

OUT = ROOT / "var" / "audit-2026-10-10"
OUT.mkdir(parents=True, exist_ok=True)
result = {
    "platform": platform.platform(),
    "python": platform.python_version(),
    "duckdb": duckdb.__version__,
    "caveat": "Shared host concurrent repo test/eval work; small synthetic in-cache mechanisms, not production or remote DB performance.",
}


def timed(fn):
    t = time.perf_counter()
    value = fn()
    return time.perf_counter() - t, value


with tempfile.TemporaryDirectory(prefix="perf04-", dir=OUT) as td:
    root = Path(td)
    result["insert_kernels"] = []
    for n in (5000, 20000):
        rows = [(i, f"item-{i}", date(2026, 1, 1), Decimal("12.34")) for i in range(n)]
        for kind in ("executemany", "column_unnest"):
            times = []
            for repeat in range(2):
                con = duckdb.connect(config={"enable_external_access": "false", "threads": "1"})
                con.execute("CREATE TABLE x(i BIGINT,s VARCHAR,d DATE,a DECIMAL(12,2))")

                def run():
                    con.execute("BEGIN")
                    for offset in range(0, n, 1000):
                        batch = rows[offset : offset + 1000]
                        if kind == "executemany":
                            con.executemany("INSERT INTO x VALUES (?,?,?,?)", batch)
                        else:
                            columns = [list(v) for v in zip(*batch)]
                            con.execute(
                                "INSERT INTO x SELECT unnest(?::BIGINT[]), unnest(?::VARCHAR[]), unnest(?::DATE[]), unnest(?::DECIMAL(12,2)[])",
                                columns,
                            )
                    con.execute("COMMIT")

                elapsed, _ = timed(run)
                checksum = con.execute("SELECT count(*), sum(i), sum(a) FROM x").fetchone()
                assert checksum == (n, n * (n - 1) // 2, Decimal("12.34") * n)
                times.append(elapsed)
                con.close()
            result["insert_kernels"].append({"rows": n, "kind": kind, "seconds": times})
            print(json.dumps(result["insert_kernels"][-1]), flush=True)
    extract = root / "extract"
    extract.mkdir()
    with (extract / "data.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "label", "day", "amount"])
        writer.writerows((i, f"item-{i}", "2026-01-01", "12.34") for i in range(20000))
    manifest = {
        "source_id": "audit_perf",
        "company_id": "audit_perf",
        "as_of": "2026-01-01",
        "tables": [
            {
                "schema_name": "erp",
                "table_name": "items",
                "file": "data.csv",
                "columns": {"id": "BIGINT", "label": "VARCHAR", "day": "DATE", "amount": "DECIMAL(12,2)"},
            }
        ],
    }
    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    elapsed, receipt = timed(lambda: import_csv(manifest_path, extract, root / "sources"))
    result["real_csv_import"] = {
        "rows": 20000,
        "csv_bytes": (extract / "data.csv").stat().st_size,
        "seconds": elapsed,
        "snapshot_bytes": (root / "sources/audit_perf/source.duckdb").stat().st_size,
    }
    print(json.dumps(result["real_csv_import"]), flush=True)

    db = root / "profile.duckdb"
    with duckdb.connect(str(db), config={"threads": "1"}) as c:
        c.execute("CREATE SCHEMA erp")
        expr = ",".join(f"'item-' || CAST(i+{j} AS VARCHAR) AS label{j}" for j in range(8))
        c.execute(f"CREATE TABLE erp.items AS SELECT {expr} FROM range(50000) t(i)")
    adapter = DuckDBAdapter(
        ConnectionSpec(connection_id="audit", company_id="audit_perf", path=str(db), schemas=["erp"])
    )
    adapter.con.execute("SET threads=1")
    adapter.describe_table("erp", "items")
    params = [pattern[0] for j in range(8) for pattern in pii.PATTERNS.values()]
    exprs = [
        f"count(*) FILTER (WHERE {'regexp_full_match' if full else 'regexp_matches'}(label{j}, ?)) AS p{j}_{i}"
        for j in range(8)
        for i, (_, full) in enumerate(pii.PATTERNS.values())
    ]

    def separate():
        return [adapter.pattern_counts("erp", "items", f"label{j}", pii.PATTERNS) for j in range(8)]

    def combined():
        return adapter._query(f"SELECT {','.join(exprs)} FROM erp.items", params)[0]

    separate()
    combined()
    profile_times = {"rows": 50000, "string_columns": 8, "patterns_each": len(pii.PATTERNS)}
    for name, fn in (("separate", separate), ("combined", combined)):
        query_start = adapter.query_count
        runs = [timed(fn) for _ in range(3)]
        profile_times[name] = {"seconds": [r[0] for r in runs], "queries": adapter.query_count - query_start}
        if name == "separate":
            expected = tuple(v for counts in runs[0][1] for v in counts.values())
        else:
            assert runs[0][1] == expected
    result["pattern_scan"] = profile_times
    adapter.close()
    print(json.dumps(profile_times), flush=True)

    src = SourceRows(db, None)
    tracemalloc.start()
    elapsed, values = timed(lambda: src._cols("erp.items", [f"label{j}" for j in range(8)]))
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    result["python_reconciliation_rows"] = {
        "rows": len(values),
        "columns": 8,
        "seconds_with_tracemalloc": elapsed,
        "current_python_bytes": current,
        "peak_python_bytes": peak,
        "note": "Tracemalloc excludes native DuckDB memory and adds timing overhead.",
    }
    del values
    src.close()
    print(json.dumps(result["python_reconciliation_rows"]), flush=True)
    hash_path = root / "hash.bin"
    with hash_path.open("wb") as f:
        for _ in range(32):
            f.write(b"x" * (1024 * 1024))

    def digest():
        with hash_path.open("rb") as f:
            return hashlib.file_digest(f, "sha256").hexdigest()

    result["file_hash"] = {"bytes": hash_path.stat().st_size, "seconds": [timed(digest)[0] for _ in range(3)]}
    print(json.dumps(result["file_hash"]), flush=True)

(OUT / "agent04_benchmark.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
