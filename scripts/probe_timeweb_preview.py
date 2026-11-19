"""Read-only external reachability check for the temporary Timeweb preview.

Only DNS + unauthenticated GET requests. Never uses credentials, cookies,
real user information, or mutation endpoints. The report is diagnostic, not
a PR pass/fail gate: an unavailable preview must not hide valid PR test results.
"""
import hashlib
import json
import os
import socket
import ssl
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPRedirectHandler


DEFAULT_BASE = "https://arromanov1985-opyt50-platform-fdd8.twc1.net"
BASE = os.getenv("STAZHNO_PREVIEW_URL", DEFAULT_BASE).rstrip("/")
REPORT = Path(os.getenv("STAZHNO_PREVIEW_REPORT", "preview-reachability.json"))
STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
CLIENT_ASSETS = ("app.js", "release02.js", "vacancy-wizard.js", "release09-dashboard.css")
ADDITIONAL_ASSETS = ("journal.js", "growth-admin.css")
COMMUNITY_ASSETS = ("community.js", "community.css")
CHECKED_ASSETS = CLIENT_ASSETS + ADDITIONAL_ASSETS + COMMUNITY_ASSETS
COMMUNITY_PRIVATE_ROUTES = {
    "profile": "/api/community/profile",
    "connections": "/api/community/connections",
    "moderation_profiles": "/api/admin/community/profiles",
    "moderation_reports": "/api/admin/community/reports",
}


def git_blob_revision(path):
    payload = path.read_bytes()
    return hashlib.sha1(
        f"blob {len(payload)}".encode("ascii") + bytes([0]) + payload,
        usedforsecurity=False,
    ).hexdigest()[:12]



class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def probe(path):
    request = Request(
        BASE + path,
        headers={"User-Agent": "Stazhno-Preview-ReadOnly-Probe/1.0"},
        method="GET",
    )
    try:
        with build_opener(NoRedirect).open(request, timeout=10) as response:
            return {"status": response.status, "result": "reachable"}
    except HTTPError as error:
        # Preview login (HTTP Basic) is expected for / when enabled.
        return {
            "status": error.code,
            "result": "password-protected" if error.code == 401 else "http-error",
        }
    except (URLError, OSError, ssl.SSLError, TimeoutError) as error:
        return {"result": "connection-error", "type": type(error).__name__}



def probe_asset(path, local_path):
    """Compare exact public JS bytes against the checked-out release.

    A 200 status alone is not a revision check: a cached/older build can
    respond successfully. Do not save or print downloaded application code.
    """
    expected = hashlib.sha256(local_path.read_bytes()).hexdigest()
    request = Request(
        BASE + path + "?revision_check=" + expected[:16],
        headers={
            "User-Agent": "Stazhno-Preview-ReadOnly-Probe/1.0",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
        method="GET",
    )
    try:
        with build_opener(NoRedirect).open(request, timeout=12) as response:
            payload = response.read(2_000_001)
            if len(payload) > 2_000_000:
                return {"status": response.status, "result": "asset-too-large"}
            content_type = response.headers.get("Content-Type", "").lower()
            if local_path.suffix == ".css":
                accepted = content_type.startswith("text/css")
                error_result = "not-stylesheet"
            else:
                accepted = content_type.startswith(
                    ("text/javascript", "application/javascript", "application/x-javascript")
                )
                error_result = "not-javascript"
            if not accepted:
                return {"status": response.status, "result": error_result}
            observed = hashlib.sha256(payload).hexdigest()
            return {
                "status": response.status,
                "result": "exact-match" if observed == expected else "mismatch",
                "expected_sha256": expected,
                "observed_sha256": observed,
                "bytes": len(payload),
            }
    except HTTPError as error:
        return {
            "status": error.code,
            "result": "password-protected" if error.code == 401 else "http-error",
        }
    except (URLError, OSError, ssl.SSLError, TimeoutError) as error:
        return {"result": "connection-error", "type": type(error).__name__}


def probe_index_revisions():
    """Ensure the actual public HTML references the new versioned JS/CSS URLs."""
    index = STATIC / "index.html"
    expected = {
        name: f"/static/{name}?v={git_blob_revision(STATIC / name)}"
        for name in CLIENT_ASSETS
    }
    digest = hashlib.sha256(index.read_bytes()).hexdigest()[:16]
    request = Request(
        BASE + "/?revision_check=" + digest,
        headers={
            "User-Agent": "Stazhno-Preview-ReadOnly-Probe/1.0",
            "Cache-Control": "no-cache", "Pragma": "no-cache",
        },
        method="GET",
    )
    try:
        with build_opener(NoRedirect).open(request, timeout=12) as response:
            content_type = response.headers.get("Content-Type", "").lower()
            payload = response.read(1_000_001)
            if len(payload) > 1_000_000:
                return {"status": response.status, "result": "html-too-large"}
            if not content_type.startswith("text/html"):
                return {"status": response.status, "result": "not-html"}
            html = payload.decode("utf-8", errors="replace")
            matches = {name: reference in html for name, reference in expected.items()}
            return {
                "status": response.status,
                "result": "exact-match" if all(matches.values()) else "mismatch",
                "asset_revisions": matches,
            }
    except HTTPError as error:
        return {"status": error.code, "result": "http-error"}
    except (URLError, OSError, ssl.SSLError, TimeoutError) as error:
        return {"result": "connection-error", "type": type(error).__name__}


def probe_private_route(path):
    """Unauthenticated read-only request. Protected API returns JSON 401, not 404."""
    request = Request(
        BASE + path,
        headers={"User-Agent": "Stazhno-Preview-ReadOnly-Probe/1.0"},
        method="GET",
    )
    try:
        with build_opener(NoRedirect).open(request, timeout=10) as response:
            # Do not read or retain a response that might contain private data.
            return {"status": response.status, "result": "unexpected-public-access"}
    except HTTPError as error:
        content_type = error.headers.get("Content-Type", "").lower()
        challenge = error.headers.get("WWW-Authenticate", "")
        if error.code in (401, 403) and "json" in content_type and "basic" not in challenge.lower():
            return {"status": error.code, "result": "present-and-protected"}
        if error.code == 404:
            return {"status": 404, "result": "route-not-found"}
        if error.code == 401:
            return {"status": 401, "result": "possibly-preview-auth-gate"}
        return {"status": error.code, "result": "unexpected-status"}
    except (URLError, OSError, ssl.SSLError, TimeoutError) as error:
        return {"result": "connection-error", "type": type(error).__name__}


def probe_private_draft_route():
    return probe_private_route("/api/employer/vacancy-drafts")


# GET on a PATCH/POST-only route is safe and never executes its mutation.
# Unlike a public release string, the 405 + Allow evidence confirms that the
# corresponding backend handler is actually deployed. No cookies or tokens.
BACKEND_ROUTE_CAPABILITIES = {
    "direct_invitation_outcome": ("/api/employer/invitations/0/outcome", "PATCH"),
    "candidate_invitation_response": ("/api/candidate/invitations/0/respond", "POST"),
    "employer_contact_unlock": ("/api/employer/invitations/0/demo-pay", "POST"),
    "growth_event": ("/api/growth/event", "POST"),
}


def probe_backend_route(path, expected_method):
    request = Request(
        BASE + path,
        headers={"User-Agent": "Stazhno-Preview-ReadOnly-Probe/1.0"},
        method="GET",
    )
    try:
        with build_opener(NoRedirect).open(request, timeout=10) as response:
            return {"status": response.status, "result": "unexpected-get-success"}
    except HTTPError as error:
        allow = {method.strip().upper() for method in error.headers.get("Allow", "").split(",")}
        content_type = error.headers.get("Content-Type", "").lower()
        if error.code == 405 and expected_method in allow and "json" in content_type:
            return {"status": 405, "result": "route-present-method-protected"}
        if error.code == 404:
            return {"status": 404, "result": "route-not-found"}
        if error.code in (401, 403):
            return {"status": error.code, "result": "possibly-preview-auth-gate"}
        return {"status": error.code, "result": "unexpected-response"}
    except (URLError, OSError, ssl.SSLError, TimeoutError) as error:
        return {"result": "connection-error", "type": type(error).__name__}



def probe_public_journal_pages():
    """Compare exact bytes of public editorial HTML with the checked-out code.

    No accounts, cookies, contact fields, POSTs or external services.
    """
    root = str(Path(__file__).resolve().parents[1])
    if root not in sys.path:
        sys.path.insert(0, root)
    from app.journal import ARTICLES, journal_index, journal_article

    expected_pages = {"/journal": journal_index().body}
    expected_pages.update({
        "/journal/" + article["slug"]: journal_article(article["slug"]).body
        for article in ARTICLES
    })
    results = {}
    for path, expected_body in expected_pages.items():
        fingerprint = hashlib.sha256(expected_body).hexdigest()
        request = Request(
            BASE + path + "?revision_check=" + fingerprint[:16],
            headers={
                "User-Agent": "Stazhno-Preview-ReadOnly-Probe/1.0",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
            },
            method="GET",
        )
        try:
            with build_opener(NoRedirect).open(request, timeout=12) as response:
                payload = response.read(250_001)
                if len(payload) > 250_000:
                    item = {"status": response.status, "result": "html-too-large"}
                elif not response.headers.get("Content-Type", "").lower().startswith("text/html"):
                    item = {"status": response.status, "result": "not-html"}
                else:
                    observed = hashlib.sha256(payload).hexdigest()
                    item = {
                        "status": response.status,
                        "result": "exact-match" if observed == fingerprint else "mismatch",
                        "expected_sha256": fingerprint,
                        "observed_sha256": observed,
                    }
        except HTTPError as error:
            item = {"status": error.code, "result": "route-not-found" if error.code == 404 else "http-error"}
        except (URLError, OSError, ssl.SSLError, TimeoutError) as error:
            item = {"result": "connection-error", "type": type(error).__name__}
        results[path] = item
    return {
        "result": "exact-match" if all(item["result"] == "exact-match" for item in results.values()) else "unverified",
        "pages": results,
    }


def probe_public_community_page():
    """Compare only the public directory shell; never request member data.

    The server-rendered shell has no user-specific values. Its exact bytes also
    verify that the live HTML references this release's versioned JS and CSS.
    """
    root = str(Path(__file__).resolve().parents[1])
    if root not in sys.path:
        sys.path.insert(0, root)
    from app.community_pages import community_page

    fingerprint = hashlib.sha256(community_page(mode="directory").body).hexdigest()
    request = Request(
        BASE + "/community?revision_check=" + fingerprint[:16],
        headers={
            "User-Agent": "Stazhno-Preview-ReadOnly-Probe/1.0",
            "Cache-Control": "no-cache", "Pragma": "no-cache",
        },
        method="GET",
    )
    try:
        with build_opener(NoRedirect).open(request, timeout=12) as response:
            payload = response.read(250_001)
            if len(payload) > 250_000:
                return {"status": response.status, "result": "html-too-large"}
            if not response.headers.get("Content-Type", "").lower().startswith("text/html"):
                return {"status": response.status, "result": "not-html"}
            observed = hashlib.sha256(payload).hexdigest()
            return {
                "status": response.status,
                "result": "exact-match" if observed == fingerprint else "mismatch",
                "expected_sha256": fingerprint,
                "observed_sha256": observed,
            }
    except HTTPError as error:
        return {"status": error.code, "result": "route-not-found" if error.code == 404 else "http-error"}
    except (URLError, OSError, ssl.SSLError, TimeoutError) as error:
        return {"result": "connection-error", "type": type(error).__name__}



def probe_public_search_metadata():
    """Check robots/sitemap bytes and the noindex header on preview hosts."""
    root = str(Path(__file__).resolve().parents[1])
    if root not in sys.path:
        sys.path.insert(0, root)
    from app.journal import journal_sitemap
    from urllib.parse import urlsplit

    host = urlsplit(BASE).hostname
    is_canonical = host in {"stazhno.ru", "www.stazhno.ru"}
    robots = (
        "User-agent: *\nDisallow: /api/\nSitemap: https://stazhno.ru/sitemap.xml\n"
        if is_canonical else "User-agent: *\nDisallow: /\n"
    ).encode("utf-8")
    resources = {
        "/robots.txt": (robots, "text/plain"),
        "/sitemap.xml": (journal_sitemap().body, "application/xml"),
    }
    results = {}
    for path, (expected_body, mime) in resources.items():
        request = Request(
            BASE + path + "?revision_check=" + hashlib.sha256(expected_body).hexdigest()[:16],
            headers={
                "User-Agent": "Stazhno-Preview-ReadOnly-Probe/1.0",
                "Cache-Control": "no-cache", "Pragma": "no-cache",
            },
            method="GET",
        )
        try:
            with build_opener(NoRedirect).open(request, timeout=12) as response:
                payload = response.read(250_001)
                content_type = response.headers.get("Content-Type", "").lower()
                noindex = response.headers.get("X-Robots-Tag", "").lower()
                tag_ok = "noindex" not in noindex if is_canonical else "noindex" in noindex
                if len(payload) > 250_000:
                    status = "too-large"
                elif not content_type.startswith(mime):
                    status = "incorrect-content-type"
                elif payload != expected_body:
                    status = "mismatch"
                elif not tag_ok:
                    status = "incorrect-robots-tag"
                else:
                    status = "exact-match"
                item = {"status": response.status, "result": status}
        except HTTPError as error:
            item = {"status": error.code, "result": "route-not-found" if error.code == 404 else "http-error"}
        except (URLError, OSError, ssl.SSLError, TimeoutError) as error:
            item = {"result": "connection-error", "type": type(error).__name__}
        results[path] = item
    return {
        "result": "exact-match" if all(item["result"] == "exact-match" for item in results.values()) else "unverified",
        "resources": results,
    }


def main():
    host = BASE.removeprefix("https://").split("/", 1)[0].split(":", 1)[0]
    result = {"preview_url": BASE, "read_only": True, "dns": "unknown", "paths": {}}
    try:
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        result["dns"] = "resolved" if addresses else "no-addresses"
    except OSError:
        result["dns"] = "resolution-failed"
    if result["dns"] == "resolved":
        for path in ("/api/health", "/"):
            result["paths"][path] = probe(path)
        result["deployed_assets"] = {
            name: probe_asset("/static/" + name, STATIC / name)
            for name in CHECKED_ASSETS
        }
        # Retain the original field for existing dashboards and logs.
        result["deployed_app_js"] = result["deployed_assets"]["app.js"]
        result["index_asset_revisions"] = probe_index_revisions()
        result["journal_pages"] = probe_public_journal_pages()
        result["community_page"] = probe_public_community_page()
        result["community_api"] = {
            name: probe_private_route(path)
            for name, path in COMMUNITY_PRIVATE_ROUTES.items()
        }
        result["search_metadata"] = probe_public_search_metadata()
        result["drafts_api"] = probe_private_draft_route()
        result["backend_routes"] = {
            name: probe_backend_route(path, method)
            for name, (path, method) in BACKEND_ROUTE_CAPABILITIES.items()
        }
    else:
        result["paths"] = {
            "/api/health": {"result": "not-tested-dns-failure"},
            "/": {"result": "not-tested-dns-failure"},
        }
        result["deployed_assets"] = {
            name: {"result": "not-tested-dns-failure"} for name in CHECKED_ASSETS
        }
        result["deployed_app_js"] = result["deployed_assets"]["app.js"]
        result["index_asset_revisions"] = {"result": "not-tested-dns-failure"}
        result["journal_pages"] = {"result": "not-tested-dns-failure", "pages": {}}
        result["community_page"] = {"result": "not-tested-dns-failure"}
        result["community_api"] = {
            name: {"result": "not-tested-dns-failure"}
            for name in COMMUNITY_PRIVATE_ROUTES
        }
        result["search_metadata"] = {"result": "not-tested-dns-failure", "resources": {}}
        result["drafts_api"] = {"result": "not-tested-dns-failure"}
        result["backend_routes"] = {
            name: {"result": "not-tested-dns-failure"}
            for name in BACKEND_ROUTE_CAPABILITIES
        }
    result["assessment"] = (
        "preview-health-reachable"
        if result["paths"]["/api/health"].get("status") == 200
        else "preview-unverified"
    )
    asset_results = [item["result"] for item in result["deployed_assets"].values()]
    html_result = result["index_asset_revisions"]["result"]
    frontend_matches = (
        all(value == "exact-match" for value in asset_results)
        and html_result == "exact-match"
        and result["drafts_api"]["result"] == "present-and-protected"
    )
    journal_matches = result["journal_pages"]["result"] == "exact-match"
    community_matches = (
        result["community_page"]["result"] == "exact-match"
        and all(item["result"] == "present-and-protected" for item in result["community_api"].values())
    )
    search_matches = result["search_metadata"]["result"] == "exact-match"
    backend_matches = all(
        item["result"] == "route-present-method-protected"
        for item in result["backend_routes"].values()
    )
    if frontend_matches and backend_matches and journal_matches and search_matches and community_matches:
        result["release_evidence"] = "frontend-and-backend-match"
    elif "mismatch" in asset_results or html_result == "mismatch":
        result["release_evidence"] = "frontend-version-mismatch"
    elif frontend_matches and not backend_matches:
        result["release_evidence"] = "backend-version-unverified"
    elif frontend_matches and backend_matches and not journal_matches:
        result["release_evidence"] = "journal-version-unverified"
    elif frontend_matches and backend_matches and journal_matches and not search_matches:
        result["release_evidence"] = "search-metadata-unverified"
    elif frontend_matches and backend_matches and journal_matches and search_matches and not community_matches:
        result["release_evidence"] = "community-version-unverified"
    else:
        result["release_evidence"] = "unverified"
    REPORT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
