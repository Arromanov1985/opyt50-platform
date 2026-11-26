"""Curated, open professional discussion groups; membership is private.

Groups are not private chat rooms. Every authenticated active reader can read
moderated discussions, while only joined, published candidates can contribute.
"""
from fastapi import Depends, HTTPException

from .community import _active_account, _committed, _lock_actors, _now

GROUPS = {
    "engineering": ("Инженерия и производство", "Технические задачи, качество, эксплуатация и производственный опыт"),
    "management": ("Управление и предпринимательство", "Руководство командами, бизнес-процессы и развитие бизнеса"),
    "sales": ("Продажи и работа с клиентами", "Переговоры, B2B, сервис и развитие клиентских отношений"),
    "education": ("Образование и наставничество", "Обучение сотрудников, передача знаний и методики"),
    "finance": ("Финансы и бухгалтерия", "Учёт, финансовые процессы и практические вопросы"),
    "technology": ("ИТ и цифровые технологии", "Автоматизация, цифровые инструменты и освоение технологий"),
    "operations": ("Логистика и операционная работа", "Снабжение, склады, транспорт и организация процессов"),
    "career": ("Карьера и новый профессиональный этап", "Смена направления, развитие навыков и профессиональный обмен"),
}


def group_info(slug):
    if slug not in GROUPS:
        raise HTTPException(404, "Тематическая группа не найдена")
    name, description = GROUPS[slug]
    return {"slug": slug, "name": name, "description": description}


def group_member(db, owner, slug):
    return db.execute(
        "SELECT 1 FROM community_group_memberships WHERE user_id=? AND group_slug=?",
        (owner, slug),
    ).fetchone() is not None


def install_group_routes(app, community_user, throttle, get_connection, reader, allowed):
    # Deferred import avoids a circular module import.
    from .community_feed import _private

    @app.get("/api/community/groups")
    def list_groups(user: dict = Depends(community_user), db=Depends(get_connection)):
        active = _active_account(db, user["id"])
        if active or user["role"] != "candidate":
            reader(user, db)
        memberships = db.execute(
            "SELECT group_slug FROM community_group_memberships WHERE user_id=?", (user["id"],),
        ).fetchall()
        joined = {row["group_slug"] for row in memberships}
        return _private({"groups": [{**group_info(slug), "joined": slug in joined}
                                    for slug in GROUPS if active or slug in joined],
                         "can_join": active and user["role"] == "candidate"})

    @app.put("/api/community/groups/{slug}/membership")
    def join(slug: str, user: dict = Depends(community_user), db=Depends(get_connection)):
        allowed(user, "candidate")
        group_info(slug)
        owner = user["id"]
        _lock_actors(db, owner)
        if not _active_account(db, owner):
            raise HTTPException(403, "Участие недоступно при ограничении обработки данных")
        if not group_member(db, owner, slug):
            throttle(db, owner, "community-group-join", 30, 3600)
            db.execute(
                """INSERT INTO community_group_memberships(user_id,group_slug,created_at)
                   VALUES(?,?,?) ON CONFLICT(user_id,group_slug) DO NOTHING""", (owner, slug, _now()),
            )
        return _committed(db, {"group": {**group_info(slug), "joined": True}})

    @app.delete("/api/community/groups/{slug}/membership")
    def leave(slug: str, user: dict = Depends(community_user), db=Depends(get_connection)):
        allowed(user, "candidate")
        group_info(slug)
        owner = user["id"]
        _lock_actors(db, owner)
        db.execute("DELETE FROM community_group_memberships WHERE user_id=? AND group_slug=?",
                   (owner, slug))
        return _committed(db, {"group": {**group_info(slug), "joined": False}})
