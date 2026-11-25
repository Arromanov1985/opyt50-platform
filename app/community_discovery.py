"""Private bookmarks and opt-in, transparent professional recommendations."""
from __future__ import annotations

from typing import Literal

from fastapi import Depends, HTTPException, Query
from pydantic import Field, field_validator, model_validator

from .community import (
    CommunityModel, PAGE_SIZE, _committed, _key, _lock_actors,
    _now, _public_profile, _public_text,
)
from .community_engagement import _lock_entry
from .community_feed import _private, _visible


class PreferenceRevision(CommunityModel):
    expected_revision: str | None = Field(default=None, min_length=1, max_length=64)


class DiscoveryInput(PreferenceRevision):
    keyword: str = Field(default="", max_length=100)
    city: str = Field(default="", max_length=80)
    focus: Literal["", "experience", "question", "projects", "mentoring"] = ""

    _safe = field_validator("keyword", "city")(_public_text)

    @model_validator(mode="after")
    def require_criteria(self):
        if not (self.keyword or self.city or self.focus):
            raise ValueError("Укажите хотя бы один профессиональный интерес")
        return self


def _preferences(db, owner):
    row = db.execute(
        """SELECT keyword,city,focus,revision,updated_at
           FROM community_discovery_preferences WHERE user_id=?""", (owner,),
    ).fetchone()
    return dict(row) if row else {
        "keyword": "", "city": "", "focus": "", "revision": None, "updated_at": None,
    }


def _check_revision(db, owner, expected):
    if _preferences(db, owner)["revision"] != expected:
        raise HTTPException(409, "Настройки изменились в другой вкладке. Обновите страницу")


def _own_public_id(db, owner):
    row = db.execute("SELECT public_id FROM community_profiles WHERE user_id=?", (owner,)).fetchone()
    return row["public_id"] if row else None


# Only published, currently consented profiles. No resume, contact, chat,
# behavior history, or undisclosed account information is used for matching.
_PEOPLE_SQL = """
WITH viewer AS (SELECT CAST(? AS INTEGER) AS viewer_id)
SELECT p.public_id,p.public_name,p.headline,p.city,p.skills,p.about,p.goal
FROM community_profiles p
JOIN users u ON u.id=p.user_id
LEFT JOIN account_controls ac ON ac.user_id=p.user_id
CROSS JOIN viewer v
WHERE p.user_id<>v.viewer_id AND p.status='published' AND p.consent_at IS NOT NULL
  AND p.consent_content_version=p.content_version AND p.reviewed_content_version=p.content_version
  AND u.role='candidate' AND COALESCE(ac.status,'active')='active'
  AND NOT EXISTS (
      SELECT 1 FROM privacy_rights_requests pr WHERE pr.user_id=p.user_id
        AND pr.kind IN ('deletion','stop_processing') AND pr.status IN ('received','in_review','completed')
  )
  AND NOT EXISTS (
      SELECT 1 FROM community_connections c WHERE c.status='blocked'
        AND ((c.sender_id=v.viewer_id AND c.recipient_id=p.user_id)
          OR (c.recipient_id=v.viewer_id AND c.sender_id=p.user_id))
  )
  AND (?='' OR unicode_fold(p.city)=?)
  AND (?='' OR p.goal=?)
  AND (?='' OR instr(unicode_fold(p.headline),?)>0 OR instr(unicode_fold(p.skills),?)>0)
ORDER BY p.published_at DESC,p.public_id LIMIT ? OFFSET ?
"""


def _recommend_people(db, owner, settings, page):
    keyword = settings["keyword"].casefold()
    city = settings["city"].casefold()
    goal = {"experience": "exchange", "question": "exchange"}.get(settings["focus"], settings["focus"])
    rows = db.execute(_PEOPLE_SQL, (
        owner, city, city, goal, goal, keyword, keyword, keyword,
        PAGE_SIZE + 1, (page - 1) * PAGE_SIZE,
    )).fetchall()
    return {"people": [_public_profile(row) for row in rows[:PAGE_SIZE]],
            "page": page, "has_more": len(rows) > PAGE_SIZE}


def install_discovery_routes(app, community_user, throttle, get_connection, reader, can_publish):
    @app.get("/api/community/feed/saved")
    def saved(page: int = Query(default=1, ge=1, le=10000),
              user: dict = Depends(community_user), db=Depends(get_connection)):
        reader(user, db)
        owner = user["id"]
        rows = db.execute(
            """SELECT entry_id,created_at FROM community_saved_entries WHERE user_id=?
               ORDER BY created_at DESC,entry_id LIMIT ? OFFSET ?""",
            (owner, PAGE_SIZE + 1, (page - 1) * PAGE_SIZE),
        ).fetchall()
        visible = _visible(db, owner, saved_page=page)
        by_id = {entry["id"]: entry for entry in visible["entries"]}
        # A previously saved text may become unavailable. Return only the
        # viewer's existing bookmark ID, not its hidden text or author.
        return _private({
            "records": [{**dict(row), "entry": by_id.get(row["entry_id"])}
                        for row in rows[:PAGE_SIZE]],
            "saved_entry_ids": [row["entry_id"] for row in rows[:PAGE_SIZE]],
            "following_public_ids": visible["following_public_ids"],
            "own_public_id": _own_public_id(db, owner),
            "can_publish": can_publish(user, db),
            "page": page, "has_more": len(rows) > PAGE_SIZE,
        })

    @app.put("/api/community/feed/saved/{entry_id}")
    def save_entry(entry_id: str, user: dict = Depends(community_user), db=Depends(get_connection)):
        reader(user, db)
        owner = user["id"]
        if not _visible(db, owner, entry_id=entry_id)["entries"]:
            raise HTTPException(404, "Публикация недоступна")
        _lock_entry(db, owner, entry_id)
        reader(user, db)
        if not _visible(db, owner, entry_id=entry_id)["entries"]:
            raise HTTPException(404, "Публикация недоступна")
        previous = db.execute(
            "SELECT 1 FROM community_saved_entries WHERE user_id=? AND entry_id=?",
            (owner, entry_id),
        ).fetchone()
        if previous is None:
            throttle(db, owner, "community-feed-save", 120, 3600)
            db.execute(
                """INSERT INTO community_saved_entries(user_id,entry_id,created_at)
                   VALUES(?,?,?) ON CONFLICT(user_id,entry_id) DO NOTHING""",
                (owner, entry_id, _now()),
            )
        return _committed(db, {"entry_id": entry_id, "saved": True})

    @app.delete("/api/community/feed/saved/{entry_id}")
    def remove_saved(entry_id: str, user: dict = Depends(community_user), db=Depends(get_connection)):
        reader(user, db)
        owner = user["id"]
        _lock_actors(db, owner)
        db.execute("DELETE FROM community_saved_entries WHERE user_id=? AND entry_id=?", (owner, entry_id))
        return _committed(db, {"entry_id": entry_id, "saved": False})

    @app.get("/api/community/recommendations")
    def recommendations(people_page: int = Query(default=1, ge=1, le=10000),
                        feed_page: int = Query(default=1, ge=1, le=10000),
                        user: dict = Depends(community_user), db=Depends(get_connection)):
        reader(user, db)
        owner = user["id"]
        settings = _preferences(db, owner)
        people = {"people": [], "page": people_page, "has_more": False}
        feed = {"entries": [], "page": feed_page, "has_more": False,
                "saved_entry_ids": [], "following_public_ids": []}
        if settings["revision"]:
            people = _recommend_people(db, owner, settings, people_page)
            feed = _visible(
                db, owner, kind=settings["focus"], q=settings["keyword"].casefold(),
                city=settings["city"].casefold(), page=feed_page, exclude_self=True,
                match_profile=True, opportunity_only=settings["focus"] in {"projects", "mentoring"},
            )
        return _private({"settings": settings, "people": people, "feed": feed,
                         "own_public_id": _own_public_id(db, owner),
                         "can_publish": can_publish(user, db)})

    @app.put("/api/community/recommendations/preferences")
    def save_preferences(data: DiscoveryInput, user: dict = Depends(community_user), db=Depends(get_connection)):
        reader(user, db)
        owner = user["id"]
        _lock_actors(db, owner)
        reader(user, db)
        _check_revision(db, owner, data.expected_revision)
        db.execute(
            """INSERT INTO community_discovery_preferences(user_id,keyword,city,focus,revision,updated_at)
               VALUES(?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET keyword=excluded.keyword,
               city=excluded.city,focus=excluded.focus,revision=excluded.revision,updated_at=excluded.updated_at""",
            (owner, data.keyword, data.city, data.focus, _key(), _now()),
        )
        return _committed(db, {"settings": _preferences(db, owner)})

    @app.delete("/api/community/recommendations/preferences")
    def clear_preferences(data: PreferenceRevision, user: dict = Depends(community_user), db=Depends(get_connection)):
        reader(user, db)
        owner = user["id"]
        _lock_actors(db, owner)
        reader(user, db)
        _check_revision(db, owner, data.expected_revision)
        db.execute("DELETE FROM community_discovery_preferences WHERE user_id=?", (owner,))
        return _committed(db, {"settings": _preferences(db, owner)})
