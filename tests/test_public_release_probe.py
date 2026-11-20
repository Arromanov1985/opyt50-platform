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


def test_public_manifest_identifies_current_renderer_and_all_journey_html(tmp_path):
    import hashlib
    from app.journal import journal_renderer_sha256
    from app.journal_paths import PATHS

    app = create_app(str(tmp_path / "journal-release.db"))
    with TestClient(app) as client:
        manifest = client.get("/api/public/journal/manifest").json()
        assert manifest["renderer_sha256"] == journal_renderer_sha256()
        assert len(manifest["renderer_sha256"]) == 64
        journey_urls = {"/journal/paths"} | {"/journal/paths/" + path["slug"] for path in PATHS}
        assert journey_urls <= manifest["pages"].keys()
        for path in journey_urls:
            page = client.get(path)
            assert page.status_code == 200
            assert manifest["pages"][path] == hashlib.sha256(page.content).hexdigest()


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
    (
        "backend_ok", "journal_ok", "search_ok", "community_page_result",
        "community_api_result", "asset_name", "asset_result", "expected_evidence",
    ),
    [
        (True, True, True, "exact-match", "present-and-protected", "community.css", "exact-match", "frontend-and-backend-match"),
        (False, True, True, "exact-match", "present-and-protected", "community.css", "exact-match", "backend-version-unverified"),
        (True, False, True, "exact-match", "present-and-protected", "community.css", "exact-match", "journal-version-unverified"),
        (True, True, False, "exact-match", "present-and-protected", "community.css", "exact-match", "search-metadata-unverified"),
        (True, True, True, "mismatch", "present-and-protected", "community.css", "exact-match", "community-version-unverified"),
        (True, True, True, "route-not-found", "present-and-protected", "community.css", "exact-match", "community-version-unverified"),
        (True, True, True, "exact-match", "route-not-found", "community.css", "exact-match", "community-version-unverified"),
        (True, True, True, "exact-match", "unexpected-public-access", "community.css", "exact-match", "community-version-unverified"),
        (True, True, True, "exact-match", "possibly-preview-auth-gate", "community.css", "exact-match", "community-version-unverified"),
        (True, True, True, "exact-match", "present-and-protected", "community.css", "mismatch", "frontend-version-mismatch"),
        (True, True, True, "exact-match", "present-and-protected", "community.css", "http-error", "unverified"),
    ] + [
        (True, True, True, "exact-match", "present-and-protected", asset, "mismatch", "frontend-version-mismatch")
        for asset in ("journal.css", "vacancy-share.css", "employer-share.css", "employer-directory.css", "release09-mobile.css")
    ],
)
def test_release_report_distinguishes_frontend_parity_from_backend_parity(
    monkeypatch, tmp_path, backend_ok, journal_ok, search_ok, community_page_result,
    community_api_result, asset_name, asset_result, expected_evidence,
):
    monkeypatch.setattr(probe, "REPORT", tmp_path / "release-report.json")
    monkeypatch.setattr(probe.socket, "getaddrinfo", lambda *_args, **_kwargs: [(0,)])
    monkeypatch.setattr(probe, "probe", lambda path: {"status": 200, "result": "reachable"})
    monkeypatch.setattr(
        probe, "probe_asset",
        lambda _path, source: {
            "result": asset_result if source.name == asset_name else "exact-match",
        },
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
    monkeypatch.setattr(
        probe, "probe_public_search_metadata",
        lambda: {"result": "exact-match" if search_ok else "unverified", "resources": {}},
    )
    monkeypatch.setattr(
        probe, "probe_public_community_page",
        lambda: {"result": community_page_result},
    )
    monkeypatch.setattr(
        probe, "probe_private_route",
        lambda _route: {"result": community_api_result},
    )
    assert probe.main() == 0
    saved = json.loads(probe.REPORT.read_text(encoding="utf-8"))
    assert saved["release_evidence"] == expected_evidence
    assert saved["read_only"] is True
    assert len(saved["backend_routes"]) == len(probe.BACKEND_ROUTE_CAPABILITIES)
    assert saved["journal_pages"]["result"] == ("exact-match" if journal_ok else "unverified")
    assert saved["search_metadata"]["result"] == ("exact-match" if search_ok else "unverified")
    assert saved["community_page"]["result"] == community_page_result
    assert len(saved["community_api"]) == len(probe.COMMUNITY_PRIVATE_ROUTES)
    assert {"community.js", "community.css"} <= saved["deployed_assets"].keys()
    assert {"journal.css", "vacancy-share.css", "employer-share.css", "employer-directory.css"} <= saved["deployed_assets"].keys()


@pytest.mark.parametrize("route", probe.COMMUNITY_PRIVATE_ROUTES.values())
def test_community_private_routes_deny_anonymous_read(tmp_path, route):
    app = create_app(str(tmp_path / "test-community-release.db"))
    with TestClient(app) as client:
        response = client.get(route)
    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/json")


def test_release_probe_does_not_attempt_community_reads_after_dns_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(probe, "REPORT", tmp_path / "release-report.json")

    def unavailable_dns(*_args, **_kwargs):
        raise OSError("DNS unavailable")

    def unexpected_request(*_args, **_kwargs):
        raise AssertionError("DNS failure must not trigger HTTP requests")

    monkeypatch.setattr(probe.socket, "getaddrinfo", unavailable_dns)
    monkeypatch.setattr(probe, "build_opener", unexpected_request)
    assert probe.main() == 0
    report = json.loads(probe.REPORT.read_text(encoding="utf-8"))
    assert report["release_evidence"] == "unverified"
    assert report["community_page"]["result"] == "not-tested-dns-failure"
    assert all(item["result"] == "not-tested-dns-failure" for item in report["community_api"].values())
