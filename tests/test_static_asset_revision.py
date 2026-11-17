"""Static assets used by the dashboard must have content-derived cache keys.

This prevents a stale JS or CSS file from remaining on tablets after deploy.
"""
import hashlib
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"


@pytest.mark.parametrize("asset,attribute", [
    ("app.js", "src"),
    ("vacancy-wizard.js", "src"),
    ("release09-dashboard.css", "href"),
])
def test_dashboard_asset_revision_matches_git_blob(asset, attribute):
    payload = (STATIC / asset).read_bytes()
    header = f"blob {len(payload)}".encode("ascii") + bytes([0])
    expected = hashlib.sha1(header + payload).hexdigest()[:12]

    html = (STATIC / "index.html").read_text(encoding="utf-8")
    prefix = f'{attribute}="/static/{asset}?v='
    assert html.count(prefix) == 1, f"{asset} must have one versioned reference"
    version = html.split(prefix, 1)[1].split('"', 1)[0]
    assert version == expected, (
        f"{asset} changed without updating its cache revision in index.html"
    )
