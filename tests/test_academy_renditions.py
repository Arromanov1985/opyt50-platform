"""Source-to-rendition workflow with private storage and isolated-runner doubles."""
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from app.academy_media_scan import pending_job, ScanReport, record_scan
from app.academy_renditions import parse_manifest, ready_metadata, RenditionError, reserve_copies, finalize_copies
from app.academy_rendition_worker import process_conversion
from app.db import database, init_db
from app.release02 import init_release02


SOURCE = b"%PDF-1.7\nsynthetic source"
MEDIA_ID = "a" * 32
SOURCE_KEY = "academy/quarantine/" + MEDIA_ID


def jpeg():
    stream = BytesIO()
    Image.new("RGB",(20,20),"white").save(stream,"JPEG")
    return stream.getvalue()


def entry(page, content):
    return {"name":f"page-{page:03d}.jpg","content_type":"image/jpeg",
            "byte_count":len(content),"sha256":sha256(content).hexdigest(),
            "page":page,"duration":None}


@pytest.fixture
def media_db(tmp_path):
    path = str(tmp_path / "academy.sqlite")
    init_db(path)
    init_release02(path)
    with database(path) as db:
        db.execute("INSERT INTO users(id,email,password_hash,role,name) VALUES(1,'media@example.invalid','hash','candidate','Test')")
        db.execute("""INSERT INTO academy_courses(slug,owner_id,draft_json,created_at,updated_at)
                   VALUES('course-a',1,'{}','2026-01-01','2026-01-01')""")
        db.execute(
            """INSERT INTO academy_media(id,course_slug,course_version,object_key,kind,content_type,
                       byte_count,sha256,state,created_at,updated_at)
               VALUES(?,'course-a',1,?,'document','application/pdf',?,?,'pending','2026-01-01','2026-01-01')""",
            (MEDIA_ID,SOURCE_KEY,len(SOURCE),sha256(SOURCE).hexdigest()),
        )
    return path


class Storage:
    def __init__(self, *, fail_second=False):
        self.objects={SOURCE_KEY:SOURCE}
        self.fail_second=fail_second
        self.writes=[]

    def get_object(self, **kwargs):
        data=self.objects[kwargs["Key"]]
        return {"Body":BytesIO(data),"ContentLength":len(data)}

    def put_object(self, **kwargs):
        assert kwargs["IfNoneMatch"]=="*"
        assert kwargs["ContentType"]=="application/octet-stream"
        assert kwargs["ContentDisposition"]=="attachment"
        key=kwargs["Key"]
        assert key.startswith("academy/renditions/") and key not in self.objects
        self.writes.append(key)
        if self.fail_second and len(self.writes)==2:
            raise OSError("ambiguous storage failure")
        data=kwargs["Body"].read()
        assert sha256(data).hexdigest()==kwargs["Metadata"]["sha256"]
        self.objects[key]=data


class Scanner:
    def __init__(self, verdicts=None):
        self.checked=[]
        self.verdicts=list(verdicts or [])

    def scan(self, stream):
        self.checked.append(stream.read())
        return self.verdicts.pop(0) if self.verdicts else "clean"


def converter(stream, mime, directory):
    assert stream.read()==SOURCE and mime=="application/pdf"
    content=jpeg()
    for page in (1,2):
        (directory/f"page-{page:03d}.jpg").write_bytes(content)
    return {"renditions":[entry(1,content),entry(2,content)]}


def test_complete_batch_committed_after_independent_checks(media_db):
    storage,scanner=Storage(),Scanner()
    assert process_conversion(media_db,MEDIA_ID,storage=storage,bucket="private",
                              scanner=scanner,isolated_converter=converter)=="clean"
    assert scanner.checked==[SOURCE,jpeg(),jpeg()]
    assert len(storage.writes)==2
    with database(media_db) as db:
        assert db.execute("SELECT state FROM academy_media WHERE id=?", (MEDIA_ID,)).fetchone()[0]=="clean"
        metadata=ready_metadata(db,"course-a")[MEDIA_ID]
        assert [row["position"] for row in metadata]==[1,2]
        assert all(set(row)=={"position","content_type","byte_count","duration_ms"} for row in metadata)
        assert ready_metadata(db,"other")=={}
    assert process_conversion(media_db,MEDIA_ID,storage=storage,bucket="private",
                              scanner=scanner,isolated_converter=converter)=="skipped"
    assert len(storage.writes)==2


def test_partial_put_keeps_durable_keys_and_never_exposes_pages(media_db):
    storage=Storage(fail_second=True)
    assert process_conversion(media_db,MEDIA_ID,storage=storage,bucket="private",
                              scanner=Scanner(),isolated_converter=converter)=="failed"
    with database(media_db) as db:
        rows=db.execute("SELECT state,object_key FROM academy_media_renditions ORDER BY position").fetchall()
        assert [(row["state"],row["object_key"]) for row in rows]==[("reserved",key) for key in storage.writes]
        assert ready_metadata(db,"course-a")=={}
        assert db.execute("SELECT state FROM academy_media").fetchone()[0]=="failed"
    assert process_conversion(media_db,MEDIA_ID,storage=storage,bucket="private",
                              scanner=Scanner(),isolated_converter=converter)=="skipped"


def test_original_antivirus_blocks_converter(media_db):
    def forbidden(*args):
        pytest.fail("Rejected source reached converter")
    storage=Storage()
    assert process_conversion(media_db,MEDIA_ID,storage=storage,bucket="private",
                              scanner=Scanner(["rejected"]),isolated_converter=forbidden)=="rejected"
    assert not storage.writes
    with database(media_db) as db:
        assert ready_metadata(db,"course-a")=={}
        assert db.execute("SELECT COUNT(*) FROM academy_media_renditions").fetchone()[0]==0


def test_rejected_derivative_is_not_put_or_activated(media_db):
    storage=Storage()
    assert process_conversion(media_db,MEDIA_ID,storage=storage,bucket="private",
                              scanner=Scanner(["clean","rejected"]),isolated_converter=converter)=="failed"
    assert not storage.writes
    with database(media_db) as db:
        assert ready_metadata(db,"course-a")=={}


def test_manifest_and_symlink_are_not_trusted(media_db,tmp_path):
    invalid=entry(1,jpeg())
    for change in ({"name":"../secret"},{"page":2},{"byte_count":True},{"sha256":"x"*64}):
        with pytest.raises(RenditionError):
            parse_manifest("application/pdf",{"renditions":[{**invalid,**change}]})
    outside=tmp_path/"outside.jpg"
    outside.write_bytes(jpeg())

    def malicious(stream,mime,directory):
        (directory/"page-001.jpg").symlink_to(outside)
        return {"renditions":[entry(1,jpeg())]}
    storage=Storage()
    assert process_conversion(media_db,MEDIA_ID,storage=storage,bucket="private",
                              scanner=Scanner(),isolated_converter=malicious)=="failed"
    assert not storage.writes


def test_restriction_during_conversion_prevents_all_reservations(media_db):
    def restricted(stream,mime,directory):
        result=converter(stream,mime,directory)
        with database(media_db) as db:
            db.execute("INSERT INTO account_controls(user_id,status) VALUES(1,'disabled')")
        return result
    storage=Storage()
    assert process_conversion(media_db,MEDIA_ID,storage=storage,bucket="private",
                              scanner=Scanner(),isolated_converter=restricted)=="skipped"
    assert not storage.writes
    with database(media_db) as db:
        assert db.execute("SELECT COUNT(*) FROM academy_media_renditions").fetchone()[0]==0


def test_incomplete_and_stale_completion_cannot_activate(media_db):
    with database(media_db) as db:
        job=pending_job(db,MEDIA_ID)
        copies=reserve_copies(db,job,{"renditions":[entry(1,jpeg()),entry(2,jpeg())]})
    with database(media_db) as db:
        with pytest.raises(RenditionError):
            finalize_copies(db,job,copies,{copies[0].id})
        db.execute("UPDATE academy_media SET state='purge_pending' WHERE id=?", (MEDIA_ID,))
        assert not finalize_copies(db,job,copies,{c.id for c in copies})
        assert ready_metadata(db,"course-a")=={}
