#!/usr/bin/env python3
"""Mechanical prerelease legal *readiness* checks, never a legal opinion.

This script deliberately fails on the current unresolved STAZHNO legal
baseline. It verifies presence of public artifacts and an explicit human
signoff. Truthfulness and legal adequacy of their content require a lawyer.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from app.legal_config import readiness_failures, legal_profile


def verify(root: Path) -> list[tuple[str, bool, str]]:
    site = root / "app" / "static"
    index_path = site / "index.html"
    page = index_path.read_text(encoding="utf-8") if index_path.is_file() else ""
    privacy = site / "privacy.html"
    terms = site / "terms.html"
    approval = root / "docs" / "legal" / "LEGAL_APPROVAL.md"

    def public_page(path: Path, required: tuple[str, ...]) -> bool:
        if not path.is_file():
            return False
        text = path.read_text(encoding="utf-8").casefold()
        if "{{" in text:  # Unrendered test-only page is never an approved publication.
            return False
        forbidden = (
            "не утверждено", "не вступил", "не вступили", "не публиковать",
            "не применяется", "draft", "проект —", "[подтвердить",
            "[email", "[адрес", "[рабочий", "[огрнип", "[инн",
            "проверить по егрип",
        )
        return (
            all(token.casefold() in text for token in required)
            and not any(item in text for item in forbidden)
        )

    # These checks intentionally do not accept guessed placeholder identities:
    # they are only structural checks; independent human review is mandatory.
    approval_text = approval.read_text(encoding="utf-8") if approval.is_file() else ""
    status = bool(re.search(r"(?m)^STATUS:\s*APPROVED\s*$", approval_text))
    scope = bool(re.search(r"(?mi)^RELEASE:\s*(?!TBD|TODO|PLACEHOLDER)[^\s]+", approval_text))
    reviewer = bool(re.search(r"(?mi)^REVIEWER:\s*(?!TBD|TODO|PLACEHOLDER).{5,}", approval_text))
    date = bool(re.search(r"(?m)^REVIEWED_AT:\s*20\d{2}-\d{2}-\d{2}\s*$", approval_text))
    banned = bool(re.search(r"(?i)\b(?:placeholder|tbd|todo|example\.invalid)\b", approval_text))

    return [
        ("Verified IP operator profile", not readiness_failures(legal_profile()),
         "Replace all test fields in app/legal_operator.json and obtain written signoff."),
        ("Public privacy-policy page", public_page(privacy, ("персональных данных", "оператор")),
         "Publish a lawyer-reviewed /privacy document, not a template or invented operator."),
        ("Public user-terms page", public_page(terms, ("пользователь", "условия")),
         "Publish reviewed /terms addressing candidates and employers."),
        ("Privacy-policy link in homepage", 'href="/privacy"' in page,
         "Make privacy policy reachable from every personal-data collection flow."),
        ("Terms link in homepage", 'href="/terms"' in page,
         "Link public site terms in the footer and registration form."),
        ("Legal information near registration", 'id="auth-legal-notice"' in page and
         not any(item in page.casefold() for item in (
             "документы пока не вступили в силу", "юридические документы: проект",
             "макет юридической приёмки",
         )),
         "Replace draft notices with approved basis/consents and evidentiary recording."),
        ("Visible operator identification", 'id="legal-operator-info"' in page and
         "mailto:" in page and "ожидают подтверждения" not in page.casefold(),
         "Show the verified site owner's real name, address and legal contact email."),
        ("Data-subject request channel", 'id="privacy-request-contact"' in page,
         "Explain and publish a reachable channel for correction, access and erasure requests."),
        ("Human legal release signoff", status and scope and reviewer and date and not banned,
         "Require a genuine reviewer/owner approval in docs/legal/LEGAL_APPROVAL.md for this release."),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    checks = verify(args.root.resolve())
    passed = all(ok for _, ok, _ in checks)
    if args.json:
        print(json.dumps({
            "result": "prerequisites-present" if passed else "BLOCKED",
            "checks": [{"name": name, "ok": ok, "next_step": note}
                       for name, ok, note in checks],
            "disclaimer": "Only structural readiness: legal validity requires human legal review",
        }, ensure_ascii=False, indent=2))
    else:
        print("STAZHNO legal-release technical prerequisites:",
              "PRESENT" if passed else "BLOCKED")
        for name, ok, note in checks:
            print(("OK" if ok else "BLOCKED") + " | " + name)
            if not ok:
                print("  " + note)
        print("This check cannot certify legality; independent legal signoff is mandatory.")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
