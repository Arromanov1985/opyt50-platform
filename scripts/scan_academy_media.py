"""Run a bounded batch of Academy image scans on a trusted worker host.

Example: python -m scripts.scan_academy_media --limit 10
Requires explicit storage/scan configuration. Not a public or HTTP command.
"""
from __future__ import annotations

import argparse
import os

from app.academy_media_scan import ClamAV, pending_job, check_quarantined, record_scan
from app.academy_storage import image_upload_config, build_storage_client
from app.db import database
from app.community import _active_account


def _allowed(db, job) -> bool:
    row = db.execute("SELECT owner_id FROM academy_courses WHERE slug=?", (job.course_slug,)).fetchone()
    return bool(row is not None and (row["owner_id"] is None or _active_account(db, row["owner_id"])))


def scan_batch(path: str, *, storage, bucket: str, scanner, limit: int) -> dict[str, int]:
    if not 1 <= limit <= 30:
        raise ValueError("Scan batch limit must be 1..30")
    with database(path) as db:
        rows = db.execute(
            """SELECT m.id FROM academy_media m JOIN academy_courses a ON a.slug=m.course_slug
               LEFT JOIN account_controls ac ON ac.user_id=a.owner_id
               WHERE m.state='pending' AND m.kind='image'
                 AND (a.owner_id IS NULL OR (COALESCE(ac.status,'active')='active' AND NOT EXISTS (
                   SELECT 1 FROM privacy_rights_requests pr WHERE pr.user_id=a.owner_id
                   AND pr.kind IN ('deletion','stop_processing')
                   AND pr.status IN ('received','in_review','completed'))))
               ORDER BY m.created_at,m.id LIMIT ?""", (limit,)
        ).fetchall()
        ids = [row["id"] for row in rows]
    counts = {"clean": 0, "rejected": 0, "failed": 0, "skipped": 0}
    for media_id in ids:
        with database(path) as db:
            job = pending_job(db, media_id)
            allowed = job is not None and _allowed(db, job)
        if not allowed:
            counts["skipped"] += 1
            continue
        report = check_quarantined(job, storage=storage, private_bucket=bucket, scanner=scanner)
        with database(path) as db:
            if _allowed(db, job) and record_scan(db, report):
                counts[report.verdict] += 1
            else:
                counts["skipped"] += 1
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=10, choices=range(1, 31))
    args = parser.parse_args()
    setup = image_upload_config()
    if setup is None:
        parser.exit(2, "Academy image processing is disabled\n")
    config, socket_path = setup
    if not os.getenv("DATABASE_URL", "").strip():
        parser.exit(2, "DATABASE_URL is required for the deployed worker\n")
    result = scan_batch("unused-with-DATABASE_URL", storage=build_storage_client(config),
                        bucket=config.bucket, scanner=ClamAV(socket_path), limit=args.limit)
    print(result)  # aggregate counters only, not object keys or file content
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
