"""Ensure browsers fetch the exact app.js shipped in each release.

The index route is no-store, and its app.js URL uses the Git blob SHA prefix.
"""
import hashlib
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"


def test_app_js_version_matches_its_git_blob_sha():
    payload = (STATIC / "app.js").read_bytes()
    header = f"blob {len(payload)}".encode("ascii") + b"\0"
    expected = hashlib.sha1(header + payload).hexdigest()[:12]

    html = (STATIC / "index.html").read_text(encoding="utf-8")
    prefix = 'src="/static/app.js?v='
    assert html.count(prefix) == 1, "app.js must have exactly one versioned script tag"
    version = html.split(prefix, 1)[1].split('"', 1)[0]
    assert version == expected, (
        "app.js changed without updating its cache version in index.html"
    )
