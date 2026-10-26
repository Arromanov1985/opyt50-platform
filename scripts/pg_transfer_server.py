"""Authenticated one-shot SQLite snapshot receiver for the isolated migration app.

Never deploy this over the live preview. It only accepts a signed snapshot and
copies it into an EMPTY PostgreSQL target.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from pathlib import Path
import re
import tempfile

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from scripts.migrate_sqlite_to_postgres import migrate, inspect_sqlite

MAX_BYTES = 32 * 1024 * 1024
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


def _authorize(request: Request) -> None:
    expected = os.getenv("OPYTNO_TRANSFER_TOKEN", "")
    if len(expected) < 32:
        raise HTTPException(503, "Transfer token is not configured")
    received = request.headers.get("authorization", "")
    if not hmac.compare_digest(received.encode(), ("Bearer " + expected).encode()):
        raise HTTPException(401, "Unauthorized")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    return response


@app.api_route("/", methods=["GET", "HEAD"])
@app.api_route("/api/health", methods=["GET", "HEAD"])
@app.api_route("/health", methods=["GET", "HEAD"])
def health():
    return {"status": "ok", "mode": "migration-receiver"}


@app.post("/transfer")
async def transfer(request: Request):
    _authorize(request)
    if request.headers.get("x-opytno-confirm") != "copy-to-empty-postgres":
        raise HTTPException(400, "Explicit import confirmation is required")
    digest = request.headers.get("x-snapshot-sha256", "").lower()
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise HTTPException(400, "Snapshot checksum is required")
    try:
        declared = int(request.headers.get("content-length", "0"))
    except ValueError:
        raise HTTPException(400, "Invalid length") from None
    if declared <= 0 or declared > MAX_BYTES:
        raise HTTPException(413, "Snapshot size is invalid")

    try:
        with tempfile.TemporaryDirectory(prefix="opytno-import-") as tmp:
            path = Path(tmp) / "snapshot.db"
            sha = hashlib.sha256()
            total = 0
            with path.open("xb") as handle:
                path.chmod(0o600)
                async for chunk in request.stream():
                    total += len(chunk)
                    if total > declared or total > MAX_BYTES:
                        raise HTTPException(413, "Snapshot is too large")
                    sha.update(chunk)
                    handle.write(chunk)
            if total != declared or not hmac.compare_digest(sha.hexdigest(), digest):
                raise HTTPException(400, "Snapshot checksum or length mismatch")
            await run_in_threadpool(inspect_sqlite, str(path))
            report = await run_in_threadpool(migrate, str(path), os.getenv("DATABASE_URL", ""))
            return JSONResponse({"imported": True, "source_sha256": digest, **report})
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(500, "Import failed and rolled back") from None
