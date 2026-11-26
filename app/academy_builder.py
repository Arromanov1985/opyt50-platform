"""Course studio: validated drafts, independent public snapshots and author review."""
from __future__ import annotations

import json
from typing import Literal
from uuid import UUID

from fastapi import Depends, HTTPException, Query, Request
from pydantic import Field, field_validator, model_validator

from .academy_content import COURSES
from .community import (
    CommunityModel, ModerationInput, PublishInput, VersionInput, PAGE_SIZE,
    _active_account, _committed, _is_published, _lock_actors, _now, _profile, _public_text,
)
from .community_feed import _private
from .db import database

LIMIT = 10
MAX_LESSONS = 30
DRAFT_FIELDS = ("title", "description", "audience", "outcomes", "lessons")


class Question(CommunityModel):
    text: str = Field(default="", max_length=500)
    options: list[str] = Field(default_factory=list, max_length=5)
    correct: int | None = Field(default=None, ge=0, le=4)
    feedback: str = Field(default="", max_length=1000)

    @field_validator("text", "feedback")
    @classmethod
    def safe(cls, value):
        return _public_text(value)

    @field_validator("options")
    @classmethod
    def safe_options(cls, values):
        if any(len(value) > 500 for value in values):
            raise ValueError("Вариант ответа слишком длинный")
        return [_public_text(value) for value in values]


class Lesson(CommunityModel):
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=60)
    title: str = Field(default="", max_length=180)
    minutes: int = Field(default=10, ge=1, le=180)
    goal: str = Field(default="", max_length=600)
    sections: list[list[str]] = Field(default_factory=list, max_length=12)
    example: str = Field(default="", max_length=4000)
    practice: str = Field(default="", max_length=4000)
    questions: list[Question] = Field(default_factory=list, max_length=10)

    @field_validator("title", "goal", "example", "practice")
    @classmethod
    def safe(cls, value):
        return _public_text(value)

    @field_validator("sections")
    @classmethod
    def safe_sections(cls, values):
        if any(len(section)>9 or any(len(value)>4000 for value in section) for section in values):
            raise ValueError("Блок: заголовок и до восьми абзацев по 4000 символов")
        return [[_public_text(value) for value in section] for section in values]


class CourseDraft(CommunityModel):
    title: str = Field(default="", max_length=180)
    description: str = Field(default="", max_length=600)
    audience: str = Field(default="", max_length=600)
    outcomes: list[str] = Field(default_factory=list, max_length=12)
    lessons: list[Lesson] = Field(default_factory=list, max_length=MAX_LESSONS)

    @field_validator("title", "description", "audience")
    @classmethod
    def safe(cls, value):
        return _public_text(value)

    @field_validator("outcomes")
    @classmethod
    def safe_outcomes(cls, values):
        if any(len(value)>500 for value in values):
            raise ValueError("Результат обучения — до 500 символов")
        return [_public_text(value) for value in values]

    @model_validator(mode="after")
    def check_size(self):
        if len({lesson.slug for lesson in self.lessons}) != len(self.lessons):
            raise ValueError("Уроки должны иметь разные идентификаторы")
        if len(self.model_dump_json().encode("utf-8")) > 180000:
            raise ValueError("Курс слишком велик: сократите текст или разделите на два курса")
        return self


class CourseCreate(CommunityModel):
    client_key: UUID


class CourseSave(CourseDraft):
    expected_version: int = Field(ge=1)


def readiness(draft: dict) -> list[str]:
    issues = []
    for field, name, size in (("title", "Название", 5), ("description", "Описание", 20), ("audience", "Для кого курс", 10)):
        if len(draft.get(field, "")) < size:
            issues.append(name + ": заполните поле")
    if not any(len(value) >= 5 for value in draft["outcomes"]):
        issues.append("Добавьте хотя бы один результат обучения")
    if not draft["lessons"]:
        issues.append("Добавьте хотя бы один урок")
    for index, lesson in enumerate(draft["lessons"], 1):
        prefix = "Урок " + str(index) + ": "
        if len(lesson["title"]) < 3 or len(lesson["goal"]) < 10:
            issues.append(prefix + "укажите название и цель")
        if not lesson["sections"] or any(len(section)<2 or not section[0] or not any(section[1:]) for section in lesson["sections"]):
            issues.append(prefix + "заполните заголовки и текст блоков")
        if not lesson["example"] or not lesson["practice"]:
            issues.append(prefix + "добавьте пример и практическое задание")
        if not lesson["questions"]:
            issues.append(prefix + "добавьте хотя бы один вопрос")
        for qindex, q in enumerate(lesson["questions"], 1):
            options = q["options"]
            if (not q["text"] or len(options)<2 or any(not item for item in options)
                    or len(set(options)) != len(options) or q["correct"] is None
                    or q["correct"] >= len(options) or not q["feedback"]):
                issues.append(prefix + "заполните вопрос " + str(qindex) + ", варианты, правильный ответ и пояснение")
    return issues


def _encoded(data):
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def init_academy(path):
    with database(path) as db:
        for course in COURSES:
            now = _now()
            db.execute(
                """INSERT INTO academy_courses(slug,draft_json,published_json,state,version,created_at,updated_at,published_at)
                   VALUES(?,?,?,'published',1,?,?,?) ON CONFLICT(slug) DO NOTHING""",
                (course["slug"], _encoded({key: course[key] for key in DRAFT_FIELDS}),
                 _encoded(course), now, now, now),
            )


def _row(db, slug):
    row = db.execute("SELECT * FROM academy_courses WHERE slug=?", (slug,)).fetchone()
    if row is None:
        raise HTTPException(404, "Курс недоступен")
    return row


def _is_editor(user, row):
    return (user["role"] == "admin" and row["owner_id"] is None) or (
        user["role"] == "candidate" and row["owner_id"] == user["id"])


def _public_visible(db, row):
    owner = row["owner_id"]
    return bool(row["published_json"]) and (owner is None or (_is_published(db, owner) and
        row["published_consent_at"] is not None and row["published_profile_version"] == _profile(db, owner)["content_version"]))


def _review_visible(db, row):
    owner = row["owner_id"]
    return (owner is not None and row["state"] == "pending" and row["consent_at"] is not None
            and _is_published(db, owner) and row["pending_profile_version"] == _profile(db, owner)["content_version"])


def public_courses(db):
    rows = db.execute(
        """SELECT a.slug,a.published_json,p.public_id,p.public_name
           FROM academy_courses a LEFT JOIN community_profiles p ON p.user_id=a.owner_id
           LEFT JOIN users u ON u.id=a.owner_id LEFT JOIN account_controls ac ON ac.user_id=a.owner_id
           WHERE a.published_json IS NOT NULL AND
             (a.owner_id IS NULL OR (p.status='published' AND p.consent_at IS NOT NULL
              AND p.consent_content_version=p.content_version AND p.reviewed_content_version=p.content_version
              AND a.published_consent_at IS NOT NULL AND a.published_profile_version=p.content_version AND u.role='candidate'
              AND COALESCE(ac.status,'active')='active' AND NOT EXISTS (
                SELECT 1 FROM privacy_rights_requests pr WHERE pr.user_id=a.owner_id
                AND pr.kind IN ('deletion','stop_processing') AND pr.status IN ('received','in_review','completed'))))
           ORDER BY CASE WHEN a.owner_id IS NULL THEN 0 ELSE 1 END,a.created_at,a.slug"""
    ).fetchall()
    items = []
    for row in rows:
        data = json.loads(row["published_json"])
        if row["public_id"]:
            data["author_public_id"] = row["public_id"]
            data["author_public_name"] = row["public_name"]
        items.append(data)
    return items


def public_catalog(request: Request):
    with database(request.app.state.db_path) as db:
        return public_courses(db)


def revoke_courses(db, owner):
    db.execute(
        """UPDATE academy_courses SET published_json=NULL,published_profile_version=NULL,published_consent_at=NULL,
           state='hidden',consent_at=NULL,pending_profile_version=NULL,published_at=NULL,
           version=version+1,updated_at=? WHERE owner_id=? AND (published_json IS NOT NULL OR state='pending')""",
        (_now(), owner),
    )


def _version(row, expected):
    if row["version"] != expected:
        raise HTTPException(409, "Курс изменился в другой вкладке. Обновите данные, сохранив свой текст")


def _detail(db, row, user, full=True):
    mine = _is_editor(user, row)
    reviewing = user["role"] == "admin" and _review_visible(db, row)
    visible = _public_visible(db,row)
    if not (mine or reviewing or (user["role"] == "admin" and visible)):
        raise HTTPException(404, "Курс недоступен")
    draft = json.loads(row["draft_json"] if mine or reviewing else row["published_json"])
    dto = {"slug":row["slug"],"title":draft["title"] or "Курс без названия",
           "state":row["state"] if mine or reviewing else "published",
           "version":row["version"],"lesson_count":len(draft["lessons"]),
           "minutes":sum(item["minutes"] for item in draft["lessons"]),
           "can_edit":mine,"has_publication":visible,"has_saved_publication":mine and bool(row["published_json"]),
           "moderation_reason":row["moderation_reason"] if mine else "",
           "updated_at":row["updated_at"]}
    if full:
        dto.update(draft={key:draft[key] for key in DRAFT_FIELDS},issues=readiness(draft),
                   restricted=user["role"]=="candidate" and not _active_account(db,user["id"]),
                   can_submit=user["role"]=="admin" or _is_published(db,user["id"]))
    return dto


def install_builder_routes(app, community_user, throttle, get_connection, allowed, record_security_event):
    def access(user):
        if user["role"] not in ("admin","candidate"):
            raise HTTPException(403,"Конструктор доступен авторам и редакции")

    def editable(user,db,row):
        if not _is_editor(user,row):
            raise HTTPException(404,"Курс недоступен")
        if user["role"]=="candidate" and not _active_account(db,user["id"]):
            raise HTTPException(403,"Новые материалы недоступны при ограничении обработки данных")

    @app.get("/api/community/courses")
    def list_courses(page: int = Query(default=1,ge=1,le=10000),
                     view: Literal["own","review","published"] = "own",
                     user: dict = Depends(community_user),db=Depends(get_connection)):
        access(user)
        if user["role"]=="candidate":
            if view!="own":
                raise HTTPException(403,"Доступны только собственные курсы")
            rows=db.execute("SELECT * FROM academy_courses WHERE owner_id=? ORDER BY updated_at DESC,slug",
                            (user["id"],)).fetchall()
        elif view=="own":
            rows=db.execute("SELECT * FROM academy_courses WHERE owner_id IS NULL ORDER BY updated_at DESC,slug").fetchall()
        else:
            rows=db.execute(
                """SELECT a.* FROM academy_courses a JOIN community_profiles p ON p.user_id=a.owner_id
                   JOIN users u ON u.id=a.owner_id LEFT JOIN account_controls ac ON ac.user_id=a.owner_id
                   WHERE u.role='candidate' AND p.status='published' AND p.consent_at IS NOT NULL
                     AND p.consent_content_version=p.content_version AND p.reviewed_content_version=p.content_version
                     AND COALESCE(ac.status,'active')='active' AND NOT EXISTS (
                       SELECT 1 FROM privacy_rights_requests pr WHERE pr.user_id=a.owner_id
                       AND pr.kind IN ('deletion','stop_processing') AND pr.status IN ('received','in_review','completed'))
                     AND ((?='review' AND a.state='pending' AND a.consent_at IS NOT NULL
                           AND a.pending_profile_version=p.content_version)
                       OR (?='published' AND a.published_json IS NOT NULL AND a.published_consent_at IS NOT NULL AND a.published_profile_version=p.content_version))
                   ORDER BY a.updated_at DESC,a.slug LIMIT ? OFFSET ?""",
                (view,view,PAGE_SIZE+1,(page-1)*PAGE_SIZE),
            ).fetchall()
        restricted=user["role"]=="candidate" and not _active_account(db,user["id"])
        if view=="own":
            more=len(rows)>page*PAGE_SIZE
            selected=rows[(page-1)*PAGE_SIZE:page*PAGE_SIZE]
        else:
            more=len(rows)>PAGE_SIZE
            selected=rows[:PAGE_SIZE]
        return _private({"courses":[_detail(db,row,user,False) for row in selected],"page":page,"has_more":more,
                         "can_create":not restricted and view=="own" and
                           (user["role"]=="admin" or (_profile(db,user["id"]) is not None and len(rows)<LIMIT)),
                         "restricted":restricted,"limit":None if user["role"]=="admin" else LIMIT})

    @app.get("/api/community/courses/{slug}")
    def get_course(slug: str,user: dict=Depends(community_user),db=Depends(get_connection)):
        access(user)
        return _private({"course":_detail(db,_row(db,slug),user)})

    @app.post("/api/community/courses")
    def create(data: CourseCreate,user: dict=Depends(community_user),db=Depends(get_connection)):
        access(user)
        actor=user["id"]
        _lock_actors(db,actor)
        owner=None if user["role"]=="admin" else actor
        if owner is not None and (not _active_account(db,owner) or _profile(db,owner) is None):
            raise HTTPException(409,"Сначала сохраните профессиональный профиль")
        slug="course-"+data.client_key.hex
        old=db.execute("SELECT * FROM academy_courses WHERE slug=?",(slug,)).fetchone()
        if old is not None:
            if not _is_editor(user,old):
                raise HTTPException(409,"Запрос уже использован")
            return _committed(db,{"course":_detail(db,old,user)})
        if owner is not None and db.execute("SELECT COUNT(*) FROM academy_courses WHERE owner_id=?",(owner,)).fetchone()[0]>=LIMIT:
            raise HTTPException(409,"Достигнут лимит курсов")
        throttle(db,actor,"academy-course-create",10,86400)
        stamp=_now()
        db.execute(
            """INSERT INTO academy_courses(slug,owner_id,draft_json,created_at,updated_at)
               VALUES(?,?,?,?,?) ON CONFLICT(slug) DO NOTHING""",
            (slug,owner,_encoded(CourseDraft().model_dump()),stamp,stamp),
        )
        row=_row(db,slug)
        if not _is_editor(user,row):
            raise HTTPException(409,"Запрос уже использован")
        return _committed(db,{"course":_detail(db,row,user)})

    @app.put("/api/community/courses/{slug}")
    def save(slug: str,data: CourseSave,user: dict=Depends(community_user),db=Depends(get_connection)):
        row=_row(db,slug)
        editable(user,db,row)
        _lock_actors(db,row["owner_id"] or user["id"])
        row=_row(db,slug)
        editable(user,db,row)
        _version(row,data.expected_version)
        draft=data.model_dump(exclude={"expected_version"})
        if json.loads(row["draft_json"])==draft:
            return _committed(db,{"course":_detail(db,row,user)})
        throttle(db,user["id"],"academy-course-save",120,3600)
        result=db.execute(
            """UPDATE academy_courses SET draft_json=?,state='draft',version=version+1,
               consent_at=NULL,pending_profile_version=NULL,moderation_reason='',updated_at=?
               WHERE slug=? AND version=?""",
            (_encoded(draft),_now(),slug,data.expected_version),
        )
        if result.rowcount!=1:
            raise HTTPException(409,"Курс изменился в другой вкладке")
        return _committed(db,{"course":_detail(db,_row(db,slug),user)})

    def publish(db,row,actor,profile_version):
        draft=json.loads(row["draft_json"])
        issues=readiness(draft)
        if issues:
            raise HTTPException(422,"Курс не готов: "+"; ".join(issues[:5]))
        payload={**draft,"slug":row["slug"],"revision":row["version"]+1}
        now=_now()
        result=db.execute(
            """UPDATE academy_courses SET published_json=?,state='published',version=version+1,
               published_profile_version=?,published_consent_at=?,pending_profile_version=NULL,reviewed_by=?,
               published_at=?,updated_at=?,moderation_reason='' WHERE slug=? AND version=?""",
            (_encoded(payload),profile_version,row["consent_at"],actor,now,now,row["slug"],row["version"]),
        )
        if result.rowcount!=1:
            raise HTTPException(409,"Курс изменился в другой вкладке")
        record_security_event(db,actor,"academy_course_published","course="+row["slug"])

    @app.post("/api/community/courses/{slug}/submit")
    def submit(slug: str,data: PublishInput,user: dict=Depends(community_user),db=Depends(get_connection)):
        row=_row(db,slug)
        editable(user,db,row)
        _lock_actors(db,row["owner_id"] or user["id"])
        row=_row(db,slug)
        editable(user,db,row)
        _version(row,data.expected_version)
        if not data.publish_consent:
            raise HTTPException(400,"Подтвердите права на материал и публикацию текущей версии")
        if row["state"] in ("pending","published"):
            raise HTTPException(409,"Эта версия уже опубликована или на проверке")
        issues=readiness(json.loads(row["draft_json"]))
        if issues:
            raise HTTPException(422,"Курс не готов: "+"; ".join(issues[:5]))
        throttle(db,user["id"],"academy-course-submit",15,86400)
        if user["role"]=="admin":
            publish(db,row,user["id"],None)
        else:
            if not _is_published(db,user["id"]):
                raise HTTPException(409,"Для отправки курса нужен опубликованный профиль")
            now=_now()
            result=db.execute(
                """UPDATE academy_courses SET state='pending',consent_at=?,pending_profile_version=?,
                   version=version+1,updated_at=?,moderation_reason='' WHERE slug=? AND version=?""",
                (now,_profile(db,user["id"])["content_version"],now,slug,data.expected_version),
            )
            if result.rowcount!=1:
                raise HTTPException(409,"Курс изменился в другой вкладке")
        return _committed(db,{"course":_detail(db,_row(db,slug),user)})

    @app.delete("/api/community/courses/{slug}/publication")
    def withdraw(slug: str,data: VersionInput,user: dict=Depends(community_user),db=Depends(get_connection)):
        row=_row(db,slug)
        if not _is_editor(user,row):
            raise HTTPException(404,"Курс недоступен")
        _lock_actors(db,row["owner_id"] or user["id"])
        row=_row(db,slug)
        _version(row,data.expected_version)
        result=db.execute(
            """UPDATE academy_courses SET published_json=NULL,published_profile_version=NULL,published_consent_at=NULL,state='hidden',
               consent_at=NULL,pending_profile_version=NULL,published_at=NULL,version=version+1,updated_at=?
               WHERE slug=? AND version=?""",(_now(),slug,data.expected_version),
        )
        if result.rowcount!=1:
            raise HTTPException(409,"Курс изменился в другой вкладке")
        return _committed(db,{"course":_detail(db,_row(db,slug),user)})

    @app.patch("/api/admin/community/courses/{slug}")
    def review(slug: str,data: ModerationInput,user: dict=Depends(community_user),db=Depends(get_connection)):
        allowed(user,"admin")
        row=_row(db,slug)
        if row["owner_id"] is None:
            raise HTTPException(404,"Курс недоступен")
        _lock_actors(db,row["owner_id"])
        row=_row(db,slug)
        _version(row,data.expected_version)
        if data.decision=="approve":
            if not _review_visible(db,row):
                raise HTTPException(409,"Нет действующего согласия автора")
            publish(db,row,user["id"],row["pending_profile_version"])
        else:
            if not data.reason.strip():
                raise HTTPException(422,"Укажите причину")
            if data.decision=="reject":
                if not _review_visible(db,row):
                    raise HTTPException(409,"Курс уже не ожидает проверки")
                result=db.execute(
                    """UPDATE academy_courses SET state='rejected',consent_at=NULL,pending_profile_version=NULL,
                       moderation_reason=?,reviewed_by=?,updated_at=?,version=version+1 WHERE slug=? AND version=?""",
                    (data.reason,user["id"],_now(),slug,data.expected_version),
                )
            else:
                if not _public_visible(db,row) and not _review_visible(db,row):
                    raise HTTPException(409,"Курс уже недоступен")
                result=db.execute(
                    """UPDATE academy_courses SET state='hidden',published_json=NULL,published_profile_version=NULL,published_consent_at=NULL,
                       consent_at=NULL,pending_profile_version=NULL,published_at=NULL,moderation_reason=?,
                       reviewed_by=?,updated_at=?,version=version+1 WHERE slug=? AND version=?""",
                    (data.reason,user["id"],_now(),slug,data.expected_version),
                )
            if result.rowcount!=1:
                raise HTTPException(409,"Курс изменился в другой вкладке")
            record_security_event(db,user["id"],"academy_course_reviewed","course="+slug+" decision="+data.decision)
        return _committed(db,{"ok":True})
