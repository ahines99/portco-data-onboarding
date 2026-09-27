"""Explicit disclosure policy for synthetic fixture categories, never inferred from rows.

Real connections must supply their own operator-reviewed, qualified column domains.
Even approved columns with a single unexpected value have all labels withheld.
"""

from __future__ import annotations


def fixture_category_domains(name: str) -> dict[str, list[str]]:
    base = name.partition("__")[0]
    if base == "portco_b":
        return {
            "sap.KNA1.LAND1": ["DE", "AT", "CH"],
            "sap.KNA1.BRSCH": ["MACH", "CHEM", "AUTO", "ENRG"],
            "sap.VBRK.WAERK": ["EUR"],
            "sap.VBRK.FKART": ["F2"],
            "sap.SKA1.KTOKS": ["revenue", "cogs", "opex", "asset"],
            "sap.BSEG.BUKRS": ["1000"],
            "sap.PA0001.ORGEH": ["50000100", "50000200", "50000300"],
        }
    if base != "portco_a":
        return {}
    return {
        "crm.accounts.industry": [
            "healthcare",
            "logistics",
            "manufacturing",
            "retail",
            "financial_services",
            "media",
            "energy",
            "education",
        ],
        "crm.opportunities.stage": ["prospecting", "proposal", "negotiation", "closed_won", "closed_lost"],
        "billing.customers.country": ["US", "DE", "FR", "GB"],
        "billing.customers.currency": ["USD", "EUR", "GBP"],
        "billing.subscriptions.currency": ["USD", "EUR", "GBP"],
        "billing.subscriptions.plan_code": ["starter", "growth", "scale", "enterprise"],
        "billing.subscriptions.status": ["active", "upgraded", "downgraded", "cancelled"],
        "billing.invoices.currency": ["USD", "EUR", "GBP"],
        "billing.invoices.status": ["paid", "open"],
        "billing.invoice_lines.sku": ["starter", "growth", "scale", "enterprise", "SVC-FEE"],
        "billing.payments.method": ["card", "ach", "wire"],
        "erp.gl_accounts.acct_type": ["asset", "liability", "revenue", "cogs", "opex", "da"],
        "erp.journal_lines.entity_code": ["US01", "EU01", "UK01"],
        "hr.employees.dept": ["Engineering", "Sales", "Marketing", "Support", "G&A", "Product"],
    }
