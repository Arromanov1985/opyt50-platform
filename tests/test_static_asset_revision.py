"""Keep the public app.js URL tied to its exact shipped content.

This prevents old browser/CDN caches from silently serving stale application
logic after a new release. The HTML entrypoint itself is served no-store.
"""
import hashlib
import re
from pathlib import Path


STATIC = Path(__file__).resolve().parents[1] / "app" / "static"


def test_app_js_version_is_its_git_blob_prefix():
    payload = (STATIC / "app.js").read_bytes()
    git_blob_hash = hashlib.sha1(
        f"blob {len(payload)}\\0".replace("\\0", "\0").encode("ascii") + payload
    ).hexdigest()
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    versions = re.findall(r'src="/static/app\\.js\\?v=([0-9a-f]{12})"', html)
    assert len(versions) == 1, "app.js should have exactly one versioned script tag"
    assert versions[0] == git_blob_hash[:12], (
        "app.js content changed without a new HTML asset revision: "
        "update the app.js?v= query to the new Git blob SHA prefix"
    )
