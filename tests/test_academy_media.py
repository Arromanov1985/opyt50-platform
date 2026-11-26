from hashlib import sha256
from io import BytesIO
import zipfile

import pytest

from app.academy_media import MediaRejected, RULES, Rule, stage_upload


PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


class FakePrivateStorage:
    def __init__(self):
        self.calls = []

    def put_object(self, **kwargs):
        self.calls.append({**kwargs, "Body": kwargs["Body"].read()})


def stage(payload, content_type, storage=None):
    client = storage if storage is not None else FakePrivateStorage()
    return stage_upload(BytesIO(payload), content_type, storage=client,
                        private_bucket="test-private-academy"), client


def presentation(extra=None):
    data = BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("ppt/presentation.xml", "<presentation/>")
        if extra:
            archive.writestr(extra, "untrusted")
    return data.getvalue()


@pytest.mark.parametrize("mime,header,kind", [
    ("image/png", b"\x89PNG\r\n\x1a\n", "image"),
    ("image/jpeg", b"\xff\xd8\xff", "image"),
    ("image/webp", b"RIFF\x08\x00\x00\x00WEBP", "image"),
    ("audio/wav", b"RIFF\x08\x00\x00\x00WAVE", "audio"),
    ("audio/mpeg", b"ID3", "audio"),
    ("audio/mp4", b"\x00\x00\x00\x10ftypM4A \x00\x00\x00\x00", "audio"),
    ("video/mp4", b"\x00\x00\x00\x10ftypisom\x00\x00\x00\x00", "video"),
    ("application/pdf", b"%PDF-1.7", "document"),
])
def test_upload_stages_only_private_objects(mime, header, kind):
    # Small synthetic signatures test preflight only, not decodability.
    data = header + b"example data"
    media, client = stage(data, mime)
    call, = client.calls
    assert media.kind == kind
    assert media.content_type == mime
    assert media.byte_count == len(data)
    assert media.sha256 == sha256(data).hexdigest()
    assert media.object_key == "academy/quarantine/" + media.id.hex
    assert call["Body"] == data and call["ContentLength"] == len(data)
    assert call["Bucket"] == "test-private-academy"
    assert call["Key"] == media.object_key
    assert call["ContentType"] == "application/octet-stream"
    assert call["ContentDisposition"] == "attachment"
    assert call["IfNoneMatch"] == "*"
    assert call["Metadata"] == {"sha256": media.sha256}
    assert "ACL" not in call
    assert stage(data, mime)[0].object_key != media.object_key


@pytest.mark.parametrize("mime,payload", [
    ("text/html", b"<html>"),
    ("image/svg+xml", b"<svg>"),
    ("application/octet-stream", b"whatever"),
    ("image/png", b""),
    ("image/png", b"%PDF-1.7"),
    ("video/mp4", b"anythingftyp"),
    (PPTX, b"PK\x03\x04not-a-zip"),
])
def test_rejected_files_never_reach_storage(mime, payload):
    client = FakePrivateStorage()
    with pytest.raises(MediaRejected):
        stage(payload, mime, client)
    assert client.calls == []


def test_bounded_copy_checks_actual_bytes(monkeypatch):
    monkeypatch.setitem(RULES, "image/png", Rule("image", 12))
    client = FakePrivateStorage()
    valid = b"\x89PNG\r\n\x1a\n1234"
    assert stage(valid, "image/png", client)[0].byte_count == 12
    with pytest.raises(MediaRejected, match="размер"):
        stage(valid + b"5", "image/png", client)
    assert len(client.calls) == 1


def test_presentation_preflight_rejects_unsafe_archives():
    assert stage(presentation(), PPTX)[0].kind == "presentation"
    for unsafe in ("../outside", "/absolute", "ppt\\bad", "ppt/vbaProject.bin"):
        client = FakePrivateStorage()
        with pytest.raises(MediaRejected):
            stage(presentation(unsafe), PPTX, client)
        assert client.calls == []


def test_unconfigured_storage_fails_closed():
    client = FakePrivateStorage()
    with pytest.raises(RuntimeError, match="not configured"):
        stage_upload(BytesIO(b"%PDF-1.7"), "application/pdf",
                     storage=client, private_bucket="")
    assert client.calls == []


def test_storage_failure_is_not_a_success():
    class Broken:
        def put_object(self, **kwargs):
            raise OSError("storage unavailable")

    with pytest.raises(OSError):
        stage_upload(BytesIO(b"%PDF-1.7"), "application/pdf",
                     storage=Broken(), private_bucket="private")


def test_media_access_is_bound_to_course_and_snapshot():
    from dataclasses import replace
    from app.academy_media import MediaAccess, may_read_media

    access = MediaAccess("course-a", "course-a", "clean", True,
                         True, False, False, True, True, False)
    assert may_read_media(access, view="draft")
    assert not may_read_media(access, view="public")
    assert not may_read_media(access, view="review")
    published = replace(access, in_public_snapshot=True, in_draft=False,
                        is_editor=False)
    assert may_read_media(published, view="public")
    assert not may_read_media(published, view="draft")
    assert not may_read_media(replace(published, publication_visible=False), view="public")
    review = replace(access, is_editor=False, is_reviewer=True, review_visible=True)
    assert may_read_media(review, view="review")
    assert not may_read_media(replace(review, review_visible=False), view="review")
    for view, candidate in (("draft", access), ("review", review), ("public", published)):
        for state in ("pending", "rejected", "failed"):
            assert not may_read_media(replace(candidate, scan_state=state), view=view)
        assert not may_read_media(replace(candidate, account_active=False), view=view)
        assert not may_read_media(replace(candidate, media_course_slug="course-b"), view=view)


def test_registry_reserves_exact_bytes_and_never_approves(tmp_path):
    from dataclasses import replace
    from fastapi import HTTPException
    from app.db import database, init_db
    from app.release02 import init_release02
    from app.academy_media_registry import reserve_media, upload_reserved, record_staged

    path = str(tmp_path / "media.sqlite")
    init_db(path)
    init_release02(path)
    data = b"\x89PNG\r\n\x1a\n1234"
    author = {"id": 1, "role": "candidate"}
    with database(path) as db:
        for uid in (1, 2):
            db.execute("INSERT INTO users(id,email,password_hash,role,name) VALUES(?,?,?,?,?)",
                       (uid, f"media-{uid}@example.invalid", "hash", "candidate", "Test"))
        db.execute("""INSERT INTO academy_courses(slug,owner_id,draft_json,created_at,updated_at)
                   VALUES('course-a',1,'{}','2026-01-01','2026-01-01')""")
        with pytest.raises(HTTPException) as denied:
            reserve_media(db, {"id": 2, "role": "candidate"}, "course-a", 1, "image/png", len(data))
        assert denied.value.status_code == 404
        with pytest.raises(HTTPException) as stale:
            reserve_media(db, author, "course-a", 2, "image/png", len(data))
        assert stale.value.status_code == 409
        reservation = reserve_media(db, author, "course-a", 1, "image/png", len(data))
    client = FakePrivateStorage()
    with pytest.raises(MediaRejected):
        upload_reserved(reservation, BytesIO(data + b"X"), storage=client, private_bucket="private")
    assert client.calls == []
    media = upload_reserved(reservation, BytesIO(data), storage=client, private_bucket="private")
    with database(path) as db:
        row = db.execute("SELECT * FROM academy_media WHERE id=?", (reservation.id.hex,)).fetchone()
        assert row["state"] == "reserved" and row["sha256"] is None
        assert row["object_key"] == media.object_key
        with pytest.raises(ValueError):
            record_staged(db, reservation, replace(media, byte_count=len(data)+1))
        record_staged(db, reservation, media)
        row = db.execute("SELECT * FROM academy_media WHERE id=?", (reservation.id.hex,)).fetchone()
        assert row["state"] == "pending" and row["sha256"] == sha256(data).hexdigest()
        with pytest.raises(ValueError):
            record_staged(db, reservation, media)
    # A failed or unfinished upload cannot leave an untracked object after
    # deleting its parent course: the registry must be reconciled first.
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        with database(path) as db:
            db.execute("DELETE FROM academy_courses WHERE slug='course-a'")


def test_registry_quota_and_restricted_accounts(tmp_path, monkeypatch):
    from fastapi import HTTPException
    from app.db import database, init_db
    from app.release02 import init_release02
    from app import academy_media_registry as registry

    path = str(tmp_path / "quota.sqlite")
    init_db(path)
    init_release02(path)
    actor = {"id": 1, "role": "candidate"}
    monkeypatch.setattr(registry, "MAX_COURSE_FILES", 2)
    monkeypatch.setattr(registry, "MAX_COURSE_BYTES", 30)
    with database(path) as db:
        db.execute("INSERT INTO users(id,email,password_hash,role,name) VALUES(1,'quota@example.invalid','hash','candidate','Test')")
        db.execute("""INSERT INTO academy_courses(slug,owner_id,draft_json,created_at,updated_at)
                   VALUES('course-q',1,'{}','2026-01-01','2026-01-01')""")
        registry.reserve_media(db, actor, "course-q", 1, "image/png", 20)
        with pytest.raises(HTTPException) as quota:
            registry.reserve_media(db, actor, "course-q", 1, "image/png", 11)
        assert quota.value.status_code == 409
        registry.reserve_media(db, actor, "course-q", 1, "image/png", 10)
        with pytest.raises(HTTPException) as quota:
            registry.reserve_media(db, actor, "course-q", 1, "image/png", 1)
        assert quota.value.status_code == 409
        assert db.execute("SELECT COUNT(*) FROM academy_media").fetchone()[0] == 2
        db.execute("INSERT INTO account_controls(user_id,status) VALUES(1,'disabled')")
        with pytest.raises(HTTPException) as restricted:
            registry.reserve_media(db, actor, "course-q", 1, "image/png", 1)
        assert restricted.value.status_code == 403
