"""Private delivery of a complete checked rendition, never a quarantine object."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from tempfile import SpooledTemporaryFile
import re
import time

from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool
from starlette.responses import StreamingResponse

from .academy_media import MiB
from .academy_media_scan import ScanJob, CHUNK

OUTPUT_LIMITS = {"image/jpeg":3*MiB,"audio/mp4":64*MiB,"video/mp4":160*MiB}
NAMES = {"image/jpeg":"page.jpg","audio/mp4":"audio.m4a","video/mp4":"video.mp4"}


@dataclass(frozen=True)
class Delivery:
    source: ScanJob
    id: str
    position: int
    object_key: str
    content_type: str
    byte_count: int
    sha256: str


def authorized_copy(db, source: ScanJob, position: int) -> Delivery:
    # Caller first authorizes the exact current draft/review source.
    if not 1 <= position <= 30:
        raise HTTPException(404,"Материал недоступен")
    row=db.execute(
        """SELECT r.id,r.position,r.object_key,r.content_type,r.byte_count,r.sha256
           FROM academy_media_renditions r JOIN academy_media m ON m.id=r.media_id
           WHERE r.media_id=? AND r.position=? AND m.course_slug=? AND m.state='clean'
             AND m.sha256=? AND r.state='ready' AND r.source_sha256=m.sha256
             AND NOT EXISTS(SELECT 1 FROM academy_media_renditions x WHERE x.media_id=m.id
                 AND (x.state<>'ready' OR x.source_sha256<>m.sha256))""",
        (source.id,position,source.course_slug,source.sha256)
    ).fetchone()
    if row is None:
        raise HTTPException(404,"Материал недоступен")
    result=Delivery(source,**dict(row))
    if (not re.fullmatch(r"[0-9a-f]{32}",result.id)
            or result.object_key!="academy/renditions/"+result.id
            or not re.fullmatch(r"[0-9a-f]{64}",result.sha256)
            or not 1 <= result.byte_count <= OUTPUT_LIMITS.get(result.content_type,0)):
        raise HTTPException(404,"Материал недоступен")
    return result


def byte_range(header: str | None, total: int) -> tuple[int,int,int]:
    """Single inclusive range, including suffix and open-ended requests."""
    if total <= 0:
        raise ValueError("Invalid object length")
    if header is None:
        return 0,total-1,200
    m=re.fullmatch(r"bytes=([0-9]{0,12})-([0-9]{0,12})",header)
    if m and (m[1] or m[2]):
        if m[1]:
            start=int(m[1])
            end=min(int(m[2]),total-1) if m[2] else total-1
        elif int(m[2])>0:
            start=max(0,total-int(m[2]))
            end=total-1
        else:
            start,end=total,0
        if 0 <= start <= end < total:
            return start,end,206
    raise HTTPException(416,"Недопустимый диапазон",headers={"Content-Range":f"bytes */{total}"})


def verified_stream(copy: Delivery, *, storage, bucket: str):
    """Spool bounded bytes and verify all of them before returning any range."""
    if not bucket or not 1 <= copy.byte_count <= OUTPUT_LIMITS.get(copy.content_type,0):
        raise ValueError("Invalid delivery")
    if copy.object_key!="academy/renditions/"+copy.id or not re.fullmatch(r"[0-9a-f]{32}",copy.id):
        raise ValueError("Invalid object key")
    temp=SpooledTemporaryFile(max_size=MiB,mode="w+b")
    deadline=time.monotonic()+120
    try:
        response=storage.get_object(Bucket=bucket,Key=copy.object_key)
        body=response["Body"]
        try:
            if response.get("ContentLength")!=copy.byte_count:
                raise ValueError("Object length mismatch")
            size=0
            digest=sha256()
            while True:
                if time.monotonic()>=deadline:
                    raise TimeoutError("Rendition retrieval exceeded deadline")
                chunk=body.read(min(CHUNK,copy.byte_count-size+1))
                if not chunk:
                    break
                size+=len(chunk)
                if size>copy.byte_count:
                    raise ValueError("Object length mismatch")
                digest.update(chunk)
                temp.write(chunk)
            if time.monotonic()>=deadline or size!=copy.byte_count or digest.hexdigest()!=copy.sha256:
                raise ValueError("Object integrity mismatch")
        finally:
            body.close()
        temp.seek(0)
        return temp
    except BaseException:
        temp.close()
        raise


class PrivateCopyResponse(StreamingResponse):
    """Hold the bounded delivery slot until response or disconnect completes."""
    def __init__(self, stream, copy: Delivery, start: int, end: int, status: int, release):
        self.stream=stream
        self.release=release
        stream.seek(start)

        async def chunks():
            remaining=end-start+1
            while remaining:
                data=await run_in_threadpool(stream.read,min(CHUNK,remaining))
                if not data:
                    raise RuntimeError("Verified rendition was truncated")
                remaining-=len(data)
                yield data

        headers={"Cache-Control":"no-store","X-Content-Type-Options":"nosniff",
                 "Content-Disposition":'inline; filename="'+NAMES[copy.content_type]+'"',
                 "Accept-Ranges":"bytes","Content-Length":str(end-start+1)}
        if status==206:
            headers["Content-Range"]=f"bytes {start}-{end}/{copy.byte_count}"
        super().__init__(chunks(),status_code=status,media_type=copy.content_type,headers=headers)

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope,receive,send)
        finally:
            try:
                self.stream.close()
            finally:
                self.release()
