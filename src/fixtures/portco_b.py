"""Fixture B: an industrial distributor with SAP-style technical naming (POD-105).

Shares no table or column names with fixture A. It has no subscriptions, so every
recurring-revenue metric must come back NEEDS_EVIDENCE rather than a guessed value.
"""

from __future__ import annotations

import random
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from src.fixtures.base import Fixture, Table

AS_OF = date(2025, 12, 31)
START = date(2025, 1, 1)
MATERIALS = [
    ("M-1001", "Hydraulic pump", "420.00"),
    ("M-1002", "Steel coupling", "18.50"),
    ("M-1003", "Pressure valve", "95.00"),
    ("M-1004", "Bearing kit", "61.25"),
    ("M-1005", "Control panel", "1250.00"),
    ("M-1006", "Gasket set", "7.80"),
]
NAMES = [
    "Rhein Anlagenbau",
    "Nordlicht Technik",
    "Alpen Industrie",
    "Hafen Logistik",
    "Elbe Maschinen",
    "Donau Stahl",
    "Main Hydraulik",
    "Isar Elektro",
    "Weser Metall",
    "Spree Automation",
]


def _mkey(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def build(seed: int = 7) -> Fixture:
    rng = random.Random(seed)
    kna1 = []
    for i in range(1, 81):
        kunnr = f"{100000 + i:010d}"
        name = f"{rng.choice(NAMES)} {i:02d}"
        kna1.append(
            (
                kunnr,
                name,
                rng.choice(["DE", "AT", "CH"]),
                rng.choice(["MACH", "CHEM", "AUTO", "ENRG"]),
                date(2018, 1, 1) + timedelta(days=rng.randint(0, 2000)),
                i in (5, 17),
            )
        )
    mara = [(m, n) for m, n, _ in MATERIALS]
    price = {m: Decimal(p) for m, _, p in MATERIALS}

    vbrk, vbrp = [], []
    expected_billings: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    doc = 90000000
    for day in range(0, (AS_OF - START).days + 1, 3):
        fkdat = START + timedelta(days=day)
        for _ in range(rng.randint(1, 3)):
            doc += 1
            vbeln = f"{doc:010d}"
            kunag = f"{100000 + rng.randint(1, 80):010d}"
            total = Decimal("0")
            for posnr in range(10, 10 * rng.randint(1, 4) + 1, 10):
                matnr = rng.choice(MATERIALS)[0]
                qty = rng.randint(1, 40)
                amount = (price[matnr] * qty).quantize(Decimal("0.01"))
                total += amount
                vbrp.append((vbeln, posnr, matnr, qty, amount))
            vbrk.append((vbeln, kunag, fkdat, total, "EUR", "F2"))
            expected_billings[f"{_mkey(fkdat)}|EUR"] += total

    ska1 = [
        ("0000800000", "Umsatzerloese Inland", "revenue"),
        ("0000400000", "Materialaufwand", "cogs"),
        ("0000600000", "Personalaufwand", "opex"),
        ("0000140000", "Forderungen", "asset"),
    ]
    bseg = []
    expected_revenue: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    zero = Decimal("0.00")
    for n, (_vbeln, _k, fkdat, total, _c, _t) in enumerate(vbrk, start=1):
        belnr = f"{5000000 + n:010d}"
        bseg.append((belnr, 1, "0000140000", fkdat, total, zero, "1000"))
        bseg.append((belnr, 2, "0000800000", fkdat, zero, total, "1000"))
        cost = (total * Decimal("0.55")).quantize(Decimal("0.01"))
        bseg.append((belnr, 3, "0000400000", fkdat, cost, zero, "1000"))
        bseg.append((belnr, 4, "0000140000", fkdat, zero, cost, "1000"))
        expected_revenue[_mkey(fkdat)] += total

    pa0001 = []
    for i in range(1, 41):
        eintritt = date(2012, 1, 1) + timedelta(days=rng.randint(0, 4500))
        austritt = eintritt + timedelta(days=rng.randint(200, 900)) if rng.random() < 0.1 else None
        pa0001.append(
            (
                f"{i:08d}",
                f"{rng.choice(['Anna', 'Jonas', 'Lea', 'Felix', 'Mila'])} "
                f"{rng.choice(['Weber', 'Wagner', 'Becker', 'Hoffmann'])}",
                date(1970, 1, 1) + timedelta(days=rng.randint(0, 11000)),
                rng.choice(["50000100", "50000200", "50000300"]),
                eintritt,
                austritt,
            )
        )

    tables = [
        Table(
            "sap",
            "KNA1",
            [
                ("KUNNR", "VARCHAR"),
                ("NAME1", "VARCHAR"),
                ("LAND1", "VARCHAR"),
                ("BRSCH", "VARCHAR"),
                ("ERDAT", "DATE"),
                ("LOEVM", "BOOLEAN"),
            ],
            kna1,
        ),
        Table("sap", "MARA", [("MATNR", "VARCHAR"), ("MAKTX", "VARCHAR")], mara),
        Table(
            "sap",
            "VBRK",
            [
                ("VBELN", "VARCHAR"),
                ("KUNAG", "VARCHAR"),
                ("FKDAT", "DATE"),
                ("NETWR", "DECIMAL(14,2)"),
                ("WAERK", "VARCHAR"),
                ("FKART", "VARCHAR"),
            ],
            vbrk,
        ),
        Table(
            "sap",
            "VBRP",
            [
                ("VBELN", "VARCHAR"),
                ("POSNR", "INTEGER"),
                ("MATNR", "VARCHAR"),
                ("FKIMG", "INTEGER"),
                ("NETWR", "DECIMAL(14,2)"),
            ],
            vbrp,
        ),
        Table("sap", "SKA1", [("SAKNR", "VARCHAR"), ("TXT50", "VARCHAR"), ("KTOKS", "VARCHAR")], ska1),
        Table(
            "sap",
            "BSEG",
            [
                ("BELNR", "VARCHAR"),
                ("BUZEI", "INTEGER"),
                ("HKONT", "VARCHAR"),
                ("BUDAT", "DATE"),
                ("DMBTR_S", "DECIMAL(14,2)"),
                ("DMBTR_H", "DECIMAL(14,2)"),
                ("BUKRS", "VARCHAR"),
            ],
            bseg,
        ),
        Table(
            "sap",
            "PA0001",
            [
                ("PERNR", "VARCHAR"),
                ("ENAME", "VARCHAR"),
                ("GBDAT", "DATE"),
                ("ORGEH", "VARCHAR"),
                ("EINTRITT", "DATE"),
                ("AUSTRITT", "DATE"),
            ],
            pa0001,
        ),
    ]
    months = sorted({_mkey(START + timedelta(days=d)) for d in range((AS_OF - START).days + 1)})
    ground_truth = {
        "fixture": "portco_b",
        "company_id": "portco_b",
        "as_of": AS_OF.isoformat(),
        "fiscal_year_start_month": 1,
        "months": months,
        "primary_keys": {
            "sap.KNA1": ["KUNNR"],
            "sap.MARA": ["MATNR"],
            "sap.VBRK": ["VBELN"],
            "sap.VBRP": ["VBELN", "POSNR"],
            "sap.SKA1": ["SAKNR"],
            "sap.BSEG": ["BELNR", "BUZEI"],
            "sap.PA0001": ["PERNR"],
        },
        "entities": {
            "sap.KNA1": "customer",
            "sap.MARA": "product",
            "sap.VBRK": "invoice",
            "sap.VBRP": "invoice_line",
            "sap.SKA1": "gl_account",
            "sap.BSEG": "gl_entry",
            "sap.PA0001": "employee",
        },
        "joins": [
            {"left": "sap.VBRK.KUNAG", "right": "sap.KNA1.KUNNR", "cardinality": "N:1", "orphan_rate": 0.0},
            {"left": "sap.VBRP.VBELN", "right": "sap.VBRK.VBELN", "cardinality": "N:1", "orphan_rate": 0.0},
            {"left": "sap.VBRP.MATNR", "right": "sap.MARA.MATNR", "cardinality": "N:1", "orphan_rate": 0.0},
            {"left": "sap.BSEG.HKONT", "right": "sap.SKA1.SAKNR", "cardinality": "N:1", "orphan_rate": 0.0},
        ],
        "mappings": {
            "sap.KNA1.KUNNR": "customer.customer_id",
            "sap.KNA1.NAME1": "customer.customer_name",
            "sap.KNA1.LAND1": "customer.country",
            "sap.KNA1.BRSCH": "customer.industry",
            "sap.KNA1.ERDAT": "customer.created_date",
            "sap.KNA1.LOEVM": "customer.is_deleted",
            "sap.MARA.MATNR": "product.sku",
            "sap.MARA.MAKTX": "product.product_name",
            "sap.VBRK.VBELN": "invoice.invoice_id",
            "sap.VBRK.KUNAG": "invoice.customer_id",
            "sap.VBRK.FKDAT": "invoice.invoice_date",
            "sap.VBRK.NETWR": "invoice.total_amount",
            "sap.VBRK.WAERK": "invoice.currency",
            "sap.VBRK.FKART": None,
            "sap.VBRP.VBELN": "invoice_line.invoice_id",
            "sap.VBRP.POSNR": "invoice_line.invoice_line_id",
            "sap.VBRP.MATNR": "invoice_line.sku",
            "sap.VBRP.FKIMG": "invoice_line.quantity",
            "sap.VBRP.NETWR": "invoice_line.amount",
            "sap.SKA1.SAKNR": "gl_account.account_code",
            "sap.SKA1.TXT50": "gl_account.account_name",
            "sap.SKA1.KTOKS": "gl_account.account_type",
            "sap.BSEG.BELNR": "gl_entry.journal_id",
            "sap.BSEG.BUZEI": "gl_entry.line_number",
            "sap.BSEG.HKONT": "gl_entry.account_code",
            "sap.BSEG.BUDAT": "gl_entry.posting_date",
            "sap.BSEG.DMBTR_S": "gl_entry.debit_amount",
            "sap.BSEG.DMBTR_H": "gl_entry.credit_amount",
            "sap.BSEG.BUKRS": "gl_entry.entity_code",
            "sap.PA0001.PERNR": "employee.employee_id",
            "sap.PA0001.ENAME": "employee.full_name",
            "sap.PA0001.GBDAT": "employee.date_of_birth",
            "sap.PA0001.ORGEH": "employee.department",
            "sap.PA0001.EINTRITT": "employee.hire_date",
            "sap.PA0001.AUSTRITT": "employee.termination_date",
        },
        "pii_columns": {"sap.PA0001.ENAME": "person_name", "sap.PA0001.GBDAT": "dob"},
        "traps": [],
        "row_filters": [{"table": "sap.KNA1", "column": "LOEVM", "kind": "exclude_true"}],
        "not_applicable_metrics": [
            "mrr",
            "arr",
            "active_customers",
            "new_arr",
            "expansion_arr",
            "contraction_arr",
            "churned_arr",
            "nrr",
            "grr",
            "arpa",
            "dso",
        ],
        "expected_metrics": {
            "billings": {k: str(v.quantize(Decimal("0.01"))) for k, v in sorted(expected_billings.items())},
            "revenue_recognized": {k: str(v.quantize(Decimal("0.01"))) for k, v in sorted(expected_revenue.items())},
        },
        "canaries": [],
    }
    return Fixture("portco_b", "portco_b", AS_OF, tables, ground_truth)
