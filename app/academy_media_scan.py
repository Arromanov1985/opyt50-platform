"""Bounded private-quarantine verification. No HTTP endpoint or public URL.

A successful scan requires both malware detection and an independent format
validator. Only images have a decoder adapter in this release. Quarantine
objects remain private even after verification; safe delivery is a separate
release gate.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from tempfile import SpooledTemporaryFile
from typing import BinaryIO, Literal
import os
import re
import socket
import struct
import time
import warnings

from .academy_media import MiB, RULES

Verdict = Literal["clean", "rejected", "failed"]
CHUNK = 64 * 1024
MAX_RESPONSE = 4096
MAX_IMAGE_PIXELS = 20_000_000


@dataclass(frozen=True)
class ScanJob:
    id: str
    course_slug: str
    object_key: str
    content_type: str
    byte_count: int
    sha256: str


@dataclass(frozen=True)
class ScanReport:
    job: ScanJob
    verdict: Verdict


class ClamAV:
    """Local clamd Unix socket; never accepts an address from an upload."""
    def __init__(self, socket_path: str, timeout: float = 180):
        if not os.path.isabs(socket_path) or not 0 < timeout <= 300:
            raise ValueError("Invalid local ClamAV configuration")
        self.socket_path = socket_path
        self.timeout = timeout

    def scan(self, stream: BinaryIO) -> Verdict:
        deadline = time.monotonic() + self.timeout

        def remaining():
            seconds = deadline - time.monotonic()
            if seconds <= 0:
                raise TimeoutError("ClamAV deadline exceeded")
            return seconds

        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
                conn.settimeout(remaining())
                conn.connect(self.socket_path)
                conn.settimeout(remaining())
                conn.sendall(b"zINSTREAM\x00")
                while True:
                    chunk = stream.read(CHUNK)
                    conn.settimeout(remaining())
                    conn.sendall(struct.pack("!I", len(chunk)) + chunk)
                    if not chunk:
                        break
                response = bytearray()
                while len(response) < MAX_RESPONSE:
                    conn.settimeout(remaining())
                    chunk = conn.recv(min(512, MAX_RESPONSE - len(response)))
                    if not chunk:
                        return "failed"
                    response.extend(chunk)
                    if b"\x00" in response:
                        break
                remaining()
                raw = bytes(response)
                if raw == b"stream: OK\x00":
                    return "clean"
                if re.fullmatch(rb"stream: [^\x00\r\n]+ FOUND\x00", raw):
                    return "rejected"
                # Includes size-limit errors, malformed replies, no terminator
                # and multiple responses. None can be treated as a clean scan.
                return "failed"
        except (OSError, ValueError):
            return "failed"


def validate_image(stream: BinaryIO, content_type: str) -> Verdict:
    """Decode one bounded still image; other formats stay blocked.

    A verified image is not a sanitized derivative. The original object is
    still quarantined and must not be exposed inline by a future route.
    """
    expected = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}.get(content_type)
    if expected is None:
        return "failed"
    try:
        from PIL import Image, ImageFile, UnidentifiedImageError
    except ImportError:
        return "failed"
    if ImageFile.LOAD_TRUNCATED_IMAGES:
        return "failed"
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            stream.seek(0)
            with Image.open(stream, formats=[expected]) as image:
                if (image.format != expected or image.width * image.height > MAX_IMAGE_PIXELS
                        or getattr(image, "n_frames", 1) != 1):
                    return "rejected"
                image.verify()
            stream.seek(0)
            with Image.open(stream, formats=[expected]) as image:
                if image.width * image.height > MAX_IMAGE_PIXELS:
                    return "rejected"
                image.load()
        return "clean"
    except (UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning,
            OSError, ValueError, SyntaxError, EOFError):
        return "rejected"


def _valid_job(job: ScanJob) -> bool:
    rule = RULES.get(job.content_type)
    return bool(
        rule and re.fullmatch(r"[0-9a-f]{32}", job.id)
        and job.object_key == "academy/quarantine/" + job.id
        and re.fullmatch(r"[0-9a-f]{64}", job.sha256)
        and 1 <= job.byte_count <= rule.limit
    )


def pending_job(db, media_id: str) -> ScanJob | None:
    """Read a trusted committed snapshot; perform network I/O after closing DB."""
    row = db.execute(
        """SELECT id,course_slug,object_key,content_type,byte_count,sha256
           FROM academy_media WHERE id=? AND state='pending'""", (media_id,)
    ).fetchone()
    if row is None:
        return None
    return ScanJob(**dict(row))


def check_quarantined(job: ScanJob, *, storage, private_bucket: str,
                      scanner: ClamAV, validator=validate_image,
                      read_timeout: float = 180) -> ScanReport:
    """Scan exactly the registered bytes, never trust MIME/metadata alone."""
    def report(verdict: Verdict) -> ScanReport:
        return ScanReport(job, verdict)

    if not private_bucket or not _valid_job(job) or not 0 < read_timeout <= 300:
        return report("failed")
    deadline = time.monotonic() + read_timeout
    try:
        with SpooledTemporaryFile(max_size=MiB, mode="w+b") as temp:
            response = storage.get_object(Bucket=private_bucket, Key=job.object_key)
            body = response["Body"]
            try:
                if response.get("ContentLength") != job.byte_count:
                    return report("rejected")
                checksum = sha256()
                size = 0
                while True:
                    if time.monotonic() >= deadline:
                        return report("failed")
                    chunk = body.read(min(CHUNK, job.byte_count - size + 1))
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > job.byte_count:
                        return report("rejected")
                    checksum.update(chunk)
                    temp.write(chunk)
                if time.monotonic() >= deadline:
                    return report("failed")
                if size != job.byte_count or checksum.hexdigest() != job.sha256:
                    return report("rejected")
            finally:
                body.close()
            temp.seek(0)
            verdict = scanner.scan(temp)
            if verdict != "clean":
                return report("rejected" if verdict == "rejected" else "failed")
            temp.seek(0)
            verdict = validator(temp, job.content_type)
            return report(verdict if verdict in ("clean", "rejected") else "failed")
    except Exception:
        # Worker boundary: storage, decoder or scanner failure must not
        # approve an object. Do not include SDK responses or secrets in logs.
        return report("failed")


def record_scan(db, report: ScanReport) -> bool:
    """Only trusted workers call this CAS; stale scans cannot revive a file."""
    from .community import _now

    job = report.job
    if not _valid_job(job) or report.verdict not in ("clean", "rejected", "failed"):
        raise ValueError("Invalid media scan report")
    changed = db.execute(
        """UPDATE academy_media SET state=?,updated_at=?
           WHERE id=? AND course_slug=? AND object_key=? AND content_type=?
             AND byte_count=? AND sha256=? AND state='pending'""",
        (report.verdict, _now(), job.id, job.course_slug, job.object_key,
         job.content_type, job.byte_count, job.sha256),
    )
    return changed.rowcount == 1
