"""Bounded worker invocation for Academy pending jobs, disabled by default.

Deploy on a dedicated non-root account with a quota-limited private scratch
filesystem and a local ClamAV socket. One invocation is serialized by flock.
Only aggregate results are logged. No public upload switches are modified.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path

from app.academy_storage import storage_config, build_storage_client
from app.academy_media_scan import ClamAV
from app.academy_local_converter import LocalConverter
from app.academy_rendition_worker import process_conversion
from app.db import database
from scripts.scan_academy_media import scan_batch


def rich_pending(path: str, limit: int):
    if not 1 <= limit <= 5:
        raise ValueError("Invalid batch size")
    with database(path) as db:
        rows = db.execute(
            """SELECT m.id FROM academy_media m JOIN academy_courses a ON a.slug=m.course_slug
               LEFT JOIN account_controls ac ON ac.user_id=a.owner_id
               WHERE m.state='pending' AND m.kind<>'image'
                 AND NOT EXISTS(SELECT 1 FROM academy_media_renditions r WHERE r.media_id=m.id)
                 AND (a.owner_id IS NULL OR (COALESCE(ac.status,'active')='active' AND NOT EXISTS (
                   SELECT 1 FROM privacy_rights_requests pr WHERE pr.user_id=a.owner_id
                   AND pr.kind IN ('deletion','stop_processing')
                   AND pr.status IN ('received','in_review','completed'))))
               ORDER BY m.created_at,m.id LIMIT ?""",(limit,)
        ).fetchall()
        return [row["id"] for row in rows]


def process_batch(path: str, *, storage, bucket, scanner, converter, scratch, mode, limit):
    if mode not in ("images","rich","all") or not 1 <= limit <= 5:
        raise ValueError("Invalid worker mode or limit")
    if mode != "images" and converter is None:
        raise ValueError("An isolated converter is required")
    counts = {"clean":0,"rejected":0,"failed":0,"skipped":0}
    if mode in ("images","all"):
        scanned = scan_batch(path,storage=storage,bucket=bucket,scanner=scanner,limit=limit)
        for key,value in scanned.items():
            counts[key] += value
    if mode in ("rich","all"):
        for media_id in rich_pending(path,limit):
            verdict = process_conversion(path,media_id,storage=storage,bucket=bucket,
                scanner=scanner,isolated_converter=converter,scratch_root=scratch)
            counts[verdict] += 1
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode",choices=("images","rich","all"),default="images")
    parser.add_argument("--limit",type=int,choices=range(1,6),default=1)
    args = parser.parse_args()
    if os.getenv("STAZHNO_ACADEMY_WORKER_ENABLED","0") != "1":
        parser.exit(2,"Academy worker is disabled\n")
    try:
        if os.geteuid() == 0 or not os.getenv("DATABASE_URL","").strip():
            raise RuntimeError("A dedicated non-root PostgreSQL worker is required")
        config = storage_config()
        socket_path = os.getenv("STAZHNO_ACADEMY_CLAMD_SOCKET","").strip()
        scratch_value = os.getenv("STAZHNO_ACADEMY_WORKER_SCRATCH","").strip()
        if config is None or not os.path.isabs(socket_path) or not os.path.isabs(scratch_value):
            raise RuntimeError("Incomplete worker configuration")
        scratch = Path(scratch_value).resolve(strict=True)
        if not scratch.is_dir() or scratch.stat().st_uid != os.geteuid() or scratch.stat().st_mode & 0o077:
            raise RuntimeError("Scratch directory is not private")
        # The directory is owned solely by this worker. O_NOFOLLOW prevents
        # the lock file from being redirected to another file.
        fd = os.open(scratch / ".worker.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd,"a+") as lock:
            try:
                fcntl.flock(lock,fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                print(json.dumps({"skipped":"worker_already_running"}))
                return 0
            converter = None
            if args.mode != "images":
                converter = LocalConverter(os.getenv("STAZHNO_ACADEMY_CONVERTER_IMAGE_ID",""),
                                           scratch_root=str(scratch))
                converter.check_runtime()
            result = process_batch("unused-with-DATABASE_URL",storage=build_storage_client(config),
                bucket=config.bucket,scanner=ClamAV(socket_path),converter=converter,
                scratch=scratch,mode=args.mode,limit=args.limit)
            print(json.dumps(result,separators=(",",":")))
            return 1 if result["failed"] else 0
    except Exception:
        print(json.dumps({"error":"worker_configuration_or_runtime_failed"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
