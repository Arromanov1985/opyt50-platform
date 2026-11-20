"""Unit tests for the read-only remote release-fingerprint probe."""
from email.message import Message
from urllib.error import HTTPError

import pytest

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
    from app.journal_paths import PATHS, path_detail, paths_index

    pages = {"/journal": journal_index().body}
    pages.update({
        "/journal/" + article["slug"]: journal_article(article["slug"]).body
        for article in ARTICLES
    })
    pages["/journal/paths"] = paths_index(ARTICLES).body
    pages.update({"/journal/paths/" + path["slug"]: path_detail(path["slug"], ARTICLES).body
                  for path in PATHS})
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
    # Seed parity is still useful diagnostic evidence, but the new renderer
    # digest is required before this release can be marked published.
    assert good["result"] == "unverified"
    assert good["catalog_source"] == "seed-catalog"
    assert good["renderer"]["result"] == "unverified"
    assert len(good["pages"]) == len(ARTICLES) + 2 + len(PATHS)
    assert all(item["result"] == "exact-match" for item in good["pages"].values())
    assert len(requests) == len(pages) + 1  # public manifest plus all page GETs

    monkeypatch.setattr(probe, "build_opener", lambda *_args: JournalOpener(stale=True))
    stale = probe.probe_public_journal_pages()
    assert stale["result"] == "unverified"
    assert stale["pages"]["/journal"]["result"] == "mismatch"


def published_journal_fixture(articles=None):
    """A deployed CMS catalog with this checkout's actual page renderers."""
    import hashlib
    from app.journal import ARTICLES, journal_index, journal_article, journal_renderer_sha256
    from app.journal_paths import path_detail, paths_index, visible_paths

    if articles is None:
        articles = ARTICLES
    bodies = {"/journal": journal_index(articles).body,
              "/journal/paths": paths_index(articles).body}
    bodies.update({"/journal/" + article["slug"]: journal_article(article["slug"], articles).body
                   for article in articles})
    bodies.update({"/journal/paths/" + path["slug"]: path_detail(path["slug"], articles).body
                   for path in visible_paths(articles)})
    manifest = {"pages": {path: hashlib.sha256(body).hexdigest() for path, body in bodies.items()},
                "renderer_sha256": journal_renderer_sha256()}
    return bodies, manifest


def install_journal_opener(monkeypatch, bodies, manifest):
    import json
    from urllib.parse import urlsplit

    requests = []

    class PublishedJournalOpener:
        def open(self, request, timeout=12):
            assert request.get_method() == "GET"
            assert request.get_header("Authorization") is None
            assert request.get_header("Cookie") is None
            assert request.full_url.startswith(probe.BASE + "/")
            path = urlsplit(request.full_url).path
            requests.append(path)
            if path == "/api/public/journal/manifest":
                return FakeResponse(json.dumps(manifest).encode(), "application/json")
            if path not in bodies:
                raise error(404)
            return FakeResponse(bodies[path], "text/html; charset=utf-8")

    monkeypatch.setattr(probe, "build_opener", lambda *_args: PublishedJournalOpener())
    return requests


def test_journal_manifest_probes_every_route_and_accepts_published_cms_edits(monkeypatch):
    from copy import deepcopy
    from app.journal import ARTICLES
    from app.journal_paths import PATHS

    articles = deepcopy(ARTICLES)
    articles[0]["description"] = "Редакция обновила этот текст после выпуска приложения."
    bodies, manifest = published_journal_fixture(articles)
    requests = install_journal_opener(monkeypatch, bodies, manifest)
    result = probe.probe_public_journal_pages()
    assert result["result"] == "exact-match"
    assert result["renderer"]["result"] == "exact-match"
    assert result["catalog_source"] == "cms-public-manifest"
    assert set(result["pages"]) == set(bodies)
    assert set(requests) == set(bodies) | {"/api/public/journal/manifest"}
    for path in {"/journal/paths"} | {"/journal/paths/" + item["slug"] for item in PATHS}:
        assert result["pages"][path]["result"] == "exact-match"
        assert result["pages"][path]["expected_sha256"] == manifest["pages"][path]


@pytest.mark.parametrize("missing_in_manifest", [False, True])
def test_missing_journey_never_confirms_release(monkeypatch, missing_in_manifest):
    bodies, manifest = published_journal_fixture()
    missing = "/journal/paths/delitsya-opytom"
    del bodies[missing]
    if missing_in_manifest:
        del manifest["pages"][missing]
    requests = install_journal_opener(monkeypatch, bodies, manifest)
    result = probe.probe_public_journal_pages()
    assert result["result"] == "unverified"
    assert missing in requests
    assert result["pages"][missing]["result"] == "route-not-found"


@pytest.mark.parametrize("renderer", [None, "0" * 64])
def test_self_consistent_manifest_from_old_renderer_never_confirms_release(monkeypatch, renderer):
    import hashlib

    bodies, manifest = published_journal_fixture()
    stale_route = "/journal/paths/delitsya-opytom"
    bodies[stale_route] = b"<html>Old route without counted CTA</html>"
    manifest["pages"][stale_route] = hashlib.sha256(bodies[stale_route]).hexdigest()
    if renderer is None:
        manifest.pop("renderer_sha256")
    else:
        manifest["renderer_sha256"] = renderer
    install_journal_opener(monkeypatch, bodies, manifest)
    result = probe.probe_public_journal_pages()
    assert result["result"] == "unverified"
    assert result["renderer"]["result"] == ("mismatch" if renderer else "unverified")
    assert result["pages"][stale_route]["result"] == "exact-match"


def test_stale_route_body_cannot_pass_current_manifest(monkeypatch):
    bodies, manifest = published_journal_fixture()
    stale_route = "/journal/paths/novye-navyki"
    bodies[stale_route] = b"<html>Cached earlier route</html>"
    install_journal_opener(monkeypatch, bodies, manifest)
    result = probe.probe_public_journal_pages()
    assert result["result"] == "unverified"
    assert result["pages"][stale_route]["result"] == "mismatch"


def test_hidden_journey_is_derived_from_current_published_articles(monkeypatch):
    from app.journal import ARTICLES
    from app.journal_paths import PATHS

    hidden = PATHS[1]
    hidden_slugs = {slug for slug, _label in hidden["steps"]}
    articles = [article for article in ARTICLES if article["slug"] not in hidden_slugs]
    bodies, manifest = published_journal_fixture(articles)
    requests = install_journal_opener(monkeypatch, bodies, manifest)
    result = probe.probe_public_journal_pages()
    assert result["result"] == "exact-match"
    assert "/journal/paths/" + hidden["slug"] not in requests
    assert set(result["pages"]) == set(bodies)


@pytest.mark.parametrize("unsafe_path", [
    "https://example.invalid/journal/article",
    "/api/admin/users",
    "/journal/paths/../../api/admin/users",
    "/journal/paths/not-approved",
    "/journal/article?redirect=/api/admin/users",
])
def test_editorial_manifest_never_expands_probe_to_unapproved_urls(monkeypatch, unsafe_path):
    bodies, manifest = published_journal_fixture()
    manifest["pages"][unsafe_path] = "0" * 64
    requests = install_journal_opener(monkeypatch, bodies, manifest)
    result = probe.probe_public_journal_pages()
    assert result["result"] == "unverified"
    assert result["manifest_result"] == "unavailable-or-invalid"
    assert set(requests) == set(bodies) | {"/api/public/journal/manifest"}
    assert unsafe_path not in requests


def test_search_metadata_probe_checks_both_resources_and_preview_noindex(monkeypatch):
    from urllib.parse import urlsplit
    from app.journal import journal_sitemap

    sitemap = journal_sitemap().body
    robots = b"User-agent: *\nDisallow: /\n"
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


@pytest.mark.parametrize(
    ("response_kind", "expected_result"),
    [
        ("current", "exact-match"),
        ("stale", "mismatch"),
        ("wrong-mime", "not-html"),
        ("missing", "route-not-found"),
    ],
)
def test_community_probe_requires_exact_public_shell_without_fetching_profiles(
    monkeypatch, response_kind, expected_result
):
    from urllib.parse import urlsplit
    from app.community_pages import community_page

    current = community_page(mode="directory").body
    requests = []

    class CommunityOpener:
        def open(self, request, timeout=12):
            requests.append(request)
            assert request.get_method() == "GET"
            assert urlsplit(request.full_url).path == "/community"
            assert request.get_header("Cookie") is None
            assert request.get_header("Authorization") is None
            if response_kind == "missing":
                raise error(404)
            if response_kind == "stale":
                return FakeResponse(b"<html>Previous release</html>", "text/html")
            mime = "application/json" if response_kind == "wrong-mime" else "text/html; charset=utf-8"
            return FakeResponse(current, mime)

    monkeypatch.setattr(probe, "build_opener", lambda *_args: CommunityOpener())
    result = probe.probe_public_community_page()
    assert result["result"] == expected_result
    assert len(requests) == 1
    if expected_result == "exact-match":
        assert result["expected_sha256"] == result["observed_sha256"]


@pytest.mark.parametrize("route", probe.COMMUNITY_PRIVATE_ROUTES.values())
def test_private_community_probe_never_reads_response_content_or_uses_session(monkeypatch, route):
    requests = []

    class PrivateResponse(FakeResponse):
        def read(self, _n):
            raise AssertionError("Private data must not be read even if an API is misconfigured")

    class PrivateOpener:
        def open(self, request, timeout=10):
            requests.append(request)
            assert request.get_method() == "GET"
            assert request.get_header("Authorization") is None
            assert request.get_header("Cookie") is None
            return PrivateResponse()

    monkeypatch.setattr(probe, "build_opener", lambda *_args: PrivateOpener())
    assert probe.probe_private_route(route)["result"] == "unexpected-public-access"
    assert len(requests) == 1
    assert requests[0].full_url == probe.BASE + route
