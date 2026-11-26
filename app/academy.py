"""Public, free self-study courses. Progress is device-local, not a credential."""
from __future__ import annotations

from html import escape

from fastapi import HTTPException
from fastapi.responses import HTMLResponse

from .academy_content import COURSES


def _e(value) -> str:
    return escape(str(value), quote=True)


def _course(slug: str):
    course = next((item for item in COURSES if item["slug"] == slug), None)
    if course is None:
        raise HTTPException(404, "Курс не найден")
    return course


def _url(course):
    return "/academy/" + course["slug"]


def _lesson_url(course, lesson):
    return _url(course) + "/" + lesson["slug"]


def _progress_attrs(course):
    return (' data-ac-course="' + _e(course["slug"]) + '" data-ac-revision="' +
            _e(course["revision"]) + '" data-ac-lessons="' +
            _e(" ".join(item["slug"] for item in course["lessons"])) + '"')


def _progress_panel(course):
    return (
        '<section class="ac-progress" aria-label="Прогресс обучения"' + _progress_attrs(course) + '>'
        '<h2>Ваш прогресс</h2><p data-ac-progress-label role="status">0 из ' +
        str(len(course["lessons"])) + ' уроков</p><progress data-ac-progress max="' +
        str(len(course["lessons"])) + '" value="0" aria-label="Пройденные уроки"></progress>'
        '<p data-ac-finished hidden>Все уроки пройдены. Повторите практические задания, когда понадобится.</p>'
        '<p class="ac-small">Прогресс хранится в этом браузере, не передаётся на сервер и не является сертификатом. '
        'На общем устройстве другие пользователи браузера могут его увидеть.</p>'
        '<button type="button" class="jr-save-button" data-ac-reset hidden>Сбросить прогресс курса</button>'
        '<p data-ac-storage-status class="ac-small" aria-live="polite"></p></section>')


def _page(title, description, path, body):
    from .journal import _layout, _prelaunch_note
    return HTMLResponse(_layout(title, description, path, _prelaunch_note() + body),
                        headers={"Cache-Control": "no-store"})


def academy_index():
    cards = []
    for course in COURSES:
        cards.append(
            '<article class="ac-course-card"' + _progress_attrs(course) + '>'
            '<p class="ac-eyebrow">Бесплатно · Самостоятельно</p><h2><a href="' + _url(course) + '">' +
            _e(course["title"]) + '</a></h2><p>' + _e(course["description"]) + '</p><p class="ac-small">' +
            str(len(course["lessons"])) + ' уроков · около ' +
            str(sum(lesson["minutes"] for lesson in course["lessons"])) +
            ' минут · без предварительных знаний</p><p data-ac-progress-label role="status" hidden></p>'
            '<a class="jr-primary" data-ac-start href="' + _url(course) + '">Открыть курс →</a></article>')
    body = (
        '<div class="jr-breadcrumb"><a href="/">Главная</a> / Обучение</div>'
        '<section class="jr-hero"><span class="jr-kicker">АКАДЕМИЯ СТАЖНО</span>'
        '<h1>Новые навыки — в вашем темпе</h1><p>Бесплатные практические курсы. Читайте уроки, '
        'выполняйте упражнения и проверяйте себя без регистрации.</p></section>'
        '<section class="jr-list"><h2 class="jr-list-title">Доступные курсы</h2><div class="ac-course-grid">' +
        "".join(cards) + '</div></section>'
        '<aside class="jr-path-promo"><h2>Продолжайте учиться</h2><p>В журнале есть дополнительные '
        'статьи и учебные материалы. Курсы не заменяют профессиональную аттестацию.</p>'
        '<a class="jr-primary" href="/journal/guide/learning">Учебные материалы журнала →</a></aside>')
    return _page("Академия СТАЖНО", "Бесплатные самостоятельные курсы и практические задания.", "/academy", body)


def academy_course(slug: str):
    course = _course(slug)
    outcomes = "".join("<li>" + _e(item) + "</li>" for item in course["outcomes"])
    rows = "".join(
        '<li class="ac-lesson-row"><span class="ac-number" aria-hidden="true">' + str(index) +
        '</span><div><h3><a href="' + _lesson_url(course, lesson) + '">' + _e(lesson["title"]) +
        '</a></h3><p>' + _e(lesson["goal"]) + '</p><p class="ac-small">' +
        str(lesson["minutes"]) + ' мин. <span data-ac-lesson-state="' + _e(lesson["slug"]) +
        '"></span></p></div></li>'
        for index, lesson in enumerate(course["lessons"], 1))
    body = (
        '<div class="jr-breadcrumb"><a href="/academy">Обучение</a> / ' + _e(course["title"]) +
        '</div><section class="jr-hero"><span class="jr-kicker">БЕСПЛАТНЫЙ КУРС</span><h1>' +
        _e(course["title"]) + '</h1><p>' + _e(course["description"]) + '</p></section>'
        '<div class="ac-course-layout"><section class="ac-panel"><h2>Что вы освоите</h2><ul>' +
        outcomes + '</ul><h2>Для кого этот курс</h2><p>' + _e(course["audience"]) +
        '</p><p>Материалы оригинальные, подготовлены с помощью ИИ. '
        'Практические задания рассчитаны на любой разрешённый текстовый ИИ-помощник. '
        'Проверяйте результаты самостоятельно.</p><a class="jr-primary" data-ac-resume href="' +
        _lesson_url(course, course["lessons"][0]) + '">Начать обучение →</a></section>' +
        _progress_panel(course) + '</div><section class="jr-list"><h2 class="jr-list-title">Программа курса</h2>'
        '<ol class="ac-lesson-list"' + _progress_attrs(course) + '>' + rows + '</ol></section>')
    return _page(course["title"], course["description"], _url(course), body)


def academy_lesson(slug: str, lesson_slug: str):
    course = _course(slug)
    lessons = course["lessons"]
    index = next((i for i, item in enumerate(lessons) if item["slug"] == lesson_slug), None)
    if index is None:
        raise HTTPException(404, "Урок не найден")
    lesson = lessons[index]
    sections = "".join(
        '<section class="ac-panel"><h2>' + _e(section[0]) + '</h2>' +
        "".join("<p>" + _e(p) + "</p>" for p in section[1:]) + "</section>"
        for section in lesson["sections"])
    questions = []
    for qindex, q in enumerate(lesson["questions"], 1):
        options = "".join(
            '<label class="ac-answer"><input type="radio" name="q' + str(qindex) +
            '" value="' + str(i) + '"' + (' data-ac-correct="true"' if i == q["correct"] else '') +
            ' required><span>' + _e(option) + '</span></label>'
            for i, option in enumerate(q["options"]))
        questions.append(
            '<fieldset class="ac-question" data-ac-question><legend>' + str(qindex) + '. ' +
            _e(q["text"]) + '</legend>' + options +
            '<p data-ac-feedback class="ac-feedback" hidden aria-live="polite">' +
            _e(q["feedback"]) + '</p></fieldset>')
    previous = ('<a class="jr-secondary" href="' + _lesson_url(course, lessons[index - 1]) +
                '">← Предыдущий урок</a>') if index else '<a class="jr-secondary" href="' + _url(course) + '">← К программе</a>'
    onward = (('<a class="jr-primary" href="' + _lesson_url(course, lessons[index + 1]) + '">Следующий урок →</a>')
              if index + 1 < len(lessons) else '<a class="jr-primary" href="' + _url(course) + '">К результатам курса →</a>')
    body = (
        '<div class="jr-breadcrumb"><a href="/academy">Обучение</a> / <a href="' + _url(course) + '">' +
        _e(course["title"]) + '</a> / Урок ' + str(index + 1) + '</div>'
        '<section class="jr-hero"><span class="jr-kicker">УРОК ' + str(index + 1) + ' ИЗ ' +
        str(len(lessons)) + ' · ' + str(lesson["minutes"]) + ' МИН.</span><h1>' +
        _e(lesson["title"]) + '</h1><p>' + _e(lesson["goal"]) + '</p></section>'
        '<div class="ac-lesson-content">' + sections +
        '<section class="ac-panel"><h2>Пример запроса</h2><div class="ac-example" id="ac-example-text">' +
        _e(lesson["example"]) + '</div><button type="button" data-ac-copy class="jr-save-button" hidden>Скопировать запрос</button>'
        '<p data-ac-copy-status role="status" class="ac-small"></p></section>'
        '<section class="ac-panel"><h2>Попробуйте сами</h2><p>' + _e(lesson["practice"]) +
        '</p><p class="ac-small">Выполните упражнение в любом разрешённом ИИ-помощнике. '
        'Не отправляйте сюда реальные рабочие или личные данные. Задание не нужно загружать на платформу.</p></section>'
        '<section class="ac-panel" id="ac-quiz-section"><h2>Проверьте себя</h2><p>Ответьте на оба вопроса. '
        'Можно пробовать повторно. Это самопроверка, а не экзамен.</p>'
        '<form id="ac-quiz"' + _progress_attrs(course) + ' data-ac-lesson="' + _e(lesson_slug) +
        '">' + "".join(questions) +
        '<button type="submit" class="jr-primary ac-check" hidden>Проверить ответы</button>'
        '<p id="ac-quiz-result" role="status" aria-live="polite"></p></form>'
        '<noscript><p>Для проверки ответов включите JavaScript. Урок и упражнения доступны без него.</p></noscript></section>' +
        _progress_panel(course) + '<nav class="ac-lesson-nav" aria-label="Переход между уроками">' +
        previous + onward + '</nav></div>')
    return _page(lesson["title"], lesson["goal"], _lesson_url(course, lesson), body)


def academy_pages() -> dict[str, HTMLResponse]:
    pages = {"/academy": academy_index()}
    for course in COURSES:
        pages[_url(course)] = academy_course(course["slug"])
        for lesson in course["lessons"]:
            pages[_lesson_url(course, lesson)] = academy_lesson(course["slug"], lesson["slug"])
    return pages


def install_academy_routes(app):
    app.add_api_route("/academy", academy_index, methods=["GET"], include_in_schema=False)
    app.add_api_route("/academy/{slug}", academy_course, methods=["GET"], include_in_schema=False)
    app.add_api_route("/academy/{slug}/{lesson_slug}", academy_lesson, methods=["GET"], include_in_schema=False)
