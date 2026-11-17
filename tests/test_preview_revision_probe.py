"""Unit tests for the read-only remote release-fingerprint probe."""
from email.message import Message
from urllib.error import HTTPError

from scripts import probe_timeweb_preview as probe


class FakeResponse:
    status = 200

    def __init__(self, body=b"console.log('release')", content_type="application/javascript"):
        self.body = body
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, n):
        return self.body[:n]


class FakeOpener:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error

    def open(self, request, timeout=10):
        assert request.get_method() == "GET"
        if self.error:
            raise self.error
        return self.response


def error(status, content_type="application/json", challenge=""):
    headers = Message()
    headers["Content-Type"] = content_type
    if challenge:
        headers["WWW-Authenticate"] = challenge
    return HTTPError("https://example.invalid/resource", status, "test", headers, None)


def test_asset_fingerprint_matches_exact_bytes(tmp_path, monkeypatch):
    payload = b"console.log('release')"
    local = tmp_path / "app.js"
    local.write_bytes(payload)
    monkeypatch.setattr(probe, "build_opener", lambda *a: FakeOpener(FakeResponse(payload)))
    result = probe.probe_asset("/static/app.js", local)
    assert result["result"] == "exact-match"
    assert len(result["expected_sha256"]) == 64
    assert result["expected_sha256"] == result["observed_sha256"]


def test_old_build_or_html_response_never_confirms_release(tmp_path, monkeypatch):
    local = tmp_path / "app.js"
    local.write_bytes(b"console.log('new')")
    monkeypatch.setattr(
        probe, "build_opener",
        lambda *a: FakeOpener(FakeResponse(b"console.log('old')")),
    )
    assert probe.probe_asset("/static/app.js", local)["result"] == "mismatch"
    monkeypatch.setattr(
        probe, "build_opener",
        lambda *a: FakeOpener(FakeResponse(b"<html>Login</html>", "text/html")),
    )
    assert probe.probe_asset("/static/app.js", local)["result"] == "not-javascript"


def test_protected_endpoint_evidence_requires_json_401_or_403(monkeypatch):
    monkeypatch.setattr(
        probe, "build_opener", lambda *a: FakeOpener(error=error(401)),
    )
    assert probe.probe_private_draft_route()["result"] == "present-and-protected"
    monkeypatch.setattr(
        probe, "build_opener", lambda *a: FakeOpener(error=error(404)),
    )
    assert probe.probe_private_draft_route()["result"] == "route-not-found"
    monkeypatch.setattr(
        probe, "build_opener",
        lambda *a: FakeOpener(error=error(401, "text/html", 'Basic realm="preview"')),
    )
    assert probe.probe_private_draft_route()["result"] == "possibly-preview-auth-gate"


def test_public_drafts_response_is_never_marked_protected(monkeypatch):
    monkeypatch.setattr(probe, "build_opener", lambda *a: FakeOpener(FakeResponse()))
    assert probe.probe_private_draft_route()["result"] == "unexpected-public-access"
