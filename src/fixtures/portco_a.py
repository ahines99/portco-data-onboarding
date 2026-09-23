"""Fixture A: a synthetic B2B SaaS portfolio company with deliberate onboarding traps (POD-104).

Every value here is invented. Planted traps (each listed in the ground truth):
- `billing.customers.crm_account_ref` has ~8% orphans against `crm.accounts.acct_id`.
- ~3% duplicate customers in billing with near-identical names.
- `billing.invoice_lines.amount` is in integer CENTS; `billing.invoices.total_amt` is in dollars.
- `crm.opportunities.rev` is bookings, not revenue.
- Mixed currencies (USD/EUR/GBP) with no FX table in the source.
- Soft deletes (`crm.accounts.is_deleted`) and TEST records in CRM and billing.
- `crm.accounts.created_dt` is a VARCHAR holding dates in two formats.
- The fiscal year starts in February.
- PII canary values that must never appear in any output.
"""

from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from src.fixtures.base import Fixture, Table, luhn_complete

AS_OF = date(2026, 1, 31)
WINDOW_START = date(2024, 2, 1)
FX_TO_USD = {"USD": Decimal("1.00"), "EUR": Decimal("1.08"), "GBP": Decimal("1.27")}
PLANS = [
    ("starter", Decimal("250")),
    ("growth", Decimal("800")),
    ("scale", Decimal("2400")),
    ("enterprise", Decimal("6000")),
]

CANARIES = {
    "contact_first_name": "Canary7f3a",
    "contact_email": "canary-7f3a@canary.invalid",
    "contact_phone": "+1-555-013-7337",
    "billing_email": "ap-canary-7f3a@canary.invalid",
    "employee_name": "Canary7f3a Sentinel",
    "employee_ssn": "987-65-4329",
    "card_number": "4929000073377335",
}

ADJ = [
    "Blue",
    "Summit",
    "North",
    "Bright",
    "Iron",
    "Silver",
    "Cedar",
    "Harbor",
    "Prime",
    "Atlas",
    "Vertex",
    "Maple",
    "Granite",
    "Coastal",
    "Pioneer",
    "Lumen",
    "Orbit",
    "Quarry",
    "Radiant",
    "Sierra",
]
NOUN = [
    "Logistics",
    "Health",
    "Foods",
    "Analytics",
    "Robotics",
    "Media",
    "Labs",
    "Energy",
    "Retail",
    "Freight",
    "Dental",
    "Capital",
    "Systems",
    "Works",
    "Partners",
    "Clinics",
    "Metals",
    "Studios",
]
SUFFIX = ["Inc", "LLC", "Ltd", "Corp", "Group", "GmbH"]
FIRST = [
    "Ava",
    "Liam",
    "Noah",
    "Mia",
    "Zoe",
    "Ethan",
    "Iris",
    "Omar",
    "Priya",
    "Chen",
    "Lena",
    "Mateo",
    "Sara",
    "Yusuf",
    "Hana",
    "Diego",
    "Nora",
    "Ivan",
    "Leila",
    "Tomas",
    "Aiko",
    "Ben",
    "Clara",
    "Dev",
]
LAST = [
    "Nguyen",
    "Garcia",
    "Smith",
    "Okafor",
    "Kowalski",
    "Haddad",
    "Silva",
    "Tanaka",
    "Moreau",
    "Fischer",
    "Patel",
    "Rossi",
    "Kim",
    "Novak",
    "Duarte",
    "Larsen",
    "Mensah",
    "Ortiz",
    "Byrne",
    "Ito",
]
INDUSTRIES = [
    "healthcare",
    "logistics",
    "manufacturing",
    "retail",
    "financial_services",
    "media",
    "energy",
    "education",
]
DEPTS = ["Engineering", "Sales", "Marketing", "Support", "G&A", "Product"]


def _month_starts(start: date, end: date) -> list[date]:
    out, d = [], date(start.year, start.month, 1)
    while d <= end:
        out.append(d)
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return out


def _add_months(d: date, n: int) -> date:
    idx = d.year * 12 + d.month - 1 + n
    return date(idx // 12, idx % 12 + 1, 1)


def _month_end(d: date) -> date:
    return _add_months(d, 1) - timedelta(days=1)


def _mkey(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


@dataclass
class _Sub:
    sub_id: str
    cust_id: int
    plan: str
    mrr: Decimal
    currency: str
    start: date
    end: date | None
    status: str


def build(seed: int = 42) -> Fixture:
    rng = random.Random(seed)
    months = _month_starts(WINDOW_START, AS_OF)

    # ------------------------------------------------------------------ companies
    names = [f"{a} {n} {s}" for a in ADJ for n in NOUN for s in SUFFIX]
    rng.shuffle(names)
    company_names = names[:120]

    # ------------------------------------------------------------------ CRM accounts
    account_rows = []
    account_names: dict[str, str] = {}
    for i in range(1, 121):
        acct_id = f"A{i:05d}"
        nm = company_names[i - 1]
        account_names[acct_id] = nm
        created = date(2020, 1, 1) + timedelta(days=rng.randint(0, 5 * 365))
        created_txt = created.isoformat() if rng.random() < 0.7 else created.strftime("%m/%d/%Y")
        is_deleted = 111 <= i <= 115
        account_rows.append(
            (acct_id, nm, rng.choice(INDUSTRIES), f"rep{rng.randint(1, 8)}@portco-a.example", created_txt, is_deleted)
        )
    for k in (1, 2):
        acct_id = f"A{120 + k:05d}"
        account_names[acct_id] = f"TEST Account {k}"
        account_rows.append((acct_id, f"TEST Account {k}", "education", "qa@portco-a.example", "2024-01-15", False))

    # ------------------------------------------------------------------ billing customers
    countries = [("US", "USD")] * 80 + [("DE", "EUR")] * 6 + [("FR", "EUR")] * 4 + [("GB", "GBP")] * 10
    customer_rows = []
    cust_currency: dict[int, str] = {}
    real_customers: list[int] = []
    for i in range(1, 121):
        cust_id = 1000 + i
        country, ccy = rng.choice(countries)
        ref = f"A{i:05d}" if i <= 110 else f"A9{i:04d}"
        slug = company_names[i - 1].split()[0].lower() + company_names[i - 1].split()[1].lower()
        email = CANARIES["billing_email"] if i == 7 else f"ap@{slug}.example"
        customer_rows.append((cust_id, ref, company_names[i - 1], email, country, ccy))
        cust_currency[cust_id] = ccy
        real_customers.append(cust_id)
    dup_sources = sorted(rng.sample(range(1, 111), 4))
    dup_customers: list[int] = []
    for k, src in enumerate(dup_sources, start=1):
        cust_id = 1200 + k
        orig = customer_rows[src - 1]
        customer_rows.append((cust_id, orig[1], orig[2].upper() + ".", orig[3], orig[4], orig[5]))
        cust_currency[cust_id] = orig[5]
        dup_customers.append(cust_id)
    test_customers: list[int] = []
    for k in range(1, 4):
        cust_id = 1300 + k
        customer_rows.append(
            (cust_id, f"A{120 + (k % 2) + 1:05d}", f"TEST - Sandbox {k}", "qa@portco-a.example", "US", "USD")
        )
        cust_currency[cust_id] = "USD"
        test_customers.append(cust_id)

    # ------------------------------------------------------------------ subscriptions
    subs: list[_Sub] = []
    sub_seq = 0

    def new_sub(cust_id: int, plan_idx: int, start: date, disc: Decimal) -> _Sub:
        nonlocal sub_seq
        sub_seq += 1
        plan, price = PLANS[plan_idx]
        return _Sub(
            f"SUB-{sub_seq:05d}",
            cust_id,
            plan,
            (price * disc).quantize(Decimal("0.01")),
            cust_currency[cust_id],
            start,
            None,
            "active",
        )

    all_start_months = _month_starts(date(2023, 6, 1), date(2025, 10, 1))
    for cust_id in real_customers:
        start_month = rng.choice(all_start_months)
        start = start_month + timedelta(days=rng.randint(0, 27))
        plan_idx = rng.choices(range(4), weights=[35, 35, 20, 10])[0]
        disc = rng.choice([Decimal("1"), Decimal("1"), Decimal("1"), Decimal("0.9"), Decimal("0.85")])
        cur = new_sub(cust_id, plan_idx, start, disc)
        subs.append(cur)
        later = [m for m in months if m > start]
        if later and rng.random() < 0.30 and plan_idx < 3:
            when = rng.choice(later)
            cur.end, cur.status = when, "upgraded"
            plan_idx += 1
            cur = new_sub(cust_id, plan_idx, when, disc)
            subs.append(cur)
            later = [m for m in later if m > when]
        if later and rng.random() < 0.10 and plan_idx > 0:
            when = rng.choice(later)
            cur.end, cur.status = when, "downgraded"
            plan_idx -= 1
            cur = new_sub(cust_id, plan_idx, when, disc)
            subs.append(cur)
            later = [m for m in later if m > when]
        if later and rng.random() < 0.18:
            cur.end, cur.status = rng.choice(later), "cancelled"
    for cust_id in test_customers:
        s = new_sub(cust_id, 0, date(2025, 1, 10), Decimal("0.4"))
        subs.append(s)

    # ------------------------------------------------------------------ invoices, lines, payments
    invoice_rows, line_rows, payment_rows = [], [], []
    inv_seq = line_seq = pmt_seq = 0
    subs_by_cust: dict[int, list[_Sub]] = defaultdict(list)
    for s in subs:
        subs_by_cust[s.cust_id].append(s)
    expected_billings: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    invoices_meta: list[tuple[str, int, date, Decimal, Decimal, str, str]] = []
    dup_invoice_month = {c: rng.choice(months[6:18]) for c in dup_customers}

    for m in months:
        m_end = _month_end(m)
        for cust_id in sorted(cust_currency):
            lines: list[tuple[str, int, int]] = []  # (sku, qty, cents)
            for s in subs_by_cust.get(cust_id, []):
                if s.start <= m_end and (s.end is None or s.end > m):
                    lines.append((s.plan, 1, int(s.mrr * 100)))
            if cust_id in real_customers and lines and rng.random() < 0.08:
                lines.append(("SVC-FEE", rng.randint(1, 6), rng.randint(5, 30) * 10000))
            if cust_id in dup_customers and dup_invoice_month[cust_id] == m:
                lines.append(("SVC-FEE", 1, 75000))
            if not lines:
                continue
            inv_seq += 1
            inv_no = f"INV-{inv_seq:06d}"
            total = Decimal(sum(c for _, _, c in lines)) / 100
            sub_part = Decimal(sum(c for sku, _, c in lines if sku != "SVC-FEE")) / 100
            ccy = cust_currency[cust_id]
            paid = m < date(2026, 1, 1) and rng.random() > 0.03
            status = "paid" if paid else "open"
            invoice_rows.append((inv_no, cust_id, m, m + timedelta(days=30), total, ccy, status))
            for sku, qty, cents in lines:
                line_seq += 1
                line_rows.append((line_seq, inv_no, sku, qty, cents))
            if cust_id not in test_customers:
                expected_billings[f"{_mkey(m)}|{ccy}"] += total
                invoices_meta.append((inv_no, cust_id, m, total, sub_part, ccy, status))
            if paid:
                pmt_seq += 1
                paid_at = datetime(m.year, m.month, 1, 9, 0) + timedelta(
                    days=rng.randint(3, 40), hours=rng.randint(0, 8)
                )
                method = rng.choices(["card", "ach", "wire"], weights=[50, 35, 15])[0]
                if method == "card":
                    pan = CANARIES["card_number"] if pmt_seq == 11 else luhn_complete("4", 16, rng)
                    card, last4 = pan, pan[-4:]
                else:
                    card, last4 = None, None
                payment_rows.append((f"PMT-{pmt_seq:06d}", inv_no, paid_at, total, method, card, last4))

    # ------------------------------------------------------------------ opportunities & contacts
    opp_rows = []
    for i in range(1, 301):
        acct = f"A{rng.randint(1, 120):05d}"
        opp_rows.append(
            (
                f"OPP-{i:05d}",
                acct,
                Decimal(rng.randint(50, 1200)) * 100,
                rng.choice(["prospecting", "proposal", "negotiation", "closed_won", "closed_lost"]),
                WINDOW_START + timedelta(days=rng.randint(0, 700)),
            )
        )
    contact_rows = []
    cid = 0
    for i in range(1, 123):
        acct = f"A{i:05d}"
        slug = account_names[acct].split()[0].lower()
        for _ in range(2):
            cid += 1
            if cid == 1:
                contact_rows.append(
                    (
                        cid,
                        acct,
                        CANARIES["contact_first_name"],
                        "Sentinel",
                        CANARIES["contact_email"],
                        CANARIES["contact_phone"],
                    )
                )
                continue
            fn, ln = rng.choice(FIRST), rng.choice(LAST)
            contact_rows.append(
                (
                    cid,
                    acct,
                    fn,
                    ln,
                    f"{fn}.{ln}{cid}@{slug}.example".lower(),
                    f"+1-555-{rng.randint(100, 999)}-{rng.randint(1000, 9999)}",
                )
            )

    # ------------------------------------------------------------------ general ledger
    gl_accounts = [
        ("1000", "Cash", "asset"),
        ("1100", "Accounts Receivable", "asset"),
        ("1500", "Accumulated Depreciation", "asset"),
        ("2000", "Deferred Revenue", "liability"),
        ("4000", "Subscription Revenue", "revenue"),
        ("4100", "Services Revenue", "revenue"),
        ("5000", "Hosting COGS", "cogs"),
        ("5100", "Support COGS", "cogs"),
        ("6000", "Sales & Marketing", "opex"),
        ("6100", "Research & Development", "opex"),
        ("6200", "General & Administrative", "opex"),
        ("6900", "Depreciation & Amortization", "da"),
    ]
    entity_for = {"USD": "US01", "EUR": "EU01", "GBP": "UK01"}
    je_rows = []
    je_seq = 0
    expected_revenue: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    month_sub_rev_usd: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))

    def post(posting: date, entity: str, lines: list[tuple[str, Decimal, Decimal]]) -> None:
        nonlocal je_seq
        je_seq += 1
        for n, (acct, dr, cr) in enumerate(lines, start=1):
            je_rows.append((f"JE-{je_seq:06d}", n, acct, posting, dr, cr, entity))

    zero = Decimal("0.00")
    for _inv_no, _cust, inv_date, total, sub_part, ccy, _st in invoices_meta:
        fx = FX_TO_USD[ccy]
        sub_usd = (sub_part * fx).quantize(Decimal("0.01"))
        svc_usd = ((total - sub_part) * fx).quantize(Decimal("0.01"))
        lines = [("1100", sub_usd + svc_usd, zero)]
        if sub_usd:
            lines.append(("4000", zero, sub_usd))
        if svc_usd:
            lines.append(("4100", zero, svc_usd))
        post(inv_date, entity_for[ccy], lines)
        expected_revenue[_mkey(inv_date)] += sub_usd + svc_usd
        month_sub_rev_usd[_mkey(inv_date)] += sub_usd
    posted_ccy = {meta[0]: meta[5] for meta in invoices_meta}  # test-customer invoices never hit the GL
    for _pid, inv_no, paid_at, amount, *_ in payment_rows:
        if inv_no not in posted_ccy:
            continue
        ccy = posted_ccy[inv_no]
        usd = (amount * FX_TO_USD[ccy]).quantize(Decimal("0.01"))
        post(paid_at.date(), entity_for[ccy], [("1000", usd, zero), ("1100", zero, usd)])
    for m in months:
        m_end = _month_end(m)
        rev = month_sub_rev_usd[_mkey(m)]
        hosting = (rev * Decimal("0.17")).quantize(Decimal("0.01"))
        support = (rev * Decimal("0.06")).quantize(Decimal("0.01"))
        post(m_end, "US01", [("5000", hosting, zero), ("5100", support, zero), ("1000", zero, hosting + support)])
        sm, rd, ga = (Decimal(rng.randint(a, b)) * 100 for a, b in ((400, 600), (500, 700), (200, 300)))
        post(m_end, "US01", [("6000", sm, zero), ("6100", rd, zero), ("6200", ga, zero), ("1000", zero, sm + rd + ga)])
        post(m_end, "US01", [("6900", Decimal("5000.00"), zero), ("1500", zero, Decimal("5000.00"))])

    # ------------------------------------------------------------------ employees
    emp_rows = []
    for i in range(1, 61):
        hire = date(2019, 1, 1) + timedelta(days=rng.randint(0, 6 * 365))
        term = None
        if rng.random() < 0.15 and hire < date(2025, 6, 1):
            term = hire + timedelta(days=rng.randint(120, (AS_OF - hire).days))
        if i == 3:
            name, ssn = CANARIES["employee_name"], CANARIES["employee_ssn"]
        else:
            name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
            ssn = f"{rng.randint(100, 665):03d}-{rng.randint(1, 99):02d}-{rng.randint(1, 9999):04d}"
        dob = date(1965, 1, 1) + timedelta(days=rng.randint(0, 35 * 365))
        emp_rows.append(
            (
                f"E{i:04d}",
                name,
                ssn,
                dob,
                rng.choice(DEPTS),
                hire,
                term,
                Decimal(rng.randint(60, 220)) * 1000 + Decimal("0.50"),
            )
        )

    # ------------------------------------------------------------------ tables
    tables = [
        Table(
            "crm",
            "accounts",
            [
                ("acct_id", "VARCHAR"),
                ("acct_nm", "VARCHAR"),
                ("industry", "VARCHAR"),
                ("owner_email", "VARCHAR"),
                ("created_dt", "VARCHAR"),
                ("is_deleted", "BOOLEAN"),
            ],
            account_rows,
        ),
        Table(
            "crm",
            "contacts",
            [
                ("contact_id", "INTEGER"),
                ("acct_id", "VARCHAR"),
                ("first_name", "VARCHAR"),
                ("last_name", "VARCHAR"),
                ("email", "VARCHAR"),
                ("phone", "VARCHAR"),
            ],
            contact_rows,
        ),
        Table(
            "crm",
            "opportunities",
            [
                ("opp_id", "VARCHAR"),
                ("acct_id", "VARCHAR"),
                ("rev", "DECIMAL(14,2)"),
                ("stage", "VARCHAR"),
                ("close_date", "DATE"),
            ],
            opp_rows,
        ),
        Table(
            "billing",
            "customers",
            [
                ("cust_id", "INTEGER"),
                ("crm_account_ref", "VARCHAR"),
                ("cust_name", "VARCHAR"),
                ("billing_email", "VARCHAR"),
                ("country", "VARCHAR"),
                ("currency", "VARCHAR"),
            ],
            customer_rows,
        ),
        Table(
            "billing",
            "subscriptions",
            [
                ("sub_id", "VARCHAR"),
                ("cust_id", "INTEGER"),
                ("plan_code", "VARCHAR"),
                ("mrr_amt", "DECIMAL(12,2)"),
                ("currency", "VARCHAR"),
                ("start_dt", "DATE"),
                ("end_dt", "DATE"),
                ("status", "VARCHAR"),
            ],
            [(s.sub_id, s.cust_id, s.plan, s.mrr, s.currency, s.start, s.end, s.status) for s in subs],
        ),
        Table(
            "billing",
            "invoices",
            [
                ("inv_no", "VARCHAR"),
                ("cust_id", "INTEGER"),
                ("inv_date", "DATE"),
                ("due_date", "DATE"),
                ("total_amt", "DECIMAL(14,2)"),
                ("currency", "VARCHAR"),
                ("status", "VARCHAR"),
            ],
            invoice_rows,
        ),
        Table(
            "billing",
            "invoice_lines",
            [
                ("line_id", "INTEGER"),
                ("inv_no", "VARCHAR"),
                ("sku", "VARCHAR"),
                ("qty", "INTEGER"),
                ("amount", "BIGINT"),
            ],
            line_rows,
        ),
        Table(
            "billing",
            "payments",
            [
                ("pmt_id", "VARCHAR"),
                ("inv_no", "VARCHAR"),
                ("paid_at", "TIMESTAMP"),
                ("amount", "DECIMAL(14,2)"),
                ("method", "VARCHAR"),
                ("card_number", "VARCHAR"),
                ("card_last4", "VARCHAR"),
            ],
            payment_rows,
        ),
        Table(
            "erp",
            "gl_accounts",
            [("acct_code", "VARCHAR"), ("acct_name", "VARCHAR"), ("acct_type", "VARCHAR")],
            gl_accounts,
        ),
        Table(
            "erp",
            "journal_lines",
            [
                ("je_id", "VARCHAR"),
                ("line_no", "INTEGER"),
                ("acct_code", "VARCHAR"),
                ("posting_date", "DATE"),
                ("debit", "DECIMAL(14,2)"),
                ("credit", "DECIMAL(14,2)"),
                ("entity_code", "VARCHAR"),
            ],
            je_rows,
        ),
        Table(
            "hr",
            "employees",
            [
                ("emp_id", "VARCHAR"),
                ("full_name", "VARCHAR"),
                ("ssn", "VARCHAR"),
                ("dob", "DATE"),
                ("dept", "VARCHAR"),
                ("hire_date", "DATE"),
                ("term_date", "DATE"),
                ("salary", "DECIMAL(12,2)"),
            ],
            emp_rows,
        ),
    ]

    # ------------------------------------------------------------------ independent expected metrics
    expected_arr: dict[str, str] = {}
    expected_active: dict[str, int] = {}
    for m in months:
        at = _month_end(m)
        per_ccy: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        active: set[int] = set()
        for s in subs:
            if s.cust_id in test_customers:
                continue
            if s.start <= at and (s.end is None or s.end > at):
                per_ccy[s.currency] += s.mrr
                active.add(s.cust_id)
        for ccy, v in per_ccy.items():
            expected_arr[f"{_mkey(m)}|{ccy}"] = str((v * 12).quantize(Decimal("0.01")))
        expected_active[_mkey(m)] = len(active)

    ground_truth = {
        "fixture": "portco_a",
        "company_id": "portco_a",
        "as_of": AS_OF.isoformat(),
        "fiscal_year_start_month": 2,
        "months": [_mkey(m) for m in months],
        "primary_keys": {
            "crm.accounts": ["acct_id"],
            "crm.contacts": ["contact_id"],
            "crm.opportunities": ["opp_id"],
            "billing.customers": ["cust_id"],
            "billing.subscriptions": ["sub_id"],
            "billing.invoices": ["inv_no"],
            "billing.invoice_lines": ["line_id"],
            "billing.payments": ["pmt_id"],
            "erp.gl_accounts": ["acct_code"],
            "erp.journal_lines": ["je_id", "line_no"],
            "hr.employees": ["emp_id"],
        },
        "entities": {
            "crm.accounts": "customer",
            "crm.contacts": "contact",
            "crm.opportunities": "opportunity",
            "billing.customers": "customer",
            "billing.subscriptions": "subscription",
            "billing.invoices": "invoice",
            "billing.invoice_lines": "invoice_line",
            "billing.payments": "payment",
            "erp.gl_accounts": "gl_account",
            "erp.journal_lines": "gl_entry",
            "hr.employees": "employee",
        },
        "joins": [
            {"left": "crm.contacts.acct_id", "right": "crm.accounts.acct_id", "cardinality": "N:1", "orphan_rate": 0.0},
            {
                "left": "crm.opportunities.acct_id",
                "right": "crm.accounts.acct_id",
                "cardinality": "N:1",
                "orphan_rate": 0.0,
            },
            {
                "left": "billing.customers.crm_account_ref",
                "right": "crm.accounts.acct_id",
                "cardinality": "N:1",
                "orphan_rate": round(10 / 127, 4),
            },
            {
                "left": "billing.subscriptions.cust_id",
                "right": "billing.customers.cust_id",
                "cardinality": "N:1",
                "orphan_rate": 0.0,
            },
            {
                "left": "billing.invoices.cust_id",
                "right": "billing.customers.cust_id",
                "cardinality": "N:1",
                "orphan_rate": 0.0,
            },
            {
                "left": "billing.invoice_lines.inv_no",
                "right": "billing.invoices.inv_no",
                "cardinality": "N:1",
                "orphan_rate": 0.0,
            },
            {
                "left": "billing.payments.inv_no",
                "right": "billing.invoices.inv_no",
                "cardinality": "N:1",
                "orphan_rate": 0.0,
            },
            {
                "left": "erp.journal_lines.acct_code",
                "right": "erp.gl_accounts.acct_code",
                "cardinality": "N:1",
                "orphan_rate": 0.0,
            },
        ],
        "mappings": {
            "crm.accounts.acct_id": "customer.crm_account_id",
            "crm.accounts.acct_nm": "customer.customer_name",
            "crm.accounts.industry": "customer.industry",
            "crm.accounts.owner_email": "customer.owner_email",
            "crm.accounts.created_dt": "customer.created_date",
            "crm.accounts.is_deleted": "customer.is_deleted",
            "crm.contacts.contact_id": "contact.contact_id",
            "crm.contacts.acct_id": "contact.crm_account_id",
            "crm.contacts.first_name": "contact.first_name",
            "crm.contacts.last_name": "contact.last_name",
            "crm.contacts.email": "contact.email",
            "crm.contacts.phone": "contact.phone",
            "crm.opportunities.opp_id": "opportunity.opportunity_id",
            "crm.opportunities.acct_id": "opportunity.crm_account_id",
            "crm.opportunities.rev": "opportunity.amount",
            "crm.opportunities.stage": "opportunity.stage",
            "crm.opportunities.close_date": "opportunity.close_date",
            "billing.customers.cust_id": "customer.customer_id",
            "billing.customers.crm_account_ref": "customer.crm_account_id",
            "billing.customers.cust_name": "customer.customer_name",
            "billing.customers.billing_email": "customer.billing_email",
            "billing.customers.country": "customer.country",
            "billing.customers.currency": "customer.currency",
            "billing.subscriptions.sub_id": "subscription.subscription_id",
            "billing.subscriptions.cust_id": "subscription.customer_id",
            "billing.subscriptions.plan_code": "subscription.plan_code",
            "billing.subscriptions.mrr_amt": "subscription.mrr",
            "billing.subscriptions.currency": "subscription.currency",
            "billing.subscriptions.start_dt": "subscription.start_date",
            "billing.subscriptions.end_dt": "subscription.end_date",
            "billing.subscriptions.status": "subscription.status",
            "billing.invoices.inv_no": "invoice.invoice_id",
            "billing.invoices.cust_id": "invoice.customer_id",
            "billing.invoices.inv_date": "invoice.invoice_date",
            "billing.invoices.due_date": "invoice.due_date",
            "billing.invoices.total_amt": "invoice.total_amount",
            "billing.invoices.currency": "invoice.currency",
            "billing.invoices.status": "invoice.status",
            "billing.invoice_lines.line_id": "invoice_line.invoice_line_id",
            "billing.invoice_lines.inv_no": "invoice_line.invoice_id",
            "billing.invoice_lines.sku": "invoice_line.sku",
            "billing.invoice_lines.qty": "invoice_line.quantity",
            "billing.invoice_lines.amount": "invoice_line.amount",
            "billing.payments.pmt_id": "payment.payment_id",
            "billing.payments.inv_no": "payment.invoice_id",
            "billing.payments.paid_at": "payment.paid_at",
            "billing.payments.amount": "payment.amount",
            "billing.payments.method": "payment.method",
            "billing.payments.card_number": "payment.card_number",
            "billing.payments.card_last4": "payment.card_last4",
            "erp.gl_accounts.acct_code": "gl_account.account_code",
            "erp.gl_accounts.acct_name": "gl_account.account_name",
            "erp.gl_accounts.acct_type": "gl_account.account_type",
            "erp.journal_lines.je_id": "gl_entry.journal_id",
            "erp.journal_lines.line_no": "gl_entry.line_number",
            "erp.journal_lines.acct_code": "gl_entry.account_code",
            "erp.journal_lines.posting_date": "gl_entry.posting_date",
            "erp.journal_lines.debit": "gl_entry.debit_amount",
            "erp.journal_lines.credit": "gl_entry.credit_amount",
            "erp.journal_lines.entity_code": "gl_entry.entity_code",
            "hr.employees.emp_id": "employee.employee_id",
            "hr.employees.full_name": "employee.full_name",
            "hr.employees.ssn": "employee.national_id",
            "hr.employees.dob": "employee.date_of_birth",
            "hr.employees.dept": "employee.department",
            "hr.employees.hire_date": "employee.hire_date",
            "hr.employees.term_date": "employee.termination_date",
            "hr.employees.salary": "employee.salary",
        },
        "pii_columns": {
            "crm.accounts.owner_email": "email",
            "crm.contacts.first_name": "person_name",
            "crm.contacts.last_name": "person_name",
            "crm.contacts.email": "email",
            "crm.contacts.phone": "phone",
            "billing.customers.billing_email": "email",
            "billing.payments.card_number": "payment_card",
            "hr.employees.full_name": "person_name",
            "hr.employees.ssn": "national_id",
            "hr.employees.dob": "dob",
        },
        "traps": [
            {"column": "billing.invoice_lines.amount", "reason": "UNIT_MISMATCH"},
            {"column": "crm.opportunities.rev", "reason": "SEMANTIC_TRAP"},
        ],
        "row_filters": [
            {"table": "crm.accounts", "column": "is_deleted", "kind": "exclude_true"},
            {"table": "crm.accounts", "column": "acct_nm", "kind": "exclude_prefix", "value": "TEST"},
            {"table": "billing.customers", "column": "cust_name", "kind": "exclude_prefix", "value": "TEST"},
        ],
        "expected_findings": ["DUPLICATE_ENTITIES", "ENTITY_OVERLAP", "POSSIBLE_MINOR_UNITS", "MULTI_CURRENCY"],
        "expected_metrics": {
            "billings": {k: str(v.quantize(Decimal("0.01"))) for k, v in sorted(expected_billings.items())},
            "arr": dict(sorted(expected_arr.items())),
            "active_customers": expected_active,
            "revenue_recognized": {k: str(v.quantize(Decimal("0.01"))) for k, v in sorted(expected_revenue.items())},
        },
        "canaries": sorted(CANARIES.values()),
    }
    return Fixture("portco_a", "portco_a", AS_OF, tables, ground_truth)
