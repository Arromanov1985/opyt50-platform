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
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPRedirectHandler


DEFAULT_BASE = "https://arromanov1985-opyt50-platform-fdd8.twc1.net"
BASE = os.getenv("STAZHNO_PREVIEW_URL", DEFAULT_BASE).rstrip("/")
REPORT = Path(os.getenv("STAZHNO_PREVIEW_REPORT", "preview-reachability.json"))
STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
CLIENT_ASSETS = ("app.js", "release02.js", "vacancy-wizard.js", "release09-dashboard.css")


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


def probe_private_draft_route():
    """Unauthenticated read-only request. Protected API returns JSON 401, not 404."""
    request = Request(
        BASE + "/api/employer/vacancy-drafts",
        headers={"User-Agent": "Stazhno-Preview-ReadOnly-Probe/1.0"},
        method="GET",
    )
    try:
        with build_opener(NoRedirect).open(request, timeout=10) as response:
            # The endpoint must not disclose private draft data.
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


# GET on a PATCH/POST-only route is safe and never executes its mutation.
# Unlike a public release string, the 405 + Allow evidence confirms that the
# corresponding backend handler is actually deployed. No cookies or tokens.
BACKEND_ROUTE_CAPABILITIES = {
    "direct_invitation_outcome": ("/api/employer/invitations/0/outcome", "PATCH"),
    "candidate_invitation_response": ("/api/candidate/invitations/0/respond", "POST"),
    "employer_contact_unlock": ("/api/employer/invitations/0/demo-pay", "POST"),
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
            for name in CLIENT_ASSETS
        }
        # Retain the original field for existing dashboards and logs.
        result["deployed_app_js"] = result["deployed_assets"]["app.js"]
        result["index_asset_revisions"] = probe_index_revisions()
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
            name: {"result": "not-tested-dns-failure"} for name in CLIENT_ASSETS
        }
        result["deployed_app_js"] = result["deployed_assets"]["app.js"]
        result["index_asset_revisions"] = {"result": "not-tested-dns-failure"}
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
    backend_matches = all(
        item["result"] == "route-present-method-protected"
        for item in result["backend_routes"].values()
    )
    if frontend_matches and backend_matches:
        result["release_evidence"] = "frontend-and-backend-match"
    elif "mismatch" in asset_results or html_result == "mismatch":
        result["release_evidence"] = "frontend-version-mismatch"
    elif frontend_matches and not backend_matches:
        result["release_evidence"] = "backend-version-unverified"
    else:
        result["release_evidence"] = "unverified"
    REPORT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
