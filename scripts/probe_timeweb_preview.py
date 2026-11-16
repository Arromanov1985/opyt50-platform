"""Read-only external reachability check for the temporary Timeweb preview.

Only DNS + unauthenticated GET requests. Never uses credentials, cookies,
real user information, or mutation endpoints. The report is diagnostic, not
a PR pass/fail gate: an unavailable preview must not hide valid PR test results.
"""
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
    else:
        result["paths"] = {
            "/api/health": {"result": "not-tested-dns-failure"},
            "/": {"result": "not-tested-dns-failure"},
        }
    result["assessment"] = (
        "preview-health-reachable"
        if result["paths"]["/api/health"].get("status") == 200
        else "preview-unverified"
    )
    REPORT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
