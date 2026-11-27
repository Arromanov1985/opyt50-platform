/* Journal reading preference — same key as the main STAZHNO homepage. */
'use strict';
document.addEventListener('DOMContentLoaded', () => {
  const button = document.getElementById('reading-mode-toggle');
  if (!button) return;
  const key = 'stazhno-large-text';
  const read = () => { try { return localStorage.getItem(key) === 'yes'; } catch { return false; } };
  const apply = enabled => {
    document.body.classList.toggle('comfortable-view', enabled);
    button.setAttribute('aria-pressed', String(enabled));
    button.setAttribute('aria-label', enabled ? 'Выключить крупный текст' : 'Включить крупный текст');
    button.title = enabled ? 'Обычный текст' : 'Крупный текст';
    try { localStorage.setItem(key, enabled ? 'yes' : 'no'); } catch { /* restricted storage */ }
  };
  apply(read());
  button.addEventListener('click', () => apply(!document.body.classList.contains('comfortable-view')));
});
 
// First-party aggregate counters only. No visitor ID, IP, cookies, local
// storage, query strings, UTM parameters or referrers are included in events.
// A blocked request must never stop reading or following an ordinary link.
document.addEventListener('DOMContentLoaded', () => {
  const path = window.location.pathname.endsWith('/')
    ? window.location.pathname.slice(0, -1) : window.location.pathname;
  const source = path === '/journal'
    ? 'journal'
    : path.startsWith('/journal/paths/') ? 'path:' + path.slice('/journal/paths/'.length)
    : path === '/journal/paths' || path.startsWith('/journal/guide/') || path.startsWith('/journal/author-') ? ''
    : path.startsWith('/journal/') ? path.slice('/journal/'.length)
    : /^\/vacancies\/[1-9][0-9]*$/.test(path) ? 'vacancy:' + path.slice('/vacancies/'.length)
    : /^\/(?:companies|employers)\/[1-9][0-9]*$/.test(path)
      ? 'company:' + path.split('/').pop()
      : '';
  if (!source || source.length > 90 ||
      !/^(?:(?:path|vacancy|company):)?[a-z0-9]+(?:-[a-z0-9]+)*$/.test(source)) return;
  function sendGrowthEvent(action) {
    try {
      fetch('/api/growth/event', {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'X-Requested-With': 'OPYT50'},
        credentials: 'omit',
        referrerPolicy: 'no-referrer',
        cache: 'no-store',
        keepalive: true,
        body: JSON.stringify({source, action})
      }).catch(() => {});
    } catch { /* always leave navigation usable */ }
  }
  sendGrowthEvent('view');
  document.querySelectorAll('a[data-growth-action]').forEach(link => {
    link.addEventListener('click', () => {
      const action = link.getAttribute('data-growth-action');
      if (['jobs_click','profile_click','community_click','company_click','vacancy_click','apply_click','article_click','recommended_vacancy_click'].includes(action)) {
        sendGrowthEvent(action);
      }
    });
  });
});


// Local-only discovery for the public Journal: no searches, filters, or
// visitor identities are sent to the server or written to browser storage.
document.addEventListener('DOMContentLoaded', () => {
  const search = document.getElementById('jr-article-search');
  const grid = document.getElementById('jr-article-grid');
  if (!search || !grid) return;
  const cards = Array.from(grid.querySelectorAll('.jr-card'));
  const filters = Array.from(document.querySelectorAll('[data-jr-category-filter]'));
  const count = document.getElementById('jr-results-count');
  const empty = document.getElementById('jr-no-results');
  let activeCategory = 'all';
  const normalize = text => String(text || '').trim().toLocaleLowerCase('ru-RU');
  function update() {
    const query = normalize(search.value);
    let found = 0;
    for (const card of cards) {
      const categoryMatch = activeCategory === 'all'
        || card.dataset.jrCategory === activeCategory;
      const textMatch = !query || normalize(card.textContent).includes(query);
      card.hidden = !(categoryMatch && textMatch);
      if (!card.hidden) found++;
    }
    if (count) count.textContent = `Показано: ${found} из ${cards.length}`;
    if (empty) empty.hidden = found > 0;
    for (const button of filters) {
      button.setAttribute('aria-pressed', String(button.dataset.jrCategoryFilter === activeCategory));
    }
  }
  search.addEventListener('input', update);
  for (const button of filters) {
    button.addEventListener('click', () => {
      activeCategory = button.dataset.jrCategoryFilter;
      update();
    });
  }
  document.getElementById('jr-reset-search')?.addEventListener('click', () => {
    search.value = '';
    activeCategory = 'all';
    update();
    search.focus();
  });
  update();
});


// Explicit, device-local reading choices. No profile data, network calls,
// click history or implicit interest inference. Never persist on page load.
document.addEventListener('DOMContentLoaded', () => {
  const controls = document.getElementById('jr-personal-controls');
  const buttons = [...document.querySelectorAll('[data-jr-save]')];
  if (!controls && !buttons.length) return;
  const topicsKey = 'stazhno-reading-topics-v1', savedKey = 'stazhno-reading-saved-v1';
  const validSlug = value => typeof value === 'string' && value.length <= 90 && /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(value);
  const topicInputs = [...document.querySelectorAll('[data-jr-topic]')];
  const topicIds = new Set(topicInputs.map(input => input.value));
  const cards = [...document.querySelectorAll('[data-jr-material]')];
  const status = document.getElementById('jr-reading-status');
  const say = text => { if (status) status.textContent = text; };
  function readList(key, valid, limit) {
    try {
      const raw = localStorage.getItem(key);
      if (!raw || raw.length > 32000) return [];
      const items = JSON.parse(raw);
      return Array.isArray(items) ? [...new Set(items.filter(valid))].slice(0, limit) : [];
    } catch { return []; }
  }
  function writeList(key, values) {
    try { localStorage.setItem(key, JSON.stringify(values)); return true; }
    catch { return false; }
  }
  let saved = new Set(readList(savedKey, validSlug, 100));
  const selection = () => topicInputs.filter(input => input.checked).map(input => input.value);
  function draw() {
    for (const button of buttons) {
      const active = saved.has(button.dataset.jrSave);
      button.setAttribute('aria-pressed', String(active));
      button.textContent = active ? 'Убрать из сохранённого' : 'Сохранить для чтения';
      button.hidden = false;
    }
    if (!controls) return;
    const selected = selection();
    const kind = document.getElementById('jr-personal-kind').value;
    const savedOnly = document.getElementById('jr-personal-saved').checked;
    let visible = 0;
    for (const card of cards) {
      const matchTopic = !selected.length || selected.some(topic => card.dataset.jrTopics.split(' ').includes(topic));
      const matchKind = kind === 'all' || card.dataset.jrKind === kind;
      card.hidden = !(matchTopic && matchKind && (!savedOnly || saved.has(card.dataset.jrMaterial)));
      if (!card.hidden) visible++;
    }
    const availableSaved = cards.filter(card => saved.has(card.dataset.jrMaterial)).length;
    document.getElementById('jr-personal-count').textContent =
      'Показано: ' + visible + ' из ' + cards.length + '. Доступных сохранённых: ' + availableSaved + '.';
    document.getElementById('jr-personal-empty').hidden = visible !== 0;
  }
  for (const button of buttons) {
    button.addEventListener('click', () => {
      const slug = button.dataset.jrSave;
      if (!validSlug(slug)) return;
      if (saved.has(slug)) saved.delete(slug);
      else {
        if (saved.size >= 100) {
          say('Можно сохранить до 100 материалов. Удалите ненужные закладки.');
          return;
        }
        saved.add(slug);
      }
      if (writeList(savedKey, [...saved])) {
        say(saved.has(slug) ? 'Материал сохранён в этом браузере.' : 'Материал убран из сохранённого.');
      } else {
        say('Браузер не сохранил закладки. Изменения доступны только до обновления страницы.');
      }
      draw();
    });
  }
  if (controls) {
    const remembered = new Set(readList(topicsKey, value => topicIds.has(value), 9));
    topicInputs.forEach(input => {
      input.checked = remembered.has(input.value);
      input.addEventListener('change', draw);
    });
    document.getElementById('jr-personal-kind').addEventListener('change', draw);
    document.getElementById('jr-personal-saved').addEventListener('change', draw);
    document.getElementById('jr-remember-topics').addEventListener('click', () => {
      say(writeList(topicsKey, selection()) ? 'Интересы запомнены в этом браузере.' :
        'Не удалось запомнить интересы. Фильтры доступны до обновления страницы.');
    });
    function resetFilters() {
      topicInputs.forEach(input => { input.checked = false; });
      document.getElementById('jr-personal-kind').value = 'all';
      document.getElementById('jr-personal-saved').checked = false;
    }
    document.getElementById('jr-reset-topics').addEventListener('click', () => {
      resetFilters(); draw(); say('Фильтры сброшены. Запомненные интересы не изменены.');
    });
    document.getElementById('jr-clear-reading').addEventListener('click', () => {
      if (!window.confirm('Удалить сохранённые интересы и все закладки в этом браузере?')) return;
      let cleared = true;
      try { localStorage.removeItem(topicsKey); localStorage.removeItem(savedKey); }
      catch { cleared = false; }
      saved.clear(); resetFilters(); draw();
      say(cleared ? 'Интересы и закладки удалены.' :
        'Не удалось очистить хранилище браузера. Список сброшен на этой странице.');
    });
    controls.hidden = false;
  }
  window.addEventListener('storage', event => {
    if (event.key === savedKey || event.key === null) {
      saved = new Set(readList(savedKey, validSlug, 100)); draw();
    }
  });
  draw();
});

// Event dates are calendar dates, not UTC instants. The source/organizer
// remains the authority for exact time and whether an event still takes place.
document.addEventListener('DOMContentLoaded', () => {
  const controls = document.getElementById('jr-event-controls');
  if (!controls) return;
  const grid = document.getElementById('jr-events-grid');
  const cards = [...grid.querySelectorAll('[data-jr-event-date]')];
  const period = document.getElementById('jr-event-period');
  const format = document.getElementById('jr-event-format');
  const dateKey = date => [date.getFullYear(), String(date.getMonth()+1).padStart(2,'0'),
    String(date.getDate()).padStart(2,'0')].join('-');
  function filter() {
    const today = dateKey(new Date());
    let count = 0;
    for (const card of cards) {
      const date = card.dataset.jrEventDate;
      const periodMatches = period.value === 'all' || (period.value === 'upcoming' ? date >= today : date < today);
      card.hidden = !(periodMatches && (format.value === 'all' || card.dataset.jrEventFormat === format.value));
      if (!card.hidden) count++;
    }
    document.getElementById('jr-event-count').textContent = 'Показано мероприятий: ' + count + ' из ' + cards.length;
    document.getElementById('jr-event-empty').hidden = count !== 0;
  }
  period.addEventListener('change', filter);
  format.addEventListener('change', filter);
  controls.hidden = false;
  filter();
});


// Local learning progress. Answers and exercises are never sent to a server.
// A completed lesson is a self-check, not a verified credential.
document.addEventListener('DOMContentLoaded', () => {
  const nodes = [...document.querySelectorAll('[data-ac-course]')];
  if (!nodes.length) return;
  const courses = new Map();
  for (const node of nodes) {
    const slug = node.dataset.acCourse;
    if (!courses.has(slug)) {
      const lessons = node.dataset.acLessons.split(' ').filter(Boolean);
      courses.set(slug, {slug, lessons, key:'stazhno-academy-v1:'+slug+':'+node.dataset.acRevision,
        nodes:[], completed:new Set()});
    }
    courses.get(slug).nodes.push(node);
  }
  const learning = document.getElementById('ac-learning');
  const catalogCards = [...document.querySelectorAll('#ac-course-grid .ac-course-card')];
  const filters = learning ? [...learning.querySelectorAll('[data-ac-filter]')] : [];
  let learningFilter = 'all';
  const discovery = document.getElementById('ac-discovery-form');
  const queryInput = document.getElementById('ac-course-search');
  const categoryInput = document.getElementById('ac-category');
  const levelInput = document.getElementById('ac-level');
  const normalizeSearch = value => String(value || '').toLocaleLowerCase('ru-RU').replaceAll('ё','е').trim();
  // A readable storage can still reject writes (privacy restrictions or quota).
  // Probe a dedicated, non-progress key; never overwrite a course's saved data.
  const failureKey = 'stazhno-academy-last-write-failed';
  function canWriteProgress() {
    try {
      const key = 'stazhno-academy-v1:storage-probe';
      localStorage.setItem(key, '1');
      localStorage.removeItem(key);
      return true;
    } catch { return false; }
  }
  function lastWriteFailed() {
    try { return sessionStorage.getItem(failureKey) === '1'; }
    catch { return false; }
  }
  let storageWritable = canWriteProgress();
  let writeFailed = lastWriteFailed();
  function markWrite(failed) {
    writeFailed = failed;
    storageWritable = !failed;
    // Diagnostic only: no course ID, progress, answers or personal data.
    // Keep the last failure across navigation in this tab if possible.
    try {
      if (failed) sessionStorage.setItem(failureKey, '1');
      else sessionStorage.removeItem(failureKey);
    } catch { /* session storage may also be restricted */ }
  }
  function read(course) {
    let raw;
    try {
      raw = localStorage.getItem(course.key);
      course.storageUnavailable = false;
    } catch {
      course.storageUnavailable = true;
      return new Set();
    }
    try {
      const parsed = raw && raw.length < 16000 ? JSON.parse(raw) : [];
      return new Set(Array.isArray(parsed) ? parsed.filter(item=>course.lessons.includes(item)) : []);
    } catch { return new Set(); }
  }
  function learningState(course) {
    if (!course.completed.size) return 'new';
    return course.completed.size === course.lessons.length ? 'complete' : 'active';
  }
  function drawLearning() {
    if (!learning || !catalogCards.length) return;
    const counts = {all:catalogCards.length, active:0, complete:0};
    let shown = 0;
    let unavailable = !storageWritable || writeFailed;
    const words = normalizeSearch(queryInput?.value).split(/\s+/).filter(Boolean);
    const category = categoryInput?.value || 'all';
    const level = levelInput?.value || 'all';
    const narrowed = words.length > 0 || category !== 'all' || level !== 'all';
    for (const card of catalogCards) {
      const course = courses.get(card.dataset.acCourse);
      const status = learningState(course);
      if (status !== 'new') counts[status]++;
      unavailable ||= course.storageUnavailable;
      const searchable = normalizeSearch(card.dataset.acSearch);
      const matches = words.every(word=>searchable.includes(word)) &&
        (category === 'all' || category === card.dataset.acCategory) &&
        (level === 'all' || level === card.dataset.acLevel);
      card.hidden = !matches || (learningFilter !== 'all' && learningFilter !== status);
      if (!card.hidden) shown++;
    }
    for (const button of filters) {
      const filter = button.dataset.acFilter;
      button.setAttribute('aria-pressed', String(learningFilter === filter));
      button.querySelector('[data-ac-count]').textContent = '(' + counts[filter] + ')';
    }
    document.getElementById('ac-learning-count').textContent = 'Показано: ' + shown + ' из ' + counts.all + ' курсов';
    document.getElementById('ac-learning-storage').hidden = !unavailable;
    const empty = document.getElementById('ac-learning-empty');
    empty.hidden = shown !== 0;
    if (!shown) {
      document.getElementById('ac-learning-empty-title').textContent = narrowed
        ? 'Курсы не найдены' : unavailable ? 'Прогресс недоступен' : learningFilter === 'active' ? 'Нет начатых курсов' : 'Пока нет пройденных курсов';
      document.getElementById('ac-learning-empty-text').textContent = narrowed
        ? 'Измените запрос, направление, уровень или статус обучения.'
        : unavailable ? 'Проверьте разрешения и свободное место в хранилище браузера или выберите все курсы.'
        : 'Выберите курс и успешно пройдите самопроверку в уроке.';
    }
    learning.hidden = false;
  }
  const programPanels = [...document.querySelectorAll('[data-ac-program]')];
  function drawPrograms() {
    for (const panel of programPanels) {
      const ordered = [...panel.querySelectorAll('.ac-program-step[data-ac-course]')]
        .map(node=>courses.get(node.dataset.acCourse));
      if (!ordered.length || ordered.some(course=>!course)) continue;
      const count = ordered.filter(course=>learningState(course)==='complete').length;
      const total = ordered.reduce((n,course)=>n+course.lessons.length,0);
      const completed = ordered.reduce((n,course)=>n+course.completed.size,0);
      const next = ordered.find(course=>learningState(course)!=='complete');
      const progress = panel.querySelector('[data-ac-program-progress]');
      const link = panel.querySelector('[data-ac-program-resume]');
      progress.textContent = 'Курсов пройдено: '+count+' из '+ordered.length+
        ' · Уроков: '+completed+' из '+total;
      progress.hidden = false;
      panel.querySelector('[data-ac-program-storage]').hidden =
        storageWritable && !writeFailed && !ordered.some(course=>course.storageUnavailable);
      const target = next || ordered[0];
      const base = '/academy/'+encodeURIComponent(target.slug);
      const lesson = next?.lessons.find(item=>!next.completed.has(item));
      link.href = completed && next && lesson ? base+'/'+encodeURIComponent(lesson) : base;
      link.textContent = !next ? 'Повторить программу →' : completed ? 'Продолжить программу →' : 'Начать программу →';
    }
  }
  function say(course,message) {
    course.nodes.forEach(node => {
      const status=node.querySelector('[data-ac-storage-status]');
      if(status)status.textContent=message;
    });
  }
  function store(course) {
    try {
      localStorage.setItem(course.key,JSON.stringify(course.lessons.filter(item=>course.completed.has(item))));
      markWrite(false);
      return true;
    } catch { markWrite(true); return false; }
  }
  function draw(course) {
    const count=course.completed.size,total=course.lessons.length;
    for(const node of course.nodes){
      node.querySelectorAll('[data-ac-progress-label]').forEach(label=>{
        label.textContent=count+' из '+total+' уроков пройдено'; label.hidden=false;
      });
      node.querySelectorAll('[data-ac-progress]').forEach(bar=>{bar.value=count;});
      node.querySelectorAll('[data-ac-finished]').forEach(label=>{label.hidden=count!==total;});
      node.querySelectorAll('[data-ac-lesson-state]').forEach(label=>{
        label.textContent=course.completed.has(label.dataset.acLessonState)?' · ✓ Пройден':' · Не пройден';
      });
      node.querySelectorAll('[data-ac-reset]').forEach(button=>{button.hidden=false;button.disabled=count===0;});
      node.querySelectorAll('[data-ac-start]').forEach(link=>{
        const next=course.lessons.find(item=>!course.completed.has(item));
        const url='/academy/'+encodeURIComponent(course.slug);
        link.href=count&&next?url+'/'+encodeURIComponent(next):url;
        link.textContent=count===total?'Повторить курс →':count?'Продолжить обучение →':'Открыть курс →';
      });
    }
    const resume=document.querySelector('[data-ac-resume]');
    if(resume){
      const next=course.lessons.find(item=>!course.completed.has(item));
      resume.href='/academy/'+encodeURIComponent(course.slug)+'/'+encodeURIComponent(next||course.lessons[0]);
      resume.textContent=count===total?'Повторить курс →':count?'Продолжить обучение →':'Начать обучение →';
    }
  }
  for(const course of courses.values()){
    course.completed=read(course);draw(course);
    course.nodes.forEach(node=>node.querySelectorAll('[data-ac-reset]').forEach(button=>{
      button.addEventListener('click',()=>{
        if(!window.confirm('Сбросить прогресс этого курса в текущем браузере?'))return;
        let removed=true;
        try{localStorage.removeItem(course.key);}catch{removed=false;markWrite(true);}
        course.completed.clear();draw(course);
        say(course,removed?'Прогресс курса сброшен.':'Не удалось удалить данные из хранилища. Прогресс сброшен только на этой странице.');
        const result=document.getElementById('ac-quiz-result');if(result)result.textContent='';
        const form=document.getElementById('ac-quiz');if(form){
          form.reset();form.querySelectorAll('[data-ac-feedback]').forEach(p=>{p.hidden=true;});
        }
      });
    }));
  }
  drawLearning();
  drawPrograms();
  for (const button of filters) {
    button.addEventListener('click', () => {
      learningFilter = button.dataset.acFilter;
      drawLearning();
    });
  }
  function resetDiscovery() {
    learningFilter = 'all';
    discovery?.reset();
    drawLearning();
    filters.find(button=>button.dataset.acFilter==='all')?.focus();
  }
  discovery?.addEventListener('submit',event=>{event.preventDefault();drawLearning();});
  queryInput?.addEventListener('input',drawLearning);
  categoryInput?.addEventListener('change',drawLearning);
  levelInput?.addEventListener('change',drawLearning);
  document.getElementById('ac-reset-filters')?.addEventListener('click',resetDiscovery);
  document.querySelector('[data-ac-show-all]')?.addEventListener('click',resetDiscovery);
  window.addEventListener('storage',event=>{
    let changed=false;
    for(const course of courses.values())if(event.key===course.key||event.key===null){course.completed=read(course);draw(course);changed=true;}
    if(changed){drawLearning();drawPrograms();}
  });
  // Back/forward cache may restore an old catalog after finishing a lesson.
  // Re-read only the current revision of each still-listed course.
  window.addEventListener('pageshow',event=>{
    if(!event.persisted)return;
    // Revalidate course availability and pinned revisions after restoring a
    // program page from back/forward cache. A withdrawn program must not linger.
    if(programPanels.length){window.location.reload();return;}
    if(!learning)return;
    storageWritable=canWriteProgress();
    writeFailed=lastWriteFailed();
    for(const course of courses.values()){course.completed=read(course);draw(course);}
    drawLearning();
  });
  const form=document.getElementById('ac-quiz');
  if(form){
    const course=courses.get(form.dataset.acCourse);
    const lesson=form.dataset.acLesson;
    const check=form.querySelector('.ac-check');
    const result=document.getElementById('ac-quiz-result');
    check.hidden=false;
    form.addEventListener('submit',event=>{
      event.preventDefault();
      const questions=[...form.querySelectorAll('[data-ac-question]')];
      let correct=0;
      for(const question of questions){
        const answer=question.querySelector('input:checked');
        const right=Boolean(answer?.dataset.acCorrect==='true');
        if(right)correct++;
        const feedback=question.querySelector('[data-ac-feedback]');
        const explanation=feedback.dataset.explanation||feedback.textContent;
        feedback.dataset.explanation=explanation;
        feedback.textContent=(right?'Верно. ':'Попробуйте ещё раз. ')+explanation;
        feedback.classList.toggle('ac-feedback-wrong',!right);feedback.hidden=false;
      }
      if(correct===questions.length&&course.lessons.includes(lesson)){
        // Merge any progress completed in another tab before writing.
        for(const item of read(course))course.completed.add(item);
        course.completed.add(lesson);
        const persisted=store(course);draw(course);
        result.textContent='Все ответы верны. Урок пройден. '+(persisted?'Прогресс сохранён в этом браузере.':'Браузер не сохранил прогресс: он доступен только на этой странице.');
      }else{
        result.textContent='Верных ответов: '+correct+' из '+questions.length+'. Перечитайте пояснения и попробуйте снова.';
      }
    });
    form.addEventListener('change',event=>{
      const question=event.target.closest('[data-ac-question]');
      if(question)question.querySelector('[data-ac-feedback]').hidden=true;
      result.textContent='';
    });
  }
  const copy=document.querySelector('[data-ac-copy]');
  if(copy){
    copy.hidden=false;
    copy.addEventListener('click',async()=>{
      const text=document.getElementById('ac-example-text');
      const status=document.querySelector('[data-ac-copy-status]');
      try{await navigator.clipboard.writeText(text.textContent);status.textContent='Запрос скопирован.';}
      catch{
        try{const range=document.createRange();range.selectNodeContents(text);const selection=window.getSelection();selection.removeAllRanges();selection.addRange(range);}catch{}
        status.textContent='Автоматическое копирование недоступно. Скопируйте выделенный текст вручную.';
      }
    });
  }
});


// Practical reading routes: explicit checkmarks, scoped to published revisions.
// No progress request, cookie, account identifier or free-text input.
document.addEventListener('DOMContentLoaded', () => {
  const panels = [...document.querySelectorAll('[data-jr-journey]')];
  if (!panels.length) return;
  const journeys = new Map();
  for (const panel of panels) {
    const slug = panel.dataset.jrJourney;
    const steps = (panel.dataset.jrJourneySteps || '').split(' ').filter(
      item => /^[a-z0-9]+(?:-[a-z0-9]+)*:[a-f0-9]{24}$/.test(item));
    if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(slug) || !steps.length ||
        steps.length > 32 || new Set(steps).size !== steps.length) continue;
    // A distinct storage key per editorial revision and step means an old
    // tab cannot replace the marks of a newer tab, even during a reset.
    const prefix = 'stazhno-journey-v1:' + slug + ':';
    const keys = new Set(steps.map(step => prefix + step));
    const checks = [...panel.querySelectorAll('[data-jr-journey-check]')];
    const detail = checks.length > 0;
    let completed = new Set(), readFailed = false;
    const pending = new Map();
    const refresh = () => {
      try {
        completed = new Set(steps.filter(step => localStorage.getItem(prefix + step) === 'yes'));
        readFailed = false;
      } catch { readFailed = true; }
      // Unsaved explicit changes remain visible in this tab, but are never
      // flushed automatically or allowed to overwrite an unrelated mark.
      for (const [step, selected] of pending) {
        if (selected) completed.add(step);
        else completed.delete(step);
      }
    };
    const warning = panel.querySelector('[data-jr-journey-warning]');
    const count = panel.querySelector('[data-jr-journey-count]');
    const progress = panel.querySelector('progress');
    const resume = panel.querySelector('[data-jr-journey-resume]');
    const reset = panel.querySelector('[data-jr-journey-reset]');
    const draw = () => {
      count.textContent = 'Выполнено: ' + completed.size + ' из ' + steps.length;
      progress.value = completed.size;
      for (const check of checks) {
        check.checked = completed.has(check.dataset.jrJourneyCheck);
        check.closest('[data-jr-journey-step]')?.classList.toggle('jr-journey-done', check.checked);
      }
      const next = steps.findIndex(item => !completed.has(item));
      const base = detail ? '' : '/journal/paths/' + slug;
      if (next < 0) {
        resume.setAttribute('href', detail ? '#jr-journey-next' : base);
        resume.textContent = detail ? 'Перейти к следующему действию →' : 'План выполнен · открыть →';
      } else {
        const anchor = '#step-' + steps[next].split(':')[0];
        resume.setAttribute('href', !detail && !completed.size ? base : base + anchor);
        resume.textContent = completed.size ? 'Продолжить с шага ' + (next + 1) + ' →'
          : detail ? 'Начать с первого шага →' : 'Выбрать маршрут →';
      }
      const failed = readFailed || pending.size > 0;
      if (reset) reset.disabled = completed.size === 0 && !failed;
      warning.hidden = !failed;
      if (failed) warning.textContent = detail
        ? 'Браузер не сохранил или не открыл отметки. Изменения могут остаться только на этой странице.'
        : 'Сохранённые отметки в этом браузере недоступны.';
    };
    const persistStep = (step, selected) => {
      if (!steps.includes(step)) return;
      try {
        if (selected) localStorage.setItem(prefix + step, 'yes');
        else localStorage.removeItem(prefix + step);
        pending.delete(step);
        if (selected) completed.add(step);
        else completed.delete(step);
      } catch { pending.set(step, selected); }
    };
    refresh();
    for (const check of checks) {
      check.closest('[data-jr-journey-control]').hidden = false;
      check.addEventListener('change', () => {
        persistStep(check.dataset.jrJourneyCheck, check.checked);
        refresh(); draw();
      });
    }
    reset?.addEventListener('click', () => {
      // Reset only the currently visible revisions. Never touch a newer
      // revision or a different plan that may be open elsewhere.
      for (const step of steps) persistStep(step, false);
      refresh(); draw(); resume.focus();
    });
    panel.querySelector('[data-jr-journey-progress]').hidden = false;
    draw();
    for (const key of keys) journeys.set(key, () => { refresh(); draw(); });
  }
  window.addEventListener('storage', event => {
    if (event.key === null) {
      for (const update of new Set(journeys.values())) update();
    } else journeys.get(event.key)?.();
  });
  // Re-fetch currently published steps rather than restoring outdated editorial
  // markup from back-forward cache. The persisted marks are read on the new page.
  window.addEventListener('pageshow', event => {
    if (event.persisted) window.location.reload();
  });
});
