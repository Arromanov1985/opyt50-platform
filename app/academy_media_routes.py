"""Opt-in authenticated image upload and private sanitized draft preview.

Only JPEG/PNG/WebP initially. No public delivery, no original download and
no multipart parsing. Never hold a DB transaction across storage I/O.
"""
from __future__ import annotations

import asyncio
import json
from tempfile import SpooledTemporaryFile

from fastapi import Depends, HTTPException, Query, Request, Response
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect

from .academy_media import MiB, MediaRejected, RULES, MediaAccess, may_read_media
from .academy_media_registry import (
    course_media_metadata, media_ids, reserve_media, upload_reserved, record_staged,
)
from .academy_storage import build_storage_client, image_upload_config
from .academy_media_scan import ScanJob
from .academy_image_preview import sanitized_preview


def _backend():
    try:
        setup = image_upload_config()
        if setup is None:
            raise RuntimeError("Disabled")
        config, _ = setup
        return config, build_storage_client(config)
    except Exception:
        raise HTTPException(503, "Загрузка изображений пока недоступна") from None


def _check_editor(db, user, slug, version):
    from .academy_builder import _row, _is_editor, _version
    from .community import _active_account
    row = _row(db, slug)
    if not _is_editor(user, row):
        raise HTTPException(404, "Курс недоступен")
    if not _active_account(db, user["id"]):
        raise HTTPException(403, "Обработка данных ограничена")
    _version(row, version)


def _reauth(request, db, initial_user):
    from .main import active_user
    fresh = active_user(request, db)
    if fresh["id"] != initial_user["id"] or fresh["role"] != initial_user["role"]:
        raise HTTPException(409, "Аккаунт изменился. Обновите страницу")
    return fresh


async def _copy_body(request, stream, expected_size):
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > expected_size:
            raise HTTPException(413, "Размер файла превышен")
        stream.write(chunk)
    if total != expected_size:
        raise HTTPException(400, "Размер файла не соответствует заявленному")
    stream.seek(0)


def _preview_job(db, user, slug, media_id):
    from .academy_builder import _row, _is_editor, _review_visible
    from .community import _active_account
    course = _row(db, slug)
    mine = _is_editor(user, course)
    reviewing = user["role"] == "admin" and _review_visible(db, course)
    row = db.execute(
        """SELECT id,course_slug,object_key,content_type,byte_count,sha256,state
           FROM academy_media WHERE id=? AND course_slug=?""", (media_id, slug)
    ).fetchone()
    if row is None or RULES.get(row["content_type"]) is None or RULES[row["content_type"]].kind != "image":
        raise HTTPException(404, "Изображение недоступно")
    owner = course["owner_id"]
    active = _active_account(db, user["id"]) and (owner is None or _active_account(db, owner))
    access = MediaAccess(slug, row["course_slug"], row["state"], active, mine,
                         reviewing, reviewing, False,
                         media_id in media_ids(json.loads(course["draft_json"])), False)
    if not may_read_media(access, view="draft" if mine else "review"):
        raise HTTPException(404, "Изображение недоступно")
    return ScanJob(row["id"], row["course_slug"], row["object_key"],
                   row["content_type"], row["byte_count"], row["sha256"])


def install_media_routes(app, community_user, throttle, get_connection):
    # Bounded simultaneous upload/preview work per web worker. Deployment
    # must additionally configure proxy body size, timeouts and global quotas.
    upload_slots = asyncio.Semaphore(2)
    preview_slots = asyncio.Semaphore(2)

    @app.post("/api/community/courses/{slug}/media/upload", status_code=201)
    async def upload_image(slug: str, request: Request,
                           expected_version: int = Query(ge=1),
                           user: dict = Depends(community_user), db=Depends(get_connection)):
        config, storage = await run_in_threadpool(_backend)
        media_type = request.headers.get("content-type", "").strip().lower()
        rule = RULES.get(media_type)
        if rule is None or rule.kind != "image":
            raise HTTPException(415, "Поддерживаются JPEG, PNG и WebP")
        if request.headers.get("content-encoding", "identity").lower() != "identity":
            raise HTTPException(415, "Сжатое тело запроса не поддерживается")
        try:
            size = int(request.headers.get("content-length", ""))
        except ValueError:
            raise HTTPException(411, "Укажите размер файла") from None
        if size < 1 or size > rule.limit:
            raise HTTPException(413, "Изображение должно быть не больше 10 МиБ")
        if request.headers.get("transfer-encoding"):
            raise HTTPException(400, "Неоднозначный размер запроса")

        def preflight():
            _check_editor(db, user, slug, expected_version)
            throttle(db, user["id"], "academy-image-upload", 12, 3600)
            db.commit()

        await run_in_threadpool(preflight)
        if upload_slots.locked():
            raise HTTPException(429, "Слишком много загрузок. Повторите позже")
        async with upload_slots:
            with SpooledTemporaryFile(max_size=MiB, mode="w+b") as temp:
                try:
                    await asyncio.wait_for(_copy_body(request, temp, size), timeout=60)
                except (TimeoutError, ClientDisconnect):
                    raise HTTPException(408, "Загрузка прервана") from None

                def reserve():
                    fresh = _reauth(request, db, user)
                    reservation = reserve_media(db, fresh, slug, expected_version, media_type, size)
                    db.commit()
                    return reservation

                reservation = await run_in_threadpool(reserve)
                try:
                    staged = await run_in_threadpool(
                        upload_reserved, reservation, temp, storage=storage, private_bucket=config.bucket
                    )
                except MediaRejected:
                    # No object was written by validation failure. Keep the
                    # reservation as a failed record for later reconciliation.
                    from .community import _now
                    def reject():
                        db.execute(
                            "UPDATE academy_media SET state='failed',updated_at=? WHERE id=? AND state='reserved'",
                            (_now(), reservation.id.hex),
                        )
                        db.commit()
                    await run_in_threadpool(reject)
                    raise HTTPException(422, "Файл не соответствует заявленному формату") from None
                except Exception:
                    # Network failures can be ambiguous: retain the durable
                    # reservation instead of retrying with another object key.
                    raise HTTPException(503, "Не удалось подтвердить загрузку. Обновите реестр") from None

                def finish():
                    # The staged bytes must be accounted for even if the user
                    # was restricted or the session expired during the PUT.
                    record_staged(db, reservation, staged)
                    db.commit()
                    fresh = _reauth(request, db, user)
                    _check_editor(db, fresh, slug, expected_version)
                    result = course_media_metadata(db, slug)
                    db.commit()
                    return result

                files = await run_in_threadpool(finish)
                return {"file_id": reservation.id.hex, "media_files": files}

    @app.get("/api/community/courses/{slug}/media/{media_id}/preview")
    async def preview_image(slug: str, media_id: str, request: Request,
                            user: dict = Depends(community_user), db=Depends(get_connection)):
        def authorize():
            job = _preview_job(db, user, slug, media_id)
            throttle(db, user["id"], "academy-image-preview", 240, 3600)
            db.commit()
            return job

        job = await run_in_threadpool(authorize)
        if preview_slots.locked():
            raise HTTPException(429, "Предпросмотр занят. Повторите позже")
        async with preview_slots:
            config, storage = await run_in_threadpool(_backend)
            try:
                content = await run_in_threadpool(
                    sanitized_preview, job, storage=storage, private_bucket=config.bucket
                )
            except Exception:
                raise HTTPException(503, "Предпросмотр недоступен") from None

            def recheck():
                fresh = _reauth(request, db, user)
                if _preview_job(db, fresh, slug, media_id) != job:
                    raise HTTPException(404, "Изображение недоступно")
                db.commit()

            await run_in_threadpool(recheck)
            return Response(content=content, media_type="image/jpeg", headers={
                "Cache-Control": "no-store", "Content-Disposition": 'inline; filename="preview.jpg"',
                "X-Content-Type-Options": "nosniff",
            })
