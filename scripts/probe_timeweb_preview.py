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
            if not response.headers.get("Content-Type", "").lower().startswith(
                ("text/javascript", "application/javascript", "application/x-javascript")
            ):
                return {"status": response.status, "result": "not-javascript"}
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
        result["deployed_app_js"] = probe_asset(
            "/static/app.js", Path(__file__).resolve().parents[1] / "app" / "static" / "app.js",
        )
        result["drafts_api"] = probe_private_draft_route()
    else:
        result["paths"] = {
            "/api/health": {"result": "not-tested-dns-failure"},
            "/": {"result": "not-tested-dns-failure"},
        }
        result["deployed_app_js"] = {"result": "not-tested-dns-failure"}
        result["drafts_api"] = {"result": "not-tested-dns-failure"}
    result["assessment"] = (
        "preview-health-reachable"
        if result["paths"]["/api/health"].get("status") == 200
        else "preview-unverified"
    )
    if (result["deployed_app_js"]["result"] == "exact-match"
            and result["drafts_api"]["result"] == "present-and-protected"):
        result["release_evidence"] = "frontend-match-and-protected-drafts-api"
    elif result["deployed_app_js"]["result"] == "mismatch":
        result["release_evidence"] = "frontend-version-mismatch"
    else:
        result["release_evidence"] = "unverified"
    REPORT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
