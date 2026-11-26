"""Trusted orchestration for one isolated Academy conversion.

The converter callable must be an isolated one-job execution service, not
the parser in the web process. It receives only the checked input stream,
its MIME and an empty private job directory; it returns the bounded manifest.
It must be fully stopped before returning. DB/storage credentials never
enter the converter. No public upload or playback is enabled by this module.
"""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from .academy_media import RULES
from .academy_media_scan import ScanReport, check_quarantined, pending_job, record_scan
from .academy_renditions import (
    RenditionError, lock_source, parse_manifest, reserve_copies, store_copy, finalize_copies,
)
from .db import database


def _unreserved(db, job):
    return lock_source(db, job) and db.execute(
        "SELECT 1 FROM academy_media_renditions WHERE media_id=?", (job.id,)
    ).fetchone() is None


def process_conversion(path: str, media_id: str, *, storage, bucket: str,
                       scanner, isolated_converter, scratch_root=None) -> str:
    """Process exactly one pending non-image file, without holding DB during I/O.

    Return only a state label. If a storage write has an uncertain outcome,
    retain all reservations for reconciliation; never retry the same key.
    """
    with database(path) as db:
        job = pending_job(db, media_id)
        if job is None or RULES.get(job.content_type) is None or RULES[job.content_type].kind == "image":
            return "skipped"
        if not _unreserved(db, job):
            return "skipped"

    with TemporaryDirectory(prefix="academy-rendition-", dir=scratch_root) as temp:
        output = Path(temp) / "output"
        output.mkdir(mode=0o700)
        manifest = None

        def convert(verified_stream, content_type):
            nonlocal manifest
            # Called only after check_quarantined verifies original size,
            # SHA-256 and malware result, using those exact bytes.
            manifest = isolated_converter(verified_stream, content_type, output)
            parse_manifest(content_type, manifest)
            return "clean"

        report = check_quarantined(job, storage=storage, private_bucket=bucket,
                                   scanner=scanner, validator=convert)
        if report.verdict != "clean":
            with database(path) as db:
                if not _unreserved(db, job):
                    return "skipped"
                return report.verdict if record_scan(db, report) else "skipped"

        try:
            with database(path) as db:
                if not _unreserved(db, job):
                    return "skipped"
                copies = reserve_copies(db, job, manifest)
        except RenditionError:
            # No durable reservation after this failed transaction. Do not
            # mark a source belonging to another running worker as failed.
            with database(path) as db:
                if not _unreserved(db, job):
                    return "skipped"
                return "failed" if record_scan(db, ScanReport(job, "failed")) else "skipped"

        stored_ids = set()
        try:
            for copy in copies:
                with database(path) as db:
                    if not lock_source(db, job):
                        return "skipped"
                stored_ids.add(store_copy(copy, output, storage=storage, bucket=bucket, scanner=scanner))
            with database(path) as db:
                return "clean" if finalize_copies(db, job, copies, stored_ids) else "skipped"
        except Exception:
            # Reserved records remain durable for operator cleanup even when
            # S3 returned an ambiguous failure. No partial batch is served.
            with database(path) as db:
                if lock_source(db, job):
                    record_scan(db, ScanReport(job, "failed"))
            return "failed"
