"""Read-only deployment verification: no credentials, cookies or mutation calls."""
import json
from email.message import Message
from urllib.error import HTTPError

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from scripts import probe_timeweb_preview as probe


@pytest.mark.parametrize(
    ("route", "expected"),
    list(probe.BACKEND_ROUTE_CAPABILITIES.values()),
)
def test_backend_capability_is_get_read_only_and_method_protected(tmp_path, route, expected):
    app = create_app(str(tmp_path / "test-release.db"))
    with TestClient(app) as client:
        response = client.get(route)
    assert response.status_code == 405
    assert expected in response.headers["allow"].upper().split(",")


@pytest.mark.parametrize(
    ("status", "allow", "content_type", "expected_result"),
    [
        (405, "PATCH", "application/json", "route-present-method-protected"),
        (405, "GET, POST", "application/json", "unexpected-response"),
        (405, "PATCH", "text/html", "unexpected-response"),
        (404, "", "application/json", "route-not-found"),
        (401, "", "application/json", "possibly-preview-auth-gate"),
    ],
)
def test_release_probe_never_calls_mutating_method(monkeypatch, status, allow, content_type, expected_result):
    requests = []

    class FakeOpener:
        def open(self, request, timeout):
            requests.append(request)
            headers = Message()
            headers.add_header("Allow", allow)
            headers.add_header("Content-Type", content_type)
            raise HTTPError(request.full_url, status, "sample", headers, None)

    monkeypatch.setattr(probe, "build_opener", lambda _handler: FakeOpener())
    result = probe.probe_backend_route("/api/employer/invitations/0/outcome", "PATCH")
    assert result["result"] == expected_result
    assert len(requests) == 1
    assert requests[0].get_method() == "GET"
    assert requests[0].get_header("Authorization") is None
    assert requests[0].get_header("Cookie") is None


@pytest.mark.parametrize(
    ("backend_ok", "journal_ok", "expected_evidence"),
    [
        (True, True, "frontend-and-backend-match"),
        (False, True, "backend-version-unverified"),
        (True, False, "journal-version-unverified"),
    ],
)
def test_release_report_distinguishes_frontend_parity_from_backend_parity(
    monkeypatch, tmp_path, backend_ok, journal_ok, expected_evidence
):
    monkeypatch.setattr(probe, "REPORT", tmp_path / "release-report.json")
    monkeypatch.setattr(probe.socket, "getaddrinfo", lambda *_args, **_kwargs: [(0,)])
    monkeypatch.setattr(probe, "probe", lambda path: {"status": 200, "result": "reachable"})
    monkeypatch.setattr(
        probe, "probe_asset",
        lambda _path, _source: {"status": 200, "result": "exact-match"},
    )
    monkeypatch.setattr(
        probe, "probe_index_revisions",
        lambda: {"status": 200, "result": "exact-match"},
    )
    monkeypatch.setattr(
        probe, "probe_private_draft_route",
        lambda: {"status": 401, "result": "present-and-protected"},
    )
    monkeypatch.setattr(
        probe, "probe_backend_route",
        lambda _route, _method: {
            "status": 405 if backend_ok else 404,
            "result": "route-present-method-protected" if backend_ok else "route-not-found",
        },
    )
    monkeypatch.setattr(
        probe, "probe_public_journal_pages",
        lambda: {"result": "exact-match" if journal_ok else "unverified", "pages": {}},
    )
    assert probe.main() == 0
    saved = json.loads(probe.REPORT.read_text(encoding="utf-8"))
    assert saved["release_evidence"] == expected_evidence
    assert saved["read_only"] is True
    assert len(saved["backend_routes"]) == len(probe.BACKEND_ROUTE_CAPABILITIES)
    assert saved["journal_pages"]["result"] == ("exact-match" if journal_ok else "unverified")
