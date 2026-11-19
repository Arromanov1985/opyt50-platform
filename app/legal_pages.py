"""Noindex previews of UNAPPROVED legal documents.

These pages are deliberately drafts. They do NOT satisfy the obligations
of a registered and verified data controller. Never merge to the live site
without replacing placeholders, lawyer sign-off, and changing the status.
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

STATIC = Path(__file__).resolve().parent / "static"
LEGAL_DRAFT_ROUTES = {
    "/privacy": "privacy.html",
    "/terms": "terms.html",
    "/legal/consent": "consent.html",
}


def install_legal_draft_routes(app: FastAPI) -> None:
    for path, filename in LEGAL_DRAFT_ROUTES.items():
        def page(filename=filename):
            return FileResponse(
                STATIC / filename,
                media_type="text/html; charset=utf-8",
                headers={
                    "Cache-Control": "no-store",
                    "X-Robots-Tag": "noindex, nofollow",
                },
            )
        app.add_api_route(path, page, methods=["GET"], include_in_schema=False)
