"""Review-only retention policy registry. No TTL defaults or deletion scheduling.

The central JSON file remains explicitly TEST_ONLY until every category has
legal basis, verified trigger, retention period and human signoff.
"""
from __future__ import annotations
import json
from pathlib import Path

REGISTER = Path(__file__).resolve().parents[1] / "docs" / "legal" / "RETENTION_REGISTER.json"
REQUIRED = frozenset({
    "account_identity", "candidate_profiles", "employer_profiles", "vacancies",
    "applications", "introductions", "communications", "auth_secrets",
    "security_traces", "legal_acceptances", "rights_requests", "complaints",
    "aggregated_analytics", "host_backups", "hosting_logs", "third_party_copies",
})
ALLOWED_DISPOSITION = {"erase", "anonymize", "retain_with_legal_basis"}


def retention_readiness(path: Path = REGISTER) -> dict:
    doc = json.loads(path.read_text(encoding="utf-8"))
    categories = doc.get("categories")
    if not isinstance(categories, list):
        raise ValueError("Retention categories must be a list")
    errors = []
    seen = set()
    summary = []
    for item in categories:
        if not isinstance(item, dict):
            errors.append("invalid category")
            continue
        code = str(item.get("code", ""))
        if code in seen:
            errors.append(f"duplicate category: {code}")
        seen.add(code)
        duration = item.get("retention_days")
        approved = (
            item.get("approval_status") == "APPROVED"
            and item.get("legal_basis") not in ("", None, "NOT_APPROVED")
            and item.get("disposition") in ALLOWED_DISPOSITION
            and isinstance(item.get("verified_by"), str)
            and len(item["verified_by"].strip()) >= 5
            and isinstance(duration, int)
            and not isinstance(duration, bool)
            and duration >= 0
            and bool(item.get("start_event"))
        )
        if not approved:
            errors.append(f"category not legally approved: {code}")
        summary.append({
            "code": code,
            "purpose": item.get("purpose", ""),
            "approval_status": item.get("approval_status", "MISSING"),
            "period_defined": isinstance(duration, int) and not isinstance(duration, bool),
            "disposition_defined": item.get("disposition") in ALLOWED_DISPOSITION,
        })
    missing = REQUIRED - seen
    extra = seen - REQUIRED
    if missing:
        errors.append("missing categories: " + ",".join(sorted(missing)))
    if extra:
        errors.append("unknown categories: " + ",".join(sorted(extra)))
    if doc.get("status") != "APPROVED" or not doc.get("effective_date"):
        errors.append("registry itself is not signed and effective")
    return {
        "approved": not errors,
        "status": doc.get("status", "INVALID"),
        "total": len(categories),
        "approved_count": sum(x["approval_status"] == "APPROVED" for x in summary),
        "categories": summary,
        "blockers": errors,
        "automatic_purge_enabled": False,
        "operator": doc.get("operator"),
    }
