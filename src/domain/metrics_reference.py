"""Reference metric calculators (POD-108).

Pure functions over typed records. Every metric the generated dbt / semantic layer produces
is reconciled against these, so they are written for obviousness, not speed.

Conventions
- Money is `Decimal`, quantized to 0.01 with ROUND_HALF_EVEN; ratios to 0.0001.
- Months are "YYYY-MM" keys. A subscription/employee is active at a month end when
  start <= month_end and (end is None or end > month_end)  (end dates are exclusive).
- Undefined results (division by zero) are `None`, never 0.
"""

from __future__ import annotations

import calendar
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from itertools import pairwise

CENT = Decimal("0.01")
RATIO = Decimal("0.0001")
ZERO = Decimal("0")
TWELVE = Decimal("12")


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_EVEN)


def ratio(value: Decimal) -> Decimal:
    return value.quantize(RATIO, rounding=ROUND_HALF_EVEN)


# --------------------------------------------------------------------------- calendar


def month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def month_end(key: str) -> date:
    year, month = (int(p) for p in key.split("-"))
    return date(year, month, calendar.monthrange(year, month)[1])


def days_in_month(key: str) -> int:
    return month_end(key).day


def month_range(start: str, end: str) -> list[str]:
    """Inclusive list of month keys from start to end."""
    y, m = (int(p) for p in start.split("-"))
    out: list[str] = []
    while f"{y:04d}-{m:02d}" <= end:
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def shift_month(key: str, delta: int) -> str:
    y, m = (int(p) for p in key.split("-"))
    idx = y * 12 + (m - 1) + delta
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}"


def fiscal_period(d: date, fy_start_month: int) -> str:
    """Fiscal label, e.g. FY2026-P01. The fiscal year is named after the year it ends in."""
    if not 1 <= fy_start_month <= 12:
        raise ValueError("fy_start_month must be 1..12")
    offset = (d.month - fy_start_month) % 12
    fy_start_year = d.year if d.month >= fy_start_month else d.year - 1
    fy_label = fy_start_year + (1 if fy_start_month != 1 else 0)
    return f"FY{fy_label}-P{offset + 1:02d}"


# --------------------------------------------------------------------------- records


@dataclass(frozen=True)
class InvoiceRec:
    invoice_id: str
    customer_id: str
    invoice_date: date
    total_amount: Decimal
    currency: str


@dataclass(frozen=True)
class SubscriptionRec:
    customer_id: str
    mrr: Decimal
    currency: str
    start_date: date
    end_date: date | None


@dataclass(frozen=True)
class PaymentRec:
    invoice_id: str
    paid_on: date
    amount: Decimal


@dataclass(frozen=True)
class GlLineRec:
    posting_date: date
    account_type: str
    debit: Decimal
    credit: Decimal


@dataclass(frozen=True)
class EmployeeRec:
    hire_date: date
    termination_date: date | None


@dataclass(frozen=True)
class ArrMovement:
    new: Decimal
    expansion: Decimal
    contraction: Decimal
    churned: Decimal


def _active(start: date, end: date | None, at: date) -> bool:
    return start <= at and (end is None or end > at)


# --------------------------------------------------------------------------- billings


def billings(invoices: Iterable[InvoiceRec]) -> dict[tuple[str, str], Decimal]:
    out: dict[tuple[str, str], Decimal] = defaultdict(lambda: ZERO)
    for inv in invoices:
        out[(month_key(inv.invoice_date), inv.currency)] += inv.total_amount
    return {k: money(v) for k, v in sorted(out.items())}


# --------------------------------------------------------------------------- recurring revenue


def mrr_by_customer(
    subs: Sequence[SubscriptionRec], months: Sequence[str]
) -> dict[str, dict[tuple[str, str], Decimal]]:
    """month -> (customer_id, currency) -> MRR at month end."""
    out: dict[str, dict[tuple[str, str], Decimal]] = {}
    for key in months:
        at = month_end(key)
        bucket: dict[tuple[str, str], Decimal] = defaultdict(lambda: ZERO)
        for s in subs:
            if _active(s.start_date, s.end_date, at):
                bucket[(s.customer_id, s.currency)] += s.mrr
        out[key] = dict(bucket)
    return out


def mrr(subs: Sequence[SubscriptionRec], months: Sequence[str]) -> dict[tuple[str, str], Decimal]:
    out: dict[tuple[str, str], Decimal] = {}
    for key, bucket in mrr_by_customer(subs, months).items():
        per_ccy: dict[str, Decimal] = defaultdict(lambda: ZERO)
        for (_, ccy), value in bucket.items():
            per_ccy[ccy] += value
        for ccy, value in per_ccy.items():
            out[(key, ccy)] = money(value)
    return dict(sorted(out.items()))


def arr(subs: Sequence[SubscriptionRec], months: Sequence[str]) -> dict[tuple[str, str], Decimal]:
    return {k: money(v * TWELVE) for k, v in mrr(subs, months).items()}


def active_customers(subs: Sequence[SubscriptionRec], months: Sequence[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for key, bucket in mrr_by_customer(subs, months).items():
        out[key] = len({cust for (cust, _), value in bucket.items() if value > ZERO})
    return out


def arr_movements(subs: Sequence[SubscriptionRec], months: Sequence[str]) -> dict[tuple[str, str], ArrMovement]:
    """ARR bridge per month and currency, comparing each month end with the previous one."""
    if not months:
        return {}
    all_months = [shift_month(months[0], -1), *months]
    by_cust = mrr_by_customer(subs, all_months)
    out: dict[tuple[str, str], ArrMovement] = {}
    for prev_key, key in pairwise(all_months):
        prev, cur = by_cust[prev_key], by_cust[key]
        acc: dict[str, list[Decimal]] = defaultdict(lambda: [ZERO, ZERO, ZERO, ZERO])
        for cust_ccy in set(prev) | set(cur):
            p, c = prev.get(cust_ccy, ZERO), cur.get(cust_ccy, ZERO)
            ccy = cust_ccy[1]
            if p == ZERO and c > ZERO:
                acc[ccy][0] += c
            elif p > ZERO and c == ZERO:
                acc[ccy][3] += p
            elif c > p:
                acc[ccy][1] += c - p
            elif c < p:
                acc[ccy][2] += p - c
        for ccy, (n, e, co, ch) in acc.items():
            out[(key, ccy)] = ArrMovement(
                new=money(n * TWELVE),
                expansion=money(e * TWELVE),
                contraction=money(co * TWELVE),
                churned=money(ch * TWELVE),
            )
    return dict(sorted(out.items()))


def _retention(subs: Sequence[SubscriptionRec], month: str, *, gross: bool) -> dict[str, Decimal | None]:
    start_key = shift_month(month, -12)
    by_cust = mrr_by_customer(subs, [start_key, month])
    start, end = by_cust[start_key], by_cust[month]
    num: dict[str, Decimal] = defaultdict(lambda: ZERO)
    den: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for cust_ccy, s in start.items():
        if s <= ZERO:
            continue
        e = end.get(cust_ccy, ZERO)
        den[cust_ccy[1]] += s
        num[cust_ccy[1]] += min(e, s) if gross else e
    currencies = {c for (_, c) in start} | {c for (_, c) in end}
    return {ccy: (ratio(num[ccy] / den[ccy]) if den[ccy] > ZERO else None) for ccy in sorted(currencies)}


def nrr(subs: Sequence[SubscriptionRec], month: str) -> dict[str, Decimal | None]:
    return _retention(subs, month, gross=False)


def grr(subs: Sequence[SubscriptionRec], month: str) -> dict[str, Decimal | None]:
    return _retention(subs, month, gross=True)


def arpa(subs: Sequence[SubscriptionRec], months: Sequence[str]) -> dict[tuple[str, str], Decimal | None]:
    out: dict[tuple[str, str], Decimal | None] = {}
    for key, bucket in mrr_by_customer(subs, months).items():
        totals: dict[str, Decimal] = defaultdict(lambda: ZERO)
        counts: dict[str, int] = defaultdict(int)
        for (_, ccy), value in bucket.items():
            if value > ZERO:
                totals[ccy] += value
                counts[ccy] += 1
        for ccy in totals:
            out[(key, ccy)] = money(totals[ccy] * TWELVE / counts[ccy]) if counts[ccy] else None
    return dict(sorted(out.items()))


# --------------------------------------------------------------------------- general ledger


def _gl_sum(lines: Iterable[GlLineRec], account_type: str, *, credit_normal: bool) -> dict[str, Decimal]:
    out: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for ln in lines:
        if ln.account_type != account_type:
            continue
        delta = ln.credit - ln.debit if credit_normal else ln.debit - ln.credit
        out[month_key(ln.posting_date)] += delta
    return {k: money(v) for k, v in sorted(out.items())}


def revenue_recognized(lines: Sequence[GlLineRec]) -> dict[str, Decimal]:
    return _gl_sum(lines, "revenue", credit_normal=True)


def cogs(lines: Sequence[GlLineRec]) -> dict[str, Decimal]:
    return _gl_sum(lines, "cogs", credit_normal=False)


def opex(lines: Sequence[GlLineRec]) -> dict[str, Decimal]:
    return _gl_sum(lines, "opex", credit_normal=False)


def gross_margin_pct(lines: Sequence[GlLineRec]) -> dict[str, Decimal | None]:
    rev, cost = revenue_recognized(lines), cogs(lines)
    months = sorted(set(rev) | set(cost))
    return {
        m: (ratio((rev.get(m, ZERO) - cost.get(m, ZERO)) / rev[m]) if rev.get(m, ZERO) != ZERO else None)
        for m in months
    }


def ebitda(lines: Sequence[GlLineRec]) -> dict[str, Decimal]:
    rev, cost, op = revenue_recognized(lines), cogs(lines), opex(lines)
    months = sorted(set(rev) | set(cost) | set(op))
    return {m: money(rev.get(m, ZERO) - cost.get(m, ZERO) - op.get(m, ZERO)) for m in months}


# --------------------------------------------------------------------------- people & cash


def headcount(employees: Sequence[EmployeeRec], months: Sequence[str]) -> dict[str, int]:
    return {
        key: sum(1 for e in employees if _active(e.hire_date, e.termination_date, month_end(key))) for key in months
    }


def dso(
    invoices: Sequence[InvoiceRec], payments: Sequence[PaymentRec], months: Sequence[str]
) -> dict[tuple[str, str], Decimal | None]:
    """Open AR at month end / billings in the month * days in the month, per currency."""
    inv_by_id = {i.invoice_id: i for i in invoices}
    bill = billings(invoices)
    currencies = sorted({i.currency for i in invoices})
    out: dict[tuple[str, str], Decimal | None] = {}
    for key in months:
        at = month_end(key)
        for ccy in currencies:
            billed = sum((i.total_amount for i in invoices if i.currency == ccy and i.invoice_date <= at), ZERO)
            paid = sum(
                (
                    p.amount
                    for p in payments
                    if p.paid_on <= at
                    and p.invoice_id in inv_by_id
                    and inv_by_id[p.invoice_id].currency == ccy
                    and inv_by_id[p.invoice_id].invoice_date <= at
                ),
                ZERO,
            )
            month_billings = bill.get((key, ccy), ZERO)
            out[(key, ccy)] = (
                money((billed - paid) / month_billings * days_in_month(key)) if month_billings != ZERO else None
            )
    return out
