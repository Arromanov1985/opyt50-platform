"""All-or-nothing registry of private, independently checked derivative files.

Only trusted backend workers may reserve/store/finalize a complete batch.
The isolated converter has no DB or S3 access. Reserved keys survive partial
or ambiguous PUTs; no retry may overwrite them or expose an incomplete set.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from tempfile import SpooledTemporaryFile
import math
import os
import re
import stat
from uuid import uuid4

from .academy_media import MiB, RULES, _matches_type
from .academy_media_scan import ScanJob, _valid_job, pending_job, validate_image

MAX_DERIVATIVE_BYTES = 1024 * MiB
DOCUMENT_TYPES = {"application/pdf", "application/vnd.openxmlformats-officedocument.presentationml.presentation"}


class RenditionError(ValueError):
    pass


@dataclass(frozen=True)
class CopySpec:
    position: int
    name: str
    content_type: str
    byte_count: int
    sha256: str
    duration_ms: int | None


@dataclass(frozen=True)
class ReservedCopy:
    id: str
    spec: CopySpec

    @property
    def object_key(self):
        return "academy/renditions/" + self.id


def parse_manifest(source_type: str, manifest: dict) -> tuple[CopySpec, ...]:
    """Accept exactly the output contract; never trust arbitrary output paths."""
    rule = RULES.get(source_type)
    if not rule or rule.kind == "image" or type(manifest) is not dict or set(manifest) != {"renditions"}:
        raise RenditionError("Unsupported converter manifest")
    entries = manifest["renditions"]
    documents = source_type in DOCUMENT_TYPES
    if type(entries) is not list or not 1 <= len(entries) <= (30 if documents else 1):
        raise RenditionError("Invalid derivative count")
    result = []
    total = 0
    for position, entry in enumerate(entries, 1):
        if type(entry) is not dict or set(entry) != {"name","content_type","byte_count","sha256","duration","page"}:
            raise RenditionError("Invalid derivative fields")
        if documents:
            name, mime, limit = f"page-{position:03d}.jpg", "image/jpeg", 3 * MiB
            if type(entry["page"]) is not int or entry["page"] != position or entry["duration"] is not None:
                raise RenditionError("Invalid derivative page order")
            duration_ms = None
        else:
            video = rule.kind == "video"
            name = "video.mp4" if video else "audio.m4a"
            mime = "video/mp4" if video else "audio/mp4"
            limit = (160 if video else 64) * MiB
            seconds = entry["duration"]
            if (entry["page"] is not None or type(seconds) not in (float, int)
                    or not 0 < seconds <= (901 if video else 1801) or not math.isfinite(seconds)):
                raise RenditionError("Invalid derivative duration")
            duration_ms = max(1, round(seconds * 1000))
        if (entry["name"] != name or entry["content_type"] != mime
                or type(entry["byte_count"]) is not int or not 1 <= entry["byte_count"] <= limit
                or type(entry["sha256"]) is not str or not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])):
            raise RenditionError("Invalid derivative metadata")
        total += entry["byte_count"]
        if documents and total > 60 * MiB:
            raise RenditionError("Document rendition quota exceeded")
        result.append(CopySpec(position,name,mime,entry["byte_count"],entry["sha256"],duration_ms))
    return tuple(result)


def lock_source(db, job: ScanJob) -> bool:
    """Acquire locks in the same owner->course order as course mutations."""
    from .community import _active_account, _lock_actors
    course = db.execute("SELECT owner_id FROM academy_courses WHERE slug=?", (job.course_slug,)).fetchone()
    if course is None or not _valid_job(job):
        return False
    owner = course["owner_id"]
    if owner is not None:
        _lock_actors(db, owner)
    db.execute("UPDATE academy_courses SET version=version WHERE slug=?", (job.course_slug,))
    return pending_job(db, job.id) == job and (owner is None or _active_account(db, owner))


def reserve_copies(db, job: ScanJob, manifest: dict) -> tuple[ReservedCopy, ...]:
    from .community import _now
    specs = parse_manifest(job.content_type, manifest)
    if not lock_source(db, job):
        raise RenditionError("Source is no longer eligible")
    if db.execute("SELECT 1 FROM academy_media_renditions WHERE media_id=?", (job.id,)).fetchone():
        raise RenditionError("Existing reservation requires reconciliation")
    used = db.execute(
        """SELECT COALESCE(SUM(r.byte_count),0) FROM academy_media_renditions r
           JOIN academy_media m ON m.id=r.media_id WHERE m.course_slug=?""", (job.course_slug,)
    ).fetchone()[0]
    if used + sum(s.byte_count for s in specs) > MAX_DERIVATIVE_BYTES:
        raise RenditionError("Course derivative quota exceeded")
    copies = tuple(ReservedCopy(uuid4().hex, spec) for spec in specs)
    now = _now()
    for copy in copies:
        s = copy.spec
        db.execute(
            """INSERT INTO academy_media_renditions(id,media_id,source_sha256,position,
                      content_type,byte_count,sha256,duration_ms,object_key,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (copy.id,job.id,job.sha256,s.position,s.content_type,s.byte_count,s.sha256,
             s.duration_ms,copy.object_key,now,now),
        )
    return copies


def store_copy(copy: ReservedCopy, directory: Path, *, storage, bucket: str, scanner) -> str:
    """Read one isolated output without following symlinks, scan, and PUT once."""
    if not bucket or not re.fullmatch(r"[0-9a-f]{32}", copy.id):
        raise RenditionError("Invalid private storage reservation")
    s = copy.spec
    # Even a compromised converter cannot select a file outside its output
    # directory or make us block on a FIFO. The supervisor must stop the
    # converter before importing its files; the directory belongs to this job.
    allowed_name = s.name in ("audio.m4a","video.mp4") or re.fullmatch(r"page-[0-9]{3}\.jpg", s.name)
    if not allowed_name or not hasattr(os, "O_NOFOLLOW"):
        raise RenditionError("Unsafe converter output")
    directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fd = os.open(s.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
        with os.fdopen(fd,"rb") as source, SpooledTemporaryFile(max_size=MiB,mode="w+b") as temp:
            st = os.fstat(source.fileno())
            if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_size != s.byte_count:
                raise RenditionError("Invalid converter output file")
            checksum = sha256()
            size = 0
            while chunk := source.read(min(MiB,s.byte_count-size+1)):
                size += len(chunk)
                if size > s.byte_count:
                    raise RenditionError("Derivative size mismatch")
                checksum.update(chunk)
                temp.write(chunk)
            if size != s.byte_count or checksum.hexdigest() != s.sha256:
                raise RenditionError("Derivative integrity mismatch")
            temp.seek(0)
            if not _matches_type(temp,s.content_type,size):
                raise RenditionError("Derivative format mismatch")
            if s.content_type == "image/jpeg" and validate_image(temp,s.content_type) != "clean":
                raise RenditionError("Invalid document preview")
            temp.seek(0)
            if scanner.scan(temp) != "clean":
                raise RenditionError("Derivative security check did not pass")
            temp.seek(0)
            storage.put_object(Bucket=bucket,Key=copy.object_key,Body=temp,ContentLength=size,
                               ContentType="application/octet-stream",ContentDisposition="attachment",
                               IfNoneMatch="*",Metadata={"sha256":s.sha256})
        return copy.id
    finally:
        os.close(directory_fd)


def finalize_copies(db, job: ScanJob, copies: tuple[ReservedCopy, ...], stored_ids: set[str]) -> bool:
    """Commit all copies and the source status together; caller owns transaction."""
    from .community import _now
    from .academy_media_scan import record_scan, ScanReport
    if not copies or stored_ids != {c.id for c in copies} or len(stored_ids) != len(copies):
        raise RenditionError("Incomplete derivative upload")
    if not lock_source(db, job):
        return False
    rows = db.execute(
        """SELECT id,source_sha256,position,content_type,byte_count,sha256,duration_ms,object_key,state
           FROM academy_media_renditions WHERE media_id=? ORDER BY position""", (job.id,)
    ).fetchall()
    if len(rows) != len(copies):
        raise RenditionError("Derivative registry changed")
    for row, copy in zip(rows, copies):
        s=copy.spec
        expected=(copy.id,job.sha256,s.position,s.content_type,s.byte_count,s.sha256,
                  s.duration_ms,copy.object_key,"reserved")
        if tuple(row[i] for i in range(len(expected))) != expected:
            raise RenditionError("Derivative reservation changed")
    if not record_scan(db,ScanReport(job,"clean")):
        return False
    updated = db.execute(
        "UPDATE academy_media_renditions SET state='ready',updated_at=? WHERE media_id=? AND state='reserved'",
        (_now(),job.id),
    )
    if updated.rowcount != len(copies):
        raise RenditionError("Incomplete derivative activation")
    return True


def ready_metadata(db, course_slug: str) -> dict[str, list[dict]]:
    rows = db.execute(
        """SELECT r.media_id,r.position,r.content_type,r.byte_count,r.duration_ms
           FROM academy_media_renditions r JOIN academy_media m ON m.id=r.media_id
           WHERE m.course_slug=? AND m.state='clean' AND r.state='ready' AND r.source_sha256=m.sha256
             AND NOT EXISTS(SELECT 1 FROM academy_media_renditions x WHERE x.media_id=m.id
                 AND (x.state<>'ready' OR x.source_sha256<>m.sha256))
           ORDER BY r.media_id,r.position""",(course_slug,)
    ).fetchall()
    result = {}
    for row in rows:
        data=dict(row)
        result.setdefault(data.pop("media_id"),[]).append(data)
    return result
