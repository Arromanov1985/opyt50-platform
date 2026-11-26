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
  function read(course) {
    try {
      const raw = localStorage.getItem(course.key);
      const parsed = raw && raw.length < 16000 ? JSON.parse(raw) : [];
      return new Set(Array.isArray(parsed) ? parsed.filter(item=>course.lessons.includes(item)) : []);
    } catch { return new Set(); }
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
      return true;
    } catch { return false; }
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
        link.textContent=count===total?'Повторить курс →':count?'Продолжить курс →':'Открыть курс →';
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
        try{localStorage.removeItem(course.key);}catch{removed=false;}
        course.completed.clear();draw(course);
        say(course,removed?'Прогресс курса сброшен.':'Не удалось удалить данные из хранилища. Прогресс сброшен только на этой странице.');
        const result=document.getElementById('ac-quiz-result');if(result)result.textContent='';
        const form=document.getElementById('ac-quiz');if(form){
          form.reset();form.querySelectorAll('[data-ac-feedback]').forEach(p=>{p.hidden=true;});
        }
      });
    }));
  }
  window.addEventListener('storage',event=>{
    for(const course of courses.values())if(event.key===course.key||event.key===null){course.completed=read(course);draw(course);}
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

