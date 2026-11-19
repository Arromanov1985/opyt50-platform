/* Professional community. Drafts, conversations and credentials stay in memory. */
'use strict';
(() => {
  const $ = (selector, root = document) => root.querySelector(selector);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, character => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[character]));
  const goals = {work:'Работа и подработка', projects:'Совместные проекты', mentoring:'Наставничество', exchange:'Обмен опытом'};
  const profileStates = {draft:'Черновик — виден только вам', pending:'На проверке — ещё не опубликован', published:'Профиль опубликован', rejected:'Нужны изменения', hidden:'Профиль скрыт'};
  const connectionStates = {pending:'Ожидает ответа', accepted:'Знакомство принято', declined:'Запрос отклонён', cancelled:'Запрос отозван', blocked:'Общение прекращено'};
  const reasons = {spam:'Спам или навязчивые предложения', fraud:'Подозрение на мошенничество', harassment:'Оскорбления или давление', personal_data:'Публикация личных данных', other:'Другая проблема'};
  const mode = document.body.dataset.communityPage;
  const state = {user:null, profile:null, dirty:false, messageDirty:false, connections:[], connectionPage:1, connectionFilter:'', selected:null, messageKey:null, messageBody:null, nextBefore:null, directoryPage:1, directoryRequest:0, threadRequest:0, moderationPage:1, reportPage:1, busy:new WeakSet()};
  const content = $('#community-content');
  const dialog = $('#community-dialog');
  let dialogBusy = false;

  function notice(message, type = '') {
    const node = $('#community-notice');
    node.className = 'notice' + (type ? ' ' + type : '');
    node.textContent = message;
    node.hidden = !message;
  }
  function inlineError(root, message) {
    let node = $('.form-error', root);
    if (!node) { node = document.createElement('p'); node.className = 'notice error form-error'; node.setAttribute('role','alert'); root.prepend(node); }
    node.hidden = false;
    node.textContent = message;
  }
  async function api(path, {method = 'GET', body} = {}) {
    let response;
    const headers = body === undefined ? {} : {'Content-Type':'application/json','X-Requested-With':'OPYT50'};
    // Bind this tab to the account it loaded. A cookie change in another tab
    // must not save this person's draft into a different account.
    if (state.user && (path.startsWith('/api/community/') || path.startsWith('/api/admin/community/'))) headers['X-Community-Actor'] = String(state.user.id);
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 20000);
    try {
      response = await fetch(path, {method, credentials:'same-origin', cache:'no-store', signal:controller.signal, headers, ...(body === undefined ? {} : {body:JSON.stringify(body)})});
    } catch {
      throw new Error('Не удалось связаться с сервером. Введённый текст сохранён в этой вкладке. Проверьте соединение и повторите действие.');
    } finally { clearTimeout(timeout); }
    let payload = {};
    try { payload = await response.json(); } catch { /* A proxy may return a plain error page. */ }
    if (!response.ok) {
      let message = typeof payload.detail === 'string' ? payload.detail : '';
      if (Array.isArray(payload.detail)) message = payload.detail.map(item => item.msg.replace(/^Value error, /, '')).join(' ');
      if (!message) message = response.status >= 500 ? 'Сервер временно недоступен. Введённый текст остаётся в этой вкладке. Повторите позже.' : 'Не удалось выполнить действие. Обновите данные и попробуйте снова.';
      if (response.status === 401) message = 'Сессия завершилась. Войдите на главной в другой вкладке, затем повторите действие здесь — введённый текст останется.';
      const error = new Error(message); error.status = response.status; throw error;
    }
    return payload;
  }
  async function busy(root, action) {
    if (state.busy.has(root)) return;
    state.busy.add(root);
    root.setAttribute('aria-busy','true');
    const controls = [...root.querySelectorAll('button,input,textarea,select')].map(node => [node,node.disabled]);
    controls.forEach(([node]) => { node.disabled = true; });
    if (dialog.contains(root)) dialogBusy = true;
    try { return await action(); }
    catch (error) { inlineError(root, error.message); }
    finally {
      state.busy.delete(root); root.removeAttribute('aria-busy');
      controls.forEach(([node, disabled]) => { if (node.isConnected) node.disabled = disabled; });
      if (dialog.contains(root) || !root.isConnected) dialogBusy = false;
    }
  }
  function openDialog(title, markup) {
    $('#community-dialog-title').textContent = title;
    $('#community-dialog-content').innerHTML = markup;
    if (!dialog.open) dialog.showModal();
  }
  function closeDialog() {
    if (dialogBusy) return;
    dialog.close();
  }
  function confirmAction(title, text, label, action) {
    openDialog(title, `<p class="confirmation-copy">${esc(text)}</p><form id="confirm-community-form"><p class="form-error notice error" role="alert" hidden></p><div class="actions"><button type="submit" class="button danger" id="confirm-community-action">${esc(label)}</button><button type="button" class="button secondary" data-close-dialog>Отмена</button></div></form>`);
    const form = $('#confirm-community-form');
    form.addEventListener('submit', event => { event.preventDefault(); busy(form, async () => { await action(); dialogBusy = false; closeDialog(); }); });
  }
  function statusBadge(status, labels) { return `<span class="status-badge ${esc(status)}">${esc(labels[status] || status)}</span>`; }
  function options(values, selected, emptyLabel = null) { return (emptyLabel === null ? '' : `<option value="">${esc(emptyLabel)}</option>`) + Object.entries(values).map(([value,label]) => `<option value="${value}"${selected === value ? ' selected' : ''}>${esc(label)}</option>`).join(''); }
  function date(value) { if (!value) return ''; const parsed = new Date(value.endsWith('Z') || /[+-]\d\d:\d\d$/.test(value) ? value : value.replace(' ','T') + 'Z'); return Number.isNaN(parsed.getTime()) ? '' : parsed.toLocaleString('ru-RU',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'}); }
  function empty(title, text, action = '') { return `<div class="empty-state"><span class="empty-symbol" aria-hidden="true">↗</span><h2>${esc(title)}</h2><p>${esc(text)}</p>${action}</div>`; }
  function pager(page, hasMore, action) { return `<div class="pager" aria-label="Страницы"><button class="button secondary compact" type="button" data-action="${action}" data-page="${page-1}"${page <= 1 ? ' disabled' : ''}>← Назад</button><span>Страница ${page}</span><button class="button secondary compact" type="button" data-action="${action}" data-page="${page+1}"${hasMore ? '' : ' disabled'}>Далее →</button></div>`; }
  function personCard(person, preview = false) {
    const name = person.public_name || 'Ваше публичное имя';
    const url = preview ? '' : '/people/' + encodeURIComponent(person.public_id);
    return `<article class="person-card"${preview ? '' : ` data-person-id="${esc(person.public_id)}"`}><div class="person-card-top"><span class="person-avatar" aria-hidden="true">${esc(name.charAt(0).toUpperCase())}</span><span class="tag">${esc(goals[person.goal] || goals.exchange)}</span></div><h2>${preview ? esc(name) : `<a href="${url}">${esc(name)}</a>`}</h2><p class="headline">${esc(person.headline || 'Профессия и направление')}</p><p class="location">${esc(person.city || 'Город не указан')}</p><p class="card-about">${esc((person.about || 'Здесь будет короткий рассказ о том, чем вы можете быть полезны.').slice(0,180))}${(person.about || '').length > 180 ? '…' : ''}</p><div class="card-footer"><a href="${url}">Посмотреть профиль <span aria-hidden="true">→</span></a></div></article>`;
  }
  function loginMarkup() {
    return `<form id="community-login-form" class="dialog-form"><div class="field"><label for="community-email">Электронная почта</label><input id="community-email" name="email" type="email" autocomplete="username" maxlength="254" required></div><div class="field"><label for="community-password">Пароль</label><input id="community-password" name="password" type="password" autocomplete="current-password" maxlength="128" required></div><button class="button primary" type="submit">Войти</button><p class="help">Нет аккаунта? <a href="/#candidate-path">Зарегистрируйтесь на главной</a>, затем откройте сообщество.</p><p class="help">Вход администратора с дополнительной проверкой доступен <a href="/">на главной странице</a>.</p></form>`;
  }
  function bindLogin(root, after) {
    $('#community-login-form',root).addEventListener('submit', event => {
      event.preventDefault(); const form = event.currentTarget; const data = Object.fromEntries(new FormData(form));
      busy(form,async () => {
        const result = await api('/api/login',{method:'POST',body:data});
        if (result.mfa_required) throw new Error('Для входа администратора перейдите на главную и завершите дополнительную проверку.');
        state.user = (await api('/api/me')).user;
        updateIdentity(); dialogBusy = false; closeDialog(); await after();
      });
    });
  }
  function loginDialog(after) { openDialog('Войдите, чтобы продолжить', loginMarkup()); bindLogin(dialog,after); }
  function accountGate(title) {
    content.innerHTML = `<section class="panel account-gate"><span class="eyebrow">ВАШЕ ПРОФЕССИОНАЛЬНОЕ ПРОСТРАНСТВО</span><h1>${esc(title)}</h1><p>Войдите в свой аккаунт СТАЖНО. Профиль и переписка будут доступны в вашем кабинете.</p>${loginMarkup()}</section>`;
    bindLogin(content, renderMode);
  }
  function updateIdentity() { $('#moderation-nav').hidden = state.user?.role !== 'admin'; }

  async function renderDirectory() {
    const params = new URLSearchParams(location.search);
    content.innerHTML = `<div class="section-heading"><div><h2>Люди, с которыми есть о чём поговорить</h2><p>Выберите направление и найдите близкий вам профессиональный опыт.</p></div></div><form id="community-search" class="search-form" role="search"><label>Профессия или навык<input type="search" name="q" maxlength="100" value="${esc(params.get('q') || '')}" placeholder="Например, бухгалтерия"></label><label>Город<input type="search" name="city" maxlength="80" value="${esc(params.get('city') || '')}" placeholder="Например, Москва"></label><label>Интерес<select name="goal">${options(goals,params.get('goal'),'Все направления')}</select></label><button class="button primary" type="submit">Найти участников</button></form><div class="results-bar"><span id="people-count" role="status"></span><a href="/community">Сбросить поиск</a></div><div id="community-people"><div class="loading" role="status">Загружаем участников…</div></div><p class="help">В каталоге появляются только профили, добровольно отправленные на публикацию и прошедшие проверку содержания. Квалификация участников не подтверждается автоматически.</p>`;
    $('#community-search').addEventListener('submit', event => { event.preventDefault(); state.directoryPage=1; loadPeople(); });
    state.directoryPage = Math.max(1, Math.min(10000, Number.parseInt(params.get('page'),10) || 1));
    await loadPeople();
  }
  async function loadPeople() {
    const form = $('#community-search');
    const params = new URLSearchParams(new FormData(form)); params.set('page',String(state.directoryPage));
    for (const key of ['q','city','goal']) if (!params.get(key)?.trim()) params.delete(key);
    const request = ++state.directoryRequest;
    $('#community-people').setAttribute('aria-busy','true');
    try {
      const result = await api('/api/community/people?' + params);
      if (request !== state.directoryRequest) return;
      history.replaceState(null,'', '/community' + (params.toString() ? '?' + params : ''));
      $('#people-count').textContent = `Участников по вашему поиску: ${result.total}`;
      $('#community-people').innerHTML = result.people.length ? `<div class="people-grid">${result.people.map(person=>personCard(person)).join('')}</div>` + pager(result.page,result.has_more,'people-page') : empty('Новые связи начинаются с первого профиля', 'По этим условиям пока никого нет. Попробуйте другой запрос или расскажите о своём опыте.', '<div class="actions"><a href="/community/profile" class="button primary">Создать свой профиль</a><a href="/journal" class="button secondary">Почитать журнал</a></div>');
    } catch (error) { if(request === state.directoryRequest) $('#community-people').innerHTML = `<p class="notice error" role="alert">${esc(error.message)}</p><button class="button secondary" type="button" data-action="retry-people">Повторить загрузку</button>`; }
    finally { $('#community-people')?.removeAttribute('aria-busy'); }
  }

  function profileValues() { return Object.fromEntries(new FormData($('#professional-profile-form'))); }
  function updateProfilePreview() { $('#profile-preview-card').innerHTML = personCard(profileValues(),true); }
  function renderProfileForm(preserved = null) {
    const p = state.profile, values = preserved || p;
    const canSubmit = p.version > 0 && !['published','pending'].includes(p.status) && !preserved;
    content.innerHTML = `<div class="section-heading"><div><h1>Ваш опыт — вашими словами</h1><p>Создайте отдельную страницу для коллег, проектов и наставничества. Вы сами выбираете, что рассказывать о себе.</p></div><a class="button secondary compact" href="/community/connections">Мои связи →</a></div>
    <div class="profile-layout"><div class="panel"><div class="status-line" id="profile-status">${statusBadge(p.status,profileStates)}</div>${p.moderation_reason ? `<p class="notice warning">Комментарий модератора: ${esc(p.moderation_reason)}</p>` : ''}
    <form id="professional-profile-form" class="profile-form"><div class="form-grid"><div class="field"><label for="public-name">Публичное имя *</label><input id="public-name" name="public_name" maxlength="60" value="${esc(values.public_name)}" placeholder="Имя или профессиональный псевдоним"><p class="help">Не обязательно указывать полное имя.</p></div><div class="field"><label for="public-city">Город</label><input id="public-city" name="city" maxlength="80" value="${esc(values.city)}" placeholder="Например, Москва"></div></div>
    <div class="field"><label for="public-headline">Профессия и направление *</label><input id="public-headline" name="headline" maxlength="120" value="${esc(values.headline)}" placeholder="Бухгалтер · помогаю малому бизнесу"></div>
    <div class="field"><label for="public-goal">Что вам интересно</label><select id="public-goal" name="goal">${options(goals,values.goal || 'exchange')}</select></div>
    <div class="field"><label for="public-about">Чем можете быть полезны *</label><textarea id="public-about" name="about" maxlength="2000" rows="6" placeholder="Расскажите об опыте, задачах и знаниях, которыми готовы делиться.">${esc(values.about)}</textarea><p class="help">Для публикации — от 20 символов. Без телефона, email, ссылок и адреса проживания.</p></div>
    <div class="field"><label for="public-skills">Навыки и темы</label><textarea id="public-skills" name="skills" maxlength="400" rows="3" placeholder="Например: управленческий учёт, 1С, обучение коллег">${esc(values.skills)}</textarea><p class="help">Указывайте только свой опыт. Не добавляйте личные сведения других людей.</p></div>
    <div class="form-footer"><button id="save-professional-profile" class="button primary" type="submit">Сохранить черновик</button><p id="profile-save-state" class="save-state" role="status">${preserved ? 'Есть несохранённые изменения' : p.version ? 'Сохранённая версия профиля' : 'Данные появятся на сервере после сохранения'}</p></div></form>
    <section class="publication-panel" id="profile-publication"><h2>Публикация — отдельный шаг</h2><p class="help">Сохранение черновика не публикует профиль. Изменённый профиль нужно снова отправить на проверку.</p>
    ${p.status === 'published' ? `<p><a class="public-link" href="/people/${encodeURIComponent(p.public_id)}">Открыть мою публичную страницу →</a></p>` : ''}
    <label class="consent-label"><input type="checkbox" id="publish-consent"${canSubmit ? '' : ' disabled'}><span>Я разрешаю публиковать выбранное публичное имя, профессию, город, описание опыта, навыки и интерес. Их сможет прочитать любой посетитель. Я могу скрыть профиль и отозвать это разрешение.</span></label>
    <div class="actions"><button class="button primary" id="submit-profile-review" type="button" disabled>Отправить на проверку</button>${['pending','published'].includes(p.status) || p.consent_at ? '<button class="button secondary" id="withdraw-profile" type="button">Скрыть и отозвать согласие</button>' : ''}</div>
    <details class="publication-rules" id="publication-rules"><summary>Что будет опубликовано и как это отменить</summary><p>Публикуются только поля этой формы. Имя, email, телефон и резюме из вашего аккаунта сюда не переносятся. Перед отправкой проверьте описание и навыки: они тоже будут публичными.</p><p>После проверки профиль появится в сообществе и получит отдельную ссылку. Скрытие уберёт страницу и закроет возможность новых запросов. Уже начатые разговоры останутся в «Моих связях»; прекратить их можно блокировкой. Копии, которые ранее сделали другие люди, СТАЖНО удалить не сможет.</p></details>
    <p class="help">Тестовый запуск: для проверки используйте вымышленные сведения.</p></section></div>
    <aside class="panel profile-preview" id="profile-preview"><span class="eyebrow">ПРЕДПРОСМОТР</span><h2>Так вас увидят участники</h2><p class="help">Проверьте текст до публикации. Контакты из аккаунта здесь не отображаются.</p><div id="profile-preview-card">${personCard(values,true)}</div><p class="help">Ваша профессиональная страница не меняет резюме и настройки поиска работы.</p></aside></div>`;
    state.dirty = Boolean(preserved);
    const form = $('#professional-profile-form');
    const changed = () => { state.dirty = true; $('#profile-save-state').textContent='Есть несохранённые изменения'; $('#publish-consent').checked=false; $('#publish-consent').disabled=true; $('#submit-profile-review').disabled=true; updateProfilePreview(); };
    form.addEventListener('input',changed); form.addEventListener('change',changed);
    $('#publish-consent').addEventListener('change', event => { $('#submit-profile-review').disabled = !event.target.checked || state.dirty || !canSubmit; });
    form.addEventListener('submit', event => {
      event.preventDefault();
      const data = profileValues();
      const save = async () => {
        const result = await api('/api/community/profile',{method:'PUT',body:{...data,expected_version:p.version}});
        state.profile = result.profile; state.dirty=false; renderProfileForm(); notice('Черновик сохранён. Для публикации проверьте текст и отдельно отправьте профиль на проверку.');
      };
      if (p.status === 'published' || p.status === 'pending') {
        confirmAction('Сохранить новую версию?', 'Если текст изменился, текущая публикация или заявка на проверку будет снята. Новую версию можно отправить на проверку после сохранения.', 'Сохранить новую версию', () => busy(form.closest('.panel'),save));
      } else busy(form.closest('.panel'),save);
    });
    $('#submit-profile-review').addEventListener('click', () => {
      if (!$('#publish-consent').checked || state.dirty) return;
      const panel = $('#professional-profile-form').closest('.panel');
      busy(panel,async () => { const result=await api('/api/community/profile/submit',{method:'POST',body:{expected_version:p.version,publish_consent:true}}); state.profile=result.profile; renderProfileForm(); notice('Профиль отправлен на проверку. До решения модератора он доступен только вам.'); });
    });
    $('#withdraw-profile')?.addEventListener('click', () => confirmAction('Скрыть профессиональный профиль?', 'Страница и карточка исчезнут из сообщества, новые запросы станут недоступны. Уже начатые разговоры сохранятся. Введённые изменения останутся в форме.', 'Скрыть профиль', async () => {
      const draft = state.dirty ? profileValues() : null;
      const result=await api('/api/community/profile/publication',{method:'DELETE',body:{expected_version:p.version}}); state.profile=result.profile; renderProfileForm(draft); notice('Профиль скрыт. Разрешение на публикацию отозвано.');
    }));
  }
  async function renderProfile() {
    if (!state.user) return accountGate('Мой профессиональный профиль');
    if (state.user.role !== 'candidate') { content.innerHTML=empty('Профиль компании уже есть в вашем кабинете','Профессиональные страницы создают участники с аккаунтом соискателя. Как работодатель вы можете знакомиться с ними от имени компании.','<div class="actions"><a class="button primary" href="/community">Найти участников</a><a class="button secondary" href="/#account">Кабинет компании</a></div>'); return; }
    state.profile=(await api('/api/community/profile')).profile; renderProfileForm();
  }

  async function requestConnection() {
    if (!state.user) return loginDialog(requestConnection);
    if (state.user.role === 'admin') { notice('Администратор проверяет профили. Для знакомства используйте обычный аккаунт участника.','warning'); return; }
    if (state.user.role === 'candidate') {
      const own=(await api('/api/community/profile')).profile;
      if (own.public_id === document.body.dataset.personId) { notice('Это ваша профессиональная страница.'); return; }
      if (own.status !== 'published') { openDialog('Сначала представьтесь', '<p>Чтобы отправить запрос коллеге, опубликуйте свой профессиональный профиль. Так человек сможет понять, кто предлагает знакомство.</p><a class="button primary" href="/community/profile">Подготовить мой профиль</a>'); return; }
    }
    openDialog('Предложить профессиональное знакомство', `<p class="help">Участник сам решит, начинать ли разговор. Контакты из аккаунта не передаются.</p><form id="connection-request-form" class="dialog-form"><div class="field"><label for="connection-purpose">О чём хотите поговорить</label><select id="connection-purpose" name="purpose">${options(goals,'exchange')}</select></div><div class="field"><label for="connection-note">Коротко о предложении</label><textarea id="connection-note" name="note" maxlength="500" rows="4" placeholder="Расскажите, что вас заинтересовало и чем можете быть полезны."></textarea><p class="help">Без телефона, email и ссылок. Личная переписка откроется после согласия.</p></div><button class="button primary" type="submit">Отправить запрос</button></form>`);
    $('#connection-request-form').addEventListener('submit', event => {event.preventDefault(); const form=event.currentTarget; const data=Object.fromEntries(new FormData(form)); busy(form,async()=>{
      const result=await api('/api/community/connections',{method:'POST',body:{...data,public_id:document.body.dataset.personId}});
      dialogBusy=false; closeDialog(); notice(result.connection.status==='accepted' ? 'Вы уже знакомы. Разговор доступен в «Моих связях».' : 'Запрос отправлен. Ответ появится в «Моих связях».');
      $('#person-action-hint').innerHTML=`<a href="/community/connections?thread=${encodeURIComponent(result.connection.id)}">Открыть мои связи →</a>`;
    });});
  }
  function report(target) {
    if (!state.user) return loginDialog(()=>report(target));
    openDialog('Сообщить о проблеме', `<p class="help">Жалоба будет видна модератору. Другой участник не увидит, кто её отправил. Переписку можно дополнительно прекратить кнопкой блокировки.</p><form id="community-report-form" class="dialog-form"><div class="field"><label for="community-report-reason">Причина</label><select id="community-report-reason" name="reason">${options(reasons,'spam')}</select></div><div class="field"><label for="community-report-details">Что произошло</label><textarea id="community-report-details" name="details" rows="5" maxlength="1000" placeholder="Опишите проблему без лишних личных данных."></textarea></div><button class="button primary" type="submit">Отправить жалобу</button></form>`);
    $('#community-report-form').addEventListener('submit', event=>{event.preventDefault();const form=event.currentTarget;const data=Object.fromEntries(new FormData(form));busy(form,async()=>{await api('/api/community/reports',{method:'POST',body:{...target,...data}});dialogBusy=false;closeDialog();notice('Жалоба передана модератору. Спасибо, что помогаете сохранять безопасное общение.');});});
  }
  async function renderPerson() {
    $('#request-connection').addEventListener('click',()=>requestConnection().catch(error=>notice(error.message,'error')));
    $('#report-person').addEventListener('click',()=>report({public_id:document.body.dataset.personId}));
  }

  function connectionCard(c) {
    const other=c.counterpart;
    const title=other.public_id ? `<a href="/people/${encodeURIComponent(other.public_id)}">${esc(other.public_name)}</a>` : esc(other.public_name);
    return `<article class="panel connection-card${state.selected?.id===c.id?' selected':''}" data-connection-id="${esc(c.id)}"><span class="direction">${c.direction==='incoming'?'Вам предлагают знакомство':'Ваше предложение'}</span><h2>${title}</h2><p class="help">${esc(other.headline)}${other.role==='employer'?' · Работодатель':''}</p><div class="status-line">${statusBadge(c.status,connectionStates)}<span class="tag">${esc(goals[c.purpose])}</span></div>${c.note?`<p class="note">${esc(c.note)}</p>`:''}<div class="actions">${c.can_respond?`<button class="button primary" type="button" data-action="accept-connection" data-id="${esc(c.id)}">Принять знакомство</button><button class="button secondary" type="button" data-action="decline-connection" data-id="${esc(c.id)}">Отклонить</button>`:''}${c.can_cancel?`<button class="button secondary" type="button" data-action="cancel-connection" data-id="${esc(c.id)}">Отозвать запрос</button>`:''}<button class="button secondary" type="button" data-action="open-thread" data-id="${esc(c.id)}">${['accepted','blocked'].includes(c.status)?'Открыть переписку':'Подробности'}</button></div>${c.can_respond?'<p class="help">Принятие откроет переписку внутри СТАЖНО. Контакты из аккаунта останутся закрыты.</p>':''}</article>`;
  }
  async function renderConnections() {
    if (!state.user) return accountGate('Мои профессиональные связи');
    if (state.user.role==='admin') {content.innerHTML=empty('Модерация сообщества','Управляйте публичными профилями и рассматривайте жалобы.','<a class="button primary" href="/community/moderation">Перейти к модерации</a>');return;}
    content.innerHTML=`<div class="section-heading"><div><h1>Профессиональные связи</h1><p>Запросы на знакомство и ваши разговоры. Переписка доступна только участникам после принятия запроса.</p></div><a class="button secondary compact" href="/community">Найти коллег →</a></div><div class="connections-toolbar"><label class="help" for="connection-filter">Показать<select id="connection-filter">${options(connectionStates,state.connectionFilter,'Все знакомства')}</select></label><button class="button secondary compact" id="refresh-connections" type="button">Обновить</button></div><div class="connections-layout"><div><div class="connection-list" id="community-connections-list"></div><div id="connections-pager"></div></div><section id="community-thread" class="panel thread-panel"><div class="thread-empty"><p>Выберите знакомство слева,<br>чтобы увидеть подробности или переписку.</p></div></section></div>`;
    $('#connection-filter').addEventListener('change',event=>{state.connectionFilter=event.target.value;state.connectionPage=1;loadConnections().catch(error=>notice(error.message,'error'));});
    $('#refresh-connections').addEventListener('click',async()=>{try{await loadConnections();if(state.selected)await openThread(state.selected.id,{preserve:true});notice('Список обновлён.');}catch(error){notice(error.message,'error');}});
    await loadConnections();
    const thread=new URLSearchParams(location.search).get('thread'); if(thread && /^[a-f0-9-]{20,64}$/i.test(thread)) await openThread(thread);
  }
  async function loadConnections() {
    const params=new URLSearchParams({page:String(state.connectionPage)});if(state.connectionFilter)params.set('status',state.connectionFilter);
    const result=await api('/api/community/connections?'+params);state.connections=result.connections;
    $('#community-connections-list').innerHTML=result.connections.length?result.connections.map(connectionCard).join(''):empty('Здесь начнутся ваши знакомства','Выберите участника сообщества и предложите обсудить общий профессиональный интерес.','<a class="button primary" href="/community">Посмотреть участников</a>');
    $('#connections-pager').innerHTML=result.connections.length?pager(result.page,result.has_more,'connections-page'):'';
  }
  function messageMarkup(message) {return `<article class="message${message.mine?' mine':''}" data-message-id="${esc(message.id)}"><span class="message-author">${message.mine?'Вы':esc(state.selected?.counterpart.public_name || 'Участник')}</span><p>${esc(message.body)}</p><time>${esc(date(message.created_at))}</time></article>`;}
  async function openThread(id, {preserve=false}={}) {
    const currentForm = $('#community-message-form');
    if (currentForm && state.busy.has(currentForm)) { notice('Дождитесь результата отправки. Сообщение пока остаётся в этой вкладке.'); return; }
    if (state.selected?.id===id) preserve=true;
    if (state.messageDirty && state.selected?.id!==id && !window.confirm('В сообщении есть несохранённый текст. Перейти к другому разговору?')) return;
    const draft=preserve?$('#community-message-form textarea')?.value:null;
    const request=++state.threadRequest;
    const result=await api('/api/community/connections/'+encodeURIComponent(id));
    if(request!==state.threadRequest)return;
    state.selected=result.connection;const c=state.selected;
    if(!preserve){state.messageDirty=false;state.messageKey=null;state.messageBody=null;}
    history.replaceState(null,'','/community/connections?thread='+encodeURIComponent(id));
    $('#community-thread').innerHTML=`<div class="thread-heading"><span class="eyebrow">${esc(goals[c.purpose])}</span><h2>${esc(c.counterpart.public_name)}</h2>${statusBadge(c.status,connectionStates)}<div class="actions"><button class="text-button" type="button" data-action="report-connection" data-id="${esc(id)}">Сообщить о проблеме</button>${c.can_block?`<button class="text-button" type="button" data-action="block-connection" data-id="${esc(id)}">Прекратить общение</button>`:''}<button class="text-button" type="button" data-action="refresh-thread" data-id="${esc(id)}">Обновить разговор</button></div></div>
    ${['accepted','blocked'].includes(c.status)?`<div class="thread-body"><div class="older-control"><button class="button secondary compact" id="load-older-messages" type="button" hidden>Более ранние сообщения</button></div><div id="thread-history" class="thread-history" role="log" aria-label="Переписка"><p class="help">Загружаем сообщения…</p></div></div>`:`<div class="thread-empty"><p>${c.status==='pending'?'Переписка откроется после принятия запроса.':'Этот запрос завершён. Переписка не открывалась.'}</p></div>`}
    ${c.can_message?`<form id="community-message-form" class="message-form"><label for="community-message">Ваше сообщение</label><textarea id="community-message" name="body" rows="4" maxlength="2000" required placeholder="Напишите о задаче или опыте, который хотите обсудить.">${esc(draft || '')}</textarea><div class="actions"><p class="help">Не отправляйте пароли, коды и платёжные данные.</p><button class="button primary" type="submit">Отправить</button></div></form>`:'<p class="help thread-heading">Отправка сообщений недоступна. Контакты из аккаунта не раскрываются.</p>'}`;
    document.querySelectorAll('[data-connection-id]').forEach(node=>node.classList.toggle('selected',node.dataset.connectionId===id));
    if (['accepted','blocked'].includes(c.status)) await loadMessages(id,false,request);
    $('#load-older-messages')?.addEventListener('click',()=>loadMessages(id,true,request).catch(error=>notice(error.message,'error')));
    const form=$('#community-message-form');
    if(form){
      form.addEventListener('input',()=>{state.messageDirty=Boolean(form.elements.body.value.trim());});
      form.addEventListener('submit',event=>{event.preventDefault();const body=form.elements.body.value.trim();if(!body)return;
        if(!state.messageKey || state.messageBody!==body){state.messageKey=crypto.randomUUID();state.messageBody=body;}
        const clientKey=state.messageKey;
        busy(form,async()=>{await api('/api/community/connections/'+encodeURIComponent(id)+'/messages',{method:'POST',body:{body,client_key:clientKey}});form.elements.body.value='';if(request===state.threadRequest&&state.selected?.id===id){state.messageDirty=false;state.messageKey=null;state.messageBody=null;}$('.form-error',form)?.remove();await loadMessages(id,false,request);});
      });
    }
  }
  async function loadMessages(id,older,request) {
    if(request!==state.threadRequest)return;
    const button=$('#load-older-messages');if(button)button.disabled=true;
    try{
      const params=older&&state.nextBefore?'?before='+encodeURIComponent(state.nextBefore):'';
      const result=await api('/api/community/connections/'+encodeURIComponent(id)+'/messages'+params);
      if(request!==state.threadRequest)return;
      const historyNode=$('#thread-history');
      const markup=result.messages.map(messageMarkup).join('');
      if(older)historyNode.insertAdjacentHTML('afterbegin',markup);else historyNode.innerHTML=markup||'<p class="help">Знакомство принято. Можно начать разговор.</p>';
      state.nextBefore=result.next_before;
      if(button){button.hidden=!result.has_more;button.disabled=false;}
      if(!older){const body=$('.thread-body');body.scrollTop=body.scrollHeight;}
    }catch(error){if(button)button.disabled=false;throw error;}
  }
  async function connectionAction(id,action) {
    const route=action==='accept-connection'||action==='decline-connection'?'respond':action==='cancel-connection'?'cancel':'block';
    const body=route==='respond'?{decision:action==='accept-connection'?'accept':'decline'}:{};
    const result=await api('/api/community/connections/'+encodeURIComponent(id)+'/'+route,{method:'POST',body});await loadConnections();await openThread(result.connection.id);notice(action==='accept-connection'?'Знакомство принято. Теперь можно общаться внутри СТАЖНО.':action==='block-connection'?'Общение прекращено. Новые сообщения и запросы между вами недоступны.':'Решение сохранено.');
  }

  async function renderModeration() {
    if(!state.user)return accountGate('Модерация сообщества');
    if(state.user.role!=='admin'){content.innerHTML=empty('Раздел доступен модератору','Вы можете управлять своим профилем и отправлять жалобы из сообщества.','<a class="button primary" href="/community">К участникам</a>');return;}
    content.innerHTML=`<div class="section-heading"><div><h1>Модерация сообщества</h1><p>Перед публикацией проверьте отсутствие контактов, личных данных других людей, спама и недостоверных обещаний. Одобрение относится только к текущей версии профиля.</p></div></div><div class="connections-toolbar"><label for="moderation-filter">Профили<select id="moderation-filter">${options({pending:'Ожидают проверки',published:'Опубликованы',rejected:'Отклонены',hidden:'Скрыты'},'pending')}</select></label><button class="button secondary compact" type="button" data-action="reload-moderation">Обновить очередь</button></div><div id="moderation-list" class="moderation-grid"></div><div id="moderation-pager"></div><section class="section-divider"><h2>Жалобы участников</h2><div id="moderation-reports" class="moderation-grid"></div><div id="reports-pager"></div><p class="help">Жалобы содержат только отправленные участниками сведения. Доступ ко всей переписке здесь не открывается. При необходимости профиль можно скрыть в разделе опубликованных профилей.</p></section>`;
    $('#moderation-filter').addEventListener('change',()=>{state.moderationPage=1;loadModeration().catch(error=>notice(error.message,'error'));});
    await Promise.all([loadModeration(),loadReports()]);
  }
  async function loadModeration() {
    const filter=$('#moderation-filter').value;
    const result=await api('/api/admin/community/profiles?'+new URLSearchParams({status:filter,page:String(state.moderationPage)}));
    $('#moderation-list').innerHTML=result.profiles.length?result.profiles.map(p=>`<article class="panel moderation-card" data-profile-id="${esc(p.public_id)}"><div class="status-line">${statusBadge(p.status,profileStates)}<span class="help">Версия ${p.version}</span></div><h2>${esc(p.public_name)}</h2><p><strong>${esc(p.headline)}</strong></p><p class="help">${esc(p.city)} · ${esc(goals[p.goal])}</p><p class="multiline">${esc(p.about)}</p><p class="help multiline">Навыки: ${esc(p.skills || 'не указаны')}</p>${p.moderation_reason?`<p class="reason">${esc(p.moderation_reason)}</p>`:''}<div class="actions">${p.status==='pending'?`<button class="button primary compact" type="button" data-action="approve-profile" data-id="${esc(p.public_id)}" data-version="${p.version}">Одобрить</button><button class="button secondary compact" type="button" data-action="reject-profile" data-id="${esc(p.public_id)}" data-version="${p.version}">Вернуть на доработку</button>`:''}${p.status==='published'?`<a class="button secondary compact" href="/people/${encodeURIComponent(p.public_id)}">Открыть страницу</a><button class="button danger compact" type="button" data-action="hide-profile" data-id="${esc(p.public_id)}" data-version="${p.version}">Скрыть профиль</button>`:''}</div></article>`).join(''):'<p class="notice">В этой очереди пока нет профилей.</p>';
    $('#moderation-pager').innerHTML=result.profiles.length?pager(result.page,result.has_more,'moderation-page'):'';
  }
  async function loadReports() {
    const result=await api('/api/admin/community/reports?'+new URLSearchParams({status:'new',page:String(state.reportPage)}));
    $('#moderation-reports').innerHTML=result.reports.length?result.reports.map(r=>`<article class="panel moderation-card"><span class="eyebrow">${r.public_id?'ЖАЛОБА НА ПРОФИЛЬ':'ЖАЛОБА НА ОБЩЕНИЕ'}</span><h3>${esc(reasons[r.reason])}</h3><p class="multiline">${esc(r.details || 'Без дополнительного описания')}</p><p class="help">${esc(date(r.created_at))}</p>${r.public_id?`<a href="/people/${encodeURIComponent(r.public_id)}">Открыть публичный профиль</a>`:'<p class="help">Идентификатор разговора: '+esc(r.connection_id)+'</p>'}<div class="actions"><button class="button primary compact" type="button" data-action="resolve-report" data-id="${esc(r.id)}">Рассмотрено</button><button class="button secondary compact" type="button" data-action="dismiss-report" data-id="${esc(r.id)}">Отклонить жалобу</button></div></article>`).join(''):'<p class="notice">Новых жалоб нет.</p>';
    $('#reports-pager').innerHTML=result.reports.length?pager(result.page,result.has_more,'reports-page'):'';
  }
  function moderateProfile(button) {
    const decision=button.dataset.action==='approve-profile'?'approve':button.dataset.action==='reject-profile'?'reject':'hide';
    const perform=async(reason='')=>{await api('/api/admin/community/profiles/'+encodeURIComponent(button.dataset.id),{method:'PATCH',body:{decision,expected_version:Number(button.dataset.version),reason}});await loadModeration();notice('Решение модерации сохранено.');};
    if(decision==='approve'){confirmAction('Опубликовать проверенный профиль?','Подтвердите, что вы прочитали все поля этой версии. Профиль станет доступен посетителям сообщества.','Одобрить публикацию',()=>perform());return;}
    openDialog(decision==='reject'?'Что нужно исправить?':'Почему профиль скрывается?',`<form id="moderation-decision-form" class="dialog-form"><div class="field"><label for="moderation-reason">Комментарий участнику</label><textarea id="moderation-reason" name="reason" rows="4" maxlength="500" minlength="3" required></textarea></div><button type="submit" class="button primary">Сохранить решение</button></form>`);
    $('#moderation-decision-form').addEventListener('submit',event=>{event.preventDefault();const form=event.currentTarget;const reason=form.elements.reason.value;busy(form,async()=>{await perform(reason);dialogBusy=false;closeDialog();});});
  }

  async function handleAction(event) {
    const button=event.target.closest('[data-action]');if(!button||button.disabled)return;
    const {action,id}=button.dataset;
    try{
      if(action==='people-page'){state.directoryPage=Number(button.dataset.page);await loadPeople();}
      else if(action==='retry-people')await loadPeople();
      else if(action==='connections-page'){state.connectionPage=Number(button.dataset.page);await loadConnections();}
      else if(action==='open-thread')await openThread(id);
      else if(action==='refresh-thread')await openThread(id,{preserve:true});
      else if(action==='accept-connection')await busy(button.closest('article'),()=>connectionAction(id,action));
      else if(['decline-connection','cancel-connection','block-connection'].includes(action))confirmAction(action==='block-connection'?'Прекратить общение?':'Завершить этот запрос?',action==='block-connection'?'Вы больше не сможете отправлять друг другу сообщения и новые запросы. История разговора сохранится. Блокировка в этом выпуске необратима.':'Запрос будет завершён. Отправить повторное приглашение этому участнику будет нельзя.',action==='block-connection'?'Прекратить общение':'Подтвердить',()=>connectionAction(id,action));
      else if(action==='report-connection')report({connection_id:id});
      else if(['approve-profile','reject-profile','hide-profile'].includes(action))moderateProfile(button);
      else if(action==='reload-moderation')await Promise.all([loadModeration(),loadReports()]);
      else if(action==='moderation-page'){state.moderationPage=Number(button.dataset.page);await loadModeration();}
      else if(action==='reports-page'){state.reportPage=Number(button.dataset.page);await loadReports();}
      else if(['resolve-report','dismiss-report'].includes(action))await busy(button.closest('article'),async()=>{await api('/api/admin/community/reports/'+encodeURIComponent(id),{method:'PATCH',body:{status:action==='resolve-report'?'resolved':'dismissed'}});await loadReports();notice('Статус жалобы сохранён.');});
      else if(action==='retry-community')await renderMode();
    }catch(error){notice(error.message,'error');}
  }
  async function renderMode() {
    try{
      if(mode==='directory')await renderDirectory();
      else if(mode==='profile')await renderProfile();
      else if(mode==='connections')await renderConnections();
      else if(mode==='moderation')await renderModeration();
      else if(mode==='person')await renderPerson();
    }catch(error){content.innerHTML=`<section class="panel"><h1>Не удалось загрузить раздел</h1><p class="notice error" role="alert">${esc(error.message)}</p><button class="button secondary" type="button" data-action="retry-community">Повторить загрузку</button></section>`;}
  }
  function readingMode() {
    const button=$('#reading-mode-toggle'),key='stazhno-large-text';
    const apply=value=>{document.body.classList.toggle('comfortable-view',value);button.setAttribute('aria-pressed',String(value));button.setAttribute('aria-label',value?'Выключить крупный текст':'Включить крупный текст');};
    try{apply(localStorage.getItem(key)==='yes');}catch{apply(false);}
    button.addEventListener('click',()=>{const enabled=!document.body.classList.contains('comfortable-view');apply(enabled);try{localStorage.setItem(key,enabled?'yes':'no');}catch{/* Reading preference only. */}});
  }
  async function boot() {
    readingMode();document.addEventListener('click',handleAction);
    $('#close-community-dialog').addEventListener('click',closeDialog);
    dialog.addEventListener('click',event=>{if(event.target.closest('[data-close-dialog]'))closeDialog();});
    dialog.addEventListener('cancel',event=>{if(dialogBusy)event.preventDefault();});
    window.addEventListener('beforeunload',event=>{if(state.dirty||state.messageDirty){event.preventDefault();event.returnValue='';}});
    try{state.user=(await api('/api/me')).user;}catch(error){if(error.status!==401){notice(error.message,'error');if(!['directory','person'].includes(mode)){content.innerHTML='<section class="panel"><h1>Аккаунт временно недоступен</h1><p>Обновите страницу, когда соединение восстановится.</p><button class="button secondary" type="button" id="retry-account">Повторить</button></section>';$('#retry-account').addEventListener('click',()=>location.reload());return;}}}
    updateIdentity();await renderMode();
  }
  document.addEventListener('DOMContentLoaded',boot);
})();
