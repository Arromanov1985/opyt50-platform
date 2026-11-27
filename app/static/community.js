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
  const opportunityMode=['mentoring','projects'].includes(mode);
  const groupSlug=mode==='feed'?new URLSearchParams(location.search).get('group')||'':'';
  const state = {user:null, profile:null, profileVisible:false, dirty:false, messageDirty:false, connections:[], connectionPage:1, connectionFilter:'', connectionListRequest:0, readThrough:null, selected:null, messageKey:null, messageBody:null, nextBefore:null, directoryPage:1, directoryRequest:0, threadSelectionRequest:0, threadRequest:0, messageLoadRequest:0, moderationPage:1, reportPage:1, busy:new WeakSet(), feedPage:1, feedMinePage:1, feedReviewPage:1, feedRequest:0, feedThreadRequest:0, feedReviewRequest:0, feedThreadId:null, feedThreadPage:1, feedCanPublish:false, feedDirty:false, feedCommentDirty:false, feedFollowingIds:new Set(), feedOwnPublicId:null, feedFollowsPage:1, feedAlertsPage:1, feedReportsPage:1, feedFollowsRequest:0, feedAlertsRequest:0, feedReportsRequest:0, feedSavedIds:new Set(), savedPage:1, savedRequest:0, discoveryPeoplePage:1, discoveryFeedPage:1, discoveryRequest:0, discoveryRevision:null, discoveryDirty:false, portfolioEntries:[], portfolioCanPublish:false, portfolioEdit:null, portfolioDirty:false, portfolioRequest:0, portfolioReviewRequest:0, portfolioReviewPage:1,reputationDirection:'incoming',reputationPage:1,reputationRequest:0,reputationDirty:false,reputationRestricted:false,portfolioRestricted:false,group:null,groupsRequest:0,groupsMine:false,authorEntries:[],authorTopics:{},authorRestricted:false,authorCanSubmit:false,authorDirty:false,authorEdit:null,authorPage:1,authorRequest:0,builderDirty:false};
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
    content.innerHTML = `<div class="section-heading"><div><h1>Ваш опыт — вашими словами</h1><p>Создайте отдельную страницу для коллег, проектов и наставничества. Вы сами выбираете, что рассказывать о себе.</p></div><div class="actions"><a class="button secondary compact" href="/community/portfolio">Моё портфолио →</a><a class="button secondary compact" href="/community/author-articles">Мои статьи</a><a class="button secondary compact" href="/community/courses">Мои курсы</a><a class="button secondary compact" href="/community/reputation">Рекомендации коллег</a><button class="button secondary compact" type="button" data-action="invite-colleague">Пригласить коллегу</button><a class="button secondary compact" href="/community/connections">Мои связи →</a></div></div>
    <div class="profile-layout"><div class="panel"><div class="status-line" id="profile-status">${statusBadge(p.status,profileStates)}</div>${p.moderation_reason ? `<p class="notice warning">Комментарий модератора: ${esc(p.moderation_reason)}</p>` : ''}
    <form id="professional-profile-form" class="profile-form"><div class="form-grid"><div class="field"><label for="public-name">Публичное имя *</label><input id="public-name" name="public_name" maxlength="60" value="${esc(values.public_name)}" placeholder="Имя или профессиональный псевдоним"><p class="help">Не обязательно указывать полное имя.</p></div><div class="field"><label for="public-city">Город</label><input id="public-city" name="city" maxlength="80" value="${esc(values.city)}" placeholder="Например, Москва"></div></div>
    <div class="field"><label for="public-headline">Профессия и направление *</label><input id="public-headline" name="headline" maxlength="120" value="${esc(values.headline)}" placeholder="Бухгалтер · помогаю малому бизнесу"></div>
    <div class="field"><label for="public-goal">Что вам интересно</label><select id="public-goal" name="goal">${options(goals,values.goal || 'exchange')}</select></div>
    <div class="field"><label for="public-about">Чем можете быть полезны *</label><textarea id="public-about" name="about" maxlength="2000" rows="6" placeholder="Расскажите об опыте, задачах и знаниях, которыми готовы делиться.">${esc(values.about)}</textarea><p class="help">Для публикации — от 20 символов. Без телефона, email, ссылок и адреса проживания.</p></div>
    <div class="field"><label for="public-skills">Навыки и темы</label><textarea id="public-skills" name="skills" maxlength="400" rows="3" placeholder="Например: управленческий учёт, 1С, обучение коллег">${esc(values.skills)}</textarea><p class="help">Указывайте только свой опыт. Не добавляйте личные сведения других людей.</p></div>
    <div class="form-footer"><button id="save-professional-profile" class="button primary" type="submit">Сохранить черновик</button><p id="profile-save-state" class="save-state" role="status">${preserved ? 'Есть несохранённые изменения' : p.version ? 'Сохранённая версия профиля' : 'Данные появятся на сервере после сохранения'}</p></div></form>
    <section class="publication-panel" id="profile-publication"><h2>Публикация — отдельный шаг</h2><p class="help">Сохранение черновика не публикует профиль. Изменённый профиль нужно снова отправить на проверку.</p>
    ${state.profileVisible && p.status === 'published' ? `<p><a class="public-link" href="/people/${encodeURIComponent(p.public_id)}">Открыть мою публичную страницу →</a></p><button type="button" class="button secondary compact" data-action="share-profile" data-id="${esc(p.public_id)}">Поделиться профилем</button>` : ''}
    <label class="consent-label"><input type="checkbox" id="publish-consent"${canSubmit ? '' : ' disabled'}><span>Я разрешаю публиковать выбранное публичное имя, профессию, город, описание опыта, навыки и интерес. Их сможет прочитать любой посетитель. Я могу скрыть профиль и отозвать это разрешение.</span></label>
    <div class="actions"><button class="button primary" id="submit-profile-review" type="button" disabled>Отправить на проверку</button>${['pending','published'].includes(p.status) || p.consent_at ? '<button class="button secondary" id="withdraw-profile" type="button">Скрыть и отозвать согласие</button>' : ''}</div>
    <details class="publication-rules" id="publication-rules"><summary>Что будет опубликовано и как это отменить</summary><p>Публикуются только поля этой формы и отдельно одобренные записи портфолио. Имя, email, телефон и резюме из вашего аккаунта сюда не переносятся. Перед отправкой проверьте описание и навыки: они тоже будут публичными.</p><p>После проверки профиль появится в сообществе и получит отдельную ссылку. Скрытие уберёт страницу и закроет возможность новых запросов. Уже начатые разговоры останутся в «Моих связях»; прекратить их можно блокировкой. Копии, которые ранее сделали другие люди, СТАЖНО удалить не сможет.</p></details>
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
        confirmAction('Сохранить новую версию?', 'Если текст изменился, текущая публикация или заявка на проверку будет снята. Новую версию можно отправить на проверку после сохранения. Авторские статьи и курсы также потребуют нового согласия.', 'Сохранить новую версию', () => busy(form.closest('.panel'),save));
      } else busy(form.closest('.panel'),save);
    });
    $('#submit-profile-review').addEventListener('click', () => {
      if (!$('#publish-consent').checked || state.dirty) return;
      const panel = $('#professional-profile-form').closest('.panel');
      busy(panel,async () => { const result=await api('/api/community/profile/submit',{method:'POST',body:{expected_version:p.version,publish_consent:true}}); state.profile=result.profile; renderProfileForm(); notice('Профиль отправлен на проверку. До решения модератора он доступен только вам.'); });
    });
    $('#withdraw-profile')?.addEventListener('click', () => confirmAction('Скрыть профессиональный профиль?', 'Страница и карточка исчезнут из сообщества, новые запросы станут недоступны. Разрешения на публикацию портфолио, рекомендаций коллег, авторских материалов и курсов также будут отозваны. Уже начатые разговоры сохранятся. Введённые изменения останутся в форме.', 'Скрыть профиль', async () => {
      const draft = state.dirty ? profileValues() : null;
      const result=await api('/api/community/profile/publication',{method:'DELETE',body:{expected_version:p.version}}); state.profile=result.profile; renderProfileForm(draft); notice('Профиль скрыт. Разрешение на публикацию отозвано.');
    }));
  }
  async function renderProfile() {
    if (!state.user) return accountGate('Мой профессиональный профиль');
    if (state.user.role !== 'candidate') { content.innerHTML=empty('Профиль компании уже есть в вашем кабинете','Профессиональные страницы создают участники с аккаунтом соискателя. Как работодатель вы можете знакомиться с ними от имени компании.','<div class="actions"><a class="button primary" href="/community">Найти участников</a><a class="button secondary" href="/#account">Кабинет компании</a></div>'); return; }
    const result=await api('/api/community/profile');state.profile=result.profile;state.profileVisible=Boolean(result.public_visible);renderProfileForm();
  }

  async function requestConnection(target=null) {
    const publicId=target?.publicId||document.body.dataset.personId;
    if (!state.user) return loginDialog(()=>requestConnection(target));
    if (state.user.role === 'admin') { notice('Администратор проверяет профили. Для знакомства используйте обычный аккаунт участника.','warning'); return; }
    if (state.user.role === 'candidate') {
      const own=(await api('/api/community/profile')).profile;
      if (own.public_id === publicId) { notice('Это ваша профессиональная страница.'); return; }
      if (own.status !== 'published') { openDialog('Сначала представьтесь', '<p>Чтобы отправить запрос коллеге, опубликуйте свой профессиональный профиль. Так человек сможет понять, кто предлагает знакомство.</p><a class="button primary" href="/community/profile">Подготовить мой профиль</a>'); return; }
    }
    openDialog('Предложить профессиональное знакомство', `<p class="help">Участник сам решит, начинать ли разговор. Контакты из аккаунта не передаются.</p><form id="connection-request-form" class="dialog-form"><div class="field"><label for="connection-purpose">О чём хотите поговорить</label><select id="connection-purpose" name="purpose">${options(goals,target?.kind||'exchange')}</select></div><div class="field"><label for="connection-note">Коротко о предложении</label><textarea id="connection-note" name="note" maxlength="500" rows="4" placeholder="Расскажите, что вас заинтересовало и чем можете быть полезны."></textarea><p class="help">Без телефона, email и ссылок. Личная переписка откроется после согласия.</p></div><button class="button primary" type="submit">Отправить запрос</button></form>`);
    if(target){
      const form=$('#connection-request-form');
      form.elements.purpose.value=target.kind;
      form.elements.purpose.disabled=true;
      form.elements.note.value='По предложению «'+target.title+'»: ';
    }
    $('#connection-request-form').addEventListener('submit', event => {event.preventDefault(); const form=event.currentTarget; const data=Object.fromEntries(new FormData(form)); busy(form,async()=>{
      const result=await api('/api/community/connections',{method:'POST',body:{...data,public_id:publicId,...(target?{purpose:target.kind,opportunity_id:target.entryId}:{})}});
      dialogBusy=false; closeDialog(); notice(result.connection.status==='accepted' ? 'Вы уже знакомы. Разговор доступен в «Моих связях».' : 'Запрос отправлен. Ответ появится в «Моих связях».');
      const hint=$('#person-action-hint');
      if(hint)hint.innerHTML=`<a href="/community/connections?thread=${encodeURIComponent(result.connection.id)}">Открыть мои связи →</a>`;
      else {const link=document.createElement('a');link.href='/community/connections?thread='+encodeURIComponent(result.connection.id);link.textContent=' Открыть мои связи →';$('#community-notice').append(link);}
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
    $('#share-person').addEventListener('click',()=>shareProfile(document.body.dataset.personId));
    const slot=$('#person-follow-slot');
    if(slot&&state.user&&['candidate','employer'].includes(state.user.role)){
      try{await refreshPersonFollow();}catch(error){notice(error.message,'error');}
    }
  }

  function connectionCard(c) {
    const other=c.counterpart;
    const title=other.public_id ? `<a href="/people/${encodeURIComponent(other.public_id)}">${esc(other.public_name)}</a>` : esc(other.public_name);
    return `<article class="panel connection-card${state.selected?.id===c.id?' selected':''}" data-connection-id="${esc(c.id)}"><span class="direction">${c.direction==='incoming'?'Вам предлагают знакомство':'Ваше предложение'}</span><h2>${title}</h2><p class="help">${esc(other.headline)}${other.role==='employer'?' · Работодатель':''}</p><div class="status-line">${statusBadge(c.status,connectionStates)}<span class="tag">${esc(goals[c.purpose])}</span>${Number(c.unread_count)>0?`<span class="community-unread">Непрочитанных: ${Number(c.unread_count)}</span>`:''}</div>${c.note?`<p class="note">${esc(c.note)}</p>`:''}<div class="actions">${c.can_respond?`<button class="button primary" type="button" data-action="accept-connection" data-id="${esc(c.id)}">Принять знакомство</button><button class="button secondary" type="button" data-action="decline-connection" data-id="${esc(c.id)}">Отклонить</button>`:''}${c.can_cancel?`<button class="button secondary" type="button" data-action="cancel-connection" data-id="${esc(c.id)}">Отозвать запрос</button>`:''}<button class="button secondary" type="button" data-action="open-thread" data-id="${esc(c.id)}">${['accepted','blocked'].includes(c.status)?'Открыть переписку':'Подробности'}</button>${state.user.role==='candidate'&&c.status==='accepted'&&other.role==='candidate'&&other.public_id?`<a class="button secondary" href="/community/reputation?connection=${encodeURIComponent(c.id)}">Рекомендовать коллегу</a>`:''}</div>${c.can_respond?'<p class="help">Принятие откроет переписку внутри СТАЖНО. Контакты из аккаунта останутся закрыты.</p>':''}</article>`;
  }
  async function renderConnections() {
    if (!state.user) return accountGate('Мои профессиональные связи');
    if (state.user.role==='admin') {content.innerHTML=empty('Модерация сообщества','Управляйте публичными профилями и рассматривайте жалобы.','<a class="button primary" href="/community/moderation">Перейти к модерации</a>');return;}
    if(new URLSearchParams(location.search).get('attention')==='1') state.connectionFilter='attention';
    content.innerHTML=`<div class="section-heading"><div><h1>Профессиональные связи</h1><p>Запросы на знакомство и ваши разговоры. Переписка доступна только участникам после принятия запроса.</p></div><div class="actions"><a class="button secondary compact" href="/community">Найти коллег →</a>${state.user.role==='candidate'?'<a class="button secondary compact" href="/community/reputation">Рекомендации коллег</a>':''}</div></div><section class="panel community-attention" id="community-attention" aria-label="Активность сообщества" role="status"><p class="help">Проверяем новые сообщения и запросы…</p></section><div class="connections-toolbar"><label class="help" for="connection-filter">Показать<select id="connection-filter">${options({attention:'Требуют внимания',...connectionStates},state.connectionFilter,'Все знакомства')}</select></label><button class="button secondary compact" id="refresh-connections" type="button">Обновить</button></div><div class="connections-layout"><div><div class="connection-list" id="community-connections-list"></div><div id="connections-pager"></div></div><section id="community-thread" class="panel thread-panel"><div class="thread-empty"><p>Выберите знакомство слева,<br>чтобы увидеть подробности или переписку.</p></div></section></div>`;
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
    const portfolioSection=document.createElement('section');portfolioSection.className='section-divider';
    portfolioSection.innerHTML='<div class="section-heading"><div><h2>Портфолио и достижения</h2><p>Проверяйте только записи, отправленные с отдельным согласием на публикацию.</p></div><a href="/community/portfolio" class="button secondary">Модерация портфолио</a><a href="/community/reputation" class="button secondary">Модерация рекомендаций</a><a href="/community/author-articles" class="button secondary">Авторские материалы</a><a href="/community/courses" class="button secondary">Редакция курсов</a></div>';
    content.append(portfolioSection);
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
  const opportunityIntents={mentoring:{offer:'Готов быть наставником',seek:'Ищу наставника'},projects:{organize:'Собираю команду',join:'Ищу проект для участия'}};
  const opportunityFormats={online:'Онлайн',offline:'Личная встреча',hybrid:'Онлайн и лично'};
  const opportunityCommitments={one_off:'Разовая помощь / задача',regular:'Регулярное участие',flexible:'По договорённости'};
  const feedStates={pending:'На проверке',published:'Одобрено',rejected:'Не опубликовано',hidden:'Скрыто'};
  function feedForm(comment=false) {
    const id=comment?'feed-comment-form':'feed-compose-form';
    return '<form class="feed-form" id="'+id+'"><h2>'+(comment?'Добавить комментарий':'Поделиться опытом')+'</h2>'+
      (comment?'':'<div class="field"><label for="feed-kind">Тема</label><select name="kind" id="feed-kind">'+options(feedCategories,'experience')+'</select></div><div class="field"><label for="feed-title">Заголовок</label><input name="title" id="feed-title" maxlength="140" required placeholder="О чём хотите рассказать?"></div>')+
      '<div class="field"><label for="'+id+'-body">'+(comment?'Ваш ответ':'Текст публикации')+'</label><textarea name="body" id="'+id+'-body" rows="'+(comment?'4':'6')+'" maxlength="'+(comment?'1000':'2400')+'" required placeholder="Расскажите по делу, без контактов и ссылок"></textarea></div>'+
      '<label class="feed-consent"><input name="publish_consent" type="checkbox" required> Согласен на показ этого текста другим участникам после проверки модератором. Не размещаю чужие персональные данные.</label>'+
      '<p class="help">Текст не появится в ленте до одобрения. Его можно скрыть в разделе «Мои публикации и комментарии».</p><button class="button primary" type="submit">Отправить на проверку</button></form>';
  }
  function opportunityFacts(entry){
    const o=entry.opportunity;if(!o)return '';
    const values=[opportunityIntents[entry.kind]?.[o.intent],opportunityFormats[o.meeting_format],opportunityCommitments[o.commitment],o.city].filter(Boolean);
    return '<div class="opportunity-facts">'+values.map(value=>'<span class="tag">'+esc(value)+'</span>').join('')+'</div>';
  }
  function feedCard(entry,{mine=false,admin=false,comment=false}={}) {
    const id=esc(entry.id), heading=entry.title?'<h2>'+esc(entry.title)+'</h2>':'';
    const author=entry.public_id?'<a href="/people/'+encodeURIComponent(entry.public_id)+'">'+esc(entry.public_name)+'</a> <span class="help">'+esc(entry.headline||'')+'</span>':'';
    const reviewContext=admin&&entry.parent_id?'<p class="help">Обсуждение: '+esc(entry.parent_title||'Недоступно')+'</p><details><summary>Текст исходной публикации</summary><p class="multiline">'+esc(entry.parent_body||'')+'</p></details>':'';
    let actions='';
    if(mine&&entry.status!=='hidden')actions='<button class="button secondary compact" type="button" data-action="withdraw-feed" data-id="'+id+'" data-version="'+Number(entry.version)+'">Скрыть</button>';
    if(admin&&entry.status==='pending')actions='<button class="button primary compact" type="button" data-action="approve-feed" data-id="'+id+'" data-version="'+Number(entry.version)+'">Одобрить</button> <button class="button secondary compact" type="button" data-action="reject-feed" data-id="'+id+'" data-version="'+Number(entry.version)+'">Отклонить</button>';
    if(admin&&entry.status==='published')actions='<button class="button secondary compact" type="button" data-action="hide-feed" data-id="'+id+'" data-version="'+Number(entry.version)+'">Скрыть</button>';
    if(!mine&&!admin&&!comment)actions='<button class="button secondary" type="button" data-action="open-feed-thread" data-id="'+id+'">Читать обсуждение</button> '+savedButton(entry.id,state.feedSavedIds.has(entry.id));
    if(!mine&&!admin&&entry.public_id!==state.feedOwnPublicId){
      if(!comment&&entry.public_id){
        if(entry.opportunity)actions='<button type="button" class="button primary" data-action="respond-opportunity" data-id="'+id+'" data-public-id="'+esc(entry.public_id)+'" data-kind="'+esc(entry.kind)+'" data-title="'+esc(entry.title)+'">Обсудить предложение</button> '+actions;
        actions+=' '+followButton(entry.public_id,state.feedFollowingIds.has(entry.public_id));
      }
      actions+=' <button class="text-button" type="button" data-action="report-feed" data-id="'+id+'">Пожаловаться</button>';
    }
    return '<article class="panel feed-card" data-feed-id="'+id+'"><div class="feed-meta"><span class="tag">'+esc(feedKinds[entry.kind]||'Публикация')+'</span>'+(entry.group_slug?'<a class="tag group-tag" href="/community/feed?group='+encodeURIComponent(entry.group_slug)+'">'+esc(entry.group_name||'Тематическая группа')+'</a>':'')+((mine||admin)?statusBadge(entry.status,feedStates):'')+'<time>'+esc(date(entry.published_at||entry.created_at))+'</time></div>'+heading+(author?'<p class="feed-author">'+author+'</p>':'')+reviewContext+opportunityFacts(entry)+'<p class="multiline feed-body">'+esc(entry.body)+'</p>'+((mine||admin)&&entry.moderation_reason?'<p class="help">Причина: '+esc(entry.moderation_reason)+'</p>':'')+(actions?'<div class="actions">'+actions+'</div>':'')+'</article>';
  }
  function bindFeedForm(form,comment=false) {
    const dirtyKey=comment?'feedCommentDirty':'feedDirty';
    form.addEventListener('input',()=>{state[dirtyKey]=Boolean(form.elements.body.value.trim()||(!comment&&form.elements.title.value.trim()));});
    form.addEventListener('submit',event=>{
      event.preventDefault();
      const fields=Object.fromEntries(new FormData(form));
      const body={kind:comment?'comment':fields.kind,title:comment?'':fields.title,body:fields.body,parent_id:comment?state.feedThreadId:null,publish_consent:fields.publish_consent==='on'};
      if(!comment&&state.group)body.group_slug=state.group.slug;
      if(!comment&&opportunityMode)body.opportunity={intent:fields.intent,meeting_format:fields.meeting_format,commitment:fields.commitment};
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
    if(state.user?.role!=='candidate'||!$('#feed-mine-list'))return;
    const result=await api('/api/community/feed/mine?page='+state.feedMinePage+(opportunityMode?'&opportunity_kind='+mode:'')+(state.group?'&group_slug='+encodeURIComponent(state.group.slug):''));
    drawFeedMine(result);
  }
  async function loadFeed() {
    const request=++state.feedRequest;
    const params=new URLSearchParams(new FormData($('#feed-filter')));
    params.set('page',String(state.feedPage));if(!params.get('kind'))params.delete('kind');
    if(state.group)params.set('group_slug',state.group.slug);
    if(opportunityMode){params.set('kind',mode);for(const key of ['intent','meeting_format','commitment'])if(!params.get(key))params.delete(key);}
    const result=await api((opportunityMode?'/api/community/opportunities?':'/api/community/feed?')+params);
    if(request!==state.feedRequest)return;
    state.feedFollowingIds=new Set(result.following_public_ids||[]);
    state.feedSavedIds=new Set(result.saved_entry_ids||[]);
    state.feedOwnPublicId=result.own_public_id||null;
    $('#feed-list').innerHTML=result.entries.length?result.entries.map(entry=>feedCard(entry)).join('')+pager(result.page,result.has_more,'feed-page'):empty(opportunityMode?'Пока нет подходящих предложений':'Пока нет публикаций',opportunityMode?'Измените условия поиска или создайте своё предложение.':'Попробуйте выбрать другую тему или поделитесь своим опытом.');
  }
  async function openFeedThread(id,page=1) {
    if(state.feedThreadId!==id&&state.feedCommentDirty){notice('Сначала отправьте или закройте текущий комментарий, чтобы не потерять текст.','error');return;}
    const request=++state.feedThreadRequest;
    const result=await api('/api/community/feed/'+encodeURIComponent(id)+'/comments?page='+page);
    if(request!==state.feedThreadRequest)return;
    const section=$('#feed-discussion');
    if(state.feedThreadId!==id||section.hidden){
      state.feedThreadId=id;section.hidden=false;
      const canComment=Boolean(result.can_comment);
      const commentHint=result.post.group_slug&&state.feedCanPublish?'<p class="help">Для комментария вступите в группу. <a href="/community/groups">Открыть группы</a></p>':'<p class="help">Комментировать могут участники с опубликованным профессиональным профилем.</p>';
      section.innerHTML='<div class="section-heading"><div><h2>Обсуждение</h2><p>'+esc(result.post.title)+'</p></div><button type="button" class="button secondary compact" data-action="close-feed-thread">Закрыть</button></div><div id="feed-comments"></div>'+(canComment?feedForm(true):commentHint);
      if(canComment)bindFeedForm($('#feed-comment-form'),true);
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

  function followButton(publicId,following){
    return '<button class="button secondary compact" type="button" data-action="'+(following?'unfollow-author':'follow-author')+'" data-id="'+esc(publicId)+'" aria-pressed="'+String(following)+'">'+(following?'Отписаться':'Подписаться')+'</button>';
  }
  async function refreshPersonFollow(){
    const id=document.body.dataset.personId;
    const result=await api('/api/community/feed/follows/'+encodeURIComponent(id));
    $('#person-follow-slot').innerHTML=result.can_follow?followButton(id,result.following)+'<p class="help">Подписка видна только вам. Она не открывает личные контакты.</p>':'';
  }
  async function loadFeedFollows(){
    const request=++state.feedFollowsRequest;
    const result=await api('/api/community/feed/follows?page='+state.feedFollowsPage);
    if(request!==state.feedFollowsRequest)return;
    if(!result.follows.length&&state.feedFollowsPage>1){state.feedFollowsPage=1;return loadFeedFollows();}
    $('#feed-follows-list').innerHTML=result.follows.length?result.follows.map(item=>'<article class="feed-follow-row"><div>'+(item.available?'<a href="/people/'+encodeURIComponent(item.public_id)+'">'+esc(item.public_name)+'</a><p class="help">'+esc(item.headline||'')+'</p>':'<strong>Недоступный участник</strong><p class="help">Публикации сейчас не отображаются.</p>')+'</div>'+followButton(item.public_id,true)+'</article>').join('')+pager(result.page,result.has_more,'feed-follows-page'): '<p class="help">Подпишитесь на интересного автора, чтобы находить его публикации в своей ленте.</p>';
  }
  async function changeFollow(button){
    const {id,action}=button.dataset;
    const root=button.closest('article')||$('#person-follow-slot');
    await busy(root,async()=>{
      const follow=action==='follow-author';
      if(follow)await api('/api/community/feed/follows',{method:'POST',body:{public_id:id}});
      else await api('/api/community/feed/follows/'+encodeURIComponent(id),{method:'DELETE',body:{}});
      notice(follow?'Подписка оформлена.':'Подписка отменена.');
      if(mode==='person')await refreshPersonFollow();
      else {await refreshFeedSurface();if($('#feed-follows-list'))await loadFeedFollows();}
    });
  }
  function paintFeedAlertBadge(result){
    const badge=$('#feed-alert-badge');
    if(!badge)return;
    const count=result.entries.length;
    badge.hidden=!count;
    badge.textContent=count?(result.has_more?String(count)+'+':String(count)):'';
    if(count)badge.setAttribute('aria-label','Есть новые комментарии');
    else badge.removeAttribute('aria-label');
  }
  async function refreshFeedAlertBadge(){
    if(!state.user||!['candidate','employer'].includes(state.user.role))return;
    try{paintFeedAlertBadge(await api('/api/community/feed/alerts'));}catch{/* The rest of the community remains usable. */}
  }
  async function loadFeedAlerts(){
    const request=++state.feedAlertsRequest;
    const result=await api('/api/community/feed/alerts?page='+state.feedAlertsPage);
    if(request!==state.feedAlertsRequest)return;
    if(!result.entries.length&&state.feedAlertsPage>1){state.feedAlertsPage=1;return loadFeedAlerts();}
    if(state.feedAlertsPage===1)paintFeedAlertBadge(result);
    else refreshFeedAlertBadge();
    $('#feed-alerts-list').innerHTML=result.entries.length?result.entries.map(entry=>'<article class="feed-alert-row"><p class="help">Новый комментарий к вашей публикации</p><h3>'+esc(entry.root_title||'Обсуждение')+'</h3><p><strong>'+esc(entry.public_name)+'</strong> · '+esc(date(entry.published_at))+'</p><p class="multiline">'+esc(entry.body)+'</p><div class="actions"><button type="button" class="button primary compact" data-action="open-feed-thread" data-id="'+esc(entry.parent_id)+'">Открыть обсуждение</button><button type="button" class="button secondary compact" data-action="read-feed-alert" data-id="'+esc(entry.id)+'">Отметить прочитанным</button></div></article>').join('')+pager(result.page,result.has_more,'feed-alerts-page'):'<p class="help">Новых комментариев пока нет. Здесь появятся одобренные ответы других участников к вашим публикациям.</p>';
  }
  function reportFeed(id){
    openDialog('Пожаловаться на текст','<form id="feed-report-form" class="dialog-form"><p>Жалоба будет доступна модератору, но не автору текста. Укажите, что следует проверить.</p><div class="field"><label for="feed-report-reason">Причина</label><select name="reason" id="feed-report-reason">'+options(reasons,'spam')+'</select></div><div class="field"><label for="feed-report-details">Подробности (необязательно)</label><textarea name="details" id="feed-report-details" maxlength="1000" rows="4"></textarea></div><div class="actions"><button type="submit" class="button primary">Отправить жалобу</button><button type="button" class="button secondary" data-close-dialog>Отмена</button></div></form>');
    const form=$('#feed-report-form');
    form.addEventListener('submit',event=>{event.preventDefault();const body=Object.fromEntries(new FormData(form));busy(form,async()=>{
      await api('/api/community/feed/'+encodeURIComponent(id)+'/reports',{method:'POST',body});
      dialogBusy=false;closeDialog();notice('Жалоба передана модератору.');
    });});
  }
  const feedReportStates={new:'Новые',resolved:'Рассмотренные',dismissed:'Отклонённые'};
  function feedReportCard(report){
    const item=report.entry,id=esc(report.id);
    return '<article class="panel feed-card" data-feed-report-id="'+id+'"><div class="feed-meta"><span class="tag">'+esc(reasons[report.reason]||report.reason)+'</span><time>'+esc(date(report.created_at))+'</time></div><h2>'+esc(item.title||item.parent_title||'Комментарий')+'</h2><p class="help">Статус текста: '+esc(feedStates[item.entry_status]||item.entry_status)+'</p><p class="multiline feed-body">'+esc(item.body)+'</p>'+(report.details?'<p><strong>Объяснение заявителя:</strong></p><p class="multiline">'+esc(report.details)+'</p>':'')+(report.status==='new'?'<div class="actions"><button type="button" class="button secondary compact" data-action="resolve-feed-report" data-id="'+id+'">Рассмотрено</button><button type="button" class="button secondary compact" data-action="dismiss-feed-report" data-id="'+id+'">Отклонить жалобу</button><button type="button" class="button danger compact" data-action="hide-feed-report" data-id="'+id+'">Скрыть текст</button></div>':'<p class="help">'+esc(feedReportStates[report.status]||report.status)+'</p>')+'</article>';
  }
  async function loadFeedReports(){
    const request=++state.feedReportsRequest;
    const status=$('#feed-reports-status').value;
    const result=await api('/api/admin/community/feed/reports?'+new URLSearchParams({status,page:String(state.feedReportsPage)}));
    if(request!==state.feedReportsRequest)return;
    if(!result.reports.length&&state.feedReportsPage>1){state.feedReportsPage=1;return loadFeedReports();}
    $('#feed-reports-list').innerHTML=result.reports.length?result.reports.map(feedReportCard).join('')+pager(result.page,result.has_more,'feed-reports-page'):empty('Нет жалоб в этом статусе','Можно обновить очередь или выбрать другой статус.');
  }
  function reviewFeedReport(button){
    const {id,action}=button.dataset,decision=action.replace('-feed-report','');
    const titles={resolve:'Отметить жалобу рассмотренной?',dismiss:'Отклонить жалобу?',hide:'Скрыть текст по жалобе?'};
    openDialog(titles[decision],'<form id="feed-report-review-form" class="dialog-form"><p>'+(decision==='hide'?'Текст исчезнет из ленты; скрытие исходной публикации также скроет её обсуждение.':'Это изменит статус жалобы, но не будет скрывать текст.')+'</p>'+(decision==='hide'?'<div class="field"><label for="feed-report-review-reason">Причина для автора текста</label><textarea name="reason" id="feed-report-review-reason" maxlength="500" required></textarea></div>':'')+'<div class="actions"><button type="submit" class="button primary">Подтвердить</button><button type="button" class="button secondary" data-close-dialog>Отмена</button></div></form>');
    const form=$('#feed-report-review-form');
    form.addEventListener('submit',event=>{event.preventDefault();const reason=form.elements.reason?.value||'';busy(form,async()=>{
      await api('/api/admin/community/feed/reports/'+encodeURIComponent(id),{method:'PATCH',body:{decision,reason}});
      dialogBusy=false;closeDialog();notice('Решение по жалобе сохранено.');
      await Promise.all([loadFeedReports(),loadFeedReview()]);
    });});
  }

  async function renderFeed(){
    if(!state.user){accountGate('Профессиональная лента');return;}
    if(state.user.role==='admin'){
      content.innerHTML='<div class="section-heading"><div><h1>Модерация профессиональной ленты</h1><p>Проверяйте публикации и комментарии до показа участникам.</p></div></div><form id="feed-review-filter" class="panel feed-form"><div class="field"><label for="feed-review-status">Статус</label><select id="feed-review-status">'+options(feedStates,'pending')+'</select></div><button type="submit" class="button secondary">Обновить</button></form><div id="feed-review-list" class="feed-list"></div><section class="section-divider"><div class="section-heading"><h2>Жалобы на публикации и комментарии</h2></div><form id="feed-reports-filter" class="panel feed-form"><div class="field"><label for="feed-reports-status">Статус жалобы</label><select id="feed-reports-status">'+options(feedReportStates,'new')+'</select></div><button type="submit" class="button secondary">Обновить жалобы</button></form><div id="feed-reports-list" class="feed-list"></div></section>';
      $('#feed-review-filter').addEventListener('submit',event=>{event.preventDefault();state.feedReviewPage=1;loadFeedReview().catch(error=>notice(error.message,'error'));});
      $('#feed-review-status').addEventListener('change',()=>{state.feedReviewPage=1;loadFeedReview().catch(error=>notice(error.message,'error'));});
      $('#feed-reports-filter').addEventListener('submit',event=>{event.preventDefault();state.feedReportsPage=1;loadFeedReports().catch(error=>notice(error.message,'error'));});
      $('#feed-reports-status').addEventListener('change',()=>{state.feedReportsPage=1;loadFeedReports().catch(error=>notice(error.message,'error'));});
      await Promise.all([loadFeedReview(),loadFeedReports()]);return;
    }
    if(groupSlug){
      const result=await api('/api/community/groups');
      state.group=result.groups.find(group=>group.slug===groupSlug)||null;
      if(!state.group){content.innerHTML=empty('Группа не найдена','Выберите существующую тематическую группу.','<a class="button primary" href="/community/groups">К группам</a>');return;}
    }
    let mine=null;
    if(state.user.role==='candidate')mine=await api('/api/community/feed/mine'+(state.group?'?group_slug='+encodeURIComponent(state.group.slug):''));
    state.feedCanPublish=Boolean(mine?.can_publish);
    const canCompose=state.feedCanPublish&&(!state.group||state.group.joined);
    const groupIntro=state.group?'<section class="panel group-intro"><a href="/community/groups">← Все профессиональные группы</a><h2>'+esc(state.group.name)+'</h2><p>'+esc(state.group.description)+'</p><p class="help">'+(state.group.joined?'Вы вступили в группу.':'Вы можете читать обсуждения. Для публикаций и комментариев вступите в группу.')+' Обсуждения открыты зарегистрированным участникам, а не являются приватным чатом.</p><a class="button secondary" href="/community/groups">Управлять участием</a></section>':'';
    content.innerHTML=groupIntro+'<div class="section-heading"><div><h1>'+(state.group?'Обсуждения группы':'Профессиональная лента')+'</h1><p>Делитесь опытом, задавайте вопросы, ищите партнёров и наставников.</p></div>'+(canCompose?'<a class="button primary" href="#feed-compose-section">Написать публикацию</a>':'')+'</div><div class="feed-layout"><div class="feed-primary"><section class="panel" id="feed-alerts"><div class="section-heading"><h2>Новые комментарии'+(state.group?' во всех темах':'')+'</h2><button type="button" class="button secondary compact" data-action="refresh-feed-alerts">Обновить</button></div><div id="feed-alerts-list" aria-live="polite"></div></section><form id="feed-filter" class="panel feed-filter" role="search"><div class="field"><label for="feed-search">Поиск</label><input id="feed-search" name="q" maxlength="100" type="search" placeholder="Тема или ключевое слово"></div><div class="field"><label for="feed-category">Направление</label><select name="kind" id="feed-category">'+options(feedCategories,'','Все темы')+'</select></div><div class="field"><label for="feed-following">Авторы</label><select name="following" id="feed-following"><option value="false">Все участники</option><option value="true">Мои подписки</option></select></div><button class="button primary" type="submit">Найти</button></form><div id="feed-list" class="feed-list" aria-live="polite"><p role="status">Загружаем публикации…</p></div><section id="feed-discussion" class="panel feed-discussion" hidden></section></div><aside class="feed-side"><section class="panel"><h2>Мои подписки</h2><p class="help">Список виден только вам.</p><div id="feed-follows-list"></div></section>'+(canCompose?'<section class="panel" id="feed-compose-section">'+feedForm()+'</section>':'<section class="panel"><h2>Участвуйте в обсуждениях</h2><p>Для публикации нужен одобренный профессиональный профиль'+(state.group?' и участие в группе':'')+'.</p>'+(state.user.role==='candidate'?(state.group&&!state.group.joined?'<a class="button primary" href="/community/groups">Вступить в группу</a>':'<a class="button primary" href="/community/profile">Мой профиль</a>'):'<p class="help">Работодатели могут читать ленту.</p>')+'</section>')+(mine?'<section class="panel"><h2>Мои публикации и комментарии</h2><p class="help">Одобренные тексты видны при действующем профессиональном профиле; скрытие публикации скрывает её обсуждение.</p><button type="button" class="button secondary compact" data-action="refresh-feed-mine">Обновить статусы</button><div id="feed-mine-list" class="feed-list"></div></section>':'')+'</aside></div>';
    $('#feed-filter').addEventListener('submit',event=>{event.preventDefault();state.feedPage=1;loadFeed().catch(error=>notice(error.message,'error'));});
    if(canCompose)bindFeedForm($('#feed-compose-form'));
    if(mine)drawFeedMine(mine);
    const params=new URLSearchParams(location.search);
    if(params.get('following')==='true')$('#feed-following').value='true';
    // Failure in a secondary panel must never replace the composer.
    await Promise.all([
      loadFeed().catch(error=>notice(error.message,'error')),
      loadFeedFollows().catch(error=>{$('#feed-follows-list').textContent=error.message;}),
      loadFeedAlerts().catch(error=>{$('#feed-alerts-list').textContent=error.message;})
    ]);
  }


  function opportunityForm(){
    const title=mode==='mentoring'?'Предложить наставничество или найти наставника':'Предложить проект или найти команду';
    return '<form class="feed-form" id="feed-compose-form"><h2>'+title+'</h2><input type="hidden" name="kind" value="'+mode+'"><div class="field"><label for="opp-intent">Ваша цель</label><select name="intent" id="opp-intent" required>'+options(opportunityIntents[mode],'')+'</select></div><div class="field"><label for="opp-format">Формат общения</label><select name="meeting_format" id="opp-format" required>'+options(opportunityFormats,'')+'</select></div><div class="field"><label for="opp-commitment">Продолжительность</label><select name="commitment" id="opp-commitment" required>'+options(opportunityCommitments,'flexible')+'</select></div><div class="field"><label for="opp-title">'+(mode==='mentoring'?'Тема наставничества':'Название или направление проекта')+'</label><input id="opp-title" name="title" maxlength="140" required placeholder="Например, обучение работе на складе"></div><div class="field"><label for="opp-body">Что предлагаете или ищете</label><textarea id="opp-body" name="body" rows="6" maxlength="2400" required placeholder="Опишите задачу, опыт, ожидания и доступное время."></textarea></div><p class="help">Город берётся из вашего опубликованного профессионального профиля. Не указывайте телефоны, ссылки, паспортные и чужие персональные данные.</p><label class="feed-consent"><input type="checkbox" name="publish_consent" required> Согласен на показ предложения другим участникам после проверки модератором.</label><button class="button primary" type="submit">Отправить на проверку</button></form>';
  }
  async function renderOpportunities(){
    const mentoring=mode==='mentoring';
    const title=mentoring?'Наставничество':'Совместные проекты';
    const desc=mentoring?'Передавайте профессиональные знания или найдите коллегу, который поможет освоить новые навыки.':'Найдите партнёров для конкретной задачи, предложите свой опыт и сформируйте команду.';
    if(!state.user){accountGate(title);return;}
    if(state.user.role==='admin'){
      content.innerHTML='<section class="panel"><h1>'+title+'</h1><p>Предложения проходят ту же проверку, что и публикации сообщества.</p><a class="button primary" href="/community/feed">Открыть модерацию ленты</a></section>';return;
    }
    let mine=null;
    if(state.user.role==='candidate')mine=await api('/api/community/feed/mine?opportunity_kind='+mode);
    state.feedCanPublish=Boolean(mine?.can_publish);
    const composer=state.feedCanPublish?'<section class="panel" id="feed-compose-section">'+opportunityForm()+'</section>':'<section class="panel"><h2>Хотите разместить предложение?</h2><p>Для публикации нужен одобренный профессиональный профиль участника.</p>'+(state.user.role==='candidate'?'<a class="button primary" href="/community/profile">Мой профиль</a>':'<p class="help">Работодатели могут искать специалистов и предложить знакомство.</p>')+'</section>';
    const own=mine?'<section class="panel"><h2>Мои предложения</h2><p class="help">Скрытие завершённого предложения убирает его из поиска и ленты. Уже принятые знакомства сохраняются.</p><button type="button" class="button secondary compact" data-action="refresh-feed-mine">Обновить статусы</button><div id="feed-mine-list" class="feed-list"></div></section>':'';
    content.innerHTML='<div class="section-heading"><div><h1>'+title+'</h1><p>'+desc+'</p></div>'+(state.feedCanPublish?'<a href="#feed-compose-section" class="button primary">Создать предложение</a>':'')+'</div><div class="feed-layout"><div class="feed-primary"><form id="feed-filter" class="panel feed-filter opportunity-filter" role="search"><div class="field"><label for="opp-search">Профессия, навык или тема</label><input type="search" id="opp-search" name="q" maxlength="100" placeholder="Например, продажи или водоочистка"></div><div class="field"><label for="opp-filter-intent">Кого ищете</label><select name="intent" id="opp-filter-intent">'+options(opportunityIntents[mode],'','Все цели')+'</select></div><div class="field"><label for="opp-filter-format">Формат</label><select name="meeting_format" id="opp-filter-format">'+options(opportunityFormats,'','Любой формат')+'</select></div><div class="field"><label for="opp-filter-commitment">Продолжительность</label><select name="commitment" id="opp-filter-commitment">'+options(opportunityCommitments,'','Любая')+'</select></div><div class="field"><label for="opp-city">Город</label><input name="city" id="opp-city" maxlength="80" placeholder="Необязательно"></div><div class="actions"><button class="button primary" type="submit">Найти предложения</button><button class="button secondary" type="reset">Сбросить</button></div></form><p class="help">Обсудите условия лично в защищённой переписке после взаимного согласия. СТАЖНО не проверяет квалификацию и не гарантирует выполнение проектов.</p><div id="feed-list" class="feed-list" aria-live="polite"></div><section id="feed-discussion" class="panel feed-discussion" hidden></section></div><aside class="feed-side">'+composer+own+'</aside></div>';
    const filter=$('#feed-filter');
    filter.addEventListener('submit',event=>{event.preventDefault();state.feedPage=1;loadFeed().catch(error=>notice(error.message,'error'));});
    filter.addEventListener('reset',()=>setTimeout(()=>{state.feedPage=1;loadFeed().catch(error=>notice(error.message,'error'));},0));
    if(state.feedCanPublish)bindFeedForm($('#feed-compose-form'));
    if(mine)drawFeedMine(mine);
    await loadFeed().catch(error=>notice(error.message,'error'));
  }


  function savedButton(id,saved){
    return '<button type="button" class="button secondary compact" data-action="'+(saved?'remove-saved':'save-entry')+'" data-id="'+esc(id)+'" aria-pressed="'+String(saved)+'">'+(saved?'Убрать из сохранённого':'Сохранить')+'</button>';
  }
  function discoveryNav(){
    return '<nav class="discovery-nav" aria-label="Моё профессиональное пространство"><a class="button '+(mode==='discovery'?'primary':'secondary')+'" href="/community/recommendations"'+(mode==='discovery'?' aria-current="page"':'')+'>Рекомендации</a><a class="button '+(mode==='saved'?'primary':'secondary')+'" href="/community/saved"'+(mode==='saved'?' aria-current="page"':'')+'>Сохранённое</a></nav>';
  }
  function discoveryAllowed(title){
    if(!state.user){accountGate(title);return false;}
    if(!['candidate','employer'].includes(state.user.role)){
      content.innerHTML=empty('Личное пространство участника','Для сохранения и рекомендаций войдите как участник или работодатель.','<a class="button primary" href="/community/feed">К ленте</a>');return false;
    }
    return true;
  }
  async function refreshFeedSurface(){
    if(mode==='saved')return loadSaved();
    if(mode==='discovery')return loadDiscovery();
    state.feedPage=1;return loadFeed();
  }
  async function changeSaved(button){
    const id=button.dataset.id,save=button.dataset.action==='save-entry';
    const root=button.closest('article');
    await busy(root,async()=>{
      await api('/api/community/feed/saved/'+encodeURIComponent(id),{method:save?'PUT':'DELETE',body:{}});
      if(save)state.feedSavedIds.add(id);else state.feedSavedIds.delete(id);
      const message=save?'Добавлено в сохранённое.':'Удалено из сохранённого.';
      notice(message);
      if(mode==='saved'){
        try{await loadSaved();}catch(error){notice(message+' Не удалось обновить список: '+error.message,'error');}
      }else{
        for(const node of document.querySelectorAll('button[data-action="save-entry"],button[data-action="remove-saved"]')){
          if(node.dataset.id===id){
            node.dataset.action=save?'remove-saved':'save-entry';
            node.setAttribute('aria-pressed',String(save));
            node.textContent=save?'Убрать из сохранённого':'Сохранить';
          }
        }
      }
    });
  }
  async function loadSaved(){
    const request=++state.savedRequest;
    const result=await api('/api/community/feed/saved?page='+state.savedPage);
    if(request!==state.savedRequest)return;
    if(!result.records.length&&state.savedPage>1){state.savedPage=1;return loadSaved();}
    state.feedSavedIds=new Set(result.saved_entry_ids);
    state.feedFollowingIds=new Set(result.following_public_ids);
    state.feedOwnPublicId=result.own_public_id;
    state.feedCanPublish=result.can_publish;
    $('#saved-list').innerHTML=result.records.length?result.records.map(record=>record.entry?feedCard(record.entry):
      '<article class="panel feed-card" data-saved-id="'+esc(record.entry_id)+'"><h2>Запись сейчас недоступна</h2><p class="help">Автор мог скрыть публикацию или изменить настройки доступа. Мы не показываем её содержимое.</p><div class="actions">'+savedButton(record.entry_id,true)+'</div></article>'
    ).join('')+pager(result.page,result.has_more,'saved-page'):empty('Пока ничего не сохранено','Добавляйте интересные публикации и предложения, чтобы вернуться к ним позже.','<a class="button primary" href="/community/feed">Открыть ленту</a>');
  }
  async function renderSaved(){
    if(!discoveryAllowed('Сохранённое'))return;
    content.innerHTML='<div class="section-heading"><div><h1>Сохранённое</h1><p>Ваш личный список интересных материалов и предложений. Другие участники его не видят.</p></div></div>'+discoveryNav()+'<div id="saved-list" class="feed-list discovery-saved" aria-live="polite"></div><section id="feed-discussion" class="panel feed-discussion" hidden></section>';
    await loadSaved();
  }
  function applyDiscoveryForm(settings){
    const form=$('#discovery-preferences');
    state.discoveryRevision=settings.revision;
    form.elements.keyword.value=settings.keyword;
    form.elements.city.value=settings.city;
    form.elements.focus.value=settings.focus;
    $('#discovery-clear').hidden=!settings.revision;
    state.discoveryDirty=false;
  }
  function drawDiscovery(result){
    const {settings,people,feed}=result;
    state.feedFollowingIds=new Set(feed.following_public_ids);
    state.feedSavedIds=new Set(feed.saved_entry_ids);
    state.feedOwnPublicId=result.own_public_id;
    state.feedCanPublish=result.can_publish;
    const criteria=[settings.keyword?'Тема: '+settings.keyword:'',settings.city?'Город: '+settings.city:'',settings.focus?feedKinds[settings.focus]:''].filter(Boolean);
    $('#discovery-explanation').textContent=settings.revision?'Подбор по сохранённым интересам: '+criteria.join(' · ')+'. Учитываются только опубликованные материалы.':'Задайте интересы и нажмите «Сохранить интересы и подобрать». Без ваших настроек персональная подборка не создаётся.';
    $('#discovery-people').innerHTML=settings.revision?(people.people.length?'<div class="discovery-people-grid">'+people.people.map(person=>personCard(person)).join('')+'</div>'+pager(people.page,people.has_more,'discovery-people-page'):empty('Нет подходящих специалистов','Попробуйте более короткую тему, другой город или направление.')):'';
    $('#discovery-feed').innerHTML=settings.revision?(feed.entries.length?feed.entries.map(entry=>feedCard(entry)).join('')+pager(feed.page,feed.has_more,'discovery-feed-page'):empty('Нет подходящих материалов','Измените интересы или вернитесь позже.')):'';
    $('#discovery-results').hidden=!settings.revision;
  }
  async function loadDiscovery(){
    const request=++state.discoveryRequest;
    const result=await api('/api/community/recommendations?'+new URLSearchParams({people_page:String(state.discoveryPeoplePage),feed_page:String(state.discoveryFeedPage)}));
    if(request!==state.discoveryRequest)return;
    drawDiscovery(result);
  }
  function saveDiscovery(form){
    const fields=Object.fromEntries(new FormData(form));
    const body={keyword:fields.keyword,city:fields.city,focus:fields.focus,expected_revision:state.discoveryRevision};
    return busy(form,async()=>{
      const result=await api('/api/community/recommendations/preferences',{method:'PUT',body});
      applyDiscoveryForm(result.settings);
      state.discoveryPeoplePage=state.discoveryFeedPage=1;
      notice('Профессиональные интересы сохранены.');
      try{await loadDiscovery();}catch(error){notice('Интересы сохранены. Не удалось обновить подборку: '+error.message,'error');}
    });
  }
  function clearDiscovery(){
    confirmAction('Очистить интересы?','Сохранённые настройки рекомендаций будут удалены. Ваши сохранённые публикации и подписки останутся.','Очистить',async()=>{
      const result=await api('/api/community/recommendations/preferences',{method:'DELETE',body:{expected_revision:state.discoveryRevision}});
      applyDiscoveryForm(result.settings);
      state.discoveryPeoplePage=state.discoveryFeedPage=1;
      notice('Интересы очищены.');
      await loadDiscovery();
    });
  }
  async function renderDiscovery(){
    if(!discoveryAllowed('Рекомендации для меня'))return;
    const initial=await api('/api/community/recommendations');
    content.innerHTML='<div class="section-heading"><div><h1>Рекомендации для меня</h1><p>Найдите коллег, материалы, наставников и проекты по темам, которые интересны именно вам.</p></div></div>'+discoveryNav()+'<section class="panel"><form id="discovery-preferences" class="feed-form discovery-form"><h2>Мои профессиональные интересы</h2><p class="help">Настройки приватны. Мы не используем закрытые резюме, личную переписку или историю поведения.</p><div class="field"><label for="discovery-keyword">Профессия, навык или тема</label><input id="discovery-keyword" name="keyword" maxlength="100" placeholder="Например, водоочистка"></div><div class="field"><label for="discovery-city">Город (необязательно)</label><input id="discovery-city" name="city" maxlength="80" placeholder="Например, Подольск"></div><div class="field"><label for="discovery-focus">Направление</label><select id="discovery-focus" name="focus">'+options(feedCategories,'','Любое направление')+'</select></div><div class="actions"><button type="submit" class="button primary">Сохранить интересы и подобрать</button><button type="button" id="discovery-clear" class="button secondary" data-action="clear-discovery" hidden>Очистить настройки</button></div></form></section><p id="discovery-explanation" class="help" aria-live="polite"></p><section id="discovery-results" hidden><div class="section-heading"><h2>Специалисты</h2></div><div id="discovery-people" aria-live="polite"></div><section class="section-divider"><h2>Публикации и предложения</h2><p class="help">Предложения по наставничеству и проектам подбираются по выбранному направлению и указанной теме.</p><div id="discovery-feed" class="feed-list" aria-live="polite"></div></section></section><section id="feed-discussion" class="panel feed-discussion" hidden></section>';
    const form=$('#discovery-preferences');
    applyDiscoveryForm(initial.settings);
    drawDiscovery(initial);
    form.addEventListener('input',()=>{state.discoveryDirty=true;});
    form.addEventListener('submit',event=>{event.preventDefault();saveDiscovery(form);});
  }


  const portfolioKinds={project:'Реализованный проект',achievement:'Достижение',experience:'Практический опыт'};
  const portfolioStatuses={draft:'Черновик',pending:'На проверке',published:'Одобрено',rejected:'Нужны изменения',hidden:'Скрыто'};
  function shareProfile(publicId, invitation=false){
    const url=new URL(publicId?'/people/'+encodeURIComponent(publicId):'/community',location.origin).href;
    const intro=invitation?'Пригласите знакомого коллегу: самостоятельно отправьте ссылку. СТАЖНО не собирает адреса получателей и не отправляет приглашения за вас.':'Скопируйте ссылку и самостоятельно отправьте её коллегам. Она открывает только опубликованные сведения, без контактов аккаунта.';
    openDialog(invitation?'Пригласить коллегу':'Поделиться профессиональным профилем','<p>'+esc(intro)+'</p><div class="field"><label for="share-profile-url">'+(invitation?'Ссылка для приглашения':'Ссылка на профиль')+'</label><input id="share-profile-url" type="url" readonly value="'+esc(url)+'"></div><div class="actions"><button type="button" class="button primary" id="copy-profile-url">Скопировать ссылку</button><button type="button" class="button secondary" data-close-dialog>Закрыть</button></div><p id="share-profile-result" class="help" role="status"></p>');
    const field=$('#share-profile-url');field.focus();field.select();
    $('#copy-profile-url').addEventListener('click',async()=>{
      try{await navigator.clipboard.writeText(url);$('#share-profile-result').textContent='Ссылка скопирована.';}
      catch{field.focus();field.select();$('#share-profile-result').textContent='Скопируйте выделенную ссылку вручную.';}
    });
  }
  function portfolioFacts(entry){
    return '<div class="portfolio-facts"><span class="tag">'+esc(portfolioKinds[entry.kind])+'</span>'+(entry.period?'<span class="help">'+esc(entry.period)+'</span>':'')+'</div><h3>'+esc(entry.title)+'</h3><h4>Мой вклад</h4><p class="multiline">'+esc(entry.contribution)+'</p><h4>Результат</h4><p class="multiline">'+esc(entry.result)+'</p>';
  }
  function portfolioCard(entry,admin=false){
    const id=esc(entry.id),v=Number(entry.version);
    let actions='';
    if(admin){
      if(entry.status==='pending')actions='<button type="button" class="button primary compact" data-action="approve-portfolio" data-id="'+id+'" data-version="'+v+'">Одобрить</button><button type="button" class="button secondary compact" data-action="reject-portfolio" data-id="'+id+'" data-version="'+v+'">Вернуть на доработку</button>';
      if(entry.status==='published')actions='<button type="button" class="button danger compact" data-action="hide-portfolio" data-id="'+id+'" data-version="'+v+'">Скрыть</button>';
    }else{
      actions=state.portfolioRestricted?'':'<button type="button" class="button secondary compact" data-action="edit-portfolio" data-id="'+id+'">Редактировать</button>';
      if(!['pending','published'].includes(entry.status)&&state.portfolioCanPublish)actions+=' <button type="button" class="button primary compact" data-action="submit-portfolio" data-id="'+id+'" data-version="'+v+'">Отправить на проверку</button>';
      if(['pending','published'].includes(entry.status))actions+=' <button type="button" class="button secondary compact" data-action="withdraw-portfolio" data-id="'+id+'" data-version="'+v+'">Скрыть и отозвать согласие</button>';
    }
    return '<article class="panel portfolio-card" data-portfolio-id="'+id+'"><div class="status-line">'+statusBadge(entry.status,portfolioStatuses)+'</div>'+
      (admin?'<p class="help">Автор: '+(entry.profile_status==='published'?'<a href="/people/'+encodeURIComponent(entry.public_id)+'">'+esc(entry.public_name)+'</a>':'Профиль сейчас не опубликован')+' '+esc(entry.headline||'')+'</p>':'')+
      portfolioFacts(entry)+(entry.moderation_reason?'<p class="notice warning">Комментарий модератора: '+esc(entry.moderation_reason)+'</p>':'')+
      (actions?'<div class="actions">'+actions+'</div>':'')+'</article>';
  }
  function showPortfolioForm(entry=null){
    const section=$('#portfolio-editor');
    state.portfolioEdit=entry;
    state.portfolioDirty=false;
    section.hidden=false;
    section.innerHTML='<form id="portfolio-form" class="feed-form"><h2>'+(entry?'Редактировать запись':'Добавить запись')+'</h2><div class="field"><label for="portfolio-kind">Вид опыта</label><select id="portfolio-kind" name="kind">'+options(portfolioKinds,entry?.kind||'project')+'</select></div><div class="field"><label for="portfolio-title">Название</label><input id="portfolio-title" name="title" maxlength="120" minlength="3" required value="'+esc(entry?.title||'')+'" placeholder="Например, внедрение складского учёта"></div><div class="field"><label for="portfolio-period">Период (необязательно)</label><input id="portfolio-period" name="period" maxlength="60" value="'+esc(entry?.period||'')+'" placeholder="Например, 2020–2024"></div><div class="field"><label for="portfolio-contribution">Что именно вы сделали</label><textarea id="portfolio-contribution" name="contribution" rows="5" minlength="10" maxlength="1200" required>'+esc(entry?.contribution||'')+'</textarea></div><div class="field"><label for="portfolio-result">Какой получился результат</label><textarea id="portfolio-result" name="result" rows="4" minlength="3" maxlength="1000" required>'+esc(entry?.result||'')+'</textarea></div><p class="help">Не указывайте контакты, ссылки, чужие персональные данные и сведения, составляющие коммерческую тайну. Пишите только о собственном вкладе. Сохранение не публикует запись.</p>'+(entry&&['pending','published'].includes(entry.status)?'<p class="notice warning">Изменение текста снимет только эту запись с публикации или проверки. Основной профиль останется без изменений.</p>':'')+'<div class="actions"><button class="button primary" type="submit">Сохранить черновик</button><button type="button" class="button secondary" data-action="cancel-portfolio">Отмена</button></div></form>';
    const form=$('#portfolio-form');
    form.addEventListener('input',()=>{state.portfolioDirty=true;});
    form.addEventListener('submit',event=>{
      event.preventDefault();
      const fields=Object.fromEntries(new FormData(form));
      const fingerprint=JSON.stringify(fields);
      if(form.portfolioFingerprint!==fingerprint){form.portfolioFingerprint=fingerprint;form.portfolioClientKey=crypto.randomUUID();}
      const target=entry?'/api/community/portfolio/'+encodeURIComponent(entry.id):'/api/community/portfolio';
      busy(form,async()=>{
        const result=await api(target,{method:entry?'PUT':'POST',body:entry?{...fields,expected_version:entry.version}:{...fields,client_key:form.portfolioClientKey}});
        state.portfolioDirty=false;
        state.portfolioEdit=null;
        section.hidden=true;
        section.innerHTML='';
        const changed=result.entry;
        state.portfolioEntries=[changed,...state.portfolioEntries.filter(item=>item.id!==changed.id)];
        drawPortfolio();
        notice('Черновик сохранён. Для публикации отправьте запись на проверку.');
        try{await loadPortfolio();}catch(error){notice('Запись сохранена. Не удалось обновить список: '+error.message,'error');}
      });
    });
    $('#portfolio-title').focus();
    section.scrollIntoView({block:'start'});
  }
  function switchPortfolioEditor(entry){
    if(state.portfolioDirty)confirmAction('Заменить несохранённый черновик?','Введённые изменения будут потеряны.','Продолжить',async()=>showPortfolioForm(entry));
    else showPortfolioForm(entry);
  }
  function cancelPortfolioEditor(){
    const clear=()=>{state.portfolioEdit=null;state.portfolioDirty=false;$('#portfolio-editor').hidden=true;$('#portfolio-editor').innerHTML='';};
    if(state.portfolioDirty)confirmAction('Закрыть редактор?','Несохранённые изменения будут потеряны.','Закрыть',async()=>clear());
    else clear();
  }
  function drawPortfolio(){
    $('#portfolio-list').innerHTML=state.portfolioEntries.length?state.portfolioEntries.map(entry=>portfolioCard(entry)).join(''):empty('Пока нет записей','Добавьте первый проект, достижение или пример своего опыта.');
  }
  async function loadPortfolio(){
    const request=++state.portfolioRequest;
    const result=await api('/api/community/portfolio');
    if(request!==state.portfolioRequest)return;
    state.portfolioEntries=result.entries;
    state.portfolioCanPublish=result.can_publish;
    state.portfolioRestricted=Boolean(result.restricted);
    $('#portfolio-add').disabled=state.portfolioRestricted||!result.has_profile||result.entries.length>=result.limit;
    $('#portfolio-capacity').textContent='Записей: '+result.entries.length+' из '+result.limit;
    $('#portfolio-publication-hint').innerHTML=state.portfolioRestricted?'<p>Обработка данных ограничена. Доступны история и отзыв согласия.</p>':result.can_publish?'<a href="/people/'+encodeURIComponent(result.public_id)+'">Открыть публичный профиль →</a>':'<p>Черновики можно готовить после сохранения профиля. Отправить запись на проверку можно после его публикации.</p><a href="/community/profile">Мой профессиональный профиль →</a>';
    drawPortfolio();
  }
  function submitPortfolio(button){
    const id=button.dataset.id,version=Number(button.dataset.version);
    const entry=state.portfolioEntries.find(item=>item.id===id);
    if(!entry)return;
    if(state.portfolioDirty&&state.portfolioEdit?.id===id){notice('Сначала сохраните изменения этой записи.','error');return;}
    openDialog('Опубликовать запись портфолио?','<div class="portfolio-consent-preview">'+portfolioFacts(entry)+'</div><form id="portfolio-submit-form" class="dialog-form"><label class="consent-label"><input type="checkbox" name="publish_consent" required><span>Я согласен на публичный показ этой записи после проверки модератором. Её сможет прочитать любой посетитель опубликованного профиля. Я могу отозвать согласие.</span></label><button class="button primary" type="submit">Отправить на проверку</button></form>');
    const form=$('#portfolio-submit-form');
    form.addEventListener('submit',event=>{event.preventDefault();busy(form,async()=>{
      await api('/api/community/portfolio/'+encodeURIComponent(id)+'/submit',{method:'POST',body:{expected_version:version,publish_consent:true}});
      dialogBusy=false;closeDialog();notice('Запись отправлена на проверку.');await loadPortfolio();
    });});
  }
  async function loadPortfolioReview(){
    const request=++state.portfolioReviewRequest;
    const status=$('#portfolio-review-status').value;
    const result=await api('/api/admin/community/portfolio?'+new URLSearchParams({status,page:String(state.portfolioReviewPage)}));
    if(request!==state.portfolioReviewRequest)return;
    $('#portfolio-review-list').innerHTML=result.entries.length?result.entries.map(entry=>portfolioCard(entry,true)).join('')+pager(result.page,result.has_more,'portfolio-review-page'):empty('Нет записей в очереди','Выберите другой статус или обновите очередь.');
  }
  function moderatePortfolio(button){
    const {id,version,action}=button.dataset,decision=action.replace('-portfolio','');
    openDialog(decision==='approve'?'Одобрить запись?':decision==='reject'?'Вернуть запись на доработку?':'Скрыть запись?','<form id="portfolio-review-form" class="dialog-form"><p>Убедитесь, что текст не содержит контактов, чужих данных и недостоверных обещаний. Модерация не подтверждает квалификацию.</p>'+(decision==='approve'?'':'<div class="field"><label for="portfolio-reason">Причина для автора</label><textarea id="portfolio-reason" name="reason" maxlength="500" required></textarea></div>')+'<button type="submit" class="button primary">Подтвердить</button></form>');
    const form=$('#portfolio-review-form');
    form.addEventListener('submit',event=>{event.preventDefault();const reason=form.elements.reason?.value||'';busy(form,async()=>{
      await api('/api/admin/community/portfolio/'+encodeURIComponent(id),{method:'PATCH',body:{decision,reason,expected_version:Number(version)}});
      dialogBusy=false;closeDialog();notice('Решение сохранено.');await loadPortfolioReview();
    });});
  }
  async function renderPortfolio(){
    if(!state.user)return accountGate('Моё портфолио');
    if(state.user.role==='admin'){
      content.innerHTML='<div class="section-heading"><div><h1>Модерация портфолио</h1><p>Отдельная проверка проектов и достижений участников.</p></div><a class="button secondary" href="/community/moderation">Модерация профилей</a></div><div class="connections-toolbar"><label for="portfolio-review-status">Статус<select id="portfolio-review-status">'+options({pending:'На проверке',published:'Одобрено'},'pending')+'</select></label><button class="button secondary" type="button" data-action="refresh-portfolio-review">Обновить</button></div><div id="portfolio-review-list" class="moderation-grid"></div>';
      $('#portfolio-review-status').addEventListener('change',()=>{state.portfolioReviewPage=1;loadPortfolioReview().catch(error=>notice(error.message,'error'));});
      await loadPortfolioReview();return;
    }
    if(state.user.role!=='candidate'){content.innerHTML=empty('Портфолио участника','Профессиональные записи создают участники с личным профилем.','<a class="button primary" href="/community">Найти специалистов</a>');return;}
    content.innerHTML='<div class="section-heading"><div><h1>Моё портфолио</h1><p>Расскажите, что вы сделали, какую задачу решили и какой результат получили.</p></div><a class="button secondary" href="/community/profile">Мой профиль</a></div><section class="panel portfolio-intro"><h2>Ваш опыт в конкретных примерах</h2><p>Каждая запись имеет собственный черновик, согласие на публикацию и статус проверки. Изменение записи не скрывает основной профиль.</p><p class="help" id="portfolio-publication-hint"></p><div class="actions"><button id="portfolio-add" type="button" class="button primary" data-action="new-portfolio" disabled>Добавить проект или достижение</button><button type="button" class="button secondary" data-action="refresh-portfolio">Обновить</button></div><p class="help" id="portfolio-capacity"></p></section><section id="portfolio-editor" class="panel portfolio-editor" hidden></section><div id="portfolio-list" class="portfolio-list" aria-live="polite"></div>';
    await loadPortfolio();
  }

  const reputationStates={offered:'Ожидает согласия получателя',pending:'На проверке',published:'Опубликована',rejected:'Нужны изменения',hidden:'Скрыта'};
  function reputationFacts(entry){
    return '<h3>'+esc(entry.skill)+'</h3><h4>Контекст работы</h4><p class="multiline">'+esc(entry.context)+'</p><h4>Рекомендация</h4><p class="multiline">'+esc(entry.body)+'</p>';
  }
  function reputationName(publicId,name){
    return publicId?'<a href="/people/'+encodeURIComponent(publicId)+'">'+esc(name)+'</a>':'Профиль недоступен';
  }
  function reputationCard(entry,admin){
    const id=esc(entry.id),v=Number(entry.version);
    const button=(action,label,kind='secondary')=>'<button class="button '+kind+' compact" type="button" data-action="'+action+'" data-id="'+id+'" data-version="'+v+'">'+label+'</button>';
    let identity='',actions='';
    if(admin){
      identity='<p class="help">Автор: '+reputationName(entry.author_public_id,entry.author_public_name)+'<br>Получатель: '+reputationName(entry.recipient_public_id,entry.recipient_public_name)+'</p>';
      if(entry.status==='pending')actions=button('approve-reputation','Одобрить','primary')+button('reject-reputation','Вернуть на доработку');
      if(entry.status==='published')actions=button('hide-reputation','Скрыть','danger');
    }else{
      identity='<p class="help">'+(entry.direction==='incoming'?'От коллеги: ':'Для коллеги: ')+reputationName(entry.counterpart_public_id,entry.counterpart_public_name)+'</p>';
      if(!state.reputationRestricted&&entry.direction==='incoming'&&entry.status==='offered')actions=button('accept-reputation','Согласиться на публикацию','primary')+button('decline-reputation','Отклонить');
      else if(['offered','pending','published','rejected'].includes(entry.status))actions=button('withdraw-reputation','Отозвать согласие');
      if(!state.reputationRestricted&&entry.direction==='outgoing'&&entry.status==='rejected')actions+='<a class="button secondary compact" href="/community/reputation?connection='+encodeURIComponent(entry.connection_id)+'">Подготовить новую редакцию</a>';
    }
    return '<article class="panel portfolio-card" data-recommendation-id="'+id+'"><div class="status-line">'+statusBadge(entry.status,reputationStates)+'</div>'+identity+reputationFacts(entry)+(entry.moderation_reason?'<p class="notice warning">Комментарий модератора: '+esc(entry.moderation_reason)+'</p>':'')+(actions?'<div class="actions">'+actions+'</div>':'')+'</article>';
  }
  async function loadReputation(){
    const request=++state.reputationRequest,admin=state.user.role==='admin';
    const params=new URLSearchParams({page:String(state.reputationPage)});
    params.set(admin?'status':'direction', $('#reputation-filter').value);
    const result=await api((admin?'/api/admin/community/reputation':'/api/community/reputation')+'?'+params);
    if(request!==state.reputationRequest)return;
    state.reputationRestricted=Boolean(result.restricted);
    const restrictedNote=$('#reputation-restricted');
    if(restrictedNote)restrictedNote.hidden=!state.reputationRestricted;
    const list=$('#reputation-list');
    list.innerHTML=result.entries.length?result.entries.map(entry=>reputationCard(entry,admin)).join('')+pager(result.page,result.has_more,'reputation-page'):empty('Пока нет рекомендаций',admin?'В этой очереди пока нет записей.':'Рекомендации появляются после профессионального знакомства и согласия автора.');
  }
  async function showRecommendationEditor(connectionId){
    if(state.reputationRestricted){notice('Доступны история и отзыв согласия. Новые рекомендации ограничены.','error');return;}
    const slot=$('#reputation-editor');
    const result=await api('/api/community/connections/'+encodeURIComponent(connectionId));
    const c=result.connection;
    if(c.status!=='accepted'||c.counterpart.role!=='candidate'||!c.counterpart.public_id){slot.innerHTML='<p class="notice warning">Нужно принятое знакомство с участником, имеющим опубликованный профиль.</p>';slot.hidden=false;return;}
    slot.hidden=false;
    slot.innerHTML='<form id="recommendation-form" class="feed-form"><h2>Рекомендовать коллегу</h2><p>Получатель: '+reputationName(c.counterpart.public_id,c.counterpart.public_name)+'</p><div class="field"><label for="recommendation-skill">Компетенция</label><input id="recommendation-skill" name="skill" minlength="3" maxlength="100" required placeholder="Например, обучение сотрудников"></div><div class="field"><label for="recommendation-context">Где вы наблюдали эту компетенцию</label><textarea id="recommendation-context" name="context" minlength="10" maxlength="200" rows="3" required placeholder="Например, вместе организовывали обучение команды"></textarea></div><div class="field"><label for="recommendation-body">В чём коллега показал себя</label><textarea id="recommendation-body" name="body" minlength="20" maxlength="1000" rows="5" required></textarea></div><p class="help">Указывайте только лично наблюдаемый опыт. Не включайте чужие персональные данные, контакты, ссылки или коммерческую тайну.</p><label class="consent-label"><input type="checkbox" name="publish_consent" required><span>Согласен на публикацию моего публичного имени и этой рекомендации после согласия коллеги и модерации. Я могу отозвать согласие.</span></label><div class="actions"><button class="button primary" type="submit">Предложить рекомендацию</button><button class="button secondary" type="button" data-action="cancel-recommendation">Отмена</button></div></form>';
    const form=$('#recommendation-form');
    form.addEventListener('input',()=>{state.reputationDirty=true;});
    form.addEventListener('submit',event=>{
      event.preventDefault();
      const fields=Object.fromEntries(new FormData(form));fields.publish_consent=form.elements.publish_consent.checked;
      const fingerprint=JSON.stringify(fields);
      if(form.reputationFingerprint!==fingerprint){form.reputationFingerprint=fingerprint;form.reputationClientKey=crypto.randomUUID();}
      busy(form,async()=>{
        await api('/api/community/reputation',{method:'POST',body:{...fields,connection_id:connectionId,client_key:form.reputationClientKey}});
        state.reputationDirty=false;slot.hidden=true;slot.innerHTML='';
        const url=new URL(location.href);url.searchParams.delete('connection');history.replaceState(null,'',url);
        $('#reputation-filter').value='outgoing';state.reputationPage=1;
        notice('Рекомендация предложена коллеге. До его согласия и проверки она не будет опубликована.');
        await loadReputation();
      });
    });
    $('#recommendation-skill').focus();slot.scrollIntoView({block:'start'});
  }
  function cancelRecommendation(){
    const clear=()=>{state.reputationDirty=false;const slot=$('#reputation-editor');slot.hidden=true;slot.innerHTML='';const url=new URL(location.href);url.searchParams.delete('connection');history.replaceState(null,'',url);};
    if(state.reputationDirty)confirmAction('Закрыть редактор?','Введённая рекомендация не сохранится.','Закрыть',async()=>clear());
    else clear();
  }
  function acceptReputation(button){
    const id=button.dataset.id,version=Number(button.dataset.version),card=button.closest('article');
    openDialog('Согласие на публикацию рекомендации','<p>Проверьте весь текст рекомендации. После одобрения модератором она появится в вашем публичном профиле. Отозвать согласие можно в любое время.</p><div class="portfolio-consent-preview"><p class="multiline">'+esc(card.querySelector('h3').textContent)+'</p>'+[...card.querySelectorAll('h4,.multiline')].map(el=>'<p class="multiline">'+esc(el.textContent)+'</p>').join('')+'</div><form id="reputation-consent-form" class="dialog-form"><label class="consent-label"><input type="checkbox" required name="publish_consent"><span>Согласен на публичное размещение этой рекомендации в моём профессиональном профиле.</span></label><button class="button primary" type="submit">Отправить на проверку</button></form>');
    const form=$('#reputation-consent-form');form.addEventListener('submit',event=>{event.preventDefault();busy(form,async()=>{
      await api('/api/community/reputation/'+encodeURIComponent(id)+'/respond',{method:'POST',body:{decision:'accept',expected_version:version,publish_consent:form.elements.publish_consent.checked}});
      dialogBusy=false;closeDialog();notice('Согласие получено. Рекомендация отправлена на модерацию.');await loadReputation();
    });});
  }
  function moderateReputation(button){
    const {id,version,action}=button.dataset,decision=action.replace('-reputation','');
    openDialog(decision==='approve'?'Одобрить рекомендацию?':decision==='reject'?'Вернуть на доработку?':'Скрыть рекомендацию?','<form id="reputation-review-form" class="dialog-form"><p>Проверяйте содержание, отсутствие контактов, чужих данных, спама и недостоверных обещаний. Одобрение не удостоверяет квалификацию.</p>'+(decision==='approve'?'':'<div class="field"><label for="reputation-reason">Причина</label><textarea id="reputation-reason" name="reason" maxlength="500" required></textarea></div>')+'<button type="submit" class="button primary">Подтвердить</button></form>');
    const form=$('#reputation-review-form');form.addEventListener('submit',event=>{event.preventDefault();const reason=form.elements.reason?.value||'';busy(form,async()=>{
      await api('/api/admin/community/reputation/'+encodeURIComponent(id),{method:'PATCH',body:{decision,reason,expected_version:Number(version)}});
      dialogBusy=false;closeDialog();notice('Решение сохранено.');await loadReputation();
    });});
  }
  async function renderReputation(){
    if(!state.user)return accountGate('Рекомендации коллег');
    const admin=state.user.role==='admin';
    if(!admin&&state.user.role!=='candidate'){content.innerHTML=empty('Рекомендации участников','Рекомендации доступны между участниками с опубликованными личными профилями.','<a class="button secondary" href="/community">К участникам</a>');return;}
    content.innerHTML='<div class="section-heading"><div><h1>'+(admin?'Модерация рекомендаций':'Рекомендации коллег')+'</h1><p>'+(admin?'Только записи с согласием обеих сторон.':'Профессиональная репутация основана на конкретном опыте, а не на звёздах или баллах.')+'</p></div><a class="button secondary" href="'+(admin?'/community/moderation':'/community/profile')+'">'+(admin?'Модерация профилей':'Мой профиль')+'</a></div>'+(admin?'':'<section class="panel portfolio-intro"><h2>Расскажите о работе с коллегой</h2><p>Выберите принятое знакомство в разделе «Мои связи». Рекомендация видна публично только после согласия обеих сторон и проверки модератором. Она не подтверждает квалификацию.</p><div class="actions"><a class="button primary" href="/community/connections">Выбрать коллегу</a><button class="button secondary" type="button" data-action="invite-colleague">Пригласить коллегу</button></div></section><p class="notice warning" id="reputation-restricted" hidden>Обработка данных ограничена. Доступны история и отзыв согласия.</p><section id="reputation-editor" class="panel portfolio-editor" hidden></section>')+'<div class="connections-toolbar reputation-toolbar"><label for="reputation-filter">'+(admin?'Статус':'Показать')+'<select id="reputation-filter">'+options(admin?{pending:'На проверке',published:'Опубликованы'}:{incoming:'Полученные',outgoing:'Написанные'},admin?'pending':'incoming')+'</select></label><button class="button secondary" type="button" data-action="refresh-reputation">Обновить</button></div><div id="reputation-list" class="portfolio-list" aria-live="polite"></div>';
    $('#reputation-filter').addEventListener('change',()=>{state.reputationPage=1;loadReputation().catch(error=>notice(error.message,'error'));});
    await loadReputation();
    if(!admin){
      const connectionId=new URLSearchParams(location.search).get('connection');
      if(connectionId&&/^[a-f0-9-]{20,64}$/i.test(connectionId)){try{await showRecommendationEditor(connectionId);}catch(error){notice(error.message,'error');}}
    }
  }

  const authorKinds={article:'Экспертная статья',case:'Профессиональный кейс',learning:'Учебный материал'};
  const authorStates={draft:'Черновик',pending:'На редакционной проверке',published:'Опубликован',rejected:'На доработке',hidden:'Скрыт'};
  const authorApi='/api/community/author-articles';
  const authorAdminApi='/api/admin/community/author-articles';
  function authorCard(entry,admin){
    const id=esc(entry.id),version=Number(entry.version);
    const btn=(action,label,kind='secondary')=>'<button type="button" class="button '+kind+' compact" data-action="'+action+'" data-id="'+id+'" data-version="'+version+'">'+label+'</button>';
    let actions='',byline='';
    if(admin){
      byline='<p class="help">Автор: <a href="/people/'+encodeURIComponent(entry.author_public_id)+'">'+esc(entry.author_public_name)+'</a></p>';
      if(entry.status==='pending')actions=btn('author-approve','Одобрить и опубликовать','primary')+btn('author-reject','Вернуть автору');
      else if(entry.status==='published')actions=btn('author-hide','Скрыть','danger');
    }else{
      if(!state.authorRestricted){
        actions=btn('author-edit','Редактировать');
        if(state.authorCanSubmit&&['draft','hidden','rejected'].includes(entry.status))actions+=btn('author-submit','Отправить в редакцию','primary');
      }
      if(['pending','published','rejected'].includes(entry.status))actions+=btn('author-withdraw','Отозвать согласие');
    }
    if(entry.public_path)actions+='<a class="button secondary compact" href="/journal/author-'+encodeURIComponent(entry.id)+'">Читать в журнале</a>';
    return '<article class="panel portfolio-card" data-author-id="'+id+'"><div class="status-line">'+statusBadge(entry.status,authorStates)+'<span class="tag">'+esc(authorKinds[entry.kind])+'</span></div>'+byline+
      '<h2>'+esc(entry.title)+'</h2><p class="multiline">'+esc(entry.description)+'</p>'+
      (entry.status==='published'&&!entry.public_path?'<p class="notice warning">Материал временно недоступен публично.</p>':'')+
      (entry.moderation_reason?'<p class="notice warning">Комментарий редакции: '+esc(entry.moderation_reason)+'</p>':'')+
      '<details class="author-full-text"><summary>Полный текст материала</summary><p class="multiline">'+esc(entry.body_text)+'</p></details>'+
      (actions?'<div class="actions">'+actions+'</div>':'')+'</article>';
  }
  async function loadAuthors(){
    const req=++state.authorRequest,admin=state.user.role==='admin';
    const result=await api(admin?authorAdminApi+'?status='+encodeURIComponent($('#author-filter').value)+'&page='+state.authorPage:authorApi);
    if(req!==state.authorRequest)return;
    state.authorEntries=result.entries;
    if(!admin){
      state.authorTopics=result.topics;state.authorCanSubmit=Boolean(result.can_submit);state.authorRestricted=Boolean(result.restricted);
      $('#author-add').disabled=state.authorRestricted||!result.has_profile||result.entries.length>=result.limit;
      $('#author-hint').textContent=state.authorRestricted?'Обработка данных ограничена. Доступны история и отзыв согласия.':
        !result.has_profile?'Сначала сохраните профессиональный профиль.':
        !result.can_submit?'Черновики доступны. Для передачи в редакцию опубликуйте профессиональный профиль.':
        'Материал появится в журнале только после вашего отдельного согласия и решения редактора.';
      $('#author-count').textContent='Материалы: '+result.entries.length+' из '+result.limit;
    }
    $('#author-list').innerHTML=result.entries.length?result.entries.map(entry=>authorCard(entry,admin)).join('')+(admin?pager(result.page,result.has_more,'author-page'):''):empty('Пока нет материалов',admin?'В этой очереди нет материалов.':'Подготовьте первую экспертную статью или профессиональный кейс.');
  }
  function showAuthorEditor(entry=null){
    const slot=$('#author-editor');state.authorEdit=entry;state.authorDirty=false;slot.hidden=false;
    const topics=Object.entries(state.authorTopics).map(([key,label])=>'<label class="consent-label"><input type="checkbox" name="topics" value="'+esc(key)+'"'+(entry?.topics?.includes(key)?' checked':'')+'><span>'+esc(label)+'</span></label>').join('');
    slot.innerHTML='<form id="author-form" class="feed-form"><h2>'+(entry?'Редактирование материала':'Новый материал')+'</h2><div class="field"><label for="author-kind">Тип материала</label><select id="author-kind" name="kind">'+options(authorKinds,entry?.kind||'article')+'</select></div>'+
      '<div class="field"><label for="author-title">Заголовок</label><input id="author-title" name="title" required minlength="8" maxlength="180" value="'+esc(entry?.title||'')+'"></div>'+
      '<div class="field"><label for="author-description">Краткое описание</label><textarea id="author-description" name="description" rows="3" required minlength="25" maxlength="350">'+esc(entry?.description||'')+'</textarea></div>'+
      '<fieldset class="author-topics"><legend>Темы (можно выбрать несколько)</legend><div class="author-topic-grid">'+topics+'</div></fieldset>'+
      '<div class="field"><label for="author-body">Текст материала</label><p class="help">Начните каждый раздел с ## Название раздела. Нужно не менее двух разделов. Абзацы разделяйте пустой строкой. Строка с «- » создаёт пункт списка.</p><textarea id="author-body" name="body_text" rows="14" required minlength="200" maxlength="12000" placeholder="## Постановка задачи&#10;Опишите проблему и свой подход…&#10;&#10;## Практический результат&#10;Расскажите, что получилось…">'+esc(entry?.body_text||'')+'</textarea></div>'+
      '<p class="help">Только ваш собственный текст. Не добавляйте контакты, ссылки, чужие личные сведения, коммерческие секреты и чужие тексты без разрешения.</p>'+
      (entry&&['published','pending'].includes(entry.status)?'<p class="notice warning">Изменение текста снимет материал с публикации или проверки. Потребуется новое согласие и решение редактора.</p>':'')+
      '<div class="actions"><button type="submit" class="button primary">Сохранить черновик</button><button type="button" class="button secondary" data-action="author-cancel">Отмена</button></div></form>';
    const form=$('#author-form');
    form.addEventListener('input',()=>{state.authorDirty=true;});
    form.addEventListener('change',()=>{state.authorDirty=true;});
    form.addEventListener('submit',event=>{
      event.preventDefault();const data=new FormData(form);
      const fields={kind:data.get('kind'),title:data.get('title'),description:data.get('description'),body_text:data.get('body_text'),topics:data.getAll('topics')};
      const fingerprint=JSON.stringify(fields);
      if(form.authorFingerprint!==fingerprint){form.authorFingerprint=fingerprint;form.authorClientKey=crypto.randomUUID();}
      busy(form,async()=>{
        const result=await api(entry?authorApi+'/'+encodeURIComponent(entry.id):authorApi,{method:entry?'PUT':'POST',body:entry?{...fields,expected_version:entry.version}:{...fields,client_key:form.authorClientKey}});
        state.authorDirty=false;state.authorEdit=null;slot.hidden=true;slot.innerHTML='';
        state.authorEntries=[result.entry,...state.authorEntries.filter(item=>item.id!==result.entry.id)];
        $('#author-list').innerHTML=state.authorEntries.map(item=>authorCard(item,false)).join('');
        notice('Материал сохранён. Для публикации отправьте его в редакцию.');
        try{await loadAuthors();}catch(error){notice('Материал сохранён, но список не обновился: '+error.message,'warning');}
      });
    });
    $('#author-title').focus();slot.scrollIntoView({block:'start'});
  }
  function switchAuthorEditor(entry){
    if(state.authorRestricted)return;
    if(state.authorDirty)confirmAction('Заменить черновик?','Несохранённые изменения будут потеряны.','Продолжить',async()=>showAuthorEditor(entry));
    else showAuthorEditor(entry);
  }
  function cancelAuthorEditor(){
    const clear=()=>{state.authorDirty=false;state.authorEdit=null;const slot=$('#author-editor');slot.hidden=true;slot.innerHTML='';};
    if(state.authorDirty)confirmAction('Закрыть редактор?','Несохранённые изменения будут потеряны.','Закрыть',async()=>clear());
    else clear();
  }
  function submitAuthor(entry){
    if(!entry||state.authorRestricted)return;
    if(state.authorDirty&&state.authorEdit?.id===entry.id){notice('Сначала сохраните изменения материала.','warning');return;}
    openDialog('Предложить материал редакции','<p>Проверьте текст, который будет размещён в журнале под вашим публичным именем после проверки редактором.</p><div class="portfolio-consent-preview"><h3>'+esc(entry.title)+'</h3><p>'+esc(entry.description)+'</p><p class="multiline">'+esc(entry.body_text)+'</p></div><form id="author-consent-form" class="dialog-form"><label class="consent-label"><input type="checkbox" required name="publish_consent"><span>Я подтверждаю право на публикацию этого текста и согласен на его размещение в журнале СТАЖНО под моим публичным именем. Согласие можно отозвать.</span></label><button type="submit" class="button primary">Отправить на проверку</button></form>');
    const form=$('#author-consent-form');form.addEventListener('submit',event=>{event.preventDefault();busy(form,async()=>{
      await api(authorApi+'/'+encodeURIComponent(entry.id)+'/submit',{method:'POST',body:{expected_version:entry.version,publish_consent:form.elements.publish_consent.checked}});
      dialogBusy=false;closeDialog();notice('Материал отправлен на редакционную проверку.');await loadAuthors();
    });});
  }
  function reviewAuthor(entry,decision){
    if(!entry)return;
    openDialog(decision==='approve'?'Опубликовать авторский материал?':decision==='reject'?'Вернуть автору?':'Скрыть материал?','<p>Проверьте права автора, практическую ценность, достоверность, отсутствие контактов и чужих персональных данных. Редакция не изменяет согласованный текст без новой версии от автора.</p><div class="portfolio-consent-preview"><h3>'+esc(entry.title)+'</h3><p>'+esc(entry.description)+'</p><p class="multiline">'+esc(entry.body_text)+'</p></div><form id="author-review-form" class="dialog-form">'+(decision==='approve'?'':'<div class="field"><label for="author-review-reason">Причина решения</label><textarea id="author-review-reason" name="reason" maxlength="500" required></textarea></div>')+'<button class="button primary" type="submit">Подтвердить решение</button></form>');
    const form=$('#author-review-form');form.addEventListener('submit',event=>{event.preventDefault();busy(form,async()=>{
      await api(authorAdminApi+'/'+encodeURIComponent(entry.id),{method:'PATCH',body:{expected_version:entry.version,decision,reason:form.elements.reason?.value||''}});
      dialogBusy=false;closeDialog();notice('Решение редакции сохранено.');await loadAuthors();
    });});
  }
  async function renderAuthors(){
    if(!state.user)return accountGate('Авторские публикации');
    const admin=state.user.role==='admin';
    if(!admin&&state.user.role!=='candidate'){content.innerHTML=empty('Авторские публикации','Предлагать материалы могут участники с личным профессиональным профилем.','<a class="button primary" href="/journal">Читать журнал</a>');return;}
    content.innerHTML='<div class="section-heading"><div><h1>'+(admin?'Редакция: материалы участников':'Мои авторские материалы')+'</h1><p>'+(admin?'Проверяйте точный текст, согласованный с автором.':'Поделитесь знаниями и практическим опытом с профессиональным сообществом.')+'</p></div><a class="button secondary" href="/journal">Открыть журнал</a></div>'+
      (admin?'<div class="connections-toolbar"><label for="author-filter">Материалы<select id="author-filter"><option value="pending">На проверке</option><option value="published">Опубликованные</option></select></label><button type="button" class="button secondary" data-action="author-refresh">Обновить</button></div>':
      '<section class="panel portfolio-intro"><h2>Станьте автором журнала</h2><p>Экспертные статьи, профессиональные кейсы, учебные материалы. Сохраните черновик, подтвердите публикацию, дождитесь решения редакции. При изменении профиля или текста потребуется новое согласие.</p><p class="help" id="author-hint"></p><p class="help" id="author-count"></p><div class="actions"><button type="button" id="author-add" class="button primary" data-action="author-add" disabled>Новый материал</button><a class="button secondary" href="/community/profile">Мой профиль</a><button type="button" class="button secondary" data-action="author-refresh">Обновить</button></div></section><section class="panel portfolio-editor" id="author-editor" hidden></section>')+
      '<div id="author-list" class="portfolio-list" aria-live="polite"></div>';
    if(admin)$('#author-filter').addEventListener('change',()=>{state.authorPage=1;loadAuthors().catch(error=>notice(error.message,'error'));});
    await loadAuthors();
  }


  // A structured course studio. No user HTML, no markup syntax or hidden autosave.
  // The same in-memory draft survives tab changes and unsuccessful requests.
  const studio={entry:null,draft:null,step:'info',lesson:0,lessonStep:'content',view:'own',page:1,key:null,loading:false,bound:false,previewPages:new Map()};
  const studioApi='/api/community/courses';
  const studioStates={draft:'Черновик',pending:'На проверке',published:'Опубликован',rejected:'На доработке',hidden:'Скрыт'};
  const studioSteps=[['info','Карточка курса'],['lessons','Уроки и задания'],['preview','Предпросмотр'],['publish','Публикация']];
  const studioButton=(action,label,kind='secondary',extra='')=>'<button type="button" class="button '+kind+'" data-studio="'+action+'" '+extra+'>'+label+'</button>';
  const studioPath=()=>studioApi+'/'+encodeURIComponent(studio.entry.slug);
  const studioEditable=()=>studio.entry?.can_edit&&!studio.entry?.restricted;
  const studioClone=value=>JSON.parse(JSON.stringify(value));
  const newStudioQuestion=()=>({text:'',options:['','',''],correct:null,feedback:''});
  const newStudioLesson=()=>({slug:'lesson-'+crypto.randomUUID(),title:'',minutes:10,goal:'',sections:[['','']],example:'',practice:'',questions:[newStudioQuestion()],media:[]});
  function studioField(label,path,value,{area=false,max=600,rows=3,help='',type='text',placeholder=''}={}){
    const id='studio-'+path.replaceAll('.','-'),attr='id="'+id+'" data-studio-path="'+path+'" '+(type==='number'?'type="number" min="1" max="180"':'maxlength="'+max+'"')+' placeholder="'+esc(placeholder)+'"';
    return '<div class="studio-field"><label for="'+id+'">'+esc(label)+'</label>'+
      (help?'<p class="help">'+esc(help)+'</p>':'')+
      (area?'<textarea '+attr+' rows="'+rows+'">'+esc(value??'')+'</textarea>':'<input '+attr+' value="'+esc(value??'')+'">')+'</div>';
  }
  // Live completion is only a writing aid; publication always uses the
  // saved server checklist, including validation and media publication gates.
  function studioLessonCompletion(lesson){
    const text=value=>String(value??'').trim();
    const content=text(lesson.title).length>=3&&text(lesson.goal).length>=10&&
      lesson.sections.length>0&&lesson.sections.every(section=>text(section[0])&&section.slice(1).some(p=>text(p)));
    const practice=Boolean(text(lesson.example)&&text(lesson.practice));
    const quiz=lesson.questions.length>0&&lesson.questions.every(q=>{
      const options=q.options.map(text);
      return Boolean(text(q.text)&&options.length>=2&&options.every(Boolean)&&new Set(options).size===options.length&&
        Number.isInteger(q.correct)&&q.correct>=0&&q.correct<options.length&&text(q.feedback));
    });
    return {content:Boolean(content),practice,quiz};
  }
  function studioCompletionLabel(lesson){
    return Object.values(studioLessonCompletion(lesson)).filter(Boolean).length+' из 3 разделов';
  }
  function studioRefreshCompletion(){
    studio.draft.lessons.forEach((item,index)=>{
      const label=$('[data-studio-completion="'+index+'"]');
      if(label)label.textContent=studioCompletionLabel(item);
    });
    const lesson=studio.draft.lessons[studio.lesson];
    if(lesson){
      const completion=studioLessonCompletion(lesson);
      for(const [key,done] of Object.entries(completion)){
        const label=$('[data-studio-section-completion="'+key+'"]');
        if(label)label.textContent=done?'Заполнено':'Не заполнено';
      }
    }
  }
  function studioChange(){
    state.builderDirty=true;
    const badge=$('#studio-save-status');if(badge)badge.textContent='Есть несохранённые изменения';
    const save=$('#studio-save');if(save)save.disabled=false;
    const name=$('#studio-course-title');if(name)name.textContent=studio.draft.title||'Курс без названия';
    const lesson=studio.draft.lessons[studio.lesson];
    const label=$('[data-studio-lesson-label="'+studio.lesson+'"]');if(label&&lesson)label.textContent=lesson.title||'Урок без названия';
    const time=$('#studio-total-time');if(time)time.textContent=studio.draft.lessons.length+' уроков · '+studio.draft.lessons.reduce((sum,item)=>sum+(Number(item.minutes)||0),0)+' мин.';
    studioRefreshCompletion();
  }
  function studioSet(path,value){
    const parts=path.split('.');
    let target=studio.draft;
    for(const key of parts.slice(0,-1))target=target[key];
    target[parts[parts.length-1]]=value;studioChange();
  }
  function studioLeave(action){
    if(state.builderDirty)confirmAction('Есть несохранённые изменения','Если продолжить, введённый текст будет потерян. Сначала можно сохранить черновик.','Выйти без сохранения',action);
    else return action();
  }
  async function studioList(){
    const result=await api(studioApi+'?view='+studio.view+'&page='+studio.page);
    studio.entry=null;studio.draft=null;state.builderDirty=false;
    content.innerHTML='<section class="section-heading"><div><span class="eyebrow">АКАДЕМИЯ СТАЖНО</span><h1>Конструктор курсов</h1><p>Создавайте понятные учебные программы: уроки, практику и самопроверку.</p></div><a class="button secondary" href="/academy">Открыть Академию ↗</a></section>'+
      '<section class="panel studio-list-intro"><div><h2>'+(state.user.role==='admin'?'Редакция Академии':'Ваши курсы')+'</h2><p>Черновики видны только автору. Изменения опубликованного курса появятся после утверждения новой версии.</p></div>'+
      (result.can_create?studioButton('new','+ Новый курс','primary'):'')+
      (result.restricted?'<p class="notice warning">Обработка данных ограничена. Можно просматривать свои курсы и отзывать публикации.</p>':!result.can_create&&state.user.role==='candidate'?'<p class="help">Для создания курса сохраните профессиональный профиль. Максимум 10 курсов. <a href="/community/profile">Мой профиль</a></p>':'')+'</section>'+
      (state.user.role==='admin'?'<nav class="studio-tabs" aria-label="Курсы редакции">'+[['own','Курсы СТАЖНО'],['review','На проверке'],['published','Курсы участников']].map(([key,label])=>studioButton('view',label,studio.view===key?'primary':'secondary','data-view="'+key+'" aria-pressed="'+(studio.view===key)+'"')).join('')+'</nav>':'')+
      '<div class="studio-catalog">'+(result.courses.length?result.courses.map(course=>
        '<article class="panel studio-catalog-card"><div class="status-line">'+statusBadge(course.state,studioStates)+(course.has_publication?'<span class="tag">Версия доступна ученикам</span>':'')+'</div><h2>'+esc(course.title)+'</h2><p class="help">'+course.lesson_count+' уроков · '+course.minutes+' мин.</p>'+
        (course.moderation_reason?'<p class="notice warning">'+esc(course.moderation_reason)+'</p>':'')+
        '<div class="actions">'+studioButton('open',course.can_edit?'Открыть редактор':'Проверить курс','primary','data-slug="'+esc(course.slug)+'"')+
        (course.has_publication?'<a class="button secondary" href="/academy/'+encodeURIComponent(course.slug)+'">Открыть курс</a>':'')+'</div></article>').join(''):empty('Пока нет курсов',studio.view==='review'?'Новые курсы участников появятся здесь после отправки на проверку.':'Создайте курс с нуля и добавьте первый урок.'))+'</div>'+
      (studio.page>1||result.has_more?'<div class="actions">'+studioButton('page','← Назад','secondary','data-page="'+(studio.page-1)+'" '+(studio.page===1?'disabled':''))+'<span>Страница '+studio.page+'</span>'+studioButton('page','Далее →','secondary','data-page="'+(studio.page+1)+'" '+(!result.has_more?'disabled':''))+'</div>':'');
  }
  function studioLoadEntry(entry){
    studio.previewPages.clear();studio.entry=entry;studio.draft=studioClone(entry.draft);studio.step=entry.can_edit?'info':'preview';studio.lesson=0;studio.lessonStep='content';state.builderDirty=false;studioRender();
  }
  function studioInfo(){
    const d=studio.draft;
    return '<section class="panel studio-panel"><h2>1. Карточка курса</h2><p class="help">Эту информацию ученик увидит до начала обучения.</p>'+
      studioField('Название курса','title',d.title,{max:180,placeholder:'Например, Основы работы с таблицами'})+
      studioField('Краткое описание','description',d.description,{area:true,max:600,help:'Что человек научится делать и зачем ему этот курс?'})+
      studioField('Для кого этот курс','audience',d.audience,{area:true,max:600,placeholder:'Начинающие, без специальной подготовки...'})+
      '<div class="studio-field"><label for="studio-outcomes">Результаты обучения</label><p class="help">Один результат на строку, до 12 строк. Например: «Составлять простой отчёт в таблице».</p><textarea id="studio-outcomes" data-studio-list="outcomes" rows="5" maxlength="6000">'+esc(d.outcomes.join('\n'))+'</textarea></div>'+
      '<div class="actions">'+studioButton('next','Перейти к урокам →','primary')+'</div></section>';
  }
  const studioMediaKinds={image:'Изображение',audio:'Аудио',video:'Видео',document:'Документ',presentation:'Презентация'};
  const studioMediaStates={reserved:'Ожидает загрузки',pending:'На проверке',clean:'Проверен',rejected:'Не прошёл проверку',failed:'Ошибка проверки',purge_pending:'Удаляется'};
  function studioMediaLabel(file){
    const copies=file.renditions||[];
    const summary=copies.length?(copies[0].duration_ms?' · '+Math.ceil(copies[0].duration_ms/1000)+' сек.':' · '+copies.length+' стр.'):'';
    return (studioMediaKinds[file.kind]||'Файл')+' · '+(file.byte_count/1048576).toFixed(2)+' МиБ · '+(studioMediaStates[file.state]||'Недоступен')+summary;
  }
  function studioUploadImage(file,progress){
    if(!file||!['image/jpeg','image/png','image/webp'].includes(file.type)||file.size<1||file.size>10*1048576){
      return Promise.reject(new Error('Выберите JPEG, PNG или WebP не больше 10 МиБ.'));
    }
    return new Promise((resolve,reject)=>{
      const xhr=new XMLHttpRequest();
      xhr.open('POST',studioPath()+'/media/upload?expected_version='+studio.entry.version);
      xhr.timeout=180000;
      xhr.responseType='json';
      xhr.setRequestHeader('Content-Type',file.type);
      xhr.setRequestHeader('X-Requested-With','OPYT50');
      xhr.setRequestHeader('X-Community-Actor',String(state.user.id));
      xhr.upload.onprogress=event=>{
        if(event.lengthComputable){
          const percent=Math.min(100,Math.round(100*event.loaded/event.total));
          progress.value=percent;
          const label=$('#studio-upload-progress-label');
          if(label)label.textContent=percent===100?'Файл передан. Подтверждаем сохранение…':'Передано '+percent+'%';
        }
      };
      const uncertain=()=>reject(new Error('Не удалось подтвердить загрузку. Текст урока сохранён в этой вкладке. Обновите реестр перед повторной попыткой.'));
      xhr.onerror=uncertain;xhr.ontimeout=uncertain;xhr.onabort=uncertain;
      xhr.onload=()=>{
        if(xhr.status===201&&xhr.response?.file_id&&Array.isArray(xhr.response.media_files)){
          resolve(xhr.response);
        }else{
          const message=typeof xhr.response?.detail==='string'?xhr.response.detail:'Не удалось подтвердить загрузку. Обновите реестр перед повторной попыткой.';
          reject(new Error(message));
        }
      };
      xhr.send(file);
    });
  }
  function studioMediaEditor(lesson,prefix){
    const blocks=lesson.media||[];
    const files=studio.entry.media_files||[];
    const available=files.filter(file=>file.state!=='purge_pending'&&!blocks.some(block=>block.file_id===file.id));
    const cards=blocks.map((block,i)=>{
      const file=files.find(item=>item.id===block.file_id),p=prefix+'.media.'+i;
      return '<section class="studio-block"><div class="studio-side-heading"><h4>Материал '+(i+1)+'</h4><div class="studio-small-actions">'+
        studioButton('media-up','↑','secondary','data-index="'+i+'" aria-label="Переместить материал выше" '+(i===0?'disabled':''))+
        studioButton('media-down','↓','secondary','data-index="'+i+'" aria-label="Переместить материал ниже" '+(i===blocks.length-1?'disabled':''))+
        studioButton('remove-media','Убрать из урока','secondary','data-index="'+i+'"')+'</div></div><p class="help">'+esc(file?studioMediaLabel(file):'Файл недоступен')+'</p>'+
        studioField('Название материала',p+'.caption',block.caption,{max:180})+
        studioField('Описание / альтернативный текст',p+'.description',block.description,{area:true,max:1000,help:'Объясните, что показывает материал. Это важно для доступности.'})+
        studioField('Расшифровка или текстовое содержание',p+'.transcript',block.transcript,{area:true,max:12000,rows:5,help:'Для аудио и видео подготовьте текстовую расшифровку.'})+'</section>';
    }).join('');
    const upload=studio.entry.image_upload_enabled
      ?'<div class="studio-block"><h4>Добавить изображение</h4><p class="help">JPEG, PNG или WebP, до 10 МиБ. Файл будет доступен в предпросмотре после проверки и сохранения черновика.</p><div class="studio-field"><label for="studio-image-file">Выберите изображение</label><input id="studio-image-file" type="file" accept="image/jpeg,image/png,image/webp"></div>'+
        studioButton('upload-image','Загрузить изображение','primary',blocks.length>=12?'disabled':'')+
        '<progress id="studio-upload-progress" max="100" value="0" aria-label="Загрузка изображения" hidden></progress><p class="help" id="studio-upload-progress-label" role="status"></p></div><p class="help">Публикация мультимедиа пока отключена.</p>'
      :'<p class="notice warning">Загрузка и публикация файлов пока не подключены. Можно подготовить расположение и описание материалов из реестра курса.</p>';
    return '<h3>Учебные файлы</h3>'+upload+studioButton('refresh-media','Обновить статус файлов')+
      cards+(available.length&&blocks.length<12?'<div class="studio-field"><label for="studio-media-picker">Выберите файл курса</label><select id="studio-media-picker">'+available.map(file=>'<option value="'+esc(file.id)+'">'+esc(studioMediaLabel(file)+' · '+file.id.slice(0,8))+'</option>').join('')+'</select></div>'+studioButton('add-media','+ Добавить материал'):'<p class="help">'+(blocks.length>=12?'До 12 материалов на урок.':'Нет дополнительных файлов в реестре.')+'</p>');
  }
  function studioMediaPreview(lesson){
    const files=studio.entry.media_files||[];
    if(!(lesson.media||[]).length)return '';
    return '<h3>Учебные материалы</h3>'+lesson.media.map(block=>{
      const file=files.find(item=>item.id===block.file_id);
      const savedReference=studio.entry.draft?.lessons?.some(item=>(item.media||[]).some(saved=>saved.file_id===block.file_id));
      const mediaPath=studioPath()+'/media/'+encodeURIComponent(block.file_id);
      const alt=block.description||block.caption||'Учебный материал';
      let preview='<p class="help">Предпросмотр пока недоступен. Сохраните связь с уроком и обновите статус проверки.</p>';
      if(savedReference&&file?.state==='clean'){
        if(file.kind==='image'&&studio.entry.image_preview_enabled){
          preview='<img class="studio-media-image" loading="lazy" src="'+mediaPath+'/preview" alt="'+esc(alt)+'">';
        }else if(studio.entry.rendition_preview_enabled&&file.renditions?.length){
          const copies=file.renditions;
          if(copies.length===1&&['audio/mp4','video/mp4'].includes(copies[0].content_type)){
            const tag=copies[0].content_type==='audio/mp4'?'audio':'video';
            preview='<'+tag+' class="studio-media-player" controls preload="none" aria-label="'+esc(alt)+'" src="'+mediaPath+'/renditions/1"></'+tag+'>';
          }else if(copies.every(item=>item.content_type==='image/jpeg')){
            const page=Math.max(1,Math.min(copies.length,studio.previewPages.get(block.file_id)||1));
            preview='<div class="studio-block"><div class="actions">'+
              studioButton('media-page','←','secondary','aria-label="Предыдущая страница" data-file-id="'+esc(block.file_id)+'" data-page="'+(page-1)+'" '+(page===1?'disabled':''))+
              '<span class="help" role="status">Страница '+page+' из '+copies.length+'</span>'+
              studioButton('media-page','→','secondary','aria-label="Следующая страница" data-file-id="'+esc(block.file_id)+'" data-page="'+(page+1)+'" '+(page===copies.length?'disabled':''))+
              '</div><img class="studio-media-image" loading="lazy" src="'+mediaPath+'/renditions/'+page+'" alt="'+esc(alt+' — страница '+page)+'"></div>';
          }
        }
      }
      return '<section class="studio-block"><h4>'+esc(block.caption||'Материал без названия')+'</h4><p class="help">'+esc(file?studioMediaLabel(file):'Файл недоступен')+'</p>'+preview+'<p class="multiline">'+esc(block.description)+'</p>'+
        (block.transcript?'<details><summary>Текст материала</summary><p class="multiline">'+esc(block.transcript)+'</p></details>':'')+'</section>';
    }).join('');
  }
  function studioLessons(){
    const lessons=studio.draft.lessons,lesson=lessons[studio.lesson];
    const sidebar='<aside class="panel studio-lessons-nav"><div class="studio-side-heading"><h2>Программа</h2>'+studioButton('add-lesson','+ Урок','secondary',lessons.length>=30?'disabled':'')+'</div><p class="help">Заполнение текста и теста. Готовность к публикации проверяется сервером после сохранения.</p>'+
      (lessons.length?'<ol>'+lessons.map((item,index)=>'<li><button type="button" class="studio-lesson-select'+(index===studio.lesson?' selected':'')+'" data-studio="lesson" data-index="'+index+'" aria-current="'+(index===studio.lesson?'step':'false')+'"><span class="studio-num">'+(index+1)+'</span><span class="studio-lesson-caption"><span data-studio-lesson-label="'+index+'">'+esc(item.title||'Урок без названия')+'</span><small data-studio-completion="'+index+'">'+studioCompletionLabel(item)+'</small></span></button></li>').join('')+'</ol>':'<p class="help">Добавьте первый урок. Его название и содержание можно заполнить позже.</p>')+'</aside>';
    if(!lesson)return '<div class="studio-lesson-layout">'+sidebar+'<section class="panel studio-panel"><h2>Добавьте первый урок</h2><p>Каждый урок состоит из объяснения, практики и вопросов для самопроверки.</p>'+studioButton('add-lesson','+ Добавить урок','primary')+'</section></div>';
    const prefix='lessons.'+studio.lesson;
    let body='';
    if(studio.lessonStep==='content'){
      body=studioField('Название урока',prefix+'.title',lesson.title,{max:180,placeholder:'Что изучаем?'})+
        studioField('Продолжительность, минут',prefix+'.minutes',lesson.minutes,{type:'number'})+
        studioField('Цель урока',prefix+'.goal',lesson.goal,{area:true,max:600,rows:2,placeholder:'Что ученик сможет сделать после урока?'})+
        '<h3>Текстовые блоки</h3><p class="help">Разделите материал на небольшие части. Никакой специальной разметки не нужно.</p>'+
        lesson.sections.map((section,index)=>'<section class="studio-block"><div class="studio-side-heading"><h4>Блок '+(index+1)+'</h4>'+studioButton('remove-block','Удалить','secondary','data-index="'+index+'"')+'</div>'+
          studioField('Заголовок блока',prefix+'.sections.'+index+'.0',section[0],{max:4000,placeholder:'Название темы'})+
          '<div class="studio-field"><label for="studio-body-'+index+'">Текст</label><textarea id="studio-body-'+index+'" rows="6" data-studio-block="'+index+'" maxlength="32000">'+esc(section.slice(1).join('\n\n'))+'</textarea><p class="help">Пустая строка отделяет абзацы (до восьми на блок).</p></div></section>').join('')+
        studioButton('add-block','+ Добавить текстовый блок','secondary',lesson.sections.length>=12?'disabled':'')+
        studioMediaEditor(lesson,prefix);
    }else if(studio.lessonStep==='practice'){
      body=studioField('Практический пример',prefix+'.example',lesson.example,{area:true,rows:6,max:4000,help:'Покажите образец решения или конкретную ситуацию.'})+
        studioField('Самостоятельное задание',prefix+'.practice',lesson.practice,{area:true,rows:6,max:4000,help:'Опишите, что выполнить и как проверить результат. Не запрашивайте личные данные.'});
    }else{
      body='<h3>Самопроверка</h3><p class="help">Добавьте вопрос, два–пять вариантов, выберите один правильный ответ и объясните почему.</p>'+
        lesson.questions.map((q,i)=>{
          const p=prefix+'.questions.'+i;
          return '<section class="studio-block"><div class="studio-side-heading"><h4>Вопрос '+(i+1)+'</h4>'+studioButton('remove-question','Удалить','secondary','data-index="'+i+'"')+'</div>'+
            studioField('Вопрос',p+'.text',q.text,{area:true,rows:2,max:500})+
            '<fieldset class="studio-options"><legend>Варианты ответа и правильный вариант</legend>'+
            q.options.map((value,j)=>'<div class="studio-option"><input type="radio" name="studio-correct-'+i+'" aria-label="Вариант '+(j+1)+' правильный" data-studio-correct="'+i+'" value="'+j+'" '+(q.correct===j?'checked':'')+'><div>'+studioField('Вариант '+(j+1),p+'.options.'+j,value,{max:500})+'</div>'+studioButton('remove-option','−','secondary','aria-label="Удалить вариант '+(j+1)+'" data-index="'+i+'" data-option="'+j+'" '+(q.options.length<=2?'disabled':''))+'</div>').join('')+
            studioButton('add-option','+ Вариант','secondary','data-index="'+i+'" '+(q.options.length>=5?'disabled':''))+'</fieldset>'+
            studioField('Пояснение после ответа',p+'.feedback',q.feedback,{area:true,rows:3,max:1000,help:'Коротко объясните правильный ответ.'})+'</section>';
        }).join('')+studioButton('add-question','+ Добавить вопрос','secondary',lesson.questions.length>=10?'disabled':'');
    }
    return '<div class="studio-lesson-layout">'+sidebar+'<section class="panel studio-panel"><div class="studio-side-heading"><h2>Урок '+(studio.lesson+1)+' из '+lessons.length+'</h2><div class="studio-small-actions">'+studioButton('move-up','↑','secondary','aria-label="Переместить урок выше" '+(studio.lesson===0?'disabled':''))+studioButton('move-down','↓','secondary','aria-label="Переместить урок ниже" '+(studio.lesson===lessons.length-1?'disabled':''))+studioButton('duplicate-lesson','Копировать','secondary',lessons.length>=30?'disabled':'')+studioButton('remove-lesson','Удалить','secondary')+'</div></div>'+
      '<nav class="studio-tabs" aria-label="Содержание урока">'+[['content','Материал'],['practice','Практика'],['quiz','Тест']].map(([key,label])=>studioButton('lesson-step',label+'<small data-studio-section-completion="'+key+'">'+(studioLessonCompletion(lesson)[key]?'Заполнено':'Не заполнено')+'</small>',key===studio.lessonStep?'primary':'secondary','data-step="'+key+'" aria-pressed="'+(key===studio.lessonStep)+'"')).join('')+'</nav>'+body+
      '<div class="actions">'+studioButton('lesson-next',studio.lessonStep==='content'?'К практическому заданию →':studio.lessonStep==='practice'?'К тесту →':'Предпросмотр курса →','primary')+'</div></section></div>';
  }
  function studioPreview(){
    const d=studio.draft,lesson=d.lessons[studio.lesson];
    return '<section class="panel studio-panel"><span class="eyebrow">ПРЕДПРОСМОТР · НЕ ОПУБЛИКОВАНО</span><h2>'+esc(d.title||'Курс без названия')+'</h2><p>'+esc(d.description||'Описание ещё не заполнено')+'</p><p class="help">'+esc(d.audience)+'</p><h3>Результаты обучения</h3><ul>'+d.outcomes.filter(Boolean).map(item=>'<li>'+esc(item)+'</li>').join('')+'</ul><h3>Программа</h3><ol>'+d.lessons.map((item,index)=>'<li>'+studioButton('preview-lesson',esc(item.title||'Урок '+(index+1))+' · '+item.minutes+' мин.',index===studio.lesson?'primary':'secondary','data-index="'+index+'"')+'</li>').join('')+'</ol></section>'+
      (lesson?'<section class="panel studio-panel studio-preview"><span class="eyebrow">УРОК '+(studio.lesson+1)+'</span><h2>'+esc(lesson.title||'Урок без названия')+'</h2><p>'+esc(lesson.goal)+'</p>'+
      lesson.sections.map(section=>'<section><h3>'+esc(section[0]||'Заголовок блока')+'</h3>'+section.slice(1).map(p=>'<p class="multiline">'+esc(p)+'</p>').join('')+'</section>').join('')+
      studioMediaPreview(lesson)+'<h3>Практический пример</h3><div class="studio-example multiline">'+esc(lesson.example)+'</div><h3>Попробуйте сами</h3><p class="multiline">'+esc(lesson.practice)+'</p><h3>Вопросы для самопроверки</h3>'+
      lesson.questions.map((q,index)=>'<section class="studio-block"><h4>'+(index+1)+'. '+esc(q.text)+'</h4><ul>'+q.options.map((value,i)=>'<li>'+esc(value)+(q.correct===i?' <strong>✓ Правильный ответ</strong>':'')+'</li>').join('')+'</ul><p class="help">'+esc(q.feedback)+'</p></section>').join('')+'</section>':'')+
      '<div class="actions">'+studioButton('next','К проверке готовности →','primary')+'</div>';
  }
  function studioPublication(){
    const entry=studio.entry,editable=studioEditable();
    const dirty=state.builderDirty;
    const issues=entry.issues||[];
    const locations=entry.issue_locations||[];
    let actions='';
    if(editable){
      actions=dirty?studioButton('save','Сохранить и проверить','primary'):entry.state==='pending'?'<p class="help">Материал передан в редакцию. Изменение черновика отменит текущую проверку.</p>':entry.state==='published'?'<p class="help">Эта версия опубликована. Измените черновик, чтобы подготовить новую.</p>':!issues.length&&entry.can_submit?studioButton('submit',state.user.role==='admin'?'Опубликовать курс':'Отправить в редакцию','primary'):!entry.can_submit?'<p class="help">Перед отправкой курса опубликуйте <a href="/community/profile">профессиональный профиль</a>.</p>':'';
    }
    if(entry.can_edit&&(entry.has_saved_publication||entry.state==='pending'))actions+=studioButton('withdraw','Снять с публикации / отозвать согласие','danger');
    if(!entry.can_edit&&state.user.role==='admin'){
      if(entry.state==='pending')actions+=studioButton('approve','Одобрить и опубликовать','primary')+studioButton('reject','Вернуть автору');
      if(entry.has_publication)actions+=studioButton('hide','Скрыть курс','danger');
    }
    return '<section class="panel studio-panel"><h2>4. Проверка и публикация</h2><div class="status-line">'+statusBadge(entry.state,studioStates)+(entry.has_publication?'<span class="tag">Предыдущая версия доступна</span>':'')+'</div>'+
      (entry.moderation_reason?'<p class="notice warning">Редакция: '+esc(entry.moderation_reason)+'</p>':'')+
      '<p>Проверьте точность, авторские права, безопасность данных и качество заданий. После публикации новой версии прогресс ученика для старой версии не переносится автоматически.</p>'+
      (dirty?'<p class="notice warning">Сохраните черновик, чтобы сервер проверил его готовность.</p>':issues.length?'<h3>Что необходимо заполнить ('+issues.length+')</h3><ul class="studio-issues">'+issues.map((issue,index)=>'<li>'+esc(issue)+(editable&&locations[index]?studioButton('fix-issue','Перейти к полю','secondary','data-index="'+index+'" aria-label="'+esc('Исправить: '+issue)+'"'):'')+'</li>').join('')+'</ul>':'<p class="studio-ready">✓ Обязательные поля заполнены. Проверьте смысл и качество материалов в предпросмотре.</p>')+
      '<div class="actions">'+actions+'</div></section>';
  }
  function studioRender(){
    const d=studio.draft,e=studio.entry,editable=studioEditable();
    if(!editable&&['info','lessons'].includes(studio.step))studio.step='preview';
    content.innerHTML='<div class="studio-top"><div><button type="button" class="button secondary compact" data-studio="back">← Все курсы</button><span class="eyebrow">КОНСТРУКТОР КУРСОВ</span><h1 id="studio-course-title">'+esc(d.title||'Курс без названия')+'</h1><div class="status-line">'+statusBadge(e.state,studioStates)+'<span class="help" id="studio-total-time">'+d.lessons.length+' уроков · '+d.lessons.reduce((sum,l)=>sum+(Number(l.minutes)||0),0)+' мин.</span></div></div><div class="studio-save-area"><p class="help" id="studio-save-status" role="status">'+(state.builderDirty?'Есть несохранённые изменения':'Черновик сохранён')+'</p>'+
      (editable?'<button type="button" class="button primary" id="studio-save" data-studio="save" '+(!state.builderDirty?'disabled':'')+'>Сохранить черновик</button>':'')+
      (e.has_publication?'<a class="button secondary" href="/academy/'+encodeURIComponent(e.slug)+'">Опубликованная версия ↗</a>':'')+'</div></div>'+
      (e.restricted?'<p class="notice warning">Доступны просмотр и отзыв согласия. Редактирование ограничено.</p>':'')+
      '<nav class="studio-steps" aria-label="Этапы создания курса">'+studioSteps.map(([key,label],i)=>'<button type="button" class="studio-step'+(key===studio.step?' current':'')+'" data-studio="step" data-step="'+key+'" '+(key===studio.step?'aria-current="step"':'')+' '+(!editable&&['info','lessons'].includes(key)?'disabled':'')+'><span class="studio-num">'+(i+1)+'</span><span>'+label+'</span></button>').join('')+'</nav>'+
      '<div id="studio-workspace">'+(studio.step==='info'?studioInfo():studio.step==='lessons'?studioLessons():studio.step==='preview'?studioPreview():studioPublication())+'</div>';
  }
  async function studioSave(){
    if(!studioEditable()||!state.builderDirty)return;
    const result=await api(studioPath(),{method:'PUT',body:{...studio.draft,expected_version:studio.entry.version}});
    studio.entry=result.course;studio.draft=studioClone(result.course.draft);state.builderDirty=false;studioRender();notice('Черновик сохранён. Опубликованная версия не изменена.');
  }
  function studioSubmit(){
    if(state.builderDirty||!studioEditable())return;
    const admin=state.user.role==='admin';
    openDialog(admin?'Опубликовать новую версию курса?':'Отправить курс в редакцию?','<p>Публикуется только сохранённая версия. '+(admin?'Убедитесь, что курс проверен и готов для учеников.':'После одобрения материал будет доступен под вашим публичным именем.')+'</p><form id="studio-consent-form" class="dialog-form"><label class="consent-label"><input type="checkbox" name="consent" required><span>Подтверждаю права на материалы, проверку содержания и согласие на размещение этой версии. Согласие можно отозвать.</span></label><button type="submit" class="button primary">'+(admin?'Опубликовать':'Отправить на проверку')+'</button></form>');
    const form=$('#studio-consent-form');form.addEventListener('submit',event=>{event.preventDefault();busy(form,async()=>{
      const result=await api(studioPath()+'/submit',{method:'POST',body:{expected_version:studio.entry.version,publish_consent:form.elements.consent.checked}});
      studio.entry=result.course;studio.draft=studioClone(result.course.draft);state.builderDirty=false;dialogBusy=false;closeDialog();studioRender();notice(admin?'Курс опубликован.':'Курс отправлен на проверку.');
    });});
  }
  function studioReview(action){
    openDialog(action==='approve'?'Одобрить курс?':action==='reject'?'Вернуть на доработку?':'Скрыть курс?','<p>Проверьте программу, уроки, вопросы и права на материалы. Утверждается только сохранённая авторская версия.</p><form id="studio-review-form" class="dialog-form">'+(action==='approve'?'':'<div class="studio-field"><label for="studio-reason">Комментарий редакции</label><textarea id="studio-reason" name="reason" maxlength="500" required rows="4"></textarea></div>')+'<button type="submit" class="button primary">Подтвердить</button></form>');
    const form=$('#studio-review-form');form.addEventListener('submit',event=>{event.preventDefault();busy(form,async()=>{
      await api('/api/admin/community/courses/'+encodeURIComponent(studio.entry.slug),{method:'PATCH',body:{expected_version:studio.entry.version,decision:action,reason:form.elements.reason?.value||''}});
      dialogBusy=false;closeDialog();await studioList();notice('Решение редакции сохранено.');
    });});
  }
  async function studioAction(event){
    const button=event.target.closest('[data-studio]');if(!button||button.disabled||mode!=='courses')return;
    const action=button.dataset.studio,index=Number(button.dataset.index);
    if(studio.loading)return;
    const lesson=studio.draft?.lessons[studio.lesson];
    const structural=()=>{
      studioChange();studioRender();
    };
    try{
      if(action==='new'){
        studio.loading=true;studio.key=studio.key||crypto.randomUUID();
        await busy(content,async()=>{const result=await api(studioApi,{method:'POST',body:{client_key:studio.key}});studio.key=null;studioLoadEntry(result.course);});
      }else if(action==='open'){
        studio.loading=true;
        const result=await api(studioApi+'/'+encodeURIComponent(button.dataset.slug));studioLoadEntry(result.course);
      }else if(action==='back'){await studioLeave(async()=>{await studioList();});}
      else if(action==='view'){studio.loading=true;studio.view=button.dataset.view;studio.page=1;await studioList();}
      else if(action==='page'){studio.loading=true;studio.page=Number(button.dataset.page);await studioList();}
      else if(action==='step'){studio.step=button.dataset.step;studioRender();}
      else if(action==='next'){studio.step=studio.step==='info'?'lessons':'publish';studioRender();}
      else if(action==='preview-lesson'){studio.lesson=index;studioRender();}
      else if(action==='media-page'){
        const id=button.dataset.fileId,page=Number(button.dataset.page);
        const file=studio.entry.media_files?.find(item=>item.id===id);
        if(file&&Number.isInteger(page)&&page>=1&&page<=file.renditions?.length){
          studio.previewPages.set(id,page);studioRender();
        }
      }
      else if(action==='save'){studio.loading=true;await busy(content,studioSave);}
      else if(action==='submit')studioSubmit();
      else if(action==='withdraw')confirmAction('Снять курс с публикации?','Опубликованная версия и текущая заявка на проверку будут скрыты. Черновик останется.','Снять с публикации',async()=>{
        const result=await api(studioPath()+'/publication',{method:'DELETE',body:{expected_version:studio.entry.version}});
        studio.entry=result.course;
        if(!state.builderDirty)studio.draft=studioClone(result.course.draft);
        studioRender();notice('Публикация отозвана.');
      });
      else if(['approve','reject','hide'].includes(action))studioReview(action);
      else if(!studioEditable())return;
      else if(action==='fix-issue'&&!state.builderDirty){
        const issue=studio.entry.issue_locations?.[index];
        if(!issue||!['info','lessons'].includes(issue.step))return;
        studio.step=issue.step;
        if(issue.step==='lessons'){
          studio.lesson=Number.isInteger(issue.lesson)?Math.max(0,Math.min(issue.lesson,studio.draft.lessons.length-1)):0;
          studio.lessonStep=['content','practice','quiz'].includes(issue.lesson_step)?issue.lesson_step:'content';
        }
        studioRender();
        const field=issue.field||'';
        let target=document.getElementById(field);
        if(!target&&['add-lesson','add-block','add-question'].includes(field))target=$('[data-studio="'+field+'"]');
        if(!target&&/^correct-[0-9]+$/.test(field))target=$('[data-studio-correct="'+field.slice(8)+'"]');
        if(!target)target=$('#studio-workspace h2');
        if(target){
          if(!target.matches('input,textarea,button,select,a[href]'))target.tabIndex=-1;
          target.focus({preventScroll:true});target.scrollIntoView({block:'center'});
        }
      }
      else if(action==='lesson'){studio.lesson=index;studio.lessonStep='content';studioRender();}
      else if(action==='lesson-step'){studio.lessonStep=button.dataset.step;studioRender();}
      else if(action==='lesson-next'){if(studio.lessonStep==='content')studio.lessonStep='practice';else if(studio.lessonStep==='practice')studio.lessonStep='quiz';else studio.step='preview';studioRender();}
      else if(action==='add-lesson'&&studio.draft.lessons.length<30){studio.draft.lessons.push(newStudioLesson());studio.lesson=studio.draft.lessons.length-1;studio.lessonStep='content';structural();}
      else if(action==='duplicate-lesson'&&lesson&&studio.draft.lessons.length<30){const copy=studioClone(lesson);copy.slug='lesson-'+crypto.randomUUID();copy.title=(copy.title+' (копия)').slice(0,180);studio.draft.lessons.splice(studio.lesson+1,0,copy);studio.lesson++;structural();}
      else if(action==='move-up'||action==='move-down'){
        const to=studio.lesson+(action==='move-up'?-1:1);
        if(to>=0&&to<studio.draft.lessons.length){studio.draft.lessons.splice(studio.lesson,1);studio.draft.lessons.splice(to,0,lesson);studio.lesson=to;structural();}
      }else if(action==='remove-lesson')confirmAction('Удалить урок?','Все материалы, задания и вопросы этого урока будут удалены из черновика.','Удалить',async()=>{studio.draft.lessons.splice(studio.lesson,1);studio.lesson=Math.max(0,Math.min(studio.lesson,studio.draft.lessons.length-1));structural();});
      else if(action==='refresh-media'){
        studio.loading=true;
        await busy(content,async()=>{
          const fresh=(await api(studioPath())).course;
          if(fresh.version!==studio.entry.version)throw new Error('Курс изменён в другой вкладке. Введённый текст остаётся здесь; сохраните его отдельно перед повторным открытием.');
          studio.entry=fresh;
          studioRender();notice('Статусы файлов обновлены.');
        });
      }
      else if(action==='upload-image'&&lesson&&studio.entry.image_upload_enabled){
        const input=$('#studio-image-file'),file=input?.files?.[0];
        const progress=$('#studio-upload-progress');
        if(!file||!progress)throw new Error('Сначала выберите изображение.');
        if((lesson.media||[]).length>=12)throw new Error('В уроке уже 12 материалов.');
        studio.loading=true;
        progress.hidden=false;
        await busy(content,async()=>{
          const result=await studioUploadImage(file,progress);
          studio.entry.media_files=result.media_files;
          lesson.media=lesson.media||[];
          if(!lesson.media.some(block=>block.file_id===result.file_id))lesson.media.push({file_id:result.file_id,caption:'',description:'',transcript:''});
          structural();notice('Изображение отправлено на проверку. Заполните описание и сохраните черновик.');
        });
      }
      else if(action==='add-media'&&lesson){
        const id=$('#studio-media-picker')?.value;
        const files=studio.entry.media_files||[];
        lesson.media=lesson.media||[];
        if(id&&lesson.media.length<12&&files.some(file=>file.id===id&&file.state!=='purge_pending')&&!lesson.media.some(block=>block.file_id===id)){
          lesson.media.push({file_id:id,caption:'',description:'',transcript:''});structural();
        }
      }
      else if(action==='remove-media'&&lesson?.media&&index>=0&&index<lesson.media.length)confirmAction('Убрать учебный материал?','Связь с уроком будет удалена из черновика. Файл останется в реестре курса.','Убрать',async()=>{lesson.media.splice(index,1);structural();});
      else if((action==='media-up'||action==='media-down')&&lesson?.media&&index>=0&&index<lesson.media.length){
        const to=index+(action==='media-up'?-1:1);
        if(to>=0&&to<lesson.media.length){const [block]=lesson.media.splice(index,1);lesson.media.splice(to,0,block);structural();}
      }
      else if(action==='add-block'&&lesson.sections.length<12){lesson.sections.push(['','']);structural();}
      else if(action==='remove-block')confirmAction('Удалить текстовый блок?','Текст будет удалён из черновика.','Удалить',async()=>{lesson.sections.splice(index,1);structural();});
      else if(action==='add-question'&&lesson.questions.length<10){lesson.questions.push(newStudioQuestion());structural();}
      else if(action==='remove-question')confirmAction('Удалить вопрос?','Вопрос и варианты будут удалены из черновика.','Удалить',async()=>{lesson.questions.splice(index,1);structural();});
      else if(action==='add-option'&&lesson.questions[index].options.length<5){lesson.questions[index].options.push('');structural();}
      else if(action==='remove-option'&&lesson.questions[index].options.length>2){
        const q=lesson.questions[index],opt=Number(button.dataset.option);q.options.splice(opt,1);
        if(q.correct===opt)q.correct=null;else if(q.correct!==null&&q.correct>opt)q.correct--;
        structural();
      }
    }catch(error){notice(error.message,'error');}finally{studio.loading=false;}
  }
  function studioInput(event){
    if(mode!=='courses'||!studioEditable()||studio.loading)return;
    const node=event.target;
    if(node.dataset.studioPath){
      const value=node.type==='number'?Number(node.value):node.value;
      studioSet(node.dataset.studioPath,value);
    }else if(node.dataset.studioList==='outcomes'){studio.draft.outcomes=node.value.split(/\r?\n/);studioChange();}
    else if(node.dataset.studioBlock!==undefined){
      const section=studio.draft.lessons[studio.lesson].sections[Number(node.dataset.studioBlock)];
      section.splice(1,section.length-1,...node.value.split(/\r?\n\s*\r?\n/));studioChange();
    }else if(node.dataset.studioCorrect!==undefined){
      studio.draft.lessons[studio.lesson].questions[Number(node.dataset.studioCorrect)].correct=Number(node.value);studioChange();
    }
  }
  async function renderCourseBuilder(){
    if(!state.user)return accountGate('Конструктор курсов');
    if(!['candidate','admin'].includes(state.user.role)){content.innerHTML=empty('Конструктор курсов','Создавать курсы могут авторы сообщества и редакция.','<a class="button primary" href="/academy">Открыть Академию</a>');return;}
    if(!studio.bound){content.addEventListener('click',studioAction);content.addEventListener('input',studioInput);studio.bound=true;}
    await studioList();
  }

  async function handleAction(event) {
    const button=event.target.closest('[data-action]');if(!button||button.disabled)return;
    const {action,id}=button.dataset;
    try{
      if(action==='people-page'){state.directoryPage=Number(button.dataset.page);await loadPeople();}
      else if(action==='retry-people')await loadPeople();
      else if(action==='refresh-groups')await loadGroups();
      else if(['join-group','leave-group'].includes(action))await changeGroup(button);
      else if(action==='connections-page'){state.connectionPage=Number(button.dataset.page);await loadConnections();}
      else if(action==='attention-connections'||action==='all-connections'){
        state.connectionFilter=action==='attention-connections'?'attention':'';
        state.connectionPage=1;$('#connection-filter').value=state.connectionFilter;await loadConnections();
      }
      else if(action==='mark-thread-read')await markThreadRead(button,id);
      else if(action==='open-thread')await openThread(id);
      else if(action==='refresh-thread')await openThread(id,{preserve:true});
      else if(action==='accept-connection')await busy(button.closest('article'),()=>connectionAction(id,action));
      else if(['decline-connection','cancel-connection','block-connection'].includes(action))confirmAction(action==='block-connection'?'Прекратить общение?':'Завершить этот запрос?',action==='block-connection'?'Вы больше не сможете отправлять друг другу сообщения и новые запросы. Рекомендации между вами будут скрыты. История разговора сохранится. Возобновить общение после блокировки будет нельзя.':'Запрос будет завершён. Отправить повторное приглашение этому участнику будет нельзя.',action==='block-connection'?'Прекратить общение':'Подтвердить',()=>connectionAction(id,action));
      else if(action==='report-connection')report({connection_id:id});
      else if(['approve-profile','reject-profile','hide-profile'].includes(action))moderateProfile(button);
      else if(action==='reload-moderation')await Promise.all([loadModeration(),loadReports()]);
      else if(action==='moderation-page'){state.moderationPage=Number(button.dataset.page);await loadModeration();}
      else if(action==='reports-page'){state.reportPage=Number(button.dataset.page);await loadReports();}
      else if(['resolve-report','dismiss-report'].includes(action))await busy(button.closest('article'),async()=>{await api('/api/admin/community/reports/'+encodeURIComponent(id),{method:'PATCH',body:{status:action==='resolve-report'?'resolved':'dismissed'}});await loadReports();notice('Статус жалобы сохранён.');});
      else if(action==='author-refresh')await loadAuthors();
      else if(action==='author-page'){state.authorPage=Number(button.dataset.page);await loadAuthors();}
      else if(action==='author-add')switchAuthorEditor(null);
      else if(action==='author-edit'){const entry=state.authorEntries.find(item=>item.id===id);if(entry)switchAuthorEditor(entry);}
      else if(action==='author-cancel')cancelAuthorEditor();
      else if(action==='author-submit')submitAuthor(state.authorEntries.find(item=>item.id===id));
      else if(action==='author-withdraw')confirmAction('Отозвать публикацию?','Материал будет скрыт из журнала. Его можно будет отправить на новую проверку.','Отозвать согласие',async()=>{await api(authorApi+'/'+encodeURIComponent(id)+'/publication',{method:'DELETE',body:{expected_version:Number(button.dataset.version)}});notice('Согласие отозвано.');await loadAuthors();});
      else if(['author-approve','author-reject','author-hide'].includes(action))reviewAuthor(state.authorEntries.find(item=>item.id===id),action.slice(7));
      else if(action==='share-profile'){const result=await api('/api/community/profile');if(result.public_visible&&result.profile.public_id===id)shareProfile(id);else notice('Профиль сейчас недоступен для публикации. Можно пригласить коллегу в сообщество.','warning');}
      else if(action==='invite-colleague'){const result=await api('/api/community/profile');shareProfile(result.public_visible?result.profile.public_id:null,true);}
      else if(action==='refresh-reputation')await loadReputation();
      else if(action==='reputation-page'){state.reputationPage=Number(button.dataset.page);await loadReputation();}
      else if(action==='cancel-recommendation')cancelRecommendation();
      else if(action==='accept-reputation')acceptReputation(button);
      else if(action==='decline-reputation')confirmAction('Отклонить рекомендацию?','Она не будет опубликована, а повторно отправить эту рекомендацию коллеге нельзя.','Отклонить',async()=>{await api('/api/community/reputation/'+encodeURIComponent(id)+'/respond',{method:'POST',body:{decision:'decline',expected_version:Number(button.dataset.version),publish_consent:false}});notice('Рекомендация отклонена.');await loadReputation();});
      else if(action==='withdraw-reputation')confirmAction('Отозвать согласие?','Рекомендация перестанет отображаться публично. Повторное предложение этой записи недоступно.','Отозвать',async()=>{await api('/api/community/reputation/'+encodeURIComponent(id)+'/publication',{method:'DELETE',body:{expected_version:Number(button.dataset.version)}});notice('Согласие отозвано.');await loadReputation();});
      else if(['approve-reputation','reject-reputation','hide-reputation'].includes(action))moderateReputation(button);
      else if(action==='new-portfolio')switchPortfolioEditor(null);
      else if(action==='edit-portfolio'){const item=state.portfolioEntries.find(entry=>entry.id===id);if(item)switchPortfolioEditor(item);}
      else if(action==='cancel-portfolio')cancelPortfolioEditor();
      else if(action==='refresh-portfolio')await loadPortfolio();
      else if(action==='submit-portfolio')submitPortfolio(button);
      else if(action==='withdraw-portfolio')confirmAction('Скрыть запись?','Разрешение на публикацию будет отозвано. Основной профиль останется без изменений.','Скрыть',async()=>{await api('/api/community/portfolio/'+encodeURIComponent(id)+'/publication',{method:'DELETE',body:{expected_version:Number(button.dataset.version)}});notice('Запись скрыта.');await loadPortfolio();});
      else if(action==='refresh-portfolio-review')await loadPortfolioReview();
      else if(action==='portfolio-review-page'){state.portfolioReviewPage=Number(button.dataset.page);await loadPortfolioReview();}
      else if(['approve-portfolio','reject-portfolio','hide-portfolio'].includes(action))moderatePortfolio(button);
      else if(action==='respond-opportunity')await requestConnection({entryId:id,publicId:button.dataset.publicId,kind:button.dataset.kind,title:button.dataset.title});
      else if(action==='save-entry'||action==='remove-saved')await changeSaved(button);
      else if(action==='saved-page'){state.savedPage=Number(button.dataset.page);await loadSaved();}
      else if(action==='discovery-people-page'){state.discoveryPeoplePage=Number(button.dataset.page);await loadDiscovery();}
      else if(action==='discovery-feed-page'){state.discoveryFeedPage=Number(button.dataset.page);await loadDiscovery();}
      else if(action==='clear-discovery')clearDiscovery();
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
        await Promise.all([loadFeedMine(),loadFeed(),...($('#feed-alerts-list')?[loadFeedAlerts()]:[refreshFeedAlertBadge()])]);
      });
      else if(['follow-author','unfollow-author'].includes(action))await changeFollow(button);
      else if(action==='feed-follows-page'){state.feedFollowsPage=Number(button.dataset.page);await loadFeedFollows();}
      else if(action==='feed-alerts-page'){state.feedAlertsPage=Number(button.dataset.page);await loadFeedAlerts();}
      else if(action==='refresh-feed-alerts'){state.feedAlertsPage=1;await loadFeedAlerts();}
      else if(action==='read-feed-alert')await busy(button.closest('article'),async()=>{await api('/api/community/feed/alerts/'+encodeURIComponent(id)+'/read',{method:'POST',body:{}});await loadFeedAlerts();});
      else if(action==='report-feed')reportFeed(id);
      else if(action==='feed-reports-page'){state.feedReportsPage=Number(button.dataset.page);await loadFeedReports();}
      else if(['resolve-feed-report','dismiss-feed-report','hide-feed-report'].includes(action))reviewFeedReport(button);
      else if(action==='feed-review-page'){state.feedReviewPage=Number(button.dataset.page);await loadFeedReview();}
      else if(['approve-feed','reject-feed','hide-feed'].includes(action))moderateFeed(button);
      else if(action==='retry-community')await renderMode();
    }catch(error){notice(error.message,'error');}
  }
  function groupCard(group,canJoin,canRead){
    const id=esc(group.slug);
    return '<article class="panel group-card" data-group-slug="'+id+'"><div class="status-line">'+(group.joined?'<span class="status-badge published">Вы участник</span>':'<span class="tag">Открытая группа</span>')+'</div><h2>'+esc(group.name)+'</h2><p>'+esc(group.description)+'</p><div class="actions">'+(canRead?'<a class="button primary" href="/community/feed?group='+encodeURIComponent(group.slug)+'">Открыть обсуждения</a>':'')+((canJoin||group.joined)?'<button type="button" class="button secondary" data-action="'+(group.joined?'leave-group':'join-group')+'" data-id="'+id+'">'+(group.joined?'Выйти':'Вступить')+'</button>':'')+'</div></article>';
  }
  async function loadGroups(){
    const request=++state.groupsRequest;
    const result=await api('/api/community/groups');
    if(request!==state.groupsRequest)return;
    const groups=result.groups.filter(group=>!state.groupsMine||group.joined);
    $('#groups-list').innerHTML=groups.length?groups.map(group=>groupCard(group,result.can_join,result.can_read)).join(''):empty('Пока нет ваших групп',result.can_join?'Вступите в интересующие вас профессиональные сообщества.':'Доступных членств нет.');
    $('#groups-summary').textContent='Ваши группы: '+result.groups.filter(group=>group.joined).length;
  }
  async function renderGroups(){
    if(!state.user)return accountGate('Профессиональные группы');
    if(state.user.role==='admin'){content.innerHTML=empty('Модерация тематических групп','Все публикации и комментарии проверяются в общей очереди ленты.','<a class="button primary" href="/community/feed">Модерация ленты</a>');return;}
    content.innerHTML='<div class="section-heading"><div><h1>Профессиональные группы</h1><p>Выберите отрасли и направления, в которых хотите обмениваться опытом с коллегами.</p></div><a href="/community/feed" class="button secondary">Общая лента</a></div><section class="panel group-intro"><h2>Общение по профессиональным интересам</h2><p>Группы открыты для чтения зарегистрированным участникам. Вступление позволяет писать публикации и комментарии после одобрения вашего профиля. Все тексты проходят модерацию. Список ваших групп виден только вам.</p><p class="help">Выход из группы не удаляет ранее опубликованные тексты. Их можно скрыть отдельно в разделе «Мои публикации и комментарии».</p><div class="connections-toolbar"><label for="groups-filter">Показать<select id="groups-filter"><option value="all">Все группы</option><option value="mine">Мои группы</option></select></label><span id="groups-summary" class="help" role="status"></span><button type="button" class="button secondary" data-action="refresh-groups">Обновить</button></div></section><div id="groups-list" class="group-grid" aria-live="polite"></div>';
    $('#groups-filter').value=state.groupsMine?'mine':'all';
    $('#groups-filter').addEventListener('change',event=>{state.groupsMine=event.target.value==='mine';loadGroups().catch(error=>notice(error.message,'error'));});
    await loadGroups();
  }
  async function changeGroup(button){
    const join=button.dataset.action==='join-group',id=button.dataset.id;
    await busy(button.closest('article'),async()=>{
      await api('/api/community/groups/'+encodeURIComponent(id)+'/membership',{method:join?'PUT':'DELETE',body:{}});
      notice(join?'Вы вступили в группу.':'Вы вышли из группы. Ранее опубликованные тексты сохранены.');
      await loadGroups();
    });
  }

  async function renderMode() {
    try{
      if(mode==='directory')await renderDirectory();
      else if(mode==='feed')await renderFeed();
      else if(mode==='groups')await renderGroups();
      else if(opportunityMode)await renderOpportunities();
      else if(mode==='discovery')await renderDiscovery();
      else if(mode==='saved')await renderSaved();
      else if(mode==='profile')await renderProfile();
      else if(mode==='portfolio')await renderPortfolio();
      else if(mode==='reputation')await renderReputation();
      else if(mode==='author-articles')await renderAuthors();
      else if(mode==='courses')await renderCourseBuilder();
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
    window.addEventListener('beforeunload',event=>{if(state.dirty||state.messageDirty||state.feedDirty||state.feedCommentDirty||state.discoveryDirty||state.portfolioDirty||state.reputationDirty||state.authorDirty||state.builderDirty){event.preventDefault();event.returnValue='';}});
    try{state.user=(await api('/api/me')).user;}catch(error){if(error.status!==401){notice(error.message,'error');if(!['directory','person'].includes(mode)){content.innerHTML='<section class="panel"><h1>Аккаунт временно недоступен</h1><p>Обновите страницу, когда соединение восстановится.</p><button class="button secondary" type="button" id="retry-account">Повторить</button></section>';$('#retry-account').addEventListener('click',()=>location.reload());return;}}}
    updateIdentity();await renderMode();if(mode!=='feed')refreshFeedAlertBadge();
  }
  document.addEventListener('DOMContentLoaded',boot);
})();
