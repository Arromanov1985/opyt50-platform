"""Noindex previews of UNAPPROVED legal documents.

These pages are deliberately drafts. They do NOT satisfy the obligations
of a registered and verified data controller. Never merge to the live site
without replacing placeholders, lawyer sign-off, and changing the status.
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from .legal_config import render_template

STATIC = Path(__file__).resolve().parent / "static"
LEGAL_DRAFT_ROUTES = {
    "/privacy": "privacy.html",
    "/terms": "terms.html",
    "/legal/consent": "consent.html",
}


def install_legal_draft_routes(app: FastAPI) -> None:
    def handler_for(filename: str):
        def page():
            markup = render_template((STATIC / filename).read_text(encoding="utf-8"))
            return HTMLResponse(
                markup,
                headers={
                    "Cache-Control": "no-store",
                    "X-Robots-Tag": "noindex, nofollow",
                },
            )
        return page

    for path, filename in LEGAL_DRAFT_ROUTES.items():
        app.add_api_route(path, handler_for(filename), methods=["GET"], include_in_schema=False)
