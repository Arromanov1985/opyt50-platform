"""Small editorial CMS for STAZHNO: versioned drafts and explicit publication.

Public HTML is rendered by journal.py from published_json only. Editing never
changes the live copy until an administrator presses Publish. Historical edits
are not exposed to visitors. No visitor queries or identifiers are recorded.
"""
from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import date, datetime, timezone
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .db import database


DDL = (
    """CREATE TABLE IF NOT EXISTS journal_entries (
        slug TEXT PRIMARY KEY,
        draft_json TEXT NOT NULL,
        published_json TEXT,
        status TEXT NOT NULL CHECK(status IN ('draft','published','hidden','archived')),
        version INTEGER NOT NULL DEFAULT 1,
        sort_order INTEGER NOT NULL DEFAULT 100,
        published_at TEXT,
        updated_at TEXT NOT NULL
    )""",
    """CREATE INDEX IF NOT EXISTS idx_journal_entries_public
       ON journal_entries(status,sort_order,slug)""",
    """CREATE TABLE IF NOT EXISTS journal_edit_events (
        event_id TEXT PRIMARY KEY,
        admin_id INTEGER NOT NULL REFERENCES users(id),
        slug TEXT NOT NULL,
        action TEXT NOT NULL CHECK(action IN ('create','save','publish','hide','archive')),
        version INTEGER NOT NULL,
        created_at TEXT NOT NULL
    )""",
    """CREATE INDEX IF NOT EXISTS idx_journal_edit_events_time
       ON journal_edit_events(created_at)""",
)
SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class ArticleInput(BaseModel):
    title: str = Field(min_length=8, max_length=180)
    description: str = Field(min_length=25, max_length=350)
    category: str = Field(min_length=3, max_length=55)
    read: str = Field(min_length=3, max_length=30)
    body_text: str = Field(min_length=200, max_length=20000)
    version: int = Field(default=0, ge=0)
    content_type: Literal['article', 'news', 'learning', 'event'] = 'article'
    source_name: str = Field(default='', max_length=180)
    source_url: str = Field(default='', max_length=1500)
    event_date: date | None = None
    event_format: Literal['online', 'offline', 'hybrid'] | None = None


class ArticleCreate(ArticleInput):
    slug: str = Field(min_length=5, max_length=90, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class VersionInput(BaseModel):
    version: int = Field(ge=1)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sections_to_text(sections: list) -> str:
    parts = []
    for section in sections:
        parts.append("## " + section["title"])
        parts.extend(section["paragraphs"])
        parts.extend("- " + text for text in section.get("bullets", []))
    return "\n\n".join(parts)


def parse_sections(value: str) -> list[dict]:
    """Accepted plain-text syntax: ## heading, paragraphs, - bullets.

    No HTML/Markdown renderer or third-party script execution. Existing public
    renderer always uses html.escape on all fields.
    """
    if "<script" in value.casefold():
        raise HTTPException(422, "Для статей используйте обычный текст без HTML")
    sections = []
    current = None
    paragraph = []
    def flush():
        nonlocal paragraph
        if paragraph and current is not None:
            current["paragraphs"].append(" ".join(paragraph).strip())
        paragraph = []
    for raw in value.replace("\r", "").split("\n"):
        line = raw.strip()
        if line.startswith("## "):
            flush()
            heading = line[3:].strip()
            if not 6 <= len(heading) <= 150:
                raise HTTPException(422, "Заголовок раздела должен содержать 6–150 символов")
            current = {"title": heading, "paragraphs": [], "bullets": []}
            sections.append(current)
        elif not line:
            flush()
        elif line.startswith("- "):
            if current is None:
                raise HTTPException(422, "Сначала укажите заголовок раздела: ## Название")
            flush()
            if len(line[2:]) > 500:
                raise HTTPException(422, "Пункт списка слишком длинный")
            current["bullets"].append(line[2:])
        else:
            if current is None:
                raise HTTPException(422, "Сначала укажите заголовок раздела: ## Название")
            paragraph.append(line)
    flush()
    if len(sections) < 2 or len(sections) > 16:
        raise HTTPException(422, "Нужно от 2 до 16 разделов с заголовками ##")
    if any(not section["paragraphs"] for section in sections):
        raise HTTPException(422, "Каждый раздел должен содержать основной текст")
    if any(len(p) > 1800 for section in sections for p in section["paragraphs"]):
        raise HTTPException(422, "Абзац слишком длинный; разделите его на несколько частей")
    return [{k:v for k,v in section.items() if v} for section in sections]


def normalize_article(slug: str, data: ArticleInput) -> dict:
    if not SLUG_PATTERN.fullmatch(slug) or slug in {"journal", "paths"}:
        raise HTTPException(422, "Некорректный адрес статьи")
    from .journal_guide import source_url
    name = data.source_name.strip()
    url = source_url(data.source_url)
    if data.content_type == "news" and (not name or not url):
        raise HTTPException(422, "Для новости укажите название и HTTPS-ссылку на источник")
    if data.content_type == "event" and (not data.event_date or not data.event_format or not name):
        raise HTTPException(422, "Для мероприятия укажите дату, формат и организатора")
    if data.content_type != "event" and (data.event_date or data.event_format):
        raise HTTPException(422, "Дата и формат допустимы только для мероприятия")
    result = {
        "slug": slug,
        "title": data.title.strip(),
        "description": data.description.strip(),
        "category": data.category.strip(),
        "read": data.read.strip(),
        "sections": parse_sections(data.body_text),
    }
    if data.content_type != "article":
        result["content_type"] = data.content_type
    if name:
        result["source_name"] = name
    if url:
        result["source_url"] = url
    if data.event_date:
        result["event_date"] = data.event_date.isoformat()
        result["event_format"] = data.event_format
    return result


def init_journal(path: str) -> None:
    """Seed once: never overwrite a published page or editor's unpublished work."""
    from .journal import ARTICLES, PUBLISHED
    initial_date = PUBLISHED + "T00:00:00+00:00"
    with database(path) as db:
        for statement in DDL:
            db.execute(statement)
        for index, article in enumerate(ARTICLES):
            encoded = json.dumps(article, ensure_ascii=False, separators=(",", ":"))
            db.execute(
                """INSERT INTO journal_entries
                   (slug,draft_json,published_json,status,version,sort_order,published_at,updated_at)
                   VALUES(?,?,?,'published',1,?,?,?)
                   ON CONFLICT(slug) DO NOTHING""",
                (article["slug"], encoded, encoded, index, initial_date, initial_date),
            )


def public_articles(db) -> list[dict]:
    rows = db.execute(
        """SELECT slug,published_json,published_at FROM journal_entries
           WHERE status='published' AND published_json IS NOT NULL
           ORDER BY sort_order,slug"""
    ).fetchall()
    items = []
    for row in rows:
        article = json.loads(row["published_json"])
        article["slug"] = row["slug"]
        article["published_at"] = row["published_at"]
        items.append(article)
    return items


def _event(db, user: dict, slug: str, action: str, version: int) -> None:
    db.execute(
        """INSERT INTO journal_edit_events(event_id,admin_id,slug,action,version,created_at)
           VALUES(?,?,?,?,?,?)""",
        (uuid.uuid4().hex, user["id"], slug, action, version, now_iso()),
    )


def _entry(db, slug: str) -> dict:
    row = db.execute(
        """SELECT slug,draft_json,published_json,status,version,sort_order,
                  updated_at,published_at
           FROM journal_entries WHERE slug=?""",
        (slug,),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Статья не найдена")
    return dict(row)


def _summary(row: dict) -> dict:
    draft = json.loads(row["draft_json"])
    return {
        "slug": row["slug"], "title": draft["title"],
        "category": draft["category"], "status": row["status"],
        "content_type": draft.get("content_type", "article"),
        "version": row["version"], "updated_at": row["updated_at"],
        "published_at": row["published_at"],
        "has_changes": row["published_json"] != row["draft_json"],
    }


def install_journal_admin_routes(app: FastAPI) -> None:
    from .main import active_user, allowed, get_connection, BASE

    def admin_only(user: dict) -> None:
        allowed(user, "admin")

    @app.get("/admin/journal", include_in_schema=False)
    def editor_page(user: dict = Depends(active_user)):
        admin_only(user)
        response = FileResponse(BASE / "static" / "journal-admin.html")
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        return response

    @app.get("/api/admin/journal")
    def list_articles(user: dict = Depends(active_user), db=Depends(get_connection)):
        admin_only(user)
        rows = db.execute(
            """SELECT slug,draft_json,published_json,status,version,updated_at,published_at
               FROM journal_entries ORDER BY sort_order,slug"""
        ).fetchall()
        return {"articles": [_summary(dict(row)) for row in rows]}

    @app.get("/api/admin/journal/audit")
    def audit(user: dict = Depends(active_user), db=Depends(get_connection)):
        admin_only(user)
        rows = db.execute(
            """SELECT slug,action,version,created_at FROM journal_edit_events
               ORDER BY created_at DESC,event_id DESC LIMIT 40"""
        ).fetchall()
        return {"events": [dict(row) for row in rows]}

    @app.get("/api/admin/journal/{slug}")
    def get_article(slug: str, user: dict = Depends(active_user), db=Depends(get_connection)):
        admin_only(user)
        row = _entry(db, slug)
        article = json.loads(row["draft_json"])
        return {"article": {
            **_summary(row), "description": article["description"], "read": article["read"],
            "body_text": sections_to_text(article["sections"]),
            "source_name": article.get("source_name", ""), "source_url": article.get("source_url", ""),
            "event_date": article.get("event_date"), "event_format": article.get("event_format"),
        }}

    @app.post("/api/admin/journal", status_code=201)
    def create_article(data: ArticleCreate, user: dict = Depends(active_user),
                       db=Depends(get_connection)):
        admin_only(user)
        article = normalize_article(data.slug, data)
        if db.execute("SELECT 1 FROM journal_entries WHERE slug=?", (data.slug,)).fetchone():
            raise HTTPException(409, "Этот адрес уже занят")
        payload = json.dumps(article, ensure_ascii=False)
        stamp = now_iso()
        try:
            db.execute(
                """INSERT INTO journal_entries
                   (slug,draft_json,published_json,status,version,sort_order,updated_at)
                   VALUES(?, ?, NULL, 'draft', 1, 100, ?)""",
                (data.slug, payload, stamp),
            )
        except sqlite3.IntegrityError:
            raise HTTPException(409, "Этот адрес уже занят") from None
        _event(db, user, data.slug, "create", 1)
        db.commit()
        return {"ok": True, "slug": data.slug, "version": 1}

    @app.put("/api/admin/journal/{slug}")
    def update_article(slug: str, data: ArticleInput, user: dict = Depends(active_user),
                       db=Depends(get_connection)):
        admin_only(user)
        if data.version < 1:
            raise HTTPException(422, "Не указана версия статьи")
        article = normalize_article(slug, data)
        payload = json.dumps(article, ensure_ascii=False)
        result = db.execute(
            """UPDATE journal_entries SET draft_json=?,version=version+1,updated_at=?
               WHERE slug=? AND version=? AND status != 'archived'""",
            (payload, now_iso(), slug, data.version),
        )
        if result.rowcount != 1:
            raise HTTPException(409, "Статья изменена или отправлена в архив. Обновите страницу")
        _event(db, user, slug, "save", data.version+1)
        db.commit()
        return {"ok": True, "slug":slug, "version": data.version+1}

    @app.post("/api/admin/journal/{slug}/publish")
    def publish(slug: str, data: VersionInput, user: dict = Depends(active_user),
                db=Depends(get_connection)):
        admin_only(user)
        result = db.execute(
            """UPDATE journal_entries
               SET published_json=draft_json,status='published',version=version+1,
                   published_at=?,updated_at=?
               WHERE slug=? AND version=? AND status != 'archived'""",
            (now_iso(), now_iso(), slug, data.version),
        )
        if result.rowcount != 1:
            raise HTTPException(409, "Статья изменена. Обновите данные перед публикацией")
        _event(db, user, slug, "publish", data.version+1)
        db.commit()
        return {"ok":True, "version":data.version+1}

    @app.post("/api/admin/journal/{slug}/hide")
    def hide(slug: str, data: VersionInput, user: dict = Depends(active_user),
             db=Depends(get_connection)):
        admin_only(user)
        result = db.execute(
            """UPDATE journal_entries SET status='hidden',version=version+1,updated_at=?
               WHERE slug=? AND version=? AND status NOT IN ('hidden','archived')""",
            (now_iso(),slug,data.version),
        )
        if result.rowcount != 1:
            raise HTTPException(409, "Статья уже скрыта или изменилась")
        _event(db, user, slug, "hide", data.version+1)
        db.commit()
        return {"ok":True, "version":data.version+1}

    @app.post("/api/admin/journal/{slug}/archive")
    def archive(slug: str, data: VersionInput, user: dict = Depends(active_user),
                db=Depends(get_connection)):
        admin_only(user)
        row = _entry(db, slug)
        if row["status"] != "draft":
            raise HTTPException(409, "В архив можно отправить только неопубликованный черновик")
        result = db.execute(
            """UPDATE journal_entries SET status='archived',version=version+1,updated_at=?
               WHERE slug=? AND version=? AND status='draft'""",
            (now_iso(), slug, data.version),
        )
        if result.rowcount != 1:
            raise HTTPException(409, "Черновик изменился. Обновите данные")
        _event(db, user, slug, "archive", data.version+1)
        db.commit()
        return {"ok":True, "version":data.version+1}
