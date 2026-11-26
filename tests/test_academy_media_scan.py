from dataclasses import replace
from hashlib import sha256
from io import BytesIO
import struct

import pytest

from app.academy_media_scan import (
    CHUNK, ClamAV, ScanJob, check_quarantined, pending_job, record_scan, validate_image,
)


DATA = b"\x89PNG\r\n\x1a\nexample"
JOB = ScanJob("a" * 32, "course-a", "academy/quarantine/" + "a" * 32,
              "image/png", len(DATA), sha256(DATA).hexdigest())


class Storage:
    def __init__(self, data=DATA, length=None):
        self.data = data
        self.length = len(data) if length is None else length
        self.body = None
        self.calls = []

    def get_object(self, **kwargs):
        self.calls.append(kwargs)
        self.body = BytesIO(self.data)
        return {"Body": self.body, "ContentLength": self.length}


class Scanner:
    def __init__(self, verdict):
        self.verdict = verdict
        self.inputs = []

    def scan(self, stream):
        self.inputs.append(stream.read())
        return self.verdict


def inspect(storage, scanner, validator=lambda stream, mime: "clean", job=JOB):
    return check_quarantined(job, storage=storage, private_bucket="private",
                             scanner=scanner, validator=validator)


def test_scan_uses_exact_bytes_and_both_checks():
    storage = Storage()
    scanner = Scanner("clean")
    validated = []

    def validator(stream, mime):
        validated.append((stream.read(), mime))
        return "clean"

    assert inspect(storage, scanner, validator).verdict == "clean"
    assert scanner.inputs == [DATA]
    assert validated == [(DATA, JOB.content_type)]
    assert storage.body.closed
    assert storage.calls == [{"Bucket": "private", "Key": JOB.object_key}]


@pytest.mark.parametrize("data,length", [
    (b"x" * len(DATA), len(DATA)),
    (DATA + b"x", len(DATA)),
    (DATA[:-1], len(DATA)),
    (DATA, len(DATA)+1),
])
def test_tampered_or_truncated_object_never_reaches_scanner(data, length):
    storage = Storage(data, length)
    scanner = Scanner("clean")
    assert inspect(storage, scanner).verdict == "rejected"
    assert scanner.inputs == [] and storage.body.closed


@pytest.mark.parametrize("scan_result,validation_result,expected", [
    ("rejected", "clean", "rejected"),
    ("failed", "clean", "failed"),
    ("unexpected", "clean", "failed"),
    ("clean", "rejected", "rejected"),
    ("clean", "failed", "failed"),
])
def test_no_approval_on_scan_or_validation_failure(scan_result, validation_result, expected):
    assert inspect(Storage(), Scanner(scan_result), lambda *_: validation_result).verdict == expected


def test_storage_and_decoder_errors_fail_closed():
    class Broken:
        def get_object(self, **kwargs):
            raise OSError("backend unavailable")

    assert inspect(Broken(), Scanner("clean")).verdict == "failed"

    def broken(*args):
        raise RuntimeError("decoder unavailable")

    assert inspect(Storage(), Scanner("clean"), broken).verdict == "failed"
    storage = Storage()
    assert inspect(storage, Scanner("clean"), job=replace(JOB, object_key="other/key")).verdict == "failed"
    assert storage.calls == []


@pytest.mark.parametrize("chunks,expected", [
    ([b"stream: ", b"OK\x00"], "clean"),
    ([b"stream: Test FOUND\x00"], "rejected"),
    ([b"INSTREAM size limit exceeded. ERROR\x00"], "failed"),
    ([b"stream: OK"], "failed"),
    ([b"stream: OK\x00garbage"], "failed"),
    ([b"x" * 4096], "failed"),
])
def test_clamd_framed_stream_and_bounded_reply(monkeypatch, chunks, expected):
    writes = []

    class FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def settimeout(self, timeout):
            assert 0 < timeout <= 180

        def connect(self, path):
            assert path == "/run/clamav/clamd.sock"

        def sendall(self, data):
            writes.append(data)

        def recv(self, count):
            if not chunks:
                return b""
            data = chunks.pop(0)
            if len(data) > count:
                chunks.insert(0, data[count:])
            return data[:count]

    monkeypatch.setattr("app.academy_media_scan.socket.socket", lambda *_: FakeSocket())
    assert ClamAV("/run/clamav/clamd.sock").scan(BytesIO(DATA)) == expected
    assert writes == [b"zINSTREAM\x00", struct.pack("!I", len(DATA)) + DATA, b"\x00" * 4]


def test_image_decoder_only_supports_verified_still_images():
    from PIL import Image

    image = Image
    buffer = BytesIO()
    image.new("RGB", (8, 8)).save(buffer, format="PNG")
    assert validate_image(buffer, "image/png") == "clean"
    assert validate_image(buffer, "image/jpeg") == "rejected"
    assert validate_image(BytesIO(DATA), "image/png") == "rejected"
    assert validate_image(BytesIO(b"%PDF-1.7"), "application/pdf") == "failed"


def test_scan_cas_does_not_revive_removed_or_changed_media(tmp_path):
    from app.db import database, init_db
    from app.release02 import init_release02
    from app.academy_media_scan import ScanReport

    path = str(tmp_path / "scan.sqlite")
    init_db(path)
    init_release02(path)
    with database(path) as db:
        db.execute("""INSERT INTO academy_courses(slug,draft_json,created_at,updated_at)
                   VALUES('course-a','{}','2026-01-01','2026-01-01')""")
        db.execute(
            """INSERT INTO academy_media(id,course_slug,course_version,object_key,kind,content_type,
                      byte_count,sha256,state,created_at,updated_at)
               VALUES(?,?,1,?,'image',?,?,?,'pending','2026-01-01','2026-01-01')""",
            (JOB.id, JOB.course_slug, JOB.object_key, JOB.content_type, JOB.byte_count, JOB.sha256),
        )
        assert pending_job(db, JOB.id) == JOB
        assert not record_scan(db, ScanReport(replace(JOB, sha256="b"*64), "clean"))
        db.execute("UPDATE academy_media SET state='purge_pending' WHERE id=?", (JOB.id,))
        assert not record_scan(db, ScanReport(JOB, "clean"))
        assert pending_job(db, JOB.id) is None
        db.execute("UPDATE academy_media SET state='pending' WHERE id=?", (JOB.id,))
        assert record_scan(db, ScanReport(JOB, "rejected"))
        assert not record_scan(db, ScanReport(JOB, "clean"))
