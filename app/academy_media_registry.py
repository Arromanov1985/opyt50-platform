"""Durable reservations for future private Academy uploads.

Internal service functions only. The authenticated HTTP upload endpoint is
intentionally not installed. Commit the reservation before contacting storage,
and commit completion separately: failed uploads keep an auditable key.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from uuid import UUID, uuid4

from fastapi import HTTPException

from .academy_media import MiB, RULES, StagedMedia, stage_upload

MAX_COURSE_FILES = 60
MAX_COURSE_BYTES = 1024 * MiB


@dataclass(frozen=True)
class Reservation:
    id: UUID
    course_slug: str
    course_version: int
    content_type: str
    byte_count: int


def reserve_media(db, user: dict, course_slug: str, expected_version: int,
                  content_type: str, byte_count: int) -> Reservation:
    """Authorize and reserve quota atomically; no external I/O here."""
    from .academy_builder import _row, _is_editor, _version
    from .community import _active_account, _lock_actors, _now

    content_type = content_type.strip().lower()
    rule = RULES.get(content_type)
    if rule is None or type(byte_count) is not int or not 1 <= byte_count <= rule.limit:
        raise HTTPException(422, "Некорректный формат или размер файла")
    row = _row(db, course_slug)
    if not _is_editor(user, row):
        raise HTTPException(404, "Курс недоступен")
    _lock_actors(db, user["id"])
    # Serialize all reservations for this course, even for different admins
    # of an editorial course. Same no-op row update works in both databases.
    db.execute("UPDATE academy_courses SET version=version WHERE slug=?", (course_slug,))
    row = _row(db, course_slug)
    if not _is_editor(user, row):
        raise HTTPException(404, "Курс недоступен")
    if not _active_account(db, user["id"]):
        raise HTTPException(403, "Загрузка недоступна при ограничении обработки данных")
    _version(row, expected_version)
    usage = db.execute(
        "SELECT COUNT(*),COALESCE(SUM(byte_count),0) FROM academy_media WHERE course_slug=?",
        (course_slug,),
    ).fetchone()
    if usage[0] >= MAX_COURSE_FILES or usage[1] + byte_count > MAX_COURSE_BYTES:
        raise HTTPException(409, "Достигнут лимит учебных файлов курса")
    media_id = uuid4()
    now = _now()
    db.execute(
        """INSERT INTO academy_media(id,course_slug,course_version,object_key,kind,content_type,
                  byte_count,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)""",
        (media_id.hex, course_slug, expected_version, "academy/quarantine/" + media_id.hex,
         rule.kind, content_type, byte_count, now, now),
    )
    return Reservation(media_id, course_slug, expected_version, content_type, byte_count)


def upload_reserved(reservation: Reservation, stream, *, storage, private_bucket: str) -> StagedMedia:
    """After durable reservation commit, stage exactly the reserved bytes."""
    return stage_upload(stream, reservation.content_type, storage=storage,
                        private_bucket=private_bucket, media_id=reservation.id,
                        expected_bytes=reservation.byte_count)


def media_ids(draft: dict) -> set[str]:
    return {block["file_id"] for lesson in draft.get("lessons", [])
            for block in lesson.get("media", [])}


def course_media_metadata(db, course_slug: str, draft: dict | None = None) -> list[dict]:
    """Metadata only, never a storage key, checksum, signed URL or binary."""
    selected = None if draft is None else media_ids(draft)
    rows = db.execute(
        """SELECT id,kind,content_type,byte_count,state FROM academy_media
           WHERE course_slug=? ORDER BY created_at,id""", (course_slug,)
    ).fetchall()
    # Expose only metadata from a completely verified batch bound to the
    # current clean source. Reserved/partially written objects stay invisible.
    from .academy_renditions import ready_metadata
    copies = ready_metadata(db, course_slug)
    return [{**dict(row), "renditions": copies.get(row["id"], [])}
            for row in rows if selected is None or row["id"] in selected]


def validate_media_references(db, course_slug: str, draft: dict) -> None:
    wanted = media_ids(draft)
    if not wanted:
        return
    available = {row["id"] for row in course_media_metadata(db, course_slug)
                 if row["state"] != "purge_pending"}
    if not wanted <= available:
        # Do not disclose whether a foreign or missing file exists.
        raise HTTPException(422, "Учебный файл недоступен для этого курса")


def record_staged(db, reservation: Reservation, media: StagedMedia) -> None:
    """Internal completion, never approves a file for reading/publication."""
    from .community import _now

    rule = RULES.get(reservation.content_type)
    expected_key = "academy/quarantine/" + reservation.id.hex
    if (rule is None or media.id != reservation.id or media.object_key != expected_key
            or media.kind != rule.kind or media.content_type != reservation.content_type
            or media.byte_count != reservation.byte_count
            or not re.fullmatch(r"[0-9a-f]{64}", media.sha256)):
        raise ValueError("Staged media does not match its reservation")
    changed = db.execute(
        """UPDATE academy_media SET sha256=?,state='pending',updated_at=?
           WHERE id=? AND course_slug=? AND course_version=? AND object_key=?
             AND content_type=? AND kind=? AND byte_count=? AND state='reserved'""",
        (media.sha256, _now(), reservation.id.hex, reservation.course_slug,
         reservation.course_version, expected_key, media.content_type, media.kind,
         reservation.byte_count),
    )
    if changed.rowcount != 1:
        raise ValueError("Media reservation is missing or already completed")
