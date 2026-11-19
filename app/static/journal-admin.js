/* STAZHNO editorial admin: no external dependencies or user tracking. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const state = {slug: null, version: 0, status: null, dirty: false, items: []};
  const keys = {
    slug: $('article-slug'), title: $('article-title'),
    description: $('article-description'), category: $('article-category'),
    read: $('article-read'), body_text: $('article-body')
  };
  function notice(text, error=false) {
    const el = $('notice');
    el.textContent = text;
    el.className = error ? 'notice error' : 'notice success';
  }
  async function api(path, opts={}) {
    const response = await fetch(path, {
      ...opts, credentials:'same-origin',
      headers:{'X-Requested-With':'OPYT50', 'Content-Type':'application/json', ...(opts.headers || {})},
      cache:'no-store'
    });
    let body = {};
    try { body = await response.json(); } catch {}
    if (!response.ok) {
      const detail = body.detail;
      const message = typeof detail === 'string' ? detail : 'Проверьте заполнение полей и повторите действие';
      throw new Error(message + ' (HTTP ' + response.status + ')');
    }
    return body;
  }
  function setDirty(value) {
    state.dirty = value;
    $('save').textContent = value ? 'Сохранить изменения' : 'Сохранено';
    updateButtons();
  }
  function updateButtons() {
    const saved = Boolean(state.slug && state.version);
    $('publish').disabled = !saved || state.dirty || state.status === 'archived';
    $('hide').disabled = !saved || state.dirty || state.status !== 'published';
    $('archive').disabled = !saved || state.dirty || state.status !== 'draft';
    $('editor-status').textContent = state.status === 'published' ? 'Опубликовано'
      : state.status === 'hidden' ? 'Скрыто'
      : state.status === 'archived' ? 'Архив'
      : saved ? 'Черновик' : 'Новая статья';
    $('article-slug').readOnly = saved;
    $('edit-hint').textContent = state.dirty
      ? 'Есть несохранённые изменения. Сначала сохраните текст, затем публикуйте.'
      : 'Публикация всегда отдельное действие. Скрытие удаляет статью из каталога и карты сайта.';
  }
  function collect() {
    return {
      title: keys.title.value.trim(), description: keys.description.value.trim(),
      category: keys.category.value.trim(), read: keys.read.value.trim(),
      body_text: keys.body_text.value.trim(), version: state.version
    };
  }
  function clearForm() {
    for (const field of Object.values(keys)) field.value = '';
    keys.read.value = '5 минут';
    state.slug = null; state.version = 0; state.status = 'draft';
    $('editor-heading').textContent = 'Новая статья';
    $('article-preview').hidden = true;
    setDirty(true);
    keys.slug.focus();
  }
  function renderList() {
    const root = $('article-list');
    root.replaceChildren();
    if (!state.items.length) {
      root.textContent = 'Пока нет статей.';
      return;
    }
    for (const item of state.items) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'article-list-item' + (item.slug === state.slug ? ' active' : '');
      const title = document.createElement('strong');
      title.textContent = item.title;
      const meta = document.createElement('small');
      const status = {draft:'Черновик',published:'Опубликовано',hidden:'Скрыто',archived:'Архив'}[item.status] || item.status;
      meta.textContent = item.category + ' · ' + status + (item.has_changes ? ' · Не опубликованы правки' : '');
      btn.append(title,meta);
      btn.addEventListener('click', () => open(item.slug));
      root.append(btn);
    }
  }
  async function refreshList() {
    const data = await api('/api/admin/journal');
    state.items = data.articles;
    renderList();
  }
  async function open(slug) {
    if (state.dirty && !window.confirm('Перейти к другой статье и потерять несохранённые изменения?')) return;
    try {
      const result = await api('/api/admin/journal/' + encodeURIComponent(slug));
      const article = result.article;
      state.slug = article.slug;
      state.version = article.version;
      state.status = article.status;
      for (const key of ['title','description','category','read','body_text']) keys[key].value = article[key] || '';
      keys.slug.value = article.slug;
      $('editor-heading').textContent = article.title;
      $('article-preview').hidden = true;
      setDirty(false);
      renderList();
    } catch (error) { notice(error.message,true); }
  }
  async function save(event) {
    if (event) event.preventDefault();
    if (!$('article-form').reportValidity()) return;
    const payload = collect();
    const slug = state.slug || keys.slug.value.trim();
    try {
      const response = state.slug
        ? await api('/api/admin/journal/' + encodeURIComponent(slug), {
            method:'PUT', body:JSON.stringify(payload)
          })
        : await api('/api/admin/journal', {
            method:'POST',body:JSON.stringify({slug,...payload})
          });
      state.slug = slug;
      state.version = response.version;
      state.status = state.status || 'draft';
      setDirty(false);
      $('editor-heading').textContent = payload.title;
      await refreshList();
      notice('Черновик сохранён. Для публикации нажмите «Опубликовать».');
    } catch (error) { notice(error.message,true); }
  }
  async function action(kind) {
    if (!state.slug || state.dirty) {
      notice('Сначала сохраните изменения в статье.',true);
      return;
    }
    const messages = {
      publish:'Опубликовать текущую редакцию для всех посетителей?',
      hide:'Скрыть статью из журнала и карты сайта?',
      archive:'Архивировать неопубликованный черновик? Это действие нельзя отменить в редакторе.'
    };
    if (!window.confirm(messages[kind])) return;
    try {
      const response = await api('/api/admin/journal/' + encodeURIComponent(state.slug) + '/' + kind,
        {method:'POST',body:JSON.stringify({version:state.version})});
      state.version = response.version;
      state.status = {publish:'published',hide:'hidden',archive:'archived'}[kind];
      setDirty(false);
      await refreshList();
      await loadAudit();
      notice({publish:'Статья опубликована.',hide:'Статья снята с публикации.',archive:'Черновик архивирован.'}[kind]);
    } catch (error) { notice(error.message,true); }
  }
  function preview() {
    const area = $('preview-content');
    area.replaceChildren();
    const heading = document.createElement('h3');heading.textContent = keys.title.value || 'Без названия';
    const summary = document.createElement('p'); summary.textContent = keys.description.value;
    area.append(heading,summary);
    let section = null, list = null;
    for (const line of keys.body_text.value.replace(/\r/g,'').split('\n')) {
      const text = line.trim();
      if (!text) { list = null; continue; }
      if (text.startsWith('## ')) {
        section = document.createElement('section');
        const title = document.createElement('h4');title.textContent = text.slice(3);
        section.append(title);area.append(section);list = null;
      } else if (text.startsWith('- ') && section) {
        if (!list) {list=document.createElement('ul');section.append(list);}
        const item=document.createElement('li');item.textContent=text.slice(2);list.append(item);
      } else {
        const p=document.createElement('p');p.textContent=text;
        (section || area).append(p);
        list=null;
      }
    }
    $('article-preview').hidden = false;
    $('article-preview').scrollIntoView({behavior:'smooth',block:'start'});
  }
  async function loadAudit() {
    try {
      const {events} = await api('/api/admin/journal/audit');
      const root = $('audit-items');root.replaceChildren();
      if (!events.length) {root.textContent='Редакционных действий пока нет.';return;}
      for (const event of events) {
        const el=document.createElement('p');
        const action={create:'Создан',save:'Сохранён',publish:'Опубликован',hide:'Скрыт',archive:'В архиве'}[event.action] || event.action;
        el.textContent = action + ': ' + event.slug + ' · версия ' + event.version + ' · ' + event.created_at.slice(0,16);
        root.append(el);
      }
    } catch(error) { notice(error.message,true); }
  }
  for (const field of Object.values(keys)) {
    field.addEventListener('input', () => setDirty(true));
  }
  $('article-form').addEventListener('submit', save);
  $('new-article').addEventListener('click', () => {
    if (state.dirty && !window.confirm('Сбросить несохранённые изменения?')) return;
    clearForm();renderList();
  });
  $('preview').addEventListener('click', preview);
  for (const type of ['publish','hide','archive']) $(type).addEventListener('click', () => action(type));
  $('reload-list').addEventListener('click', () => refreshList().catch(e => notice(e.message,true)));
  $('reload-audit').addEventListener('click',loadAudit);
  window.addEventListener('beforeunload', event => {
    if (state.dirty) {event.preventDefault(); event.returnValue='';}
  });
  updateButtons();
  Promise.all([refreshList(),loadAudit()]).then(() => {
    const first = state.items.find(item => item.status !== 'archived');
    if (first) open(first.slug);
  }).catch(error => notice(error.message,true));
})();