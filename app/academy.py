"""Public, free self-study courses. Progress is device-local, not a credential."""
from __future__ import annotations

from html import escape

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse

from .academy_content import COURSES
from .academy_catalog import CATEGORIES, LEVELS, catalog_classification
from .academy_programs import visible_programs


def _e(value) -> str:
    return escape(str(value), quote=True)


def _course(slug: str, courses=None):
    course = next((item for item in (COURSES if courses is None else courses) if item["slug"] == slug), None)
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


def _classification_label(course):
    classification = catalog_classification(course)
    return CATEGORIES[classification["category"]] + " · " + LEVELS[classification["level"]]


def _catalog_options(options, all_label):
    return '<option value="all">' + _e(all_label) + '</option>' + "".join(
        '<option value="' + _e(key) + '">' + _e(label) + '</option>'
        for key, label in options.items()
    )


def _program_url(program):
    return "/academy/programs/" + _e(program["slug"])


def _program_cards(courses):
    cards = []
    for program in visible_programs(courses):
        minutes = sum(lesson["minutes"] for course in program["courses"] for lesson in course["lessons"])
        cards.append(
            '<article class="ac-course-card"><p class="ac-eyebrow">Учебная программа · Бесплатно</p>'
            '<h3><a href="' + _program_url(program) + '">' + _e(program["title"]) + '</a></h3>'
            '<p>' + _e(program["description"]) + '</p><p class="ac-small">Курсов: ' +
            str(len(program["courses"])) + ' · около ' + str(minutes) + ' минут</p>'
            '<a class="jr-primary" href="' + _program_url(program) + '">Открыть программу →</a></article>')
    return ('<section class="jr-list" id="ac-programs"><h2 class="jr-list-title">Образовательные программы</h2>'
            '<div class="ac-course-grid">' + "".join(cards) + '</div></section>') if cards else ""


def _program_links(course, courses):
    programs = [program for program in visible_programs(courses)
                if any(item["slug"] == course["slug"] for item in program["courses"])]
    if not programs:
        return ""
    return ('<aside class="ac-panel"><h2>Курс входит в программу</h2><ul>' +
            "".join('<li><a href="' + _program_url(program) + '">' + _e(program["title"]) + '</a></li>'
                    for program in programs) +
            '</ul><p class="ac-small">Вернитесь к программе, чтобы продолжить обучение по порядку.</p></aside>')


def academy_program(slug, courses=None):
    courses = COURSES if courses is None else courses
    program = next((item for item in visible_programs(courses) if item["slug"] == slug), None)
    if program is None:
        raise HTTPException(404, "Программа не найдена")
    rows = []
    for index, course in enumerate(program["courses"], 1):
        rows.append(
            '<li class="ac-lesson-row ac-program-step"' + _progress_attrs(course) + '>'
            '<span class="ac-number" aria-hidden="true">' + str(index) + '</span><div>'
            '<h3><a href="' + _url(course) + '">' + _e(course["title"]) + '</a></h3>'
            '<p>' + _e(course["description"]) + '</p><p class="ac-small">' +
            _e(_classification_label(course)) + ' · ' + str(sum(lesson["minutes"] for lesson in course["lessons"])) +
            ' мин.</p><p data-ac-progress-label class="ac-small" hidden></p>'
            '<a class="jr-primary" data-ac-start href="' + _url(course) + '">Открыть курс →</a></div></li>')
    minutes = sum(lesson["minutes"] for course in program["courses"] for lesson in course["lessons"])
    body = (
        '<div class="jr-breadcrumb"><a href="/academy">Академия</a> / Образовательная программа</div>'
        '<section class="jr-hero"><span class="jr-kicker">БЕСПЛАТНАЯ ПРОГРАММА · САМОСТОЯТЕЛЬНО</span>'
        '<h1>' + _e(program["title"]) + '</h1><p>' + _e(program["description"]) + '</p></section>'
        '<section class="jr-list" data-ac-program><div class="ac-panel ac-program-summary">'
        '<h2>Что вы освоите</h2><p>' + _e(program["goal"]) + '</p>'
        '<p>Курсов: ' + str(len(program["courses"])) + ' · около ' + str(minutes) + ' минут</p>'
        '<p class="ac-small">Рекомендуем проходить курсы по порядку. Все уроки доступны самостоятельно. '
        'Прогресс хранится в этом браузере, может быть виден другим пользователям общего устройства и не является сертификатом.</p>'
        '<p data-ac-program-progress role="status" hidden></p>'
        '<p data-ac-program-storage role="status" class="ac-small" hidden>Браузер может не сохранять новые результаты.</p>'
        '<a class="jr-primary" data-ac-program-resume href="' + _url(program["courses"][0]) + '">Начать программу →</a></div>'
        '<h2 class="jr-list-title ac-program-heading">Курсы по порядку</h2><ol class="ac-lesson-list">' +
        "".join(rows) + '</ol></section><p class="jr-back"><a href="/academy">← Все курсы</a></p>')
    return _page(program["title"], program["description"], _program_url(program), body)


def academy_index(courses=None):
    courses = COURSES if courses is None else courses
    cards = []
    for course in courses:
        classification = catalog_classification(course)
        searchable = " ".join([course["title"], course["description"], course["audience"],
                               *course["outcomes"], _classification_label(course)])
        cards.append(
            '<article class="ac-course-card"' + _progress_attrs(course) +
            ' data-ac-category="' + _e(classification["category"]) +
            '" data-ac-level="' + _e(classification["level"]) +
            '" data-ac-search="' + _e(searchable) + '">'
            '<p class="ac-eyebrow">Бесплатно · Самостоятельно</p><p class="ac-classification">' +
            _e(_classification_label(course)) + '</p><h2><a href="' + _url(course) + '">' +
            _e(course["title"]) + '</a></h2><p>' + _e(course["description"]) + '</p><p class="ac-small">' +
            str(len(course["lessons"])) + ' уроков · около ' +
            str(sum(lesson["minutes"] for lesson in course["lessons"])) +
            ' минут</p><p data-ac-progress-label role="status" hidden></p>'
            '<a class="jr-primary" data-ac-start href="' + _url(course) + '">Открыть курс →</a></article>')
    body = (
        '<div class="jr-breadcrumb"><a href="/">Главная</a> / Обучение</div>'
        '<section class="jr-hero"><span class="jr-kicker">АКАДЕМИЯ СТАЖНО</span>'
        '<h1>Новые навыки — в вашем темпе</h1><p>Бесплатные практические курсы. Читайте уроки, '
        'выполняйте упражнения и проверяйте себя без регистрации.</p></section>' +
        _program_cards(courses) +
        '<section class="jr-list" id="ac-catalog"><h2 class="jr-list-title">Доступные курсы</h2>'
        '<section class="ac-panel ac-learning" id="ac-learning" aria-labelledby="ac-learning-title" hidden>'
        '<h2 id="ac-learning-title">Моё обучение</h2>'
        '<p class="ac-small">Прогресс хранится только в этом браузере. На общем устройстве его могут увидеть другие пользователи. '
        'После обновления курса обучение начинается с новой версии.</p>'
        '<div class="ac-learning-filters" role="group" aria-label="Показать курсы">'
        '<button type="button" data-ac-filter="all" aria-pressed="true" aria-controls="ac-course-grid">Все курсы <span data-ac-count></span></button>'
        '<button type="button" data-ac-filter="active" aria-pressed="false" aria-controls="ac-course-grid">Продолжить обучение <span data-ac-count></span></button>'
        '<button type="button" data-ac-filter="complete" aria-pressed="false" aria-controls="ac-course-grid">Пройдено <span data-ac-count></span></button></div>'
        '<p class="ac-small">Счётчики статусов относятся ко всему каталогу.</p>'
        '<form id="ac-discovery-form" class="ac-discovery" role="search" aria-label="Поиск и фильтры курсов">'
        '<div><label for="ac-course-search">Поиск по курсам</label><input type="search" id="ac-course-search" maxlength="120" placeholder="Название или навык"></div>'
        '<div><label for="ac-category">Направление</label><select id="ac-category">' +
        _catalog_options(CATEGORIES, "Все направления") + '</select></div>'
        '<div><label for="ac-level">Уровень</label><select id="ac-level">' +
        _catalog_options(LEVELS, "Любой уровень") + '</select></div>'
        '<button type="button" id="ac-reset-filters" class="jr-save-button">Сбросить фильтры</button></form>'
        '<p class="ac-small" id="ac-learning-count" role="status"></p>'
        '<p class="ac-small" id="ac-learning-storage" role="status" hidden>Браузер может не сохранять новые результаты. Уже сохранённый прогресс отображается, если доступен. Обучение можно продолжать.</p></section>'
        '<div class="ac-course-grid" id="ac-course-grid">' +
        ("".join(cards) or '<p>Пока нет опубликованных курсов.</p>') +
        '</div><section class="ac-panel ac-learning-empty" id="ac-learning-empty" hidden>'
        '<h3 id="ac-learning-empty-title"></h3><p id="ac-learning-empty-text"></p>'
        '<button type="button" class="jr-save-button" data-ac-show-all>Все курсы</button></section></section>'
        '<aside class="jr-path-promo"><h2>Поделитесь опытом</h2><p>Создавайте учебные программы в понятном конструкторе.</p><a class="jr-primary" href="/community/courses">Конструктор курсов →</a></aside>'
        '<aside class="jr-path-promo"><h2>Продолжайте учиться</h2><p>В журнале есть дополнительные '
        'статьи и учебные материалы. Курсы не заменяют профессиональную аттестацию.</p>'
        '<a class="jr-primary" href="/journal/guide/learning">Учебные материалы журнала →</a></aside>')
    return _page("Академия СТАЖНО", "Бесплатные самостоятельные курсы и практические задания.", "/academy", body)


def academy_course(slug: str, courses=None):
    course = _course(slug, courses)
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
        _e(course["title"]) + '</h1><p>' + _e(course["description"]) +
        '</p><p class="ac-hero-classification">' + _e(_classification_label(course)) + '</p></section>'
        '<div class="ac-course-layout"><section class="ac-panel"><h2>Что вы освоите</h2><ul>' +
        outcomes + '</ul><h2>Для кого этот курс</h2><p>' + _e(course["audience"]) +
        '</p><p>' + (_e(course["author_public_name"]) + ' · <a href="/people/' + _e(course["author_public_id"]) + '">Профиль автора</a>' if course.get("author_public_id") else 'Редакционный курс СТАЖНО') + '</p><p>Выполняйте задания самостоятельно. Курсы не подтверждают квалификацию.</p><a class="jr-primary" data-ac-resume href="' +
        _lesson_url(course, course["lessons"][0]) + '">Начать обучение →</a></section>' +
        _progress_panel(course) + '</div><section class="jr-list"><h2 class="jr-list-title">Программа курса</h2>'
        '<ol class="ac-lesson-list"' + _progress_attrs(course) + '>' + rows + '</ol></section>' +
        _program_links(course, COURSES if courses is None else courses))
    return _page(course["title"], course["description"], _url(course), body)


def academy_lesson(slug: str, lesson_slug: str, courses=None):
    course = _course(slug, courses)
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
        '<section class="ac-panel"><h2>' + ('Пример запроса' if slug == "ai-basics" else 'Практический пример') + '</h2><div class="ac-example" id="ac-example-text">' +
        _e(lesson["example"]) + '</div><button type="button" data-ac-copy class="jr-save-button" hidden>Скопировать пример</button>'
        '<p data-ac-copy-status role="status" class="ac-small"></p></section>'
        '<section class="ac-panel"><h2>Попробуйте сами</h2><p>' + _e(lesson["practice"]) +
        '</p><p class="ac-small">Выполните упражнение по инструкции автора. '
        'Не отправляйте сюда реальные рабочие или личные данные. Задание не нужно загружать на платформу.</p></section>'
        '<section class="ac-panel" id="ac-quiz-section"><h2>Проверьте себя</h2><p>Ответьте на все вопросы. '
        'Можно пробовать повторно. Это самопроверка, а не экзамен.</p>'
        '<form id="ac-quiz"' + _progress_attrs(course) + ' data-ac-lesson="' + _e(lesson_slug) +
        '">' + "".join(questions) +
        '<button type="submit" class="jr-primary ac-check" hidden>Проверить ответы</button>'
        '<p id="ac-quiz-result" role="status" aria-live="polite"></p></form>'
        '<noscript><p>Для проверки ответов включите JavaScript. Урок и упражнения доступны без него.</p></noscript></section>' +
        _progress_panel(course) + '<nav class="ac-lesson-nav" aria-label="Переход между уроками">' +
        previous + onward + '</nav>' + _program_links(course, COURSES if courses is None else courses) + '</div>')
    return _page(lesson["title"], lesson["goal"], _lesson_url(course, lesson), body)


def academy_pages(courses=None) -> dict[str, HTMLResponse]:
    courses = COURSES if courses is None else courses
    pages = {"/academy": academy_index(courses)}
    for course in courses:
        pages[_url(course)] = academy_course(course["slug"], courses)
        for lesson in course["lessons"]:
            pages[_lesson_url(course, lesson)] = academy_lesson(course["slug"], lesson["slug"], courses)
    for program in visible_programs(courses):
        pages[_program_url(program)] = academy_program(program["slug"], courses)
    return pages


def install_academy_routes(app):
    from .academy_builder import public_catalog

    def index(request: Request):
        return academy_index(public_catalog(request))

    def detail(slug: str, request: Request):
        return academy_course(slug, public_catalog(request))

    def lesson(slug: str, lesson_slug: str, request: Request):
        return academy_lesson(slug, lesson_slug, public_catalog(request))

    def program(slug: str, request: Request):
        return academy_program(slug, public_catalog(request))

    app.add_api_route("/academy/programs/{slug}", program, methods=["GET"], include_in_schema=False)
    app.add_api_route("/academy", index, methods=["GET"], include_in_schema=False)
    app.add_api_route("/academy/{slug}", detail, methods=["GET"], include_in_schema=False)
    app.add_api_route("/academy/{slug}/{lesson_slug}", lesson, methods=["GET"], include_in_schema=False)
