"""Prepare a bounded, attributed UCI operational-data extract and verify CSV profiling.

Raw downloads/extracts remain local. No reviewer decisions or publication are performed.
The fixed archive checksum intentionally requires review before a changed upstream file is used.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import subprocess
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any

import anyio
import duckdb

from src.domain.models import Principal, Role, StepName
from src.settings import Settings
from src.workflows.facade import OnboardingService

SOURCE_URL = "https://archive.ics.uci.edu/static/public/352/online%2Bretail.zip"
SOURCE_PAGE = "https://archive.ics.uci.edu/dataset/352/online+retail"
SOURCE_SHA256 = "f5385cbb54bbebf7196389109c6b0621faab0c304e3702548165e71c84aede8b"
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
COLUMNS = {
    "InvoiceNo": "VARCHAR",
    "StockCode": "VARCHAR",
    "Quantity": "INTEGER",
    "InvoiceDate": "TIMESTAMP",
    "UnitPrice": "DECIMAL(38,18)",
    "CustomerID": "VARCHAR",
    "IsCancellation": "BOOLEAN",
    "Currency": "VARCHAR",
}


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def download(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # This is a fixed public source, never a URL supplied by a source manifest or model.
    with urllib.request.urlopen(SOURCE_URL, timeout=60) as response, path.open("xb") as out:
        total = 0
        while chunk := response.read(1024 * 1024):
            total += len(chunk)
            if total > 40 * 1024 * 1024:
                raise ValueError("public archive exceeds the download limit")
            out.write(chunk)


def pseudonym(value: str, namespace: str) -> str:
    if not value:
        return ""
    return hashlib.sha256(f"uci352:{namespace}:{value}".encode()).hexdigest()


def prepare(archive: Path, out: Path, limit: int) -> dict[str, Any]:
    if not 1 <= limit <= 50_000:
        raise ValueError("row limit must be between 1 and 50000")
    if archive.stat().st_size > 40 * 1024 * 1024 or digest(archive) != SOURCE_SHA256:
        raise ValueError("public archive checksum does not match the reviewed source")
    out.mkdir(parents=True, exist_ok=False)
    stats: dict[str, Any] = {
        "rows": 0,
        "cancellations": 0,
        "negative_quantities": 0,
        "nonpositive_unit_prices": 0,
        "missing_customer_ids": 0,
    }
    amount = Decimal(0)
    dates: list[datetime] = []
    with zipfile.ZipFile(archive) as outer:
        if outer.getinfo("Online Retail.xlsx").file_size > 30 * 1024 * 1024:
            raise ValueError("workbook exceeds the reviewed size boundary")
        with zipfile.ZipFile(io.BytesIO(outer.read("Online Retail.xlsx"))) as workbook:
            if workbook.getinfo("xl/sharedStrings.xml").file_size > 1024 * 1024:
                raise ValueError("shared strings exceed the reviewed size boundary")
            strings = [
                "".join(element.itertext())
                for element in ET.fromstring(workbook.read("xl/sharedStrings.xml")).findall(f"{NS}si")  # noqa: S314
            ]
            if workbook.getinfo("xl/worksheets/sheet1.xml").file_size > 250 * 1024 * 1024:
                raise ValueError("worksheet exceeds the reviewed size boundary")
            # XML is parsed only after exact archive SHA-256 verification above.
            with (
                workbook.open("xl/worksheets/sheet1.xml") as sheet,
                (out / "transactions.csv").open("w", encoding="utf-8", newline="") as stream,
            ):
                writer = csv.DictWriter(stream, fieldnames=list(COLUMNS))
                writer.writeheader()
                for _, element in ET.iterparse(sheet, events=("end",)):  # noqa: S314
                    if element.tag != f"{NS}row":
                        continue
                    values = {}
                    for cell in element.findall(f"{NS}c"):
                        column = "".join(c for c in cell.attrib["r"] if c.isalpha())
                        raw = cell.findtext(f"{NS}v", "")
                        values[column] = strings[int(raw)] if cell.attrib.get("t") == "s" and raw else raw
                    element.clear()
                    if not stats["rows"] and values.get("A") == "InvoiceNo":
                        if [values.get(c) for c in "ABCDEFGH"] != [
                            "InvoiceNo",
                            "StockCode",
                            "Description",
                            "Quantity",
                            "InvoiceDate",
                            "UnitPrice",
                            "CustomerID",
                            "Country",
                        ]:
                            raise ValueError("public workbook header changed")
                        continue
                    invoice = values.get("A", "")
                    quantity = int(values["D"])
                    price = Decimal(values["F"])
                    when = datetime(1899, 12, 30) + timedelta(days=float(values["E"]))
                    when = when.replace(microsecond=0)
                    customer = values.get("G", "")
                    cancelled = invoice.upper().startswith("C")
                    writer.writerow(
                        {
                            "InvoiceNo": pseudonym(invoice, "invoice"),
                            "StockCode": pseudonym(values.get("B", ""), "product"),
                            "Quantity": quantity,
                            "InvoiceDate": when.isoformat(sep=" "),
                            "UnitPrice": str(price),
                            "CustomerID": pseudonym(customer, "customer") if customer else "\\N",
                            "IsCancellation": str(cancelled).lower(),
                            "Currency": "GBP",
                        }
                    )
                    stats["rows"] += 1
                    stats["cancellations"] += int(cancelled)
                    stats["negative_quantities"] += int(quantity < 0)
                    stats["nonpositive_unit_prices"] += int(price <= 0)
                    stats["missing_customer_ids"] += int(not customer)
                    with localcontext() as ctx:
                        ctx.prec = 60
                        amount += quantity * price
                    dates.append(when)
                    if stats["rows"] == limit:
                        break
    if not stats["rows"]:
        raise ValueError("public extract is empty")
    stats.update(
        {
            "first_timestamp": min(dates).isoformat(),
            "last_timestamp": max(dates).isoformat(),
            "quantity_times_unit_price_sum_gbp": str(amount),
        }
    )
    manifest = {
        "source_id": f"uci_retail_{limit}",
        "company_id": "uci_retail",
        "as_of": max(dates).date().isoformat(),
        "tables": [
            {"schema_name": "retail", "table_name": "transactions", "file": "transactions.csv", "columns": COLUMNS}
        ],
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return stats


async def probe(archive: Path, out: Path, state: Path, limit: int) -> dict[str, Any]:
    from src.adapters.csv_source import import_csv

    stats = prepare(archive, out, limit)
    settings = Settings(_env_file=None, var_root=state.resolve(), env="test", log_level="WARNING")
    receipt = import_csv(out / "manifest.json", out, settings.var_root / "sources")
    svc = OnboardingService.build(settings)
    principal = Principal(principal_id="agent:public-retail", role=Role.AGENT, company_ids=("uci_retail",))
    spec = svc.connections.resolve(receipt["connection_id"])
    with duckdb.connect(spec.path, read_only=True) as connection:
        totals = connection.execute(
            'SELECT COUNT(*), SUM("Quantity" * "UnitPrice"), '
            'COUNT(*) FILTER (WHERE "CustomerID" IS NULL), '
            'COUNT(*) FILTER (WHERE "IsCancellation"), '
            'COUNT(*) FILTER (WHERE "Quantity" < 0) FROM retail.transactions'
        ).fetchone()
    if totals is None or (
        totals[0] != stats["rows"]
        or totals[1] != Decimal(stats["quantity_times_unit_price_sum_gbp"])
        or totals[2] != stats["missing_customer_ids"]
        or totals[3] != stats["cancellations"]
        or totals[4] != stats["negative_quantities"]
    ):
        raise ValueError("imported aggregate control totals differ from the prepared extract")
    run = await svc.start_run(principal, receipt["connection_id"], stop_after=StepName.SCHEMA_PROFILING)
    profile = svc.artifact(principal, run.run_id, StepName.SCHEMA_PROFILING)
    profile_data = profile.model_dump(mode="json")
    if len(profile.tables) != 1 or profile.tables[0].row_count != stats["rows"]:
        raise ValueError("profile row count differs from the prepared extract")
    # Only aggregate counts and provenance are published, never the raw extract or profile values.
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "worktree_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], text=True).strip()),
        "implementation_sha256": {
            path: digest(Path(path)) for path in ("scripts/public_retail_probe.py", "src/adapters/csv_source.py")
        },
        "source": {
            "url": SOURCE_URL,
            "page": SOURCE_PAGE,
            "archive_sha256": digest(archive),
            "citation": "Chen, D. (2015). Online Retail. UCI Machine Learning Repository. DOI:10.24432/C5BW33",
            "license": "CC BY 4.0",
            "license_url": "https://creativecommons.org/licenses/by/4.0/",
        },
        "selection": f"First {limit} transaction rows in source worksheet order; not random or representative.",
        "adaptation": (
            "Drop Description/Country; hash invoice/product/customer IDs with a public namespace; "
            "retain missing IDs and all negative/cancelled/zero-price records; "
            "add cancellation flag and documented GBP currency."
        ),
        "privacy_limit": (
            "Deterministic hashes are pseudonyms, not a guarantee of anonymization; "
            "public IDs can be guessed. Raw inputs remain local."
        ),
        "extract_sha256": digest(out / "transactions.csv"),
        "manifest_sha256": digest(out / "manifest.json"),
        "import_control_checks": {
            "row_count": True,
            "exact_quantity_price_sum": True,
            "missing_customer_count": True,
            "cancellation_count": True,
            "negative_quantity_count": True,
            "profile_row_count": True,
        },
        "observed_extract": stats,
        "workflow": {
            "connection_id": receipt["connection_id"],
            "status": run.status.value,
            "stop_after": "schema_profiling",
            "profile_table_count": len(profile_data.get("tables", [])),
            "approved": False,
            "published": False,
        },
        "limitations": (
            "Public historical retail data, not a participating portfolio company or independently labeled "
            "financial benchmark. Quantity-times-price is an extract control sum, not recognized revenue. "
            "No mapping, certified metrics, adoption, time saving or business impact is established."
        ),
    }
    svc.store.engine.dispose()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=Path("var/public-data/online-retail.zip"))
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--out", type=Path, required=True, help="New local extract directory")
    parser.add_argument("--state", type=Path, required=True, help="Isolated runtime state directory")
    parser.add_argument("--rows", type=int, default=10_000)
    parser.add_argument("--report", type=Path, default=Path("var/public-retail-report.json"))
    args = parser.parse_args()
    if args.download and not args.archive.exists():
        download(args.archive)
    if args.state.exists():
        parser.error("state must be a new isolated directory")
    report = anyio.run(probe, args.archive, args.out, args.state, args.rows)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "rows": report["observed_extract"]["rows"],
                "profiled": report["workflow"]["profile_table_count"],
                "published": False,
            }
        )
    )


if __name__ == "__main__":
    main()
