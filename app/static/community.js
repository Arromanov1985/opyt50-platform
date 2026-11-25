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
  const state = {user:null, profile:null, dirty:false, messageDirty:false, connections:[], connectionPage:1, connectionFilter:'', connectionListRequest:0, readThrough:null, selected:null, messageKey:null, messageBody:null, nextBefore:null, directoryPage:1, directoryRequest:0, threadSelectionRequest:0, threadRequest:0, messageLoadRequest:0, moderationPage:1, reportPage:1, busy:new WeakSet(), feedPage:1, feedMinePage:1, feedReviewPage:1, feedRequest:0, feedThreadRequest:0, feedReviewRequest:0, feedThreadId:null, feedThreadPage:1, feedCanPublish:false, feedDirty:false, feedCommentDirty:false};
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
    return `<article class="panel connection-card${state.selected?.id===c.id?' selected':''}" data-connection-id="${esc(c.id)}"><span class="direction">${c.direction==='incoming'?'Вам предлагают знакомство':'Ваше предложение'}</span><h2>${title}</h2><p class="help">${esc(other.headline)}${other.role==='employer'?' · Работодатель':''}</p><div class="status-line">${statusBadge(c.status,connectionStates)}<span class="tag">${esc(goals[c.purpose])}</span>${Number(c.unread_count)>0?`<span class="community-unread">Непрочитанных: ${Number(c.unread_count)}</span>`:''}</div>${c.note?`<p class="note">${esc(c.note)}</p>`:''}<div class="actions">${c.can_respond?`<button class="button primary" type="button" data-action="accept-connection" data-id="${esc(c.id)}">Принять знакомство</button><button class="button secondary" type="button" data-action="decline-connection" data-id="${esc(c.id)}">Отклонить</button>`:''}${c.can_cancel?`<button class="button secondary" type="button" data-action="cancel-connection" data-id="${esc(c.id)}">Отозвать запрос</button>`:''}<button class="button secondary" type="button" data-action="open-thread" data-id="${esc(c.id)}">${['accepted','blocked'].includes(c.status)?'Открыть переписку':'Подробности'}</button></div>${c.can_respond?'<p class="help">Принятие откроет переписку внутри СТАЖНО. Контакты из аккаунта останутся закрыты.</p>':''}</article>`;
  }
  async function renderConnections() {
    if (!state.user) return accountGate('Мои профессиональные связи');
    if (state.user.role==='admin') {content.innerHTML=empty('Модерация сообщества','Управляйте публичными профилями и рассматривайте жалобы.','<a class="button primary" href="/community/moderation">Перейти к модерации</a>');return;}
    if(new URLSearchParams(location.search).get('attention')==='1') state.connectionFilter='attention';
    content.innerHTML=`<div class="section-heading"><div><h1>Профессиональные связи</h1><p>Запросы на знакомство и ваши разговоры. Переписка доступна только участникам после принятия запроса.</p></div><a class="button secondary compact" href="/community">Найти коллег →</a></div><section class="panel community-attention" id="community-attention" aria-label="Активность сообщества" role="status"><p class="help">Проверяем новые сообщения и запросы…</p></section><div class="connections-toolbar"><label class="help" for="connection-filter">Показать<select id="connection-filter">${options({attention:'Требуют внимания',...connectionStates},state.connectionFilter,'Все знакомства')}</select></label><button class="button secondary compact" id="refresh-connections" type="button">Обновить</button></div><div class="connections-layout"><div><div class="connection-list" id="community-connections-list"></div><div id="connections-pager"></div></div><section id="community-thread" class="panel thread-panel"><div class="thread-empty"><p>Выберите знакомство слева,<br>чтобы увидеть подробности или переписку.</p></div></section></div>`;
    $('#connection-filter').addEventListener('change',event=>{state.connectionFilter=event.target.value;state.connectionPage=1;loadConnections().catch(error=>notice(error.message,'error'));});
    $('#refresh-connections').addEventListener('click',async()=>{try{await loadConnections();if(state.selected)await openThread(state.selected.id,{preserve:true});notice('Список обновлён.');}catch(error){notice(error.message,'error');}});
    await loadConnections();
    const thread=new URLSearchParams(location.search).get('thread'); if(thread && /^[a-f0-9-]{20,64}$/i.test(thread)) await openThread(thread);
  }
  async function loadConnections() {
    const request=++state.connectionListRequest;
    const params=new URLSearchParams({page:String(state.connectionPage)});
    if(state.connectionFilter==='attention')params.set('attention','true');
    else if(state.connectionFilter)params.set('status',state.connectionFilter);
    const [result,activity]=await Promise.all([
      api('/api/community/connections?'+params),
      api('/api/community/activity').catch(()=>null)
    ]);
    if(request!==state.connectionListRequest)return;
    if(!result.connections.length && state.connectionPage>1 && result.total>0){
      state.connectionPage=1;return loadConnections();
    }
    state.connections=result.connections;
    $('#community-attention').innerHTML=activity
      ? activity.restricted
        ? '<p class="help">Новые действия приостановлены по обращению о персональных данных. История разговоров доступна.</p>'
        : `<div class="community-attention-metrics"><div><strong>${Number(activity.pending_requests||0)}</strong><span>Запросы на знакомство</span></div><div><strong>${Number(activity.unread_messages||0)}</strong><span>Непрочитанные сообщения</span><small>В разговорах: ${Number(activity.unread_threads||0)}</small></div></div><button class="button secondary compact" type="button" data-action="attention-connections">Требуют внимания</button>`
      : '<p class="help">Счётчики временно недоступны. Нажмите «Обновить».</p>';
    $('#community-connections-list').innerHTML=result.connections.length
      ? result.connections.map(connectionCard).join('')
      : state.connectionFilter==='attention'
        ? empty('Новых действий нет','Когда придёт запрос или новое сообщение, разговор появится здесь.','<button class="button secondary" type="button" data-action="all-connections">Все знакомства</button>')
        : state.connectionFilter
          ? empty('Нет знакомств с таким статусом','Выберите другой фильтр.','<button class="button secondary" type="button" data-action="all-connections">Все знакомства</button>')
          : empty('Здесь начнутся ваши знакомства','Выберите участника сообщества и предложите обсудить общий профессиональный интерес.','<a class="button primary" href="/community">Посмотреть участников</a>');
    $('#connections-pager').innerHTML=result.connections.length?pager(result.page,result.has_more,'connections-page'):'';
  }
  function messageMarkup(message) {return `<article class="message${message.mine?' mine':''}" data-message-id="${esc(message.id)}"><span class="message-author">${message.mine?'Вы':esc(state.selected?.counterpart.public_name || 'Участник')}</span><p>${esc(message.body)}</p><time>${esc(date(message.created_at))}</time></article>`;}
  async function openThread(id, {preserve=false}={}) {
    const currentForm = $('#community-message-form');
    if (currentForm && state.busy.has(currentForm)) { notice('Дождитесь результата отправки. Сообщение пока остаётся в этой вкладке.'); return; }
    // Keep the visible composer's token valid until a replacement is ready.
    // Failed detail requests must not detach the current conversation's state.
    const selectionRequest=++state.threadSelectionRequest;
    let result;
    try { result=await api('/api/community/connections/'+encodeURIComponent(id)); }
    catch (error) { if(selectionRequest===state.threadSelectionRequest)throw error;return; }
    if(selectionRequest!==state.threadSelectionRequest)return;
    const latestForm = $('#community-message-form');
    if (latestForm && state.busy.has(latestForm)) { notice('Дождитесь результата отправки. Сообщение пока остаётся в этой вкладке.'); return; }
    preserve=state.selected?.id===id;
    if (state.messageDirty && !preserve && !window.confirm('В сообщении есть несохранённый текст. Перейти к другому разговору?')) return;
    const draft=preserve?$('#community-message-form textarea')?.value:null;
    const request=++state.threadRequest;
    state.selected=result.connection;state.readThrough=null;const c=state.selected;
    if(!preserve){state.messageDirty=false;state.messageKey=null;state.messageBody=null;}
    history.replaceState(null,'','/community/connections?thread='+encodeURIComponent(id));
    $('#community-thread').innerHTML=`<div class="thread-heading"><span class="eyebrow">${esc(goals[c.purpose])}</span><h2>${esc(c.counterpart.public_name)}</h2>${statusBadge(c.status,connectionStates)}<div class="actions"><button class="text-button" type="button" data-action="report-connection" data-id="${esc(id)}">Сообщить о проблеме</button>${c.can_block?`<button class="text-button" type="button" data-action="block-connection" data-id="${esc(id)}">Прекратить общение</button>`:''}<button class="text-button" type="button" data-action="refresh-thread" data-id="${esc(id)}">Обновить разговор</button></div>${c.can_message?`<button class="button secondary compact community-mark-read" id="community-mark-read" type="button" data-action="mark-thread-read" data-id="${esc(id)}" hidden>Отметить разговор прочитанным</button><p class="help" id="community-read-hint" hidden>Отметка относится ко всей истории до последнего показанного сообщения. Она видна только вам.</p>`:''}</div>
    ${['accepted','blocked'].includes(c.status)?`<div class="thread-body"><div class="older-control"><button class="button secondary compact" id="load-older-messages" type="button" hidden>Более ранние сообщения</button></div><div id="thread-history" class="thread-history" role="log" aria-label="Переписка"><p class="help">Загружаем сообщения…</p></div></div>`:`<div class="thread-empty"><p>${c.status==='pending'?'Переписка откроется после принятия запроса.':'Этот запрос завершён. Переписка не открывалась.'}</p></div>`}
    ${c.can_message?`<form id="community-message-form" class="message-form" method="post"><label for="community-message">Ваше сообщение</label><textarea id="community-message" name="body" rows="4" maxlength="2000" required placeholder="Напишите о задаче или опыте, который хотите обсудить.">${esc(draft || '')}</textarea><div class="actions"><p class="help">Не отправляйте пароли, коды и платёжные данные.</p><button class="button primary" type="submit">Отправить</button></div></form>`:'<p class="help thread-heading">Отправка сообщений недоступна. Контакты из аккаунта не раскрываются.</p>'}`;
    document.querySelectorAll('[data-connection-id]').forEach(node=>node.classList.toggle('selected',node.dataset.connectionId===id));
    // Bind the composer synchronously before loading history. A slow or failed
    // GET must never leave a visible form with a native navigation submit.
    $('#load-older-messages')?.addEventListener('click',()=>loadMessages(id,true,request).catch(error=>notice(error.message,'error')));
    const form=$('#community-message-form');
    if(form){
      form.addEventListener('input',()=>{state.messageDirty=Boolean(form.elements.body.value.trim());});
      form.addEventListener('submit',event=>{event.preventDefault();const body=form.elements.body.value.trim();if(!body)return;
        if(!state.messageKey || state.messageBody!==body){state.messageKey=crypto.randomUUID();state.messageBody=body;}
        const clientKey=state.messageKey;
        busy(form,async()=>{
          await api('/api/community/connections/'+encodeURIComponent(id)+'/messages',{method:'POST',body:{body,client_key:clientKey}});
          form.elements.body.value='';
          if(request===state.threadRequest&&state.selected?.id===id){state.messageDirty=false;state.messageKey=null;state.messageBody=null;notice('Сообщение отправлено.');}
          $('.form-error',form)?.remove();
          try { await loadMessages(id,false,request); }
          catch { if(request===state.threadRequest&&state.selected?.id===id)notice('Сообщение отправлено, но не удалось обновить переписку. Нажмите «Обновить разговор».','warning'); }
        });
      });
    }
    if (['accepted','blocked'].includes(c.status)) {
      try { await loadMessages(id,false,request); }
      catch (error) { if (request===state.threadRequest) notice(error.message,'error'); }
    }
  }
  async function loadMessages(id,older,request) {
    if(request!==state.threadRequest)return;
    const loadRequest=++state.messageLoadRequest;
    const button=$('#load-older-messages');if(button)button.disabled=true;
    try{
      const params=older&&state.nextBefore?'?before='+encodeURIComponent(state.nextBefore):'';
      const result=await api('/api/community/connections/'+encodeURIComponent(id)+'/messages'+params);
      if(request!==state.threadRequest || loadRequest!==state.messageLoadRequest)return;
      const historyNode=$('#thread-history');
      const markup=result.messages.map(messageMarkup).join('');
      if(older)historyNode.insertAdjacentHTML('afterbegin',markup);else historyNode.innerHTML=markup||'<p class="help">Знакомство принято. Можно начать разговор.</p>';
      state.nextBefore=result.next_before;
      if(button){button.hidden=!result.has_more;button.disabled=false;}
      if(!older){
        state.readThrough=result.messages.at(-1)?.id||null;
        const body=$('.thread-body');body.scrollTop=body.scrollHeight;
      }
      const mark=$('#community-mark-read');
      if(mark){
        mark.hidden=!(state.readThrough && Number(result.unread_count)>0);
        $('#community-read-hint').hidden=mark.hidden;
      }
    }catch(error){if(request!==state.threadRequest || loadRequest!==state.messageLoadRequest)return;if(button)button.disabled=false;throw error;}
  }
  async function markThreadRead(button,id) {
    const through=state.readThrough, request=state.threadRequest;
    if(state.selected?.id!==id || !through)return;
    button.disabled=true;
    try {
      const result=await api('/api/community/connections/'+encodeURIComponent(id)+'/read',
        {method:'POST',body:{through_message_id:through}});
      if(request!==state.threadRequest || state.selected?.id!==id)return;
      state.selected.unread_count=Number(result.unread_count||0);
      button.hidden=true;
      const hint=$('#community-read-hint');if(hint)hint.hidden=true;
      notice(result.unread_count?'История отмечена до последнего показанного сообщения. Есть новые сообщения — обновите разговор.':'Разговор отмечен прочитанным.');
      try{await loadConnections();}
      catch{if(request===state.threadRequest)notice('Отметка сохранена, но не удалось обновить список. Нажмите «Обновить».','warning');}
    }finally{button.disabled=false;}
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


  const feedKinds={experience:'Опыт и полезные советы',question:'Профессиональный вопрос',projects:'Совместные проекты',mentoring:'Наставничество',comment:'Комментарий'};
  const feedCategories=Object.fromEntries(Object.entries(feedKinds).filter(([key])=>key!=='comment'));
  const feedStates={pending:'На проверке',published:'Одобрено',rejected:'Не опубликовано',hidden:'Скрыто'};
  function feedForm(comment=false) {
    const id=comment?'feed-comment-form':'feed-compose-form';
    return '<form class="feed-form" id="'+id+'"><h2>'+(comment?'Добавить комментарий':'Поделиться опытом')+'</h2>'+
      (comment?'':'<div class="field"><label for="feed-kind">Тема</label><select name="kind" id="feed-kind">'+options(feedCategories,'experience')+'</select></div><div class="field"><label for="feed-title">Заголовок</label><input name="title" id="feed-title" maxlength="140" required placeholder="О чём хотите рассказать?"></div>')+
      '<div class="field"><label for="'+id+'-body">'+(comment?'Ваш ответ':'Текст публикации')+'</label><textarea name="body" id="'+id+'-body" rows="'+(comment?'4':'6')+'" maxlength="'+(comment?'1000':'2400')+'" required placeholder="Расскажите по делу, без контактов и ссылок"></textarea></div>'+
      '<label class="feed-consent"><input name="publish_consent" type="checkbox" required> Согласен на показ этого текста другим участникам после проверки модератором. Не размещаю чужие персональные данные.</label>'+
      '<p class="help">Текст не появится в ленте до одобрения. Его можно скрыть в разделе «Мои публикации и комментарии».</p><button class="button primary" type="submit">Отправить на проверку</button></form>';
  }
  function feedCard(entry,{mine=false,admin=false,comment=false}={}) {
    const id=esc(entry.id), heading=entry.title?'<h2>'+esc(entry.title)+'</h2>':'';
    const author=entry.public_id?'<a href="/people/'+encodeURIComponent(entry.public_id)+'">'+esc(entry.public_name)+'</a> <span class="help">'+esc(entry.headline||'')+'</span>':'';
    const reviewContext=admin&&entry.parent_id?'<p class="help">Обсуждение: '+esc(entry.parent_title||'Недоступно')+'</p><details><summary>Текст исходной публикации</summary><p class="multiline">'+esc(entry.parent_body||'')+'</p></details>':'';
    let actions='';
    if(mine&&entry.status!=='hidden')actions='<button class="button secondary compact" type="button" data-action="withdraw-feed" data-id="'+id+'" data-version="'+Number(entry.version)+'">Скрыть</button>';
    if(admin&&entry.status==='pending')actions='<button class="button primary compact" type="button" data-action="approve-feed" data-id="'+id+'" data-version="'+Number(entry.version)+'">Одобрить</button> <button class="button secondary compact" type="button" data-action="reject-feed" data-id="'+id+'" data-version="'+Number(entry.version)+'">Отклонить</button>';
    if(admin&&entry.status==='published')actions='<button class="button secondary compact" type="button" data-action="hide-feed" data-id="'+id+'" data-version="'+Number(entry.version)+'">Скрыть</button>';
    if(!mine&&!admin&&!comment)actions='<button class="button secondary" type="button" data-action="open-feed-thread" data-id="'+id+'">Читать обсуждение</button>';
    return '<article class="panel feed-card" data-feed-id="'+id+'"><div class="feed-meta"><span class="tag">'+esc(feedKinds[entry.kind]||'Публикация')+'</span>'+((mine||admin)?statusBadge(entry.status,feedStates):'')+'<time>'+esc(date(entry.published_at||entry.created_at))+'</time></div>'+heading+(author?'<p class="feed-author">'+author+'</p>':'')+reviewContext+'<p class="multiline feed-body">'+esc(entry.body)+'</p>'+((mine||admin)&&entry.moderation_reason?'<p class="help">Причина: '+esc(entry.moderation_reason)+'</p>':'')+(actions?'<div class="actions">'+actions+'</div>':'')+'</article>';
  }
  function bindFeedForm(form,comment=false) {
    const dirtyKey=comment?'feedCommentDirty':'feedDirty';
    form.addEventListener('input',()=>{state[dirtyKey]=Boolean(form.elements.body.value.trim()||(!comment&&form.elements.title.value.trim()));});
    form.addEventListener('submit',event=>{
      event.preventDefault();
      const fields=Object.fromEntries(new FormData(form));
      const body={kind:comment?'comment':fields.kind,title:comment?'':fields.title,body:fields.body,parent_id:comment?state.feedThreadId:null,publish_consent:fields.publish_consent==='on'};
      const fingerprint=JSON.stringify(body);
      if(form.feedFingerprint!==fingerprint){form.feedFingerprint=fingerprint;form.feedKey=crypto.randomUUID();}
      body.client_key=form.feedKey;
      busy(form,async()=>{
        await api('/api/community/feed',{method:'POST',body});
        form.reset();form.feedFingerprint=null;form.feedKey=null;state[dirtyKey]=false;
        notice('Текст принят на проверку. Он ещё не опубликован.');
        state.feedMinePage=1;
        try{await loadFeedMine();}catch(error){notice('Текст принят на проверку. Список пока не обновился: '+error.message,'error');}
      });
    });
  }
  function drawFeedMine(result) {
    $('#feed-mine-list').innerHTML=result.entries.length?result.entries.map(entry=>feedCard(entry,{mine:true})).join('')+pager(result.page,result.has_more,'feed-mine-page'):empty('Пока нет ваших публикаций','Отправьте первый текст на проверку.');
  }
  async function loadFeedMine() {
    if(state.user?.role!=='candidate')return;
    const result=await api('/api/community/feed/mine?page='+state.feedMinePage);
    drawFeedMine(result);
  }
  async function loadFeed() {
    const request=++state.feedRequest;
    const params=new URLSearchParams(new FormData($('#feed-filter')));
    params.set('page',String(state.feedPage));if(!params.get('kind'))params.delete('kind');
    const result=await api('/api/community/feed?'+params);
    if(request!==state.feedRequest)return;
    $('#feed-list').innerHTML=result.entries.length?result.entries.map(entry=>feedCard(entry)).join('')+pager(result.page,result.has_more,'feed-page'):empty('Пока нет публикаций','Попробуйте выбрать другую тему или поделитесь своим опытом.');
  }
  async function openFeedThread(id,page=1) {
    if(state.feedThreadId!==id&&state.feedCommentDirty){notice('Сначала отправьте или закройте текущий комментарий, чтобы не потерять текст.','error');return;}
    const request=++state.feedThreadRequest;
    const result=await api('/api/community/feed/'+encodeURIComponent(id)+'/comments?page='+page);
    if(request!==state.feedThreadRequest)return;
    const section=$('#feed-discussion');
    if(state.feedThreadId!==id||section.hidden){
      state.feedThreadId=id;section.hidden=false;
      section.innerHTML='<div class="section-heading"><div><h2>Обсуждение</h2><p>'+esc(result.post.title)+'</p></div><button type="button" class="button secondary compact" data-action="close-feed-thread">Закрыть</button></div><div id="feed-comments"></div>'+(state.feedCanPublish?feedForm(true):'<p class="help">Комментировать могут участники с опубликованным профессиональным профилем.</p>');
      if(state.feedCanPublish)bindFeedForm($('#feed-comment-form'),true);
      section.scrollIntoView({block:'start'});
    }
    state.feedThreadPage=page;
    $('#feed-comments').innerHTML=result.entries.length?result.entries.map(entry=>feedCard(entry,{comment:true})).join('')+pager(result.page,result.has_more,'feed-comment-page'):empty('Пока нет комментариев','Начните профессиональное обсуждение.');
  }
  function closeFeedThread(){
    const close=()=>{++state.feedThreadRequest;state.feedThreadId=null;state.feedCommentDirty=false;$('#feed-discussion').hidden=true;$('#feed-discussion').innerHTML='';};
    if(state.feedCommentDirty)confirmAction('Закрыть обсуждение?','Неотправленный комментарий будет потерян.','Закрыть',async()=>close());
    else close();
  }
  async function loadFeedReview(){
    const status=$('#feed-review-status').value;
    const request=++state.feedReviewRequest;
    const result=await api('/api/admin/community/feed?'+new URLSearchParams({status,page:String(state.feedReviewPage)}));
    if(request!==state.feedReviewRequest)return;
    $('#feed-review-list').innerHTML=result.entries.length?result.entries.map(entry=>feedCard(entry,{admin:true})).join('')+pager(result.page,result.has_more,'feed-review-page'):empty('Нет текстов в этом статусе','Выберите другой статус или обновите список.');
  }
  function moderateFeed(button){
    const {id,version,action}=button.dataset,decision=action.replace('-feed','');
    openDialog(decision==='approve'?'Одобрить текст?':decision==='reject'?'Отклонить текст?':'Скрыть текст?', '<form id="feed-review-form" class="dialog-form"><p>Одобрение делает текст видимым в сообществе. Проверьте содержание и отсутствие персональных данных.</p>'+(decision==='approve'?'':'<div class="field"><label for="feed-review-reason">Причина для автора</label><textarea name="reason" id="feed-review-reason" maxlength="500" required></textarea></div>')+'<div class="actions"><button class="button primary" type="submit">Подтвердить</button><button class="button secondary" type="button" data-close-dialog>Отмена</button></div></form>');
    const form=$('#feed-review-form');
    form.addEventListener('submit',event=>{event.preventDefault();const reason=form.elements.reason?.value||'';busy(form,async()=>{
      await api('/api/admin/community/feed/'+encodeURIComponent(id),{method:'PATCH',body:{expected_version:Number(version),decision,reason}});
      dialogBusy=false;closeDialog();notice('Решение сохранено.');await loadFeedReview();
    });});
  }
  async function renderFeed(){
    if(!state.user){accountGate('Профессиональная лента');return;}
    if(state.user.role==='admin'){
      content.innerHTML='<div class="section-heading"><div><h1>Модерация профессиональной ленты</h1><p>Проверяйте публикации и комментарии до показа участникам.</p></div></div><form id="feed-review-filter" class="panel feed-form"><div class="field"><label for="feed-review-status">Статус</label><select id="feed-review-status">'+options(feedStates,'pending')+'</select></div><button type="submit" class="button secondary">Обновить</button></form><div id="feed-review-list" class="feed-list"></div>';
      $('#feed-review-filter').addEventListener('submit',event=>{event.preventDefault();state.feedReviewPage=1;loadFeedReview().catch(error=>notice(error.message,'error'));});
      $('#feed-review-status').addEventListener('change',()=>{state.feedReviewPage=1;loadFeedReview().catch(error=>notice(error.message,'error'));});
      await loadFeedReview();return;
    }
    let mine=null;
    if(state.user.role==='candidate')mine=await api('/api/community/feed/mine');
    state.feedCanPublish=Boolean(mine?.can_publish);
    content.innerHTML='<div class="section-heading"><div><h1>Профессиональная лента</h1><p>Делитесь опытом, задавайте вопросы, ищите партнёров и наставников.</p></div>'+(state.feedCanPublish?'<a class="button primary" href="#feed-compose-section">Написать публикацию</a>':'')+'</div><div class="feed-layout"><div class="feed-primary"><form id="feed-filter" class="panel feed-filter" role="search"><div class="field"><label for="feed-search">Поиск</label><input id="feed-search" name="q" maxlength="100" type="search" placeholder="Тема или ключевое слово"></div><div class="field"><label for="feed-category">Направление</label><select name="kind" id="feed-category">'+options(feedCategories,'','Все темы')+'</select></div><button class="button primary" type="submit">Найти</button></form><div id="feed-list" class="feed-list" aria-live="polite"><p role="status">Загружаем публикации…</p></div><section id="feed-discussion" class="panel feed-discussion" hidden></section></div><aside class="feed-side">'+(state.feedCanPublish?'<section class="panel" id="feed-compose-section">'+feedForm()+'</section>':'<section class="panel"><h2>Участвуйте в обсуждениях</h2><p>Публикации доступны участникам с одобренным профессиональным профилем.</p>'+(state.user.role==='candidate'?'<a class="button primary" href="/community/profile">Мой профиль</a>':'<p class="help">Работодатели могут читать ленту.</p>')+'</section>')+(mine?'<section class="panel"><h2>Мои публикации и комментарии</h2><p class="help">Одобренные тексты видны при действующем профессиональном профиле; скрытие публикации скрывает её обсуждение.</p><button type="button" class="button secondary compact" data-action="refresh-feed-mine">Обновить статусы</button><div id="feed-mine-list" class="feed-list"></div></section>':'')+'</aside></div>';
    $('#feed-filter').addEventListener('submit',event=>{event.preventDefault();state.feedPage=1;loadFeed().catch(error=>notice(error.message,'error'));});
    if(state.feedCanPublish)bindFeedForm($('#feed-compose-form'));
    if(mine)drawFeedMine(mine);
    await loadFeed();
  }

  async function handleAction(event) {
    const button=event.target.closest('[data-action]');if(!button||button.disabled)return;
    const {action,id}=button.dataset;
    try{
      if(action==='people-page'){state.directoryPage=Number(button.dataset.page);await loadPeople();}
      else if(action==='retry-people')await loadPeople();
      else if(action==='connections-page'){state.connectionPage=Number(button.dataset.page);await loadConnections();}
      else if(action==='attention-connections'||action==='all-connections'){
        state.connectionFilter=action==='attention-connections'?'attention':'';
        state.connectionPage=1;$('#connection-filter').value=state.connectionFilter;await loadConnections();
      }
      else if(action==='mark-thread-read')await markThreadRead(button,id);
      else if(action==='open-thread')await openThread(id);
      else if(action==='refresh-thread')await openThread(id,{preserve:true});
      else if(action==='accept-connection')await busy(button.closest('article'),()=>connectionAction(id,action));
      else if(['decline-connection','cancel-connection','block-connection'].includes(action))confirmAction(action==='block-connection'?'Прекратить общение?':'Завершить этот запрос?',action==='block-connection'?'Вы больше не сможете отправлять друг другу сообщения и новые запросы. История разговора сохранится. Возобновить общение после блокировки будет нельзя.':'Запрос будет завершён. Отправить повторное приглашение этому участнику будет нельзя.',action==='block-connection'?'Прекратить общение':'Подтвердить',()=>connectionAction(id,action));
      else if(action==='report-connection')report({connection_id:id});
      else if(['approve-profile','reject-profile','hide-profile'].includes(action))moderateProfile(button);
      else if(action==='reload-moderation')await Promise.all([loadModeration(),loadReports()]);
      else if(action==='moderation-page'){state.moderationPage=Number(button.dataset.page);await loadModeration();}
      else if(action==='reports-page'){state.reportPage=Number(button.dataset.page);await loadReports();}
      else if(['resolve-report','dismiss-report'].includes(action))await busy(button.closest('article'),async()=>{await api('/api/admin/community/reports/'+encodeURIComponent(id),{method:'PATCH',body:{status:action==='resolve-report'?'resolved':'dismissed'}});await loadReports();notice('Статус жалобы сохранён.');});
      else if(action==='feed-page'){state.feedPage=Number(button.dataset.page);await loadFeed();}
      else if(action==='feed-mine-page'){state.feedMinePage=Number(button.dataset.page);await loadFeedMine();}
      else if(action==='refresh-feed-mine'){state.feedMinePage=1;await loadFeedMine();}
      else if(action==='open-feed-thread')await openFeedThread(id);
      else if(action==='close-feed-thread')closeFeedThread();
      else if(action==='feed-comment-page')await openFeedThread(state.feedThreadId,Number(button.dataset.page));
      else if(action==='withdraw-feed')confirmAction('Скрыть текст?','Текст перестанет отображаться в ленте. Если это публикация, обсуждение также будет скрыто.','Скрыть',async()=>{
        await api('/api/community/feed/'+encodeURIComponent(id),{method:'DELETE',body:{expected_version:Number(button.dataset.version)}});
        notice('Текст скрыт.');
        if(state.feedThreadId===id){
          ++state.feedThreadRequest;
          $('#feed-comments').innerHTML=empty('Обсуждение скрыто','Этот текст больше не отображается в ленте.');
          if(!state.feedCommentDirty){state.feedThreadId=null;$('#feed-discussion').hidden=true;$('#feed-discussion').innerHTML='';}
        }
        await Promise.all([loadFeedMine(),loadFeed()]);
      });
      else if(action==='feed-review-page'){state.feedReviewPage=Number(button.dataset.page);await loadFeedReview();}
      else if(['approve-feed','reject-feed','hide-feed'].includes(action))moderateFeed(button);
      else if(action==='retry-community')await renderMode();
    }catch(error){notice(error.message,'error');}
  }
  async function renderMode() {
    try{
      if(mode==='directory')await renderDirectory();
      else if(mode==='feed')await renderFeed();
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
    window.addEventListener('beforeunload',event=>{if(state.dirty||state.messageDirty||state.feedDirty||state.feedCommentDirty){event.preventDefault();event.returnValue='';}});
    try{state.user=(await api('/api/me')).user;}catch(error){if(error.status!==401){notice(error.message,'error');if(!['directory','person'].includes(mode)){content.innerHTML='<section class="panel"><h1>Аккаунт временно недоступен</h1><p>Обновите страницу, когда соединение восстановится.</p><button class="button secondary" type="button" id="retry-account">Повторить</button></section>';$('#retry-account').addEventListener('click',()=>location.reload());return;}}}
    updateIdentity();await renderMode();
  }
  document.addEventListener('DOMContentLoaded',boot);
})();
