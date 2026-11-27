"""Editorial programs are composed only from explicitly approved public revisions."""
from __future__ import annotations

import re

# Add an entry only after editorial approval of every referenced public
# course and revision. No pending author data or future slugs in this registry.
PROGRAMS: tuple[dict, ...] = ()
MAX_PROGRAM_COURSES = 12


def configured_programs():
    """Return well-formed, unambiguous editorial definitions."""
    seen = set()
    for item in PROGRAMS:
        slug = item["slug"]
        steps = item["steps"]
        if (not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug)
                or len(slug) > 60 or slug in seen
                or not 2 <= len(steps) <= MAX_PROGRAM_COURSES
                or len({step[0] for step in steps}) != len(steps)
                or any(not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", course_slug)
                       or len(course_slug) > 60 or type(revision) is not int or revision < 1
                       for course_slug, revision in steps)):
            raise ValueError("Invalid Academy program definition")
        seen.add(slug)
        yield item


def visible_programs(courses: list[dict]) -> list[dict]:
    """Fail closed if even one pinned course revision is absent."""
    by_slug = {course["slug"]: course for course in courses}
    result = []
    for item in configured_programs():
        resolved = []
        for slug, revision in item["steps"]:
            course = by_slug.get(slug)
            if not course or course.get("revision") != revision or not course.get("lessons"):
                break
            resolved.append(course)
        else:
            result.append({**item, "courses": resolved})
    return result
