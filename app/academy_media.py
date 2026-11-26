"""Private quarantine ingestion for Academy media; never publishes a file.

This module is deliberately not exposed through HTTP routes until the course
ownership checks, scanning and retention lifecycle have been integrated.
Storage credentials and the private bucket must be configured server-side.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from tempfile import SpooledTemporaryFile
from typing import BinaryIO, Literal, Protocol
from uuid import UUID, uuid4
import zipfile


MiB = 1024 * 1024
MediaKind = Literal["image", "audio", "video", "document", "presentation"]


class MediaRejected(ValueError):
    """Invalid or unsupported upload (safe to return to the author)."""


@dataclass(frozen=True)
class Rule:
    kind: MediaKind
    limit: int


RULES = {
    "image/jpeg": Rule("image", 10 * MiB),
    "image/png": Rule("image", 10 * MiB),
    "image/webp": Rule("image", 10 * MiB),
    "audio/mpeg": Rule("audio", 80 * MiB),
    "audio/wav": Rule("audio", 80 * MiB),
    "audio/mp4": Rule("audio", 80 * MiB),
    "video/mp4": Rule("video", 300 * MiB),
    "application/pdf": Rule("document", 25 * MiB),
    "application/vnd.openxmlformats-officedocument.presentationml.presentation":
        Rule("presentation", 50 * MiB),
}


@dataclass(frozen=True)
class StagedMedia:
    id: UUID
    object_key: str
    kind: MediaKind
    content_type: str
    byte_count: int
    sha256: str


class PrivateStorage(Protocol):
    def put_object(self, **kwargs: object) -> object: ...


def _pptx_container(stream: BinaryIO) -> bool:
    """Bound metadata inspection only; scanning/decoding is a separate gate."""
    try:
        with zipfile.ZipFile(stream) as archive:
            entries = archive.infolist()
            if not entries or len(entries) > 2000:
                return False
            names = set()
            total = 0
            for entry in entries:
                name = entry.filename
                parts = name.rstrip("/").split("/")
                if (not name or "\\" in name or ":" in name or
                        any(ord(c) < 32 for c in name) or
                        any(part in ("", ".", "..") for part in parts) or
                        name in names or entry.flag_bits & 1 or
                        (entry.external_attr >> 16) & 0o170000 == 0o120000 or
                        name.lower().endswith("vbaproject.bin")):
                    return False
                names.add(name)
                total += entry.file_size
                if total > 250 * MiB:
                    return False
            return (
                "[Content_Types].xml" in names
                and "ppt/presentation.xml" in names
                and not archive.getinfo("ppt/presentation.xml").is_dir()
            )
    except (OSError, ValueError, zipfile.BadZipFile, NotImplementedError):
        return False
    finally:
        stream.seek(0)


def _matches_type(stream: BinaryIO, content_type: str, size: int) -> bool:
    header = stream.read(32)
    stream.seek(0)
    if content_type == "image/jpeg":
        return header.startswith(b"\xff\xd8\xff")
    if content_type == "image/png":
        return header.startswith(b"\x89PNG\r\n\x1a\n")
    if content_type == "image/webp":
        return len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP"
    if content_type == "audio/wav":
        return len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WAVE"
    if content_type == "audio/mpeg":
        return header.startswith(b"ID3") or (
            len(header) >= 4 and header[0] == 255 and header[1] & 0xe0 == 0xe0
        )
    if content_type in ("audio/mp4", "video/mp4"):
        return (len(header) >= 16 and header[4:8] == b"ftyp" and
                16 <= int.from_bytes(header[:4], "big") <= size)
    if content_type == "application/pdf":
        return header.startswith(b"%PDF-")
    return header.startswith(b"PK\x03\x04") and _pptx_container(stream)


def stage_upload(stream: BinaryIO, declared_content_type: str, *,
                 storage: PrivateStorage, private_bucket: str) -> StagedMedia:
    """Copy and hash a bounded stream, then write only to private quarantine.

    A matching signature is NOT an antivirus, transcoding or content safety
    decision. The returned record is staged, never approved for publication.
    The configured bucket must deny anonymous reads. No public URL is returned.
    """
    content_type = declared_content_type.strip().lower()
    rule = RULES.get(content_type)
    if rule is None:
        raise MediaRejected("Неподдерживаемый формат файла")
    if not private_bucket:
        raise RuntimeError("Private Academy media storage is not configured")
    digest = sha256()
    size = 0
    with SpooledTemporaryFile(max_size=MiB, mode="w+b") as temp:
        while True:
            chunk = stream.read(min(MiB, rule.limit - size + 1))
            if not chunk:
                break
            size += len(chunk)
            if size > rule.limit:
                raise MediaRejected("Файл превышает допустимый размер")
            temp.write(chunk)
            digest.update(chunk)
        if not size:
            raise MediaRejected("Файл пуст")
        temp.seek(0)
        if not _matches_type(temp, content_type, size):
            raise MediaRejected("Содержимое файла не соответствует формату")
        media_id = uuid4()
        key = "academy/quarantine/" + media_id.hex
        checksum = digest.hexdigest()
        # No user-supplied filename, URL, ACL, executable content type or
        # public-read policy. A storage failure must propagate, not succeed.
        storage.put_object(
            Bucket=private_bucket, Key=key, Body=temp, ContentLength=size,
            ContentType="application/octet-stream",
            ContentDisposition="attachment",
            Metadata={"sha256": checksum},
        )
    return StagedMedia(media_id, key, rule.kind, content_type, size, checksum)


@dataclass(frozen=True)
class MediaAccess:
    """Inputs must be derived from trusted database rows, never request JSON."""
    course_slug: str
    media_course_slug: str
    scan_state: Literal["pending", "clean", "rejected", "failed"]
    account_active: bool
    is_editor: bool
    is_reviewer: bool
    review_visible: bool
    publication_visible: bool
    in_draft: bool
    in_public_snapshot: bool


def may_read_media(access: MediaAccess, *, view: Literal["draft", "review", "public"]) -> bool:
    """Fail closed across course boundaries and independent publication snapshots.

    This policy does not replace authentication, database ownership checks or
    actual scanner integration. Quarantine objects are never served directly.
    """
    if (not access.account_active or not access.course_slug
            or access.course_slug != access.media_course_slug
            or access.scan_state != "clean"):
        return False
    if view == "draft":
        return access.is_editor and access.in_draft
    if view == "review":
        return access.is_reviewer and access.review_visible and access.in_draft
    if view == "public":
        return access.publication_visible and access.in_public_snapshot
    return False
