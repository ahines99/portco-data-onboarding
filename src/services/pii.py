"""PII classifier (POD-303). Conservative: when signals disagree, flag the column."""

from __future__ import annotations

from src.domain.models import Confidence
from src.domain.project_models import PiiClass
from src.services.text import raw_tokens

NAME_LEXICON: dict[PiiClass, frozenset[str]] = {
    PiiClass.EMAIL: frozenset({"email", "mail", "smtp"}),
    PiiClass.PHONE: frozenset({"phone", "tel", "telephone", "mobile", "telf1", "fax"}),
    PiiClass.NATIONAL_ID: frozenset({"ssn", "sin", "nin", "passport"}),
    PiiClass.DOB: frozenset({"dob", "birth", "gbdat", "birthday"}),
    PiiClass.PAYMENT_CARD: frozenset({"card", "pan", "cc"}),
    PiiClass.ADDRESS: frozenset({"address", "street", "addr", "postcode", "zip"}),
    PiiClass.IP_ADDRESS: frozenset({"ip"}),
}
PERSON_NAME_COLUMNS = frozenset(
    {
        "first_name",
        "last_name",
        "full_name",
        "fname",
        "lname",
        "surname",
        "given_name",
        "family_name",
        "ename",
        "employee_name",
        "emp_name",
        "first_nm",
        "last_nm",
        "contact_name",
        "person_name",
    }
)
NON_PII_CARD_TOKENS = frozenset({"last4", "brand", "type", "expiry"})
SENSITIVE_TOKENS = frozenset(
    {
        "salary",
        "salaries",
        "wage",
        "wages",
        "compensation",
        "comp",
        "bonus",
        "payroll",
        "ssn",
        "dob",
        "birth",
        "gbdat",
        "medical",
        "diagnosis",
        "religion",
        "ethnicity",
    }
)


def is_sensitive_name(column: str) -> bool:
    """Columns whose individual values are sensitive even when they are not direct identifiers."""
    return bool(set(raw_tokens(column)) & SENSITIVE_TOKENS)


# Regex patterns evaluated in-adapter; only match counts leave the source.
PATTERNS: dict[str, tuple[str, bool]] = {
    "email": (r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", True),
    "phone": (r"\+?[0-9]{1,3}[ \-.()][0-9 ()\-.]{6,}[0-9]", True),
    "ssn": (r"[0-9]{3}-[0-9]{2}-[0-9]{4}", True),
    "card_digits": (r"[0-9]{13,19}", True),
    "iso_date": (r"[0-9]{4}-[0-9]{2}-[0-9]{2}", True),
    "us_date": (r"[0-9]{2}/[0-9]{2}/[0-9]{4}", True),
    "numeric_text": (r"-?[0-9]+(\.[0-9]+)?", True),
    "ipv4": (r"([0-9]{1,3}\.){3}[0-9]{1,3}", True),
    "test_prefix": (r"^(TEST|Test|test)\b", False),
    "contains_email": (r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", False),
    "contains_ssn": (r"(^|[^0-9-])[0-9]{3}-[0-9]{2}-[0-9]{4}([^0-9-]|$)", False),
}


def classify(
    column: str, family: str, non_null: int, counts: dict[str, int], luhn_valid: int = 0
) -> tuple[PiiClass | None, Confidence | None]:
    toks = set(raw_tokens(column))
    low = column.lower()

    def ratio(key: str) -> float:
        return counts.get(key, 0) / non_null if non_null else 0.0

    def lex(cls: PiiClass) -> bool:
        return bool(toks & NAME_LEXICON[cls])

    if family == "string" and non_null and luhn_valid / non_null >= 0.8 and not toks & NON_PII_CARD_TOKENS:
        return PiiClass.PAYMENT_CARD, Confidence.HIGH
    if lex(PiiClass.PAYMENT_CARD) and ({"number", "no", "num"} & toks or low in {"pan", "cc_number"}):
        return PiiClass.PAYMENT_CARD, Confidence.MEDIUM
    if ratio("ssn") >= 0.8:
        return PiiClass.NATIONAL_ID, Confidence.HIGH
    if lex(PiiClass.NATIONAL_ID) or low in {"national_id", "tax_id", "national_insurance_no"}:
        return PiiClass.NATIONAL_ID, Confidence.MEDIUM
    if ratio("email") >= 0.8:
        return PiiClass.EMAIL, Confidence.HIGH
    if lex(PiiClass.EMAIL):
        return PiiClass.EMAIL, Confidence.MEDIUM
    if lex(PiiClass.DOB) and family in {"date", "timestamp", "string"}:
        return PiiClass.DOB, Confidence.HIGH
    if low in PERSON_NAME_COLUMNS:
        return PiiClass.PERSON_NAME, Confidence.HIGH
    if ratio("phone") >= 0.8 or (lex(PiiClass.PHONE) and ratio("phone") >= 0.3):
        return PiiClass.PHONE, Confidence.HIGH if ratio("phone") >= 0.8 else Confidence.MEDIUM
    if lex(PiiClass.PHONE):
        return PiiClass.PHONE, Confidence.MEDIUM
    if lex(PiiClass.ADDRESS):
        return PiiClass.ADDRESS, Confidence.MEDIUM
    if ratio("ipv4") >= 0.8:
        return PiiClass.IP_ADDRESS, Confidence.HIGH
    if family == "string" and (ratio("contains_email") > 0.02 or ratio("contains_ssn") > 0.02):
        return PiiClass.FREE_TEXT, Confidence.HIGH
    return None, None
