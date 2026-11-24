"""Deterministic public-content recommendations for STAZHNO.

Recommendations depend only on the public page being viewed and currently
published public content. They never use visitor identity, cookies, sessions,
candidate profiles, click history, referrers or UTM parameters.
"""
from __future__ import annotations

import re

_WORD_RE = re.compile(r"[0-9A-Za-zА-Яа-яЁё]{3,}")
_STOPWORDS = {
    "для", "как", "что", "это", "или", "при", "без", "все", "его", "еще",
    "уже", "если", "чтобы", "после", "перед", "можно", "нужно", "будет",
    "работа", "работы", "работе", "работу", "ваканс", "стажно", "компан",
    "опыт", "опыта", "навык", "навыки", "услови", "котор", "своего",
    "свои", "свой", "этот", "этой", "также", "только", "через",
}


def _key(token: str) -> str:
    token = token.casefold().replace("ё", "е")
    # A short prefix gives a lightweight morphology tolerance for Russian
    # endings without pretending to be a linguistic stemmer.
    if len(token) >= 8:
        token = token[:6]
    elif len(token) >= 6:
        token = token[:5]
    return token


def terms(value: str) -> set[str]:
    result = set()
    for raw in _WORD_RE.findall(str(value or "")):
        key = _key(raw)
        if key not in _STOPWORDS and not key.isdigit():
            result.add(key)
    return result


def article_text(article: dict) -> str:
    parts = [
        article.get("title", ""),
        article.get("description", ""),
        article.get("category", ""),
    ]
    for section in article.get("sections", []):
        parts.append(section.get("title", ""))
        parts.extend(section.get("paragraphs", []))
        parts.extend(section.get("bullets", []))
    return " ".join(str(part or "") for part in parts)


def job_text(job: dict) -> str:
    return " ".join(str(job.get(key) or "") for key in (
        "title", "skills", "description", "schedule", "employment",
    ))


def _article_score(article: dict, context: set[str]) -> int:
    title = terms(article.get("title", ""))
    description = terms(article.get("description", ""))
    category = terms(article.get("category", ""))
    body = terms(article_text(article))
    return (
        5 * len(context & title)
        + 3 * len(context & description)
        + 2 * len(context & category)
        + len(context & body)
    )


def related_articles(
    articles: list[dict],
    context_text: str,
    *,
    limit: int = 2,
    exclude_slugs: set[str] | None = None,
    fallback_slugs: tuple[str, ...] = (),
) -> list[dict]:
    """Rank published articles by the public page text, with stable fallbacks."""
    excluded = exclude_slugs or set()
    candidates = [item for item in articles if item.get("slug") not in excluded]
    context = terms(context_text)
    indexed = list(enumerate(candidates))
    ranked = sorted(
        indexed,
        key=lambda pair: (-_article_score(pair[1], context), pair[0]),
    )
    positive = [item for _idx, item in ranked if _article_score(item, context) > 0]
    chosen = positive[:limit]
    seen = {item.get("slug") for item in chosen}
    if len(chosen) < limit:
        by_slug = {item.get("slug"): item for item in candidates}
        for slug in fallback_slugs:
            item = by_slug.get(slug)
            if item is not None and slug not in seen:
                chosen.append(item)
                seen.add(slug)
                if len(chosen) >= limit:
                    break
    if len(chosen) < limit:
        for item in candidates:
            slug = item.get("slug")
            if slug not in seen:
                chosen.append(item)
                seen.add(slug)
                if len(chosen) >= limit:
                    break
    return chosen


def _job_score(job: dict, context: set[str]) -> int:
    return (
        6 * len(context & terms(job.get("title", "")))
        + 4 * len(context & terms(job.get("skills", "")))
        + 2 * len(context & terms(job.get("description", "")))
        + len(context & terms(job.get("employment", "")))
        + len(context & terms(job.get("schedule", "")))
    )


def related_jobs(article: dict, jobs: list[dict], *, limit: int = 3) -> list[dict]:
    """Rank public open jobs against one published article.

    If editorial text has no meaningful lexical overlap with current vacancies,
    use the newest public vacancies rather than inventing relevance.
    """
    context = terms(article_text(article))
    indexed = list(enumerate(jobs))
    ranked = sorted(indexed, key=lambda pair: (-_job_score(pair[1], context), pair[0]))
    positive = [item for _idx, item in ranked if _job_score(item, context) > 0]
    if positive:
        return positive[:limit]
    return jobs[:limit]


def public_jobs(db, *, limit: int = 80) -> list[dict]:
    """Return only vacancies already eligible for unauthenticated public pages."""
    rows = db.execute(
        """SELECT v.id,v.employer_id,v.title,v.city,v.salary_min,v.salary_max,
                  v.schedule,v.employment,v.skills,v.description,
                  e.company_name
           FROM vacancies v
           JOIN employer_profiles e ON e.user_id=v.employer_id
           JOIN users u ON u.id=e.user_id AND u.role='employer'
           LEFT JOIN account_controls c ON c.user_id=v.employer_id
           LEFT JOIN vacancy_moderation vm ON vm.vacancy_id=v.id
           WHERE v.status='open'
             AND COALESCE(c.status,'active')='active'
             AND COALESCE(vm.status,'approved')='approved'
             AND NOT EXISTS (
               SELECT 1 FROM privacy_rights_requests pr
               WHERE pr.user_id=v.employer_id
                 AND pr.kind IN ('deletion','stop_processing')
                 AND pr.status IN ('received','in_review','completed')
             )
           ORDER BY v.id DESC
           LIMIT ?""",
        (max(1, min(int(limit), 100)),),
    ).fetchall()
    return [dict(row) for row in rows]
