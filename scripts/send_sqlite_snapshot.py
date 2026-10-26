"""Send a fresh SQLite snapshot directly to the migration receiver.

Run in the OLD preview container. The source SQLite is not deleted or replaced.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import getpass
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import urllib.parse
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def send(source: Path, base_url: str, token: str) -> dict:
    parsed = urllib.parse.urlsplit(base_url.strip())
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Use HTTPS receiver URL without embedded credentials")
    endpoint = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "/transfer", "", ""))
    if len(token) < 32:
        raise ValueError("Transfer token must be at least 32 characters")
    if not source.is_file():
        raise ValueError("SQLite source is missing")

    with tempfile.TemporaryDirectory(prefix="opytno-send-") as tmp:
        snap = Path(tmp) / "source.db"
        with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as src:
            with closing(sqlite3.connect(snap)) as dst:
                src.backup(dst)
        data = snap.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        req = urllib.request.Request(endpoint, data=data, method="POST", headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/octet-stream",
            "Content-Length": str(len(data)),
            "X-Snapshot-SHA256": digest,
            "X-Opytno-Confirm": "copy-to-empty-postgres",
        })
        opener = urllib.request.build_opener(NoRedirect())
        with opener.open(req, timeout=120) as response:
            result = json.loads(response.read(1024 * 1024))
        if not result.get("imported") or result.get("source_sha256") != digest:
            raise ValueError("Receiver did not confirm this snapshot")
        return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=os.getenv("OPYT50_DB_PATH", "/srv/data/opyt50.db"))
    args = parser.parse_args()
    base_url = input("Migration receiver HTTPS URL: ").strip()
    token = os.getenv("OPYTNO_TRANSFER_TOKEN") or getpass.getpass("Transfer token: ")
    if input("Type COPY to continue: ").strip() != "COPY":
        print("Cancelled")
        return 1
    result = send(Path(args.source), base_url, token)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
