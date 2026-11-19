"""Legal operator test profile: one editable source of truth, fail-closed.

This is *not* a legal opinion. Data are intentionally invalid until validated
against the actual IP registration and reviewed by counsel.
"""
from __future__ import annotations

from functools import lru_cache
from html import escape
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
PROFILE_PATH = Path(__file__).with_name("legal_operator.json")
APPROVAL_PATH = ROOT / "docs" / "legal" / "LEGAL_APPROVAL.md"
TEMPLATE_FIELDS = (
    "operator_name", "individual_full_name", "inn", "ogrnip", "address",
    "privacy_email", "rights_email", "support_email", "rkn_notification",
    "database_country", "backups_country", "mail_provider",
    "privacy_version", "terms_version", "consent_version",
    "effective_date", "retention_rules", "processors", "crossborder_policy",
    "request_process", "security_measures", "moderation_contact",
    "termination_procedure", "legal_basis_review", "consent_optional_scope",
    "notification_status",
)
REQUIRED_VALID = (
    "operator_name", "inn", "ogrnip", "address", "privacy_email",
    "rights_email", "rkn_notification", "database_country",
    "backups_country", "mail_provider", "privacy_version",
    "terms_version", "consent_version", "effective_date", "retention_rules",
    "processors", "crossborder_policy", "request_process", "security_measures",
    "moderation_contact", "termination_procedure", "legal_basis_review",
)
TEST_WORDS = ("тест", "не подтверж", "не утверж", "заменить", "пример", "example.invalid",
              "placeholder", "todo", "не подано", "проверить", "[", "]")


@lru_cache(maxsize=1)
def legal_profile() -> dict:
    return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))


def _inn_valid(value: str) -> bool:
    if not re.fullmatch(r"\d{12}", value):
        return False
    digits = [int(x) for x in value]
    control1 = sum(x*y for x,y in zip(digits, (7,2,4,10,3,5,9,4,6,8))) % 11 % 10
    control2 = sum(x*y for x,y in zip(digits, (3,7,2,4,10,3,5,9,4,6,8))) % 11 % 10
    return digits[10] == control1 and digits[11] == control2


def _ogrnip_valid(value: str) -> bool:
    return bool(re.fullmatch(r"\d{15}", value)) and (
        int(value[:14]) % 13 % 10 == int(value[-1])
    )


def readiness_failures(profile: dict | None = None, approval_text: str | None = None) -> list[str]:
    """Technical preconditions. Does not authenticate the IP or signoff."""
    p = profile if profile is not None else legal_profile()
    errors = []
    if p.get("status") != "APPROVED":
        errors.append("status is not APPROVED")
    for key in REQUIRED_VALID:
        value = str(p.get(key, "")).strip()
        if not value or any(token in value.casefold() for token in TEST_WORDS):
            errors.append(f"missing or test-only: {key}")
    if not _inn_valid(str(p.get("inn", ""))):
        errors.append("INN format or checksum invalid")
    if not _ogrnip_valid(str(p.get("ogrnip", ""))):
        errors.append("OGRNIP format or checksum invalid")
    for key in ("privacy_email", "rights_email", "support_email", "moderation_contact"):
        email = str(p.get(key, "")).strip().casefold()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email) or email.endswith(".invalid"):
            errors.append(f"invalid live mailbox: {key}")
    if approval_text is None:
        approval_text = APPROVAL_PATH.read_text(encoding="utf-8") if APPROVAL_PATH.exists() else ""
    requirements = (
        r"(?m)^STATUS: APPROVED\s*$",
        r"(?m)^RELEASE: \S+\s*$",
        r"(?m)^REVIEWED_AT: 20\d{2}-\d{2}-\d{2}\s*$",
        r"(?m)^REVIEWER: .{5,}$",
        r"(?m)^OWNER_SIGNOFF: .{5,}$",
    )
    if not all(re.search(pattern, approval_text) for pattern in requirements):
        errors.append("missing written legal and owner signoff")
    return errors


def legal_approved() -> bool:
    """Used as a release guard; never described as certification of legality."""
    return not readiness_failures()


def render_template(content: str, profile: dict | None = None, html: bool = True) -> str:
    p = profile if profile is not None else legal_profile()
    for key in TEMPLATE_FIELDS:
        value = str(p.get(key, ""))
        content = content.replace("{{" + key.upper() + "}}", escape(value, quote=True) if html else value)
    # The warning is always kept until a lawyer approves final document wording.
    if re.search(r"{{[A-Z_]+}}", content):
        raise ValueError("Unresolved legal template token")
    return content
