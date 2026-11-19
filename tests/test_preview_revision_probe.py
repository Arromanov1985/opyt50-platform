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



def test_css_asset_fingerprint_must_match_stylesheet_mime(tmp_path, monkeypatch):
    local = tmp_path / "release09-dashboard.css"
    payload = b".vacancy-update-filter{min-height:44px}"
    local.write_bytes(payload)
    monkeypatch.setattr(
        probe, "build_opener",
        lambda *a: FakeOpener(FakeResponse(payload, "text/css; charset=utf-8")),
    )
    assert probe.probe_asset("/static/release09-dashboard.css", local)["result"] == "exact-match"
    monkeypatch.setattr(
        probe, "build_opener",
        lambda *a: FakeOpener(FakeResponse(payload, "text/html")),
    )
    assert probe.probe_asset("/static/release09-dashboard.css", local)["result"] == "not-stylesheet"


def test_public_html_revision_check_rejects_stale_entrypoint(tmp_path, monkeypatch):
    assets = {}
    for name in probe.CLIENT_ASSETS:
        data = (name + "-new-version").encode("utf-8")
        (tmp_path / name).write_bytes(data)
        assets[name] = probe.git_blob_revision(tmp_path / name)
    index = "\n".join(
        f'<script src="/static/{name}?v={revision}"></script>'
        for name, revision in assets.items()
    ).encode("utf-8")
    (tmp_path / "index.html").write_bytes(index)
    monkeypatch.setattr(probe, "STATIC", tmp_path)
    monkeypatch.setattr(
        probe, "build_opener",
        lambda *a: FakeOpener(FakeResponse(index, "text/html; charset=utf-8")),
    )
    exact = probe.probe_index_revisions()
    assert exact["result"] == "exact-match"
    assert all(exact["asset_revisions"].values())

    old = index.replace(assets["release02.js"].encode("ascii"), b"stale-revision")
    monkeypatch.setattr(
        probe, "build_opener",
        lambda *a: FakeOpener(FakeResponse(old, "text/html; charset=utf-8")),
    )
    mismatch = probe.probe_index_revisions()
    assert mismatch["result"] == "mismatch"
    assert mismatch["asset_revisions"]["release02.js"] is False
    assert mismatch["asset_revisions"]["app.js"] is True


def test_deployed_journal_check_requires_exact_html_and_get_only(monkeypatch):
    from urllib.parse import urlsplit
    from app.journal import ARTICLES, journal_index, journal_article

    pages = {"/journal": journal_index().body}
    pages.update({
        "/journal/" + article["slug"]: journal_article(article["slug"]).body
        for article in ARTICLES
    })
    requests = []

    class JournalOpener:
        def __init__(self, stale=False):
            self.stale = stale

        def open(self, request, timeout=12):
            requests.append(request)
            assert request.get_method() == "GET"
            assert request.get_header("Authorization") is None
            assert request.get_header("Cookie") is None
            path = urlsplit(request.full_url).path
            body = pages[path]
            if self.stale and path == "/journal":
                body = b"<html><h1>Old journal</h1></html>"
            return FakeResponse(body, "text/html; charset=utf-8")

    monkeypatch.setattr(probe, "build_opener", lambda *_args: JournalOpener())
    good = probe.probe_public_journal_pages()
    assert good["result"] == "exact-match"
    assert len(good["pages"]) == 4
    assert all(item["result"] == "exact-match" for item in good["pages"].values())
    assert len(requests) == 4

    monkeypatch.setattr(probe, "build_opener", lambda *_args: JournalOpener(stale=True))
    stale = probe.probe_public_journal_pages()
    assert stale["result"] == "unverified"
    assert stale["pages"]["/journal"]["result"] == "mismatch"


def test_search_metadata_probe_checks_both_resources_and_preview_noindex(monkeypatch):
    from urllib.parse import urlsplit
    from app.journal import journal_sitemap

    sitemap = journal_sitemap().body
    robots = b"User-agent: *\\nDisallow: /\\n"
    monkeypatch.setattr(probe, "BASE", "https://preview.twc1.net")
    requests = []

    class MetadataOpener:
        def __init__(self, stale=False):
            self.stale = stale

        def open(self, request, timeout=12):
            assert request.get_method() == "GET"
            assert request.get_header("Cookie") is None
            assert request.get_header("Authorization") is None
            requests.append(request)
            path = urlsplit(request.full_url).path
            if path == "/robots.txt":
                response = FakeResponse(robots if not self.stale else b"User-agent: *", "text/plain")
            else:
                assert path == "/sitemap.xml"
                response = FakeResponse(sitemap, "application/xml")
            response.headers["X-Robots-Tag"] = "noindex, nofollow"
            return response

    monkeypatch.setattr(probe, "build_opener", lambda *_args: MetadataOpener())
    assert probe.probe_public_search_metadata()["result"] == "exact-match"
    assert len(requests) == 2
    monkeypatch.setattr(probe, "build_opener", lambda *_args: MetadataOpener(stale=True))
    failed = probe.probe_public_search_metadata()
    assert failed["result"] == "unverified"
    assert failed["resources"]["/robots.txt"]["result"] == "mismatch"
