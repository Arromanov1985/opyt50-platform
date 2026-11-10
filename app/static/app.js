/* СТАЖНО — progressive vanilla JS client; no tracking or external dependencies. */
'use strict';
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const state = { user: null, mode: 'register', role: 'candidate', tab: 'overview', activeVacancy: null, editVacancy: null, employerVacancyFilter: 'all', employerApplicationsVacancyFilter: 'all' };
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money = value => Number(value || 0).toLocaleString('ru-RU') + ' ₽';
const formatPay = job => job.salary_min === job.salary_max ? money(job.salary_min) : `${money(job.salary_min)} — ${money(job.salary_max)}`;
const statusTitle = {sent:'Ожидает ответа',accepted:'Согласие получено',declined:'Не заинтересован'};
const statusBadge = {sent:'orange',accepted:'',declined:'gray'};
const activityLabels = {
  applied:'Отклик отправлен',reapplied:'Отклик отправлен повторно',
  withdrawn:'Отклик отозван',reviewing:'На рассмотрении',
  interview:'Работодатель заинтересован',rejected:'Отказ',hired:'Принят',
  invitation_sent:'Приглашение отправлено',invitation_accepted:'Согласие получено',
  invitation_declined:'Кандидат отказался',contact_opened:'Знакомство состоялось (демо)'
};
function workflowStatus(x, fallback='') {
  const stage = x.introduction_stage;
  if (stage==='introduced' || x.contact_shared) return 'Знакомство состоялось (демо)';
  if (stage==='consented') return 'Согласие получено';
  if (stage==='awaiting_consent') return 'Ожидает согласия кандидата';
  if (stage==='declined') return 'Кандидат отказался';
  return fallback;
}
function activityTimelineMarkup(x) {
  const entries = Array.isArray(x.timeline) ? x.timeline : [];
  if (!entries.length) return '';
  const recent = entries.slice(-4);
  return '<details class="application-timeline" aria-label="История взаимодействия"><summary>История взаимодействия</summary>' +
    recent.map(e=>'<span>'+esc(activityLabels[e.event]||e.event)+' · '+esc(e.created_at)+'</span>').join('')+'</details>';
}
function interactionStageMarkup(x, kind='application') {
  const introduced = x.introduction_stage === 'introduced' || x.contact_shared;
  const consented = x.introduction_stage === 'consented' || x.status === 'accepted';
  const awaiting = x.introduction_stage === 'awaiting_consent' || x.invitation_status === 'sent' || x.status === 'interview';
  const reviewing = ['reviewing','interview'].includes(x.status) || awaiting || consented || introduced;
  const applied = Boolean(x.application_id || x.vacancy_id || ['applied','reviewing','interview','withdrawn','rejected','hired'].includes(x.status));
  const steps = kind === 'invitation'
    ? [
        ['Приглашение', true],
        ['Согласие', consented || introduced],
        ['Контакт', introduced]
      ]
    : [
        ['Отклик', applied],
        ['Рассмотрение', reviewing],
        ['Согласие', consented || introduced],
        ['Знакомство', introduced]
      ];
  const activeIndex = Math.max(0, steps.reduce((last,step,index)=>step[1]?index:last,0));
  return '<div class="interaction-stage" aria-label="Этап взаимодействия">' +
    steps.map((step,index)=>'<span class="'+(step[1]?'done ':'')+(index===activeIndex?'current':'')+'"><i>'+(step[1]?'✓':index+1)+'</i><b>'+esc(step[0])+'</b></span>').join('') +
    '</div>';
}
let toastTimeout;
function toast(message, error = false) {
  const el = $('#toast'); el.textContent = message; el.className = 'toast' + (error ? ' error' : '');
  clearTimeout(toastTimeout); toastTimeout = setTimeout(() => el.classList.add('hidden'), 4500);
}
async function api(path, options = {}) {
  const headers = {...(options.headers || {})};
  if (options.method && options.method !== 'GET') {
    headers['X-Requested-With'] = 'OPYT50';
    if (options.body) headers['Content-Type'] = 'application/json';
  }
  const response = await fetch(path, {...options, credentials:'same-origin', headers});
  let data;
  try { data = await response.json(); } catch { data = {}; }
  if (!response.ok) {
    const issue = data.detail;
    const msg = Array.isArray(issue) ? issue.map(x => x.msg).join('; ') : (typeof issue === 'string' ? issue : `Ошибка ${response.status}`);
    throw new Error(msg);
  }
  return data;
}
function optList(values, value = '') { return values.map(v => `<option value="${esc(v)}" ${v === value ? 'selected' : ''}>${esc(v)}</option>`).join(''); }
const schedules = ['Любой','Полный день','Сменный','Гибкий','Удалённо'];
const employment = ['Любая','Полная','Частичная','Проектная'];
function jobMarkup(job, personalized = false) {
  return `<article class="job-card"><div class="job-top"><span class="job-company">${esc(job.company_name || 'Работодатель')}</span>${personalized ? `<span class="job-category">Подходит: ${esc(job.score)}%</span>` : '<span class="job-category">Вакансия</span>'}</div>
    <h3>${esc(job.title)}</h3><div class="job-salary">${formatPay(job)}</div><div class="job-meta"><span>⌖ ${esc(job.city)}</span><span>${esc(job.schedule)}</span><span>${esc(job.employment)}</span></div><p>${esc(job.description || 'Подробности обсудите с работодателем после знакомства.')}</p></article>`;
}
async function loadPublicJobs() {
  try {
    const city = $('#city-filter').value.trim();
    const {jobs} = await api('/api/jobs' + (city ? `?city=${encodeURIComponent(city)}` : ''));
    $('#jobs-count').textContent = `${jobs.length} вакансий`;
    $('#public-jobs').innerHTML = jobs.length ? jobs.map(job => jobMarkup(job)).join('') : '<div class="empty-state">Пока нет открытых вакансий по этому запросу. Создайте профиль, чтобы получать будущие предложения.</div>';
  } catch(e) { $('#public-jobs').innerHTML = '<div class="empty-state">Не удалось получить вакансии.</div>'; toast(e.message, true); }
}
function openAuth(mode = 'register', role = 'candidate') {
  state.mode = mode; state.role = role; updateAuth();
  $('#auth-form').reset();
  $('#auth-dialog').showModal();
  (mode === 'register' ? $('#auth-name') : $('#auth-email')).focus();
}
function updateAuth() {
  const reg = state.mode === 'register';
  const employer = state.role === 'employer';
  $('#auth-kicker').textContent = reg ? 'РЕГИСТРАЦИЯ' : 'ВХОД';
  $('#auth-title').textContent = reg ? (employer ? 'Аккаунт работодателя' : 'Создать профиль') : 'Войти в аккаунт';
  $('#auth-intro').textContent = reg
    ? (employer
      ? 'Создайте аккаунт компании. Первую вакансию можно разместить сразу после регистрации.'
      : 'Создайте простой аккаунт. Профессию, опыт и условия поиска добавите следующим шагом.')
    : 'Введите email и пароль. После входа откроется ваш рабочий кабинет.';
  $('#signup-role').classList.toggle('hidden', !reg);
  $('#auth-name-row').classList.toggle('hidden', !reg);
  $('#auth-company-row').classList.toggle('hidden', !(reg && employer));
  $('#password-hint').classList.toggle('hidden', !reg);
  $('#auth-route').classList.toggle('hidden', !reg);
  $('#auth-name').required = reg;
  $('#auth-company').required = reg && employer;
  $('#auth-password').type = 'password';
  $('#auth-password').minLength = reg ? 15 : 1;
  $('#auth-password').autocomplete = reg ? 'new-password' : 'current-password';
  const passwordToggle = $('#password-toggle');
  if (passwordToggle) { passwordToggle.textContent = 'Показать'; passwordToggle.setAttribute('aria-pressed','false'); }
  $('#auth-submit').textContent = reg ? (employer ? 'Создать аккаунт компании →' : 'Создать профиль →') : 'Войти →';
  $('#auth-guidance').textContent = reg
    ? (employer
      ? 'Нужны только имя, компания, email и пароль. Первую вакансию сможете создать сразу после регистрации.'
      : 'Нужны только имя, email и пароль. Профессию, навыки и условия поиска добавите следующим шагом.')
    : 'Если не помните пароль, воспользуйтесь восстановлением доступа.';
  if (reg) {
    $('#auth-route-title').textContent = employer ? 'Как начнётся работа' : 'Как начнётся поиск';
    $('#auth-route-steps').innerHTML = employer
      ? '<span><i>1</i>Аккаунт</span><span><i>2</i>Вакансия</span><span><i>3</i>Кандидаты</span>'
      : '<span><i>1</i>Аккаунт</span><span><i>2</i>Короткий профиль</span><span><i>3</i>Отклик</span>';
  }
  const message = $('#auth-message'); if (message) message.textContent = '';
  document.querySelectorAll('.role-btn').forEach(b => { const active = b.dataset.role === state.role; b.classList.toggle('active', active); b.setAttribute('aria-pressed', String(active)); });
  $('#auth-switch').innerHTML = reg ? 'Уже есть аккаунт? <button type="button" data-switch="login">Войти</button>' : 'Ещё нет аккаунта? <button type="button" data-switch="register">Зарегистрироваться</button>';
}
async function submitAuth(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const message = $('#auth-message');
  const showError = (text, field = null) => {
    if (message) message.textContent = text;
    if (field) field.focus();
  };
  const email = $('#auth-email');
  const password = $('#auth-password');
  if (!email.value.trim() || !email.validity.valid) {
    showError('Проверьте email — он нужен для входа и восстановления доступа.', email);
    return;
  }
  if (state.mode === 'register') {
    const name = $('#auth-name');
    if (name.value.trim().length < 2) {
      showError('Укажите имя и фамилию или привычное имя, которым к вам можно обращаться.', name);
      return;
    }
    if (state.role === 'employer') {
      const company = $('#auth-company');
      if (company.value.trim().length < 2) {
        showError('Укажите название компании.', company);
        return;
      }
    }
    if (password.value.length < 15) {
      showError('Для регистрации нужен пароль не короче 15 символов.', password);
      return;
    }
  } else if (!password.value) {
    showError('Введите пароль.', password);
    return;
  }
  const body = {email:email.value.trim(), password:password.value};
  if (state.mode === 'register') {
    body.role = state.role; body.name = $('#auth-name').value.trim();
    if (body.role === 'employer') body.company_name = $('#auth-company').value.trim();
  }
  const btn = $('#auth-submit'); btn.disabled = true;
  if (message) message.textContent = '';
  try {
    const data = await api(state.mode === 'register' ? '/api/register' : '/api/login', {method:'POST', body:JSON.stringify(body)});
    $('#auth-dialog').close(); state.user = data.user;
    state.tab = state.mode === 'register'
      ? (data.user.role === 'candidate' ? 'profile' : data.user.role === 'employer' ? 'create' : 'overview')
      : 'overview';
    await showDashboard(true);
    toast(state.mode === 'register'
      ? (data.user.role === 'candidate' ? 'Аккаунт создан. Заполните короткий профиль.' : data.user.role === 'employer' ? 'Аккаунт создан. Можно разместить первую вакансию.' : 'Аккаунт создан.')
      : 'Вы вошли в аккаунт.');
  } catch(e) {
    showError(e.message || 'Не удалось выполнить вход. Проверьте данные и попробуйте ещё раз.');
  } finally { btn.disabled = false; }
}
function syncResponsiveMemberActions() {
  const useMobile = window.matchMedia('(max-width: 700px)').matches;
  const memberDesktop = $('#member-actions');
  const memberMobile = $('#mobile-member-slot');
  const account = $('#account-open');
  const logout = $('#logout');
  if (memberDesktop && memberMobile && account && logout) {
    const memberTarget = useMobile ? memberMobile : memberDesktop;
    if (account.parentElement !== memberTarget) memberTarget.append(account, logout);
  }
  const guestDesktop = $('#guest-actions');
  const guestMobile = $('#mobile-guest-slot');
  const login = $('#login-open');
  const register = $('#register-open');
  if (guestDesktop && guestMobile && login && register) {
    const guestTarget = useMobile ? guestMobile : guestDesktop;
    if (login.parentElement !== guestTarget) guestTarget.append(login, register);
  }
}
async function reloadUser() {
  syncResponsiveMemberActions();
  try { const data = await api('/api/me'); state.user = data.user; } catch { state.user = null; }
  $('#guest-actions').classList.toggle('hidden', !!state.user);
  $('#member-actions').classList.toggle('hidden', !state.user);
  $('#mobile-guest-actions')?.classList.toggle('hidden', !!state.user);
  $('#mobile-member-actions')?.classList.toggle('hidden', !state.user);
  $('#dashboard').classList.toggle('hidden', !state.user);
}
async function showDashboard(scroll = false) {
  await reloadUser(); if (!state.user) { openAuth('login'); return; }
  $('#welcome').textContent = `Здравствуйте, ${state.user.name.split(' ')[0]}!`;
  $('#account-subtitle').textContent = ({candidate:'Вакансии, отклики и приглашения — в одном месте.',employer:'Вакансии, отклики и знакомства с кандидатами — в одном месте.',admin:'Обзор работы платформы.'})[state.user.role];
  if (state.user.role === 'candidate') await renderCandidate();
  if (state.user.role === 'employer') await renderEmployer();
  if (state.user.role === 'admin') await renderAdmin();
  if (scroll) $('#dashboard').scrollIntoView({behavior:'smooth',block:'start'});
}
function tabsMarkup(items, heading, subtitle) {
  const icons = {
    overview:'⌂',profile:'●',offers:'↗',invitations:'✉',favorites:'♡',
    applications:'✓',changes:'↻',email:'@',vacancies:'▤',create:'＋',edit:'✎',company:'◆'
  };
  const roleLabel = state.user?.role === 'employer' ? 'Работодатель' : state.user?.role === 'candidate' ? 'Соискатель' : 'Администратор';
  return `<aside class="panel side-panel">
    <div class="dashboard-identity"><span class="dashboard-avatar" aria-hidden="true">${esc((state.user?.name||roleLabel).trim().charAt(0).toUpperCase())}</span><div><span>${esc(roleLabel)}</span><strong>${esc(subtitle)}</strong></div></div>
    <span class="section-kicker dashboard-menu-kicker">${esc(heading)}</span>
    <nav class="dashboard-tabs" aria-label="Разделы личного кабинета">${items.map(t => `<button type="button" data-tab="${esc(t.id)}" class="${state.tab === t.id ? 'active' : ''}"><span class="dashboard-tab-icon" aria-hidden="true">${icons[t.id]||'•'}</span><span>${esc(t.label)}</span></button>`).join('')}</nav>
    <div class="dashboard-side-note"><span>Приватность</span><small>Контакты открываются только в сценарии знакомства.</small></div>
  </aside>`;
}
function candidateProfileHealth(profile = {}) {
  const checks = [
    Boolean((profile.profession || '').trim()),
    Boolean((profile.city || '').trim()),
    Number(profile.salary_min || 0) > 0,
    Boolean((profile.skills || '').trim()),
    Boolean((profile.about || '').trim())
  ];
  const completed = checks.filter(Boolean).length;
  const percent = completed * 20;
  const next = !checks[0] ? 'Укажите профессию'
    : !checks[1] ? 'Укажите город'
    : !checks[2] ? 'Добавьте зарплатные ожидания'
    : !checks[3] ? 'Добавьте несколько навыков'
    : !checks[4] ? 'Коротко опишите опыт'
    : 'Профиль готов к подбору';
  return {percent, next};
}
function profileMarkup(profile = {}, user = {}) {
  const health = candidateProfileHealth(profile);
  // Additional details stay optional; open them explicitly when the candidate is ready.
  return `<div class="panel candidate-profile">
    <span class="section-kicker">ВАШ ПРОФЕССИОНАЛЬНЫЙ ОПЫТ</span>
    <h3>Расскажите, какую работу вы ищете</h3>
    <p class="muted">Начните с нескольких пунктов. Большое резюме не требуется. Эти сведения используются для подбора вакансий.</p>
    <div class="profile-health" role="status" aria-label="Готовность профиля">
      <div class="profile-health-copy"><span>Готовность профиля</span><strong>${health.percent}%</strong></div>
      <div class="profile-health-track"><span style="width:${health.percent}%"></span></div>
      <small>${esc(health.next)}</small>
    </div>
    <div class="profile-visibility">
      <div><span class="profile-visibility-dot ${profile.is_active !== 0 ? 'is-active' : ''}"></span><div><strong>${profile.is_active !== 0 ? 'Профиль участвует в подборе' : 'Профиль скрыт из подбора'}</strong><small>${profile.is_active !== 0 ? 'Работодатели могут увидеть профессиональную часть профиля без ваших контактов.' : 'Работодатели не увидят профиль в подборе, пока вы его не включите.'}</small></div></div>
      <label class="switch-control"><input type="checkbox" name="is_active" form="profile-form" ${profile.is_active !== 0 ? 'checked':''}><span aria-hidden="true"></span><b>${profile.is_active !== 0 ? 'Включён' : 'Выключен'}</b></label>
    </div>
    <div class="profile-progress" role="note"><span class="profile-progress-step">1</span><div><strong>Основные сведения</strong><small>Профессия, город, навыки, зарплата и график</small></div></div>
    <form id="profile-form">
      <div class="form-grid">
        <div class="field"><label for="profile-profession">Ваша профессия <span class="required-mark">*</span></label>
          <input id="profile-profession" name="profession" value="${esc(profile.profession)}" placeholder="Например, бухгалтер" required minlength="2" maxlength="120" autocomplete="organization-title">
          <small class="field-help">Укажите привычное название профессии.</small></div>
        <div class="field"><label for="profile-city">В каком городе ищете работу? <span class="required-mark">*</span></label>
          <input id="profile-city" name="city" value="${esc(profile.city)}" placeholder="Например, Москва" required minlength="2" maxlength="100" autocomplete="address-level2"></div>
        <div class="field wide"><label for="profile-skills">Что вы хорошо умеете? (необязательно)</label>
          <input id="profile-skills" name="skills" value="${esc(profile.skills)}" placeholder="Например: 1С, учёт, Excel" maxlength="300" aria-describedby="profile-skills-help">
          <small class="field-help" id="profile-skills-help">Напишите несколько навыков через запятую. Это поможет точнее подобрать работу.</small></div>
        <div class="field"><label for="profile-salary">Желаемая зарплата от, ₽ <span class="required-mark">*</span></label>
          <input id="profile-salary" name="salary_min" type="number" inputmode="numeric" value="${profile.salary_min || 0}" min="0" max="10000000" required></div>
        <div class="field"><label for="profile-schedule">Удобный график</label>
          <select id="profile-schedule" name="schedule">${optList(schedules,profile.schedule)}</select></div>
        <div class="field wide experience-entry">
          <div class="experience-entry-inner">
            <div>
              <strong>Хотите рассказать о своём опыте?</strong>
              <p>${profile.about ? 'В вашем профиле уже есть описание. Его можно дополнить.' : 'Поможем подобрать слова по трём простым вопросам. Большое резюме не нужно.'}</p>
            </div>
            <button type="button" class="btn btn-outline" id="experience-start" aria-controls="experience-helper" aria-expanded="false">Помочь описать опыт →</button>
          </div>
        </div>
        <div class="field wide">
          <details class="profile-optional">
            <summary>Дополнительные сведения (по желанию)</summary>
            <p class="muted">Эти поля можно заполнить позже. Они не обязательны для начала поиска.</p>
            <div class="form-grid">
              <div class="field"><label for="profile-employment">Тип занятости</label>
                <select id="profile-employment" name="employment">${optList(employment,profile.employment)}</select></div>
              <div class="field"><label for="profile-phone">Телефон (необязательно)</label>
                <input id="profile-phone" name="phone" type="tel" value="${esc(user.phone)}" maxlength="30" autocomplete="off" placeholder="Например, +7 900 000-00-00">
                <small class="field-help">Телефон не показывается работодателю автоматически и открывается только в предусмотренном сценарии знакомства.</small></div>
              <div class="field wide"><label for="profile-about">Немного о вашем опыте</label>
                <textarea id="profile-about" name="about" maxlength="700" placeholder="Расскажите о своей работе и достижениях. Не указывайте здесь контакты.">${esc(profile.about)}</textarea>
                <details class="experience-helper" id="experience-helper">
                  <summary>Не знаете, что написать? Поможем описать ваш опыт</summary>
                  <p class="experience-helper-intro">Ответьте на три простых вопроса. Мы составим текст только из ваших слов. Проверьте его и при желании добавьте в профиль.</p>
                  <p class="experience-helper-privacy">Помощник работает локально и не отправляет ответы во внешние сервисы. Не добавляйте телефон, email или адрес в описание опыта.</p>
                  <div class="experience-helper-fields">
                    <label for="experience-work">1. Какой работой вы занимались?</label>
                    <textarea id="experience-work" rows="2" maxlength="220" placeholder="Например: учёт товаров на складе"></textarea>
                    <label for="experience-tasks">2. Что входило в ваши задачи?</label>
                    <textarea id="experience-tasks" rows="2" maxlength="240" placeholder="Например: принимал поставки, оформлял документы"></textarea>
                    <label for="experience-strengths">3. Что у вас получается особенно хорошо?</label>
                    <textarea id="experience-strengths" rows="2" maxlength="240" placeholder="Например: работа с 1С, аккуратный учёт"></textarea>
                  </div>
                  <div class="experience-helper-actions">
                    <button type="button" class="btn btn-outline" id="experience-build">Составить текст</button>
                    <button type="button" class="btn btn-primary" id="experience-insert" disabled>Добавить в профиль</button>
                  </div>
                  <div class="experience-helper-preview" id="experience-preview-block" hidden>
                    <strong>Предварительный вариант</strong>
                    <p id="experience-preview"></p>
                  </div>
                  <p class="experience-helper-message" id="experience-helper-message" role="status" aria-live="polite"></p>
                  <p class="field-help">При добавлении помощник сохранит существующее описание и дополнит его. Чтобы изменения остались в профиле, нажмите ниже «Сохранить профиль».</p>
                </details></div>
            </div>
          </details>
        </div>
      </div>
      <p class="form-note">* Поля, необходимые для поиска вакансий. Ваши контакты не передаются работодателю автоматически.</p>
      <button class="btn btn-primary btn-lg" type="submit">Сохранить профиль</button>
    </form>
    <section class="profile-public-preview" aria-label="Предпросмотр профиля для работодателя">
      <div class="split-header"><div><span class="section-kicker">ЧТО УВИДИТ РАБОТОДАТЕЛЬ</span><h4>${esc(profile.profession || 'Профессия пока не указана')}</h4></div><span class="privacy-chip">Контакты скрыты</span></div>
      <div class="profile-preview-meta"><span>⌖ ${esc(profile.city || 'Город не указан')}</span><span>от ${money(profile.salary_min || 0)}</span><span>${esc(profile.schedule || 'График не указан')}</span></div>
      <div class="job-skill-tags">${String(profile.skills || '').split(',').map(x=>x.trim()).filter(Boolean).slice(0,6).map(x=>`<span>${esc(x)}</span>`).join('') || '<span>Добавьте навыки</span>'}</div>
      ${profile.about ? `<p>${esc(profile.about.slice(0,260))}${profile.about.length>260?'…':''}</p>` : '<p class="muted">Добавьте короткое описание опыта — оно поможет работодателю понять вашу специализацию.</p>'}
      <div class="profile-preview-hidden"><span>🔒</span><div><strong>Имя, телефон и email не показываются</strong><small>Они открываются только после вашего отдельного согласия на знакомство.</small></div></div>
    </section>
    <div class="profile-next-actions" aria-label="Следующие шаги">
      <strong>После сохранения:</strong>
      <button type="button" class="btn btn-outline" data-tab="offers">Посмотреть подходящие вакансии →</button>
      <button type="button" class="btn btn-outline" data-tab="applications">Проверить мои отклики</button>
    </div>
  </div>`;
}
function candidateOverviewApplicationCard(item) {
  const statusText = workflowStatus(item, statusTitle[item.status] || item.status);
  return `<article class="candidate-overview-item">
    <div class="candidate-overview-item-head"><div><span class="card-eyebrow">ОТКЛИК</span><strong>${esc(item.title)}</strong><small>${esc(item.company_name)} · ${esc(item.city)}</small></div><span class="mini-badge">${esc(statusText)}</span></div>
    ${interactionStageMarkup(item,'application')}
    <button type="button" class="btn btn-outline btn-tiny" data-tab="applications">Открыть историю →</button>
  </article>`;
}
function candidateOverviewInvitationCard(item) {
  return `<article class="candidate-overview-item is-invitation">
    <div class="candidate-overview-item-head"><div><span class="card-eyebrow">ПРИГЛАШЕНИЕ</span><strong>${esc(item.title)}</strong><small>${esc(item.company_name)} · ${esc(item.city)}</small></div><span class="mini-badge ${statusBadge[item.status]||''}">${esc(workflowStatus(item,statusTitle[item.status]||item.status))}</span></div>
    ${employerPublicTrustMarkup(item)}
    <button type="button" class="btn btn-primary btn-tiny" data-tab="invitations">Ответить на приглашение →</button>
  </article>`;
}
function candidateStatusChip(ok, yes, no) {
  return `<span class="candidate-status-chip ${ok?'is-ok':'is-pending'}"><i aria-hidden="true">${ok?'✓':'!'}</i>${esc(ok?yes:no)}</span>`;
}

async function renderCandidate() {
  const nav = [{id:'overview',label:'Обзор'},{id:'profile',label:'Мой профиль'},{id:'offers',label:'Подходящие вакансии'},{id:'invitations',label:'Приглашения'}];
  if (!nav.some(t => t.id === state.tab)) state.tab = 'overview';
  $('#account-content').innerHTML = `<div class="dashboard-grid">${tabsMarkup(nav,'ДЛЯ СОИСКАТЕЛЯ','Ваша карьера')}<div id="dashboard-main"><div class="loading">Загрузка...</div></div></div>`;
  const target = $('#dashboard-main');
  try {
    if (state.tab === 'overview') {
      const [jobsResult, applicationsResult, invitationsResult, favoritesResult, updatesResult, emailResult] = await Promise.all([
        api('/api/candidate/jobs'),
        api('/api/candidate/applications'),
        api('/api/candidate/invitations'),
        api('/api/candidate/favorites'),
        api('/api/candidate/vacancy-updates'),
        api('/api/account/email/status')
      ]);
      const health = candidateProfileHealth(state.user.profile || {});
      const jobs = jobsResult.jobs || [];
      const applications = applicationsResult.applications || [];
      const invitations = invitationsResult.invitations || [];
      const favorites = favoritesResult.jobs || [];
      const pendingInvitationsList = invitations.filter(item => item.status === 'sent');
      const pendingInvitations = pendingInvitationsList.length;
      const activeApplicationsList = applications.filter(item => ['applied','reviewing','interview'].includes(item.status));
      const activeApplications = activeApplicationsList.length;
      const unreadChanges = Number(updatesResult.unread_count || 0);
      const emailVerified = Boolean(emailResult.email_verified);
      const profileActive = Boolean(state.user.profile) && state.user.profile.is_active !== 0;
      let nextTitle = 'Посмотрите подходящие вакансии';
      let nextText = 'Профиль уже может участвовать в подборе. Проверьте новые рекомендации.';
      let nextAction = '<button class="btn btn-primary" data-tab="offers">Открыть рекомендации →</button>';
      if (!emailVerified) {
        nextTitle = 'Подтвердите email';
        nextText = 'Это защитит доступ к аккаунту и поможет надёжно получать сервисные уведомления.';
        nextAction = '<button class="btn btn-primary" data-tab="email">Подтвердить email →</button>';
      } else if (health.percent < 60) {
        nextTitle = health.next;
        nextText = 'Чем полнее основные данные, тем точнее подбор вакансий.';
        nextAction = '<button class="btn btn-primary" data-tab="profile">Продолжить профиль →</button>';
      } else if (pendingInvitations > 0) {
        nextTitle = 'Ответьте на приглашение работодателя';
        nextText = `Ожидают решения: ${pendingInvitations}. Контакты не откроются без вашего согласия.`;
        nextAction = '<button class="btn btn-primary" data-tab="invitations">Открыть приглашения →</button>';
      } else if (unreadChanges > 0) {
        nextTitle = 'Проверьте изменения условий';
        nextText = `Работодатели изменили условия по ${unreadChanges} вакансии(ям), с которыми вы уже взаимодействовали.`;
        nextAction = '<button class="btn btn-primary" data-tab="changes">Посмотреть изменения →</button>';
      } else if (activeApplications > 0) {
        nextTitle = 'Проверьте статус откликов';
        nextText = `Активных откликов: ${activeApplications}. Посмотрите, на каком этапе каждый из них.`;
        nextAction = '<button class="btn btn-primary" data-tab="applications">Открыть отклики →</button>';
      } else if (!jobs.length) {
        nextTitle = 'Расширьте поиск';
        nextText = 'Строгих совпадений пока нет — можно посмотреть все открытые вакансии.';
        nextAction = '<a class="btn btn-primary" href="#jobs">Все вакансии →</a>';
      }
      target.innerHTML = `<div class="overview-stack">
        <section class="panel dashboard-overview-hero">
          <span class="section-kicker">ВАШ СЛЕДУЮЩИЙ ШАГ</span>
          <div class="overview-priority"><div><h3>${esc(nextTitle)}</h3><p class="muted">${esc(nextText)}</p></div>${nextAction}</div>
          <div class="overview-health"><span>Готовность профиля</span><div class="profile-health-track"><span style="width:${health.percent}%"></span></div><strong>${health.percent}%</strong></div>
          <div class="candidate-status-row">
            ${candidateStatusChip(emailVerified,'Email подтверждён','Подтвердите email')}
            ${candidateStatusChip(profileActive,'Профиль участвует в подборе','Профиль скрыт из подбора')}
            <span class="candidate-status-chip is-private"><i aria-hidden="true">🔒</i>Контакты скрыты по умолчанию</span>
          </div>
        </section>
        ${unreadChanges ? `<section class="overview-alert" role="status"><div><strong>Изменились условия вакансий</strong><span>Непрочитанных изменений: ${unreadChanges}</span></div><button class="btn btn-outline btn-tiny" data-tab="changes">Проверить изменения</button></section>` : ''}
        <section class="overview-stat-grid" aria-label="Сводка соискателя">
          <button type="button" class="overview-stat-card" data-tab="offers"><strong>${jobs.length}</strong><span>Подходящие вакансии</span><small>По вашему профилю</small></button>
          <button type="button" class="overview-stat-card" data-tab="applications"><strong>${activeApplications}</strong><span>Активные отклики</span><small>В процессе</small></button>
          <button type="button" class="overview-stat-card" data-tab="invitations"><strong>${pendingInvitations}</strong><span>Новые приглашения</span><small>Ждут решения</small></button>
          <button type="button" class="overview-stat-card" data-tab="favorites"><strong>${favorites.length}</strong><span>Избранное</span><small>Сохранённые вакансии</small></button>
        </section>
        <section class="candidate-overview-grid">
          <div class="panel candidate-overview-section">
            <div class="split-header"><div><span class="section-kicker">РЕКОМЕНДАЦИИ</span><h3>Вакансии для вас</h3><p class="muted">Сначала варианты с лучшим совпадением по вашему профилю.</p></div><button class="btn btn-outline btn-tiny" data-tab="offers">Все рекомендации</button></div>
            <div class="candidate-mini-jobs">${jobs.length ? jobs.slice(0,2).map(job=>jobMarkup(job,true)).join('') : '<div class="empty-state"><p>Точных совпадений пока нет.</p><a class="btn btn-outline btn-tiny" href="#jobs">Посмотреть все вакансии</a></div>'}</div>
          </div>
          <div class="panel candidate-overview-section">
            <div class="split-header"><div><span class="section-kicker">ОТКЛИКИ</span><h3>Сейчас в процессе</h3><p class="muted">Последние активные отклики и их текущий этап.</p></div><button class="btn btn-outline btn-tiny" data-tab="applications">Все отклики</button></div>
            <div class="candidate-overview-list">${activeApplicationsList.length ? activeApplicationsList.slice(0,2).map(candidateOverviewApplicationCard).join('') : '<div class="empty-state"><p>Активных откликов пока нет.</p><button class="btn btn-primary btn-tiny" data-tab="offers">Выбрать вакансию →</button></div>'}</div>
          </div>
        </section>
        ${pendingInvitationsList.length ? `<section class="panel candidate-overview-section candidate-invitations-preview"><div class="split-header"><div><span class="section-kicker">ТРЕБУЕТ ОТВЕТА</span><h3>Новые приглашения</h3><p class="muted">Решение за вами: контакты остаются закрытыми, пока вы не согласитесь.</p></div><button class="btn btn-outline btn-tiny" data-tab="invitations">Все приглашения</button></div><div class="candidate-overview-list">${pendingInvitationsList.slice(0,2).map(candidateOverviewInvitationCard).join('')}</div></section>` : ''}
        ${favorites.length ? `<section class="candidate-saved-strip"><div><span class="section-kicker">СОХРАНЕНО</span><strong>${favorites.length} вакансий в избранном</strong><small>Можно вернуться к ним позже и сравнить условия.</small></div><button class="btn btn-outline btn-tiny" data-tab="favorites">Открыть сохранённые →</button></section>` : ''}
      </div>`;
    } else if (state.tab === 'profile') target.innerHTML = profileMarkup(state.user.profile, state.user);
    else if (state.tab === 'offers') {
      const {jobs} = await api('/api/candidate/jobs');
      target.innerHTML = `<div class="panel"><h3>Подходящие вакансии</h3><p class="muted">Алгоритм учитывает навыки, город, график и ожидания по зарплате. Совпадение — рекомендация, не решение о трудоустройстве.</p><div class="dashboard-list">${jobs.length ? jobs.map(x => jobMarkup(x,true)).join('') : '<div class="empty-state"><p>Подходящих вакансий пока нет. Можно изменить профессию, город или желаемую зарплату.</p><button type="button" class="btn btn-outline" data-tab="profile">Уточнить профиль</button> <a class="btn btn-primary" href="#jobs">Посмотреть все вакансии</a></div>'}</div></div>`;
    } else {
      const {invitations} = await api('/api/candidate/invitations');
      target.innerHTML = `<div class="panel"><h3>Приглашения от компаний</h3><p class="muted">Откройте контакт только тем компаниям, с которыми вы хотите познакомиться.</p><div class="dashboard-list">${invitations.length ? invitations.map(invitationCandidateMarkup).join('') : '<div class="empty-state">Приглашений пока нет. Заполните профиль, и работодатели смогут найти вас.</div>'}</div></div>`;
    }
  } catch(e) { target.innerHTML = `<div class="panel">${esc(e.message)}</div>`; toast(e.message,true); }
}
function invitationCandidateMarkup(x) {
  return `<article class="item-card invitation-card"><header><div><span class="card-eyebrow">ПРИГЛАШЕНИЕ</span><h4>${esc(x.title)}</h4><p>${esc(x.company_name)} · ${esc(x.city)} · ${formatPay(x)}</p>${employerPublicTrustMarkup(x)}</div><span class="mini-badge ${statusBadge[x.status]}">${esc(workflowStatus(x,statusTitle[x.status]))}</span></header>
   ${interactionStageMarkup(x,'invitation')}
   <p class="invitation-description">${esc(x.description || 'Подробности на собеседовании.')}</p>
   ${activityTimelineMarkup(x)}
   ${x.status === 'sent' ? `<div class="consent-box"><strong>Хотите познакомиться с компанией?</strong><p>Имя и контакты не будут переданы, пока вы явно не согласитесь.</p><label class="checks"><input type="checkbox" id="consent-${x.id}"> Да, я разрешаю открыть мои имя и контакты этой компании после подтверждения знакомства</label></div><div class="item-actions invitation-actions"><button class="btn btn-primary" data-action="accept" data-id="${x.id}">Да, интересно →</button><button class="btn btn-outline" data-action="decline" data-id="${x.id}">Нет, спасибо</button></div>` : (x.contact_shared ? '<div class="info-box contact-opened-note"><strong>✓ Знакомство состоялось</strong><span>Контакты открыты работодателю в демонстрационном режиме.</span></div>' : '')}</article>`;
}
function employerPublicTrustMarkup(item = {}) {
  const badges = [];
  if (item.employer_verified) badges.push('<span class="employer-trust-badge verified">✓ Компания проверена</span>');
  else {
    if (item.employer_email_verified) badges.push('<span class="employer-trust-badge">✓ Email подтверждён</span>');
    if (item.employer_inn_provided) badges.push('<span class="employer-trust-badge">Реквизиты указаны</span>');
  }
  return badges.length ? `<div class="employer-trust-badges">${badges.join('')}</div>` : '<div class="employer-trust-badges"><span class="employer-trust-badge neutral">Статус компании не подтверждён</span></div>';
}
function trustSignalState(value, yes, no) {
  return `<span class="trust-signal ${value ? 'is-ok' : 'is-pending'}"><i aria-hidden="true">${value ? '✓' : '·'}</i><b>${esc(value ? yes : no)}</b></span>`;
}
function companyTrustMarkup(trust = {}) {
  const completed = [trust.email_verified,trust.inn_provided,trust.verified].filter(Boolean).length;
  return `<div class="company-trust-summary">
    <div class="company-trust-score"><strong>${completed}/3</strong><span>уровня доверия</span></div>
    <div class="company-trust-signals">
      ${trustSignalState(trust.email_verified,'Email подтверждён','Email не подтверждён')}
      ${trustSignalState(trust.inn_provided,'ИНН указан','ИНН не указан')}
      ${trustSignalState(trust.verified,'Компания проверена','Компания ещё не проверена')}
    </div>
  </div>`;
}
function employerCompanyMarkup(result) {
  const company = result.company || {};
  const trust = result.trust || {};
  const verificationText = trust.verified
    ? 'Компания проверена администратором СТАЖНО. Если изменить название или ИНН, проверка будет снята автоматически.'
    : (trust.email_verified && trust.inn_provided
      ? 'Email и реквизиты заполнены. Компания готова к проверке администратором.'
      : 'Для проверки компании подтвердите email и укажите ИНН.');
  return `<div class="panel company-profile-panel">
    <div class="split-header"><div><span class="section-kicker">КОМПАНИЯ</span><h3>Профиль работодателя</h3><p class="muted">Эти данные помогают соискателю понимать, кто разместил вакансию. ИНН публично не показывается.</p></div>${trust.verified?'<span class="verified-company-badge">✓ Компания проверена</span>':''}</div>
    ${companyTrustMarkup(trust)}
    <div class="company-verification-note ${trust.verified?'is-verified':''}"><strong>${trust.verified?'Проверка пройдена':'Статус проверки'}</strong><p>${esc(verificationText)}</p></div>
    <form id="company-form" class="company-form">
      <div class="form-grid">
        <div class="field wide"><label for="company-name">Название компании *</label><input id="company-name" name="company_name" value="${esc(company.company_name||'')}" minlength="2" maxlength="120" required><small class="field-help">Так название отображается в вакансиях и приглашениях.</small></div>
        <div class="field wide"><label for="company-about">О компании</label><textarea id="company-about" name="about" maxlength="1200" rows="5" placeholder="Коротко расскажите о компании и условиях работы.">${esc(company.about||'')}</textarea><small class="field-help">Это описание увидят соискатели в публичной карточке компании.</small></div>
        <div class="field"><label for="company-inn">ИНН компании</label><input id="company-inn" name="inn" value="${esc(company.inn||'')}" inputmode="numeric" maxlength="12" placeholder="10 или 12 цифр"><small class="field-help">Нужен для проверки компании. Соискателям полный ИНН не показывается.</small></div>
        <div class="field company-email-status"><label>Email аккаунта</label><div class="company-static-field"><strong>${esc(state.user?.email||'')}</strong><span class="${trust.email_verified?'is-ok':'is-pending'}">${trust.email_verified?'✓ Подтверждён':'Не подтверждён'}</span></div>${trust.email_verified?'':'<button type="button" class="btn btn-outline btn-tiny" data-v02-action="verify-email">Подтвердить email</button>'}</div>
      </div>
      <div class="company-form-actions"><button class="btn btn-primary" type="submit">Сохранить данные компании</button><small>Изменение названия или ИНН снимает статус проверки до повторной проверки администратором.</small></div>
    </form>
  </div>`;
}

async function renderEmployer() {
  const nav = [{id:'overview',label:'Обзор'},{id:'company',label:'Компания'},{id:'vacancies',label:'Мои вакансии'},{id:'create',label:'Новая вакансия'},{id:'invitations',label:'Приглашения и контакты'}];
  if (state.tab === 'edit') nav.splice(2, 0, {id:'edit',label:'Редактирование'});
  if (!nav.some(t => t.id === state.tab)) state.tab = 'overview';
  $('#account-content').innerHTML = `<div class="dashboard-grid">${tabsMarkup(nav,'ДЛЯ КОМПАНИИ',state.user.company?.company_name || 'Работодатель')}<div id="dashboard-main"><div class="loading">Загрузка...</div></div></div>`;
  const target = $('#dashboard-main');
  try {
    if (state.tab === 'overview') {
      const [jobsResult, applicationsResult, invitationsResult, companyResult] = await Promise.all([
        api('/api/employer/vacancies'),
        api('/api/employer/applications'),
        api('/api/employer/invitations'),
        api('/api/employer/company')
      ]);
      const jobs = jobsResult.jobs || [];
      const applications = applicationsResult.applications || [];
      const invitations = invitationsResult.invitations || [];
      const companyTrust = companyResult.trust || {};
      const openJobs = jobs.filter(job => job.status === 'open');
      const waitingApplications = applications.filter(item => ['applied','reviewing'].includes(item.status));
      const acceptedInvitations = invitations.filter(item => item.status === 'accepted' && !item.contact_shared);
      const openedContacts = invitations.filter(item => item.contact_shared).length;
      let nextTitle = 'Создайте первую вакансию';
      let nextText = 'После публикации можно получать отклики и запускать подбор кандидатов.';
      let nextAction = '<button class="btn btn-primary" data-tab="create">Создать вакансию →</button>';
      if (acceptedInvitations.length) {
        nextTitle = 'Есть согласие кандидата';
        nextText = `Можно продолжить знакомство по ${acceptedInvitations.length} кандидатам.`;
        nextAction = '<button class="btn btn-primary" data-tab="invitations">Продолжить знакомства →</button>';
      } else if (waitingApplications.length) {
        nextTitle = 'Разберите новые отклики';
        nextText = `Требуют внимания: ${waitingApplications.length}.`;
        nextAction = '<button class="btn btn-primary" data-tab="applications">Открыть отклики →</button>';
      } else if (openJobs.length) {
        nextTitle = 'Запустите подбор по открытой вакансии';
        nextText = 'Посмотрите подходящие обезличенные профили и пригласите тех, кто подходит.';
        nextAction = '<button class="btn btn-primary" data-tab="vacancies">К вакансиям →</button>';
      }
      target.innerHTML = `<div class="overview-stack">
        <section class="panel dashboard-overview-hero employer-overview-hero">
          <span class="section-kicker">ПРИОРИТЕТ СЕЙЧАС</span>
          <div class="overview-priority"><div><h3>${esc(nextTitle)}</h3><p class="muted">${esc(nextText)}</p></div>${nextAction}</div>
        </section>
        <section class="panel employer-trust-overview">
          <div class="split-header"><div><span class="section-kicker">ДОВЕРИЕ К КОМПАНИИ</span><h3>${esc(companyResult.company?.company_name || 'Компания')}</h3></div><button class="btn btn-outline btn-tiny" data-tab="company">Настроить компанию →</button></div>
          ${companyTrustMarkup(companyTrust)}
        </section>
        <section class="overview-stat-grid employer-overview-stats" aria-label="Сводка работодателя">
          <button type="button" class="overview-stat-card" data-tab="vacancies"><strong>${openJobs.length}</strong><span>Открытые вакансии</span><small>Сейчас в работе</small></button>
          <button type="button" class="overview-stat-card" data-tab="applications"><strong>${waitingApplications.length}</strong><span>Отклики требуют внимания</span><small>Новые и на рассмотрении</small></button>
          <button type="button" class="overview-stat-card" data-tab="invitations"><strong>${acceptedInvitations.length}</strong><span>Согласия кандидатов</span><small>Можно продолжить знакомство</small></button>
          <button type="button" class="overview-stat-card" data-tab="invitations"><strong>${openedContacts}</strong><span>Открытые контакты</span><small>Завершённые знакомства</small></button>
        </section>
        <section class="panel overview-funnel">
          <div class="split-header"><div><span class="section-kicker">ВОРОНКА</span><h3>От вакансии до знакомства</h3></div><button class="btn btn-outline btn-tiny" data-tab="vacancies">Управлять вакансиями</button></div>
          <div class="overview-funnel-steps">
            <div><strong>${jobs.length}</strong><span>Вакансии</span></div><b>→</b>
            <div><strong>${applications.length}</strong><span>Отклики</span></div><b>→</b>
            <div><strong>${invitations.length}</strong><span>Приглашения</span></div><b>→</b>
            <div><strong>${openedContacts}</strong><span>Знакомства</span></div>
          </div>
        </section>
      </div>`;
    } else if (state.tab === 'company') {
      const result = await api('/api/employer/company');
      target.innerHTML = employerCompanyMarkup(result);
    } else if (state.tab === 'create') target.innerHTML = vacancyFormMarkup();
    else if (state.tab === 'edit') await loadEmployerVacancyEdit();
    else if (state.tab === 'vacancies') await loadEmployerVacancies();
    else await loadEmployerInvitations();
  } catch(e) { target.innerHTML = `<div class="panel">${esc(e.message)}</div>`; toast(e.message,true); }
}
function vacancyFormMarkup(job = null) {
  const isEdit = Boolean(job);
  const sections = isEdit ? window.OpytnovacancyWizard?.splitDescription(job.description) : null;
  const legacy = isEdit && !sections;
  const fields = legacy
    ? `<div class="field vacancy-legacy"><label for="vacancy-legacy">Исходное описание (старый формат)</label>
         <textarea id="vacancy-legacy" name="legacy_description" maxlength="1200" rows="6" placeholder="Описание вакансии">${esc(job.description || '')}</textarea>
         <small class="field-help">Сохраняем прежний текст без автоматического разбиения. Здесь можно обновить требования и условия вручную.</small></div>`
    : `<div class="field"><label for="vacancy-responsibilities">Что предстоит делать? *</label>
         <textarea id="vacancy-responsibilities" name="responsibilities" maxlength="400" rows="3" required placeholder="Например: вести учёт товаров, принимать поставки, оформлять документы">${esc(sections?.responsibilities || '')}</textarea>
         <small class="field-help">Перечислите реальные обязанности, простыми словами. До 400 символов.</small>
       </div>
       <div class="field"><label for="vacancy-requirements">Что нужно уметь? *</label>
         <textarea id="vacancy-requirements" name="requirements" maxlength="300" rows="3" required placeholder="Например: базовое знание 1С, внимательность. Если особых требований нет — так и напишите">${esc(sections?.requirements || '')}</textarea>
         <small class="field-help">Только необходимые навыки. Не указывайте возрастные ограничения. До 300 символов.</small>
       </div>
       <div class="field"><label for="vacancy-conditions">Что предлагает компания? *</label>
         <textarea id="vacancy-conditions" name="conditions" maxlength="350" rows="3" required placeholder="Например: сменный график 2/2, официальное оформление, обучение на месте">${esc(sections?.conditions || '')}</textarea>
         <small class="field-help">График, оформление, место работы, особенности оплаты. До 350 символов.</small>
       </div>`;
  return `<div class="panel vacancy-compose">
    <div class="vacancy-compose-header"><div><span class="section-kicker">${isEdit ? 'РЕДАКТИРОВАНИЕ ВАКАНСИИ' : 'НОВАЯ ВАКАНСИЯ'}</span><h3>${isEdit ? 'Изменить вакансию' : 'Разместить вакансию'}</h3><p class="muted">${isEdit ? 'Исправьте условия и проверьте объявление перед сохранением. Отклики и история вакансии сохранятся.' : 'Сначала основные условия, затем короткое описание работы. Перед публикацией вы увидите вакансию глазами соискателя.'}</p></div><span class="vacancy-compose-badge">${isEdit ? 'Изменения сохранят историю' : 'Размещение бесплатно'}</span></div>
    <p class="vacancy-demo-warning">Не добавляйте телефон или email в текст вакансии. Для контакта используется защищённый сценарий знакомства.</p>
    ${isEdit ? `<p class="vacancy-edit-warning">Редактирование не удаляет отклики и приглашения. После изменения условий соискатель увидит уведомление в своём кабинете.</p>` : ``}
    <form id="vacancy-form" data-edit-id="${isEdit ? job.id : ''}" data-revision="${isEdit ? esc(job.revision) : ''}" data-edit-mode="${legacy ? 'legacy' : 'structured'}">
      <div class="vacancy-progress" aria-label="Прогресс заполнения вакансии">
        <span class="vacancy-progress-step is-current"><i>1</i><b>Основное</b></span>
        <span class="vacancy-progress-step"><i>2</i><b>Описание</b></span>
        <span class="vacancy-progress-step"><i>3</i><b>Проверка</b></span>
        <span class="vacancy-progress-step"><i>4</i><b>${isEdit ? 'Сохранение' : 'Публикация'}</b></span>
        <div class="vacancy-progress-meta"><div class="vacancy-progress-track"><span id="vacancy-progress-bar"></span></div><small id="vacancy-progress-label">Начните с основных условий</small></div>
      </div>
      <fieldset class="vacancy-step" data-vacancy-step="1">
        <legend>1. Основные условия</legend>
        <p class="vacancy-step-hint">Укажите то, по чему соискатель решает, подходит ли ему вакансия: должность, место работы, зарплату и график.</p>
        <div class="form-grid">
          <div class="field wide"><label for="vacancy-title">Должность *</label><input id="vacancy-title" name="title" value="${esc(job?.title || '')}" placeholder="Например, инженер по эксплуатации" minlength="3" maxlength="120" required></div>
          <div class="field"><label for="vacancy-city">Город или формат работы *</label><input id="vacancy-city" name="city" value="${esc(job?.city || '')}" placeholder="Например, Москва или Удалённо" minlength="2" maxlength="100" required></div>
          <div class="field"><label for="vacancy-skills">Ключевые навыки (через запятую)</label><input id="vacancy-skills" name="skills" value="${esc(job?.skills || '')}" placeholder="Например, 1С, Excel" maxlength="300"></div>
          <div class="field"><label for="vacancy-salary-min">Зарплата от, ₽ *</label><input id="vacancy-salary-min" name="salary_min" type="number" inputmode="numeric" min="0" max="10000000" value="${isEdit ? Number(job.salary_min) : 50000}" required></div>
          <div class="field"><label for="vacancy-salary-max">Зарплата до, ₽ *</label><input id="vacancy-salary-max" name="salary_max" type="number" inputmode="numeric" min="0" max="10000000" value="${isEdit ? Number(job.salary_max) : 100000}" required></div>
          <div class="field"><label for="vacancy-schedule">График</label><select id="vacancy-schedule" name="schedule">${optList(schedules,job?.schedule || 'Любой')}</select></div>
          <div class="field"><label for="vacancy-employment">Занятость</label><select id="vacancy-employment" name="employment">${optList(employment,job?.employment || 'Любая')}</select></div>
        </div>
      </fieldset>
      <fieldset class="vacancy-step" data-vacancy-step="2">
        <legend>2. Расскажите о работе</legend>
        <p class="vacancy-step-hint">${legacy ? 'Это вакансия старого формата: исходное описание сохранено без потерь.' : 'Три коротких блока: что делать, что важно уметь и что предлагает компания. Пишите простыми словами.'}</p>
        ${fields}
      </fieldset>
      <div class="vacancy-preview-intro" data-vacancy-step="3">
        <strong>3. ${isEdit ? 'Проверьте изменения глазами соискателя' : 'Проверьте вакансию глазами соискателя'}</strong>
        <p>Вы увидите должность, зарплату и описание так, как их увидит соискатель. ${isEdit ? 'До подтверждения изменения не попадут в опубликованную вакансию.' : 'До вашего подтверждения объявление не будет опубликовано.'}</p>
        <button class="btn btn-outline btn-lg" type="button" id="vacancy-show-preview" aria-controls="vacancy-preview">Посмотреть вакансию →</button>
        <p id="vacancy-form-message" class="vacancy-form-message" role="status" aria-live="polite"></p>
      </div>
      <section id="vacancy-preview" class="vacancy-preview" aria-label="Предварительный просмотр вакансии" hidden>
        <span class="section-kicker">ПРЕДПРОСМОТР ДЛЯ СОИСКАТЕЛЯ</span>
        <h4 id="vacancy-preview-title"></h4>
        <p class="vacancy-preview-company"><span id="vacancy-preview-company"></span> · <span id="vacancy-preview-city"></span></p>
        <p class="vacancy-preview-salary" id="vacancy-preview-salary"></p>
        <p id="vacancy-preview-schedule"></p>
        <p id="vacancy-preview-skills"></p>
        <p id="vacancy-preview-description" class="vacancy-preview-description"></p>
        <p class="vacancy-preview-note">Проверьте каждую строку. Чтобы исправить что-либо, измените поля выше и повторно откройте предпросмотр.</p>
      </section>
      <div class="vacancy-publish-actions">
        <button type="submit" class="btn btn-primary btn-lg" id="vacancy-publish" disabled>${isEdit ? 'Сохранить изменения ↗' : 'Опубликовать вакансию ↗'}</button>
        <p class="field-help">${isEdit ? 'Кнопка станет доступна после предпросмотра. Изменения сохранятся в той же вакансии, не удаляя отклики.' : 'Кнопка станет доступна после предварительного просмотра. Публикация отправляет вакансию в тестовую базу.'}</p>
      </div>
      ${isEdit ? '<button type="button" class="btn btn-outline vacancy-cancel" data-action="cancel-job-edit">Отменить редактирование</button>' : ''}
    </form>
  </div>`;
}
async function loadEmployerVacancyEdit() {
  const {jobs} = await api('/api/employer/vacancies');
  const job = jobs.find(item => item.id === state.editVacancy);
  if (!job) {
    state.tab = 'vacancies';
    state.editVacancy = null;
    await loadEmployerVacancies();
    toast('Вакансия для редактирования не найдена.', true);
    return;
  }
  $('#dashboard-main').innerHTML = vacancyFormMarkup(job);
}
async function loadEmployerVacancies() {
  const [jobsResult, applicationsResult] = await Promise.all([
    api('/api/employer/vacancies'),
    api('/api/employer/applications')
  ]);
  const jobs = jobsResult.jobs || [];
  const applications = applicationsResult.applications || [];
  const applicationsByJob = new Map();
  for (const a of applications) {
    const id = Number(a.vacancy_id);
    if (!applicationsByJob.has(id)) applicationsByJob.set(id, {total: 0, interested: 0});
    const stats = applicationsByJob.get(id);
    stats.total += 1;
    if (a.status === 'interview' || a.invitation_id) stats.interested += 1;
  }
  const view = $('#dashboard-main');
  const openCount = jobs.filter(job => job.status === 'open').length;
  const closedCount = jobs.length - openCount;
  const filter = ['all', 'open', 'closed'].includes(state.employerVacancyFilter) ? state.employerVacancyFilter : 'all';
  const visibleJobs = filter === 'all' ? jobs : jobs.filter(job => job.status === filter);
  const interestedCount = applications.filter(a => a.status === 'interview' || a.invitation_id).length;
  const introducedCount = applications.filter(a => a.contact_shared).length;
  const firstOpenJob = jobs.find(job => job.status === 'open');
  const firstApplication = applications[0];
  let nextAction = '<div class="employer-next"><div><span>Следующий шаг</span><strong>Создайте первую вакансию</strong><small>После публикации можно получать отклики и запускать подбор.</small></div><button class="btn btn-primary btn-tiny" data-action="new-job">Создать вакансию →</button></div>';
  if (jobs.length && applications.length === 0 && firstOpenJob) {
    nextAction = `<div class="employer-next"><div><span>Следующий шаг</span><strong>Запустите подбор кандидатов</strong><small>Открытая вакансия уже есть — посмотрите подходящие профили.</small></div><button class="btn btn-dark btn-tiny" data-action="matches" data-id="${Number(firstOpenJob.id)}">Подобрать кандидатов →</button></div>`;
  } else if (applications.length && interestedCount === 0 && firstApplication) {
    nextAction = `<div class="employer-next"><div><span>Требует внимания</span><strong>Разберите новые отклики</strong><small>Сейчас в воронке ${applications.length} откликов.</small></div><button class="btn btn-primary btn-tiny" data-action="vacancy-applications" data-id="${Number(firstApplication.vacancy_id)}">Открыть отклики →</button></div>`;
  } else if (interestedCount > introducedCount) {
    nextAction = `<div class="employer-next"><div><span>Следующий шаг</span><strong>Продолжите знакомства</strong><small>Есть кандидаты, по которым процесс ещё не завершён.</small></div><button class="btn btn-primary btn-tiny" data-tab="invitations">Открыть приглашения →</button></div>`;
  } else if (jobs.length) {
    nextAction = '<div class="employer-next employer-next-ok"><div><span>Воронка под контролем</span><strong>Продолжайте работу с вакансиями</strong><small>Статусы и следующие действия собраны в одном кабинете.</small></div></div>';
  }
  view.innerHTML = `<div class="panel">${nextAction}<div class="split-header"><div><h3>Мои вакансии</h3><p class="muted">После размещения получите список обезличенных профилей.</p></div><button class="btn btn-primary btn-tiny" data-action="new-job">+ Добавить</button></div><div class="stat-grid" aria-label="Статистика вакансий"><div class="stat-tile"><strong>${jobs.length}</strong><span>Всего вакансий</span></div><div class="stat-tile"><strong>${openCount}</strong><span>Открыты</span></div><div class="stat-tile"><strong>${closedCount}</strong><span>Закрыты</span></div></div><div class="stat-grid" aria-label="Воронка подбора"><div class="stat-tile"><strong>${applications.length}</strong><span>Отклики</span></div><div class="stat-tile"><strong>${interestedCount}</strong><span>Заинтересованные</span></div><div class="stat-tile"><strong>${introducedCount}</strong><span>Знакомства (демо)</span></div></div><div class="item-actions" role="group" aria-label="Фильтр вакансий"><button type="button" class="btn btn-tiny ${filter === 'all' ? 'btn-dark' : 'btn-outline'}" data-action="filter-employer-jobs" data-filter="all" aria-pressed="${filter === 'all'}">Все (${jobs.length})</button><button type="button" class="btn btn-tiny ${filter === 'open' ? 'btn-dark' : 'btn-outline'}" data-action="filter-employer-jobs" data-filter="open" aria-pressed="${filter === 'open'}">Открытые (${openCount})</button><button type="button" class="btn btn-tiny ${filter === 'closed' ? 'btn-dark' : 'btn-outline'}" data-action="filter-employer-jobs" data-filter="closed" aria-pressed="${filter === 'closed'}">Закрытые (${closedCount})</button></div><div class="dashboard-list">${visibleJobs.length ? visibleJobs.map(job => jobEmployerMarkup(job, applicationsByJob.get(Number(job.id)))).join('') : '<div class="empty-state">В выбранной категории вакансий нет.</div>'}</div></div><div id="employer-matches" class="hidden"></div>`;
  if (state.activeVacancy && jobs.some(j=>j.id===state.activeVacancy)) await loadMatches(state.activeVacancy);
}
function vacancyQuality(job = {}) {
  const description = String(job.description || '').trim();
  const skills = String(job.skills || '').split(',').map(x=>x.trim()).filter(Boolean);
  const checks = [
    [String(job.title || '').trim().length >= 5, 'Уточните название должности'],
    [String(job.city || '').trim().length >= 2, 'Укажите город или удалённый формат'],
    [Number(job.salary_max || 0) >= Number(job.salary_min || 0) && Number(job.salary_max || 0) > 0, 'Укажите зарплатный диапазон'],
    [job.schedule && job.schedule !== 'Любой', 'Укажите конкретный график'],
    [job.employment && job.employment !== 'Любая', 'Укажите формат занятости'],
    [skills.length >= 2, 'Добавьте 2–5 ключевых навыков'],
    [description.length >= 120, 'Добавьте больше конкретики в описание'],
    [/Обязанности:\n[\s\S]+Требования:\n[\s\S]+Условия работы:\n[\s\S]+/.test(description), 'Разделите обязанности, требования и условия']
  ];
  const passed = checks.filter(([ok])=>ok).length;
  const percent = Math.round(passed / checks.length * 100);
  return {percent,suggestions:checks.filter(([ok])=>!ok).map(([,text])=>text)};
}
function jobEmployerMarkup(x, stats = {total: 0, interested: 0}) {
  const needsAttention = x.status === 'open' && stats.total > 0;
  const nextLabel = needsAttention ? 'Есть новые отклики' : (x.status === 'open' ? 'Ищем кандидатов' : 'Вакансия закрыта');
  const quality = vacancyQuality(x);
  const qualityClass = quality.percent >= 88 ? 'high' : quality.percent >= 63 ? 'medium' : 'low';
  return `<article class="item-card employer-vacancy-card ${needsAttention ? 'needs-attention' : ''}">
    <header><div><span class="card-eyebrow">${esc(nextLabel)}</span><h4>${esc(x.title)}</h4><p>${esc(x.city)} · ${formatPay(x)} · ${esc(x.schedule)}</p><div class="vacancy-moderation-state ${esc(x.moderation_status||'approved')}"><strong>${x.moderation_status==='pending'?'На проверке':x.moderation_status==='rejected'?'Отклонена модератором':'Опубликована'}</strong>${x.moderation_reason?`<small>${esc(x.moderation_reason)}</small>`:''}</div></div><span class="mini-badge ${x.status === 'open' ? '' : 'gray'}">${x.status === 'open' ? 'Открыта' : 'Закрыта'}</span></header>
    <div class="vacancy-pipeline-mini"><span><strong>${stats.total}</strong><small>Отклики</small></span><span><strong>${stats.interested}</strong><small>Заинтересованы</small></span><span><strong>${Math.max(0,stats.total-stats.interested)}</strong><small>На рассмотрении</small></span></div>
    <div class="vacancy-quality ${qualityClass}"><div class="vacancy-quality-head"><span>Качество объявления</span><strong>${quality.percent}%</strong></div><div class="vacancy-quality-track"><span style="width:${quality.percent}%"></span></div>${quality.suggestions.length?`<p>${esc(quality.suggestions.slice(0,2).join(' · '))}</p>`:'<p>Основные условия заполнены хорошо.</p>'}</div>
    <div class="employer-vacancy-primary">${needsAttention ? `<button type="button" class="btn btn-primary" data-action="vacancy-applications-primary" data-id="${x.id}">Разобрать отклики →</button>` : `<button class="btn btn-dark" data-action="matches-primary" data-id="${x.id}" ${x.status === 'closed' ? 'disabled':''}>Подобрать кандидатов →</button>`}</div>
    <div class="item-actions employer-vacancy-secondary"><button type="button" class="btn btn-outline btn-tiny" data-action="vacancy-applications" data-id="${x.id}">Отклики</button><button class="btn btn-outline btn-tiny" data-action="matches" data-id="${x.id}" ${x.status === 'closed' ? 'disabled':''}>Подбор</button><button class="btn btn-outline btn-tiny" data-action="edit-job" data-id="${x.id}">Редактировать</button><button class="btn btn-outline btn-tiny" data-action="job-status" data-id="${x.id}" data-status="${x.status === 'open' ? 'closed' : 'open'}">${x.status === 'open' ? 'Закрыть' : 'Открыть'}</button></div>
  </article>`;
}
function employerMatchBreakdownMarkup(item) {
  const factors = Array.isArray(item.score_breakdown) ? item.score_breakdown : [];
  const cautions = Array.isArray(item.cautions) ? item.cautions : [];
  if (!factors.length) return '';
  const rows = factors.map(factor => `<div class="match-factor-row ${esc(factor.state||'good')}">
    <div class="match-factor-head"><span>${esc(factor.label||factor.key||'Фактор')}</span><strong>${Number(factor.points||0).toLocaleString('ru-RU')} / ${Number(factor.max_points||0).toLocaleString('ru-RU')}</strong></div>
    <div class="match-factor-track"><span style="width:${Math.max(0,Math.min(100,Number(factor.percent||0)))}%"></span></div>
    <small>${esc(factor.text||'')}</small>
  </div>`).join('');
  const cautionMarkup = cautions.length ? `<div class="match-cautions"><strong>Что уточнить до приглашения</strong>${cautions.slice(0,3).map(text=>`<span>! ${esc(text)}</span>`).join('')}</div>` : '';
  return `<div class="match-breakdown compact">${rows}${cautionMarkup}<p class="match-method-note">Оценка строится только по профессиональному профилю и условиям вакансии. Возраст не используется.</p></div>`;
}
async function loadMatches(jobId) {
  const target = $('#employer-matches');
  target.classList.remove('hidden');
  target.innerHTML = '<div class="panel"><div class="loading">Подбираем кандидатов...</div></div>';
  state.activeVacancy = jobId;
  try {
    const {matches} = await api(`/api/employer/vacancies/${jobId}/matches`);
    target.innerHTML = `<div class="panel matches-panel"><div class="split-header"><div><span class="section-kicker">ПОДБОР</span><h3>Подходящие кандидаты</h3><p class="muted">Сравнивайте профессию, навыки и условия. Процент прозрачно разложен по факторам; личные данные остаются скрытыми до согласия кандидата.</p></div><span class="mini-badge">${matches.length} совпадений</span></div><div class="matches-guide"><span><b>1</b>Оцените факторы</span><span><b>2</b>Отправьте приглашение</span><span><b>3</b>Дождитесь согласия</span></div><div class="dashboard-list">${matches.length ? matches.map(m => {
      const score = Number(m.score||0);
      const scoreClass = score >= 90 ? 'excellent' : score >= 80 ? 'high' : score >= 70 ? 'medium' : 'basic';
      const reasons = Array.isArray(m.strengths) ? m.strengths : (Array.isArray(m.reasons) ? m.reasons : []);
      const cautions = Array.isArray(m.cautions) ? m.cautions : [];
      const level = m.match_level || (score>=90?'Очень сильное совпадение':score>=80?'Сильное совпадение':score>=70?'Хорошее совпадение':'Подходит по основным условиям');
      let action = `<button class="btn btn-primary btn-tiny" data-action="invite" data-job="${jobId}" data-id="${m.candidate_id}">Пригласить кандидата →</button>`;
      if (m.contact_shared) action = '<button class="btn btn-outline btn-tiny" data-tab="invitations">Контакт уже открыт →</button>';
      else if (m.invitation_status === 'accepted') action = '<button class="btn btn-primary btn-tiny" data-tab="invitations">Согласие получено · продолжить →</button>';
      else if (m.invitation_status === 'sent') action = '<button class="btn btn-outline btn-tiny" data-tab="invitations">Приглашение отправлено · ожидаем ответ</button>';
      else if (m.invitation_status === 'declined') action = '<button class="btn btn-outline btn-tiny" type="button" disabled>Кандидат отказался</button>';
      return `<article class="item-card candidate-match-card ${scoreClass}">
        <header><div><h4>${esc(m.profession)}</h4><div class="candidate-match-meta"><span>⌖ ${esc(m.city)}</span><span>от ${money(m.salary_min)}</span><span>${esc(m.schedule)}</span><span>${esc(m.employment)}</span></div></div><div class="candidate-match-score"><span class="match-score-dot"></span><strong>${score}%</strong><small>${esc(level)}</small></div></header>
        <div class="job-skill-tags">${String(m.skills || '').split(',').map(s=>s.trim()).filter(Boolean).slice(0,5).map(skill=>`<span>${esc(skill)}</span>`).join('') || '<span>Навыки не указаны</span>'}</div>
        <div class="candidate-match-reasons">${reasons.slice(0,3).map(reason=>`<span>✓ ${esc(reason)}</span>`).join('')}</div>
        ${cautions.length ? `<div class="candidate-match-cautions">${cautions.slice(0,2).map(text=>`<span>! ${esc(text)}</span>`).join('')}</div>` : ''}
        <details class="candidate-match-explanation"><summary>Показать расчёт совпадения</summary>${employerMatchBreakdownMarkup(m)}</details>
        <div class="item-actions">${action}</div>
      </article>`;
    }).join('') : '<div class="empty-state"><strong>Точных совпадений пока нет.</strong><p>Попробуйте расширить график, город или зарплатный диапазон вакансии.</p></div>'}</div></div>`;
  } catch(e) { target.innerHTML = `<div class="panel">${esc(e.message)}</div>`; toast(e.message,true); }
}
async function loadEmployerInvitations() {
  const {invitations} = await api('/api/employer/invitations');
  const waiting = invitations.filter(x=>x.status==='sent').length;
  const accepted = invitations.filter(x=>x.status==='accepted' && !x.contact_shared).length;
  const opened = invitations.filter(x=>x.contact_shared).length;
  $('#dashboard-main').innerHTML = `<div class="panel invitation-center"><div class="split-header"><div><span class="section-kicker">ЗНАКОМСТВА</span><h3>Приглашения и контакты</h3><p class="muted">Здесь виден путь от приглашения до открытого контакта. Контакты появляются только после согласия кандидата.</p></div></div>
    <div class="mini-stat-row"><div><strong>${waiting}</strong><span>Ждут ответа</span></div><div><strong>${accepted}</strong><span>Есть согласие</span></div><div><strong>${opened}</strong><span>Контакты открыты</span></div></div>
    <div class="demo-note"><strong>Тестовый режим</strong><span>Открытие контакта сейчас имитирует оплату и не списывает деньги.</span></div>
    <div class="dashboard-list">${invitations.length ? invitations.map(invitationEmployerMarkup).join('') : '<div class="empty-state"><strong>Приглашений пока нет.</strong><p>Откройте вакансию, запустите подбор и пригласите подходящего кандидата.</p><button class="btn btn-primary" data-tab="vacancies">К вакансиям →</button></div>'}</div></div>`;
}
function invitationEmployerMarkup(x) {
  return `<article class="item-card invitation-card employer-invitation-card"><header><div><span class="card-eyebrow">ЗНАКОМСТВО</span><h4>${esc(x.candidate_profession)}</h4><p>${esc(x.vacancy_title)} · кандидат #${x.candidate_id}</p></div><span class="mini-badge ${statusBadge[x.status]}">${esc(workflowStatus(x,statusTitle[x.status]))}</span></header>
  ${interactionStageMarkup(x,'invitation')}
  ${activityTimelineMarkup(x)}
  ${x.contact ? `<div class="contact-card"><span>Контакт открыт (демо)</span><strong>${esc(x.contact.name)}</strong><div><a href="mailto:${esc(x.contact.email)}">${esc(x.contact.email)}</a><b>·</b><span>${esc(x.contact.phone || 'Телефон не указан')}</span></div></div>` : (x.status === 'accepted' ? `<div class="application-next-action"><span>Следующее действие</span><strong>Кандидат согласился на знакомство</strong><small>Демо-стоимость: ${money(x.price_rub)}</small></div><button class="btn btn-primary" data-action="demo-pay" data-id="${x.id}">Открыть контакт (демо) →</button>` : '<p class="muted invitation-waiting">Ожидаем решение кандидата. Контакты пока скрыты.</p>')}</article>`;
}
async function renderAdmin() {
  $('#account-content').innerHTML = '<div class="panel"><h3>Панель управления</h3><p class="muted">Статистика работы MVP, без раскрытия персональных данных.</p><div class="stat-grid" id="admin-stats"><div class="loading">Загрузка...</div></div></div>';
  try {
    const stats = await api('/api/admin/stats');
    const units = [['Соискатели',stats.candidates],['Работодатели',stats.employers],['Открытые вакансии',stats.open_vacancies],['Всего откликов',stats.applications_total],['Активные отклики',stats.applications_active],['Отозванные отклики',stats.applications_withdrawn],['Приглашения',stats.invitations],['Подтверждения',stats.confirmed],['Демо-знакомства',stats.demo_transactions],['Демо-оборот, ₽',stats.demo_turnover_rub]];
    $('#admin-stats').innerHTML = units.map(([title,value]) => `<div class="stat-tile"><strong>${Number(value).toLocaleString('ru-RU')}</strong><span>${esc(title)}</span></div>`).join('');
  } catch(e) { toast(e.message,true); }
}
function formValue(form, name) { return form.elements.namedItem(name).value.trim(); }
function parseNumber(form, name) { return Number(formValue(form,name)); }
async function handleDashboardSubmit(event) {
  const form = event.target;
  if (form.id === 'profile-form') {
    event.preventDefault();
    const body = {profession:formValue(form,'profession'),city:formValue(form,'city'),skills:formValue(form,'skills'),salary_min:parseNumber(form,'salary_min'),phone:formValue(form,'phone'),schedule:formValue(form,'schedule'),employment:formValue(form,'employment'),about:formValue(form,'about'),is_active:form.elements.namedItem('is_active').checked};
    try { await api('/api/candidate/profile',{method:'PUT',body:JSON.stringify(body)}); await reloadUser(); toast('Профиль сохранён. Теперь он участвует в подборе.'); } catch(e) { toast(e.message,true); }
  }
  if (form.id === 'company-form') {
    event.preventDefault();
    const body = {company_name:formValue(form,'company_name'),inn:formValue(form,'inn'),about:formValue(form,'about')};
    try {
      await api('/api/employer/company',{method:'PUT',body:JSON.stringify(body)});
      await reloadUser();
      const result = await api('/api/employer/company');
      $('#dashboard-main').innerHTML = employerCompanyMarkup(result);
      toast('Данные компании сохранены.');
    } catch(e) { toast(e.message,true); }
    return;
  }
    if (form.id === 'vacancy-form') {
    event.preventDefault();
    const description = window.OpytnovacancyWizard?.getReviewedDescription(form);
    if (description === null || description === undefined) {
      toast('Сначала проверьте вакансию в предпросмотре.', true);
      return;
    }
    const editing = Boolean(form.dataset.editId);
    const body = {title:formValue(form,'title'),city:formValue(form,'city'),skills:formValue(form,'skills'),salary_min:parseNumber(form,'salary_min'),salary_max:parseNumber(form,'salary_max'),schedule:formValue(form,'schedule'),employment:formValue(form,'employment'),description};
    if (editing) body.expected_revision = form.dataset.revision;
    const submit = form.querySelector('#vacancy-publish');
    submit.disabled = true;
    try {
      const endpoint = editing ? `/api/employer/vacancies/${form.dataset.editId}` : '/api/employer/vacancies';
      await api(endpoint,{method:editing ? 'PATCH' : 'POST',body:JSON.stringify(body)});
      state.editVacancy = null;
      state.activeVacancy = null;
      state.tab='vacancies';
      await showDashboard();
      await loadPublicJobs();
      toast(editing ? 'Изменения сохранены в прежней вакансии, отклики остались на месте.' : 'Вакансия опубликована. Теперь она доступна в поиске.');
    } catch(e) {
      toast(e.message,true);
      // A stale edit must never silently overwrite another browser tab's changes.
      if (editing && /изменилась|уже изменена/.test(e.message)) {
        const line = form.querySelector('#vacancy-form-message');
        if (line) line.textContent = 'Вакансия изменена в другой вкладке. Отмените редактирование и откройте её заново.';
      } else if (submit.isConnected) submit.disabled = false;
    }
  }
}
async function handleDashboardClick(event) {
  const tab = event.target.closest('[data-tab]');
  if (tab) { state.tab = tab.dataset.tab; state.activeVacancy = null; await showDashboard(); return; }
  const btn = event.target.closest('[data-action]'); if (!btn) return;
  const action = btn.dataset.action, id = Number(btn.dataset.id);
  if (btn.disabled) return;
  btn.disabled = true;
  try {
    if (action === 'filter-employer-jobs') {
      if (!['all', 'open', 'closed'].includes(btn.dataset.filter)) return;
      state.employerVacancyFilter = btn.dataset.filter;
      state.activeVacancy = null;
      await loadEmployerVacancies();
      return;
    }
    if (action === 'vacancy-applications' || action === 'vacancy-applications-primary') {
      state.employerApplicationsVacancyFilter = String(id);
      state.tab = 'applications';
      state.activeVacancy = null;
      await showDashboard();
      return;
    }
    if (action === 'new-job') { state.editVacancy=null; state.tab='create'; await showDashboard(); }
    if (action === 'edit-job') { state.editVacancy=id; state.activeVacancy=null; state.tab='edit'; await showDashboard(); }
    if (action === 'cancel-job-edit') { state.editVacancy=null; state.tab='vacancies'; await showDashboard(); }
    if (action === 'matches' || action === 'matches-primary') { await loadMatches(id); }
    if (action === 'job-status') { await api(`/api/employer/vacancies/${id}/status`,{method:'PATCH',body:JSON.stringify({status:btn.dataset.status})}); await showDashboard(); toast('Статус вакансии обновлён.'); }
    if (action === 'invite') { await api('/api/employer/invitations',{method:'POST',body:JSON.stringify({vacancy_id:Number(btn.dataset.job),candidate_id:id})}); toast('Приглашение отправлено.'); state.tab='invitations'; await showDashboard(); }
    if (action === 'accept' || action === 'decline') {
      const consent = $(`#consent-${id}`);
      if (action === 'accept' && !consent.checked) { throw new Error('Подтвердите согласие на передачу контакта.'); }
      await api(`/api/candidate/invitations/${id}/respond`,{method:'POST',body:JSON.stringify({decision:action === 'accept' ? 'accepted':'declined',share_consent:action === 'accept' && consent.checked})}); await showDashboard(); toast('Ответ работодателю сохранён.');
    }
    if (action === 'demo-pay') {
      if (!confirm('Это тестовая оплата — реальные средства НЕ списываются. Открыть контакт согласившегося кандидата?')) return;
      const result = await api(`/api/employer/invitations/${id}/demo-pay`,{method:'POST'}); await showDashboard(); toast(`Демо-платёж ${money(result.amount_rub)} проведён без списания средств.`);
    }
  } catch(e) { toast(e.message,true); } finally { if (btn.isConnected) btn.disabled = false; }
}
async function start() {
  $('#login-open').addEventListener('click',()=>openAuth('login'));
  $('#register-open').addEventListener('click',()=>openAuth('register'));
  window.addEventListener('resize', syncResponsiveMemberActions);
  syncResponsiveMemberActions();
  $('#modal-close').addEventListener('click',()=>$('#auth-dialog').close());
  $('#auth-dialog').addEventListener('click',e=>{ if(e.target === $('#auth-dialog')) $('#auth-dialog').close(); });
  $('#auth-form').addEventListener('submit',submitAuth);
  $('#auth-dialog').addEventListener('click',e=>{
    const role = e.target.closest('[data-role]'); if(role){ state.role=role.dataset.role; updateAuth(); }
    const mode = e.target.closest('[data-switch]'); if(mode){ state.mode=mode.dataset.switch; updateAuth(); }
  });
  $$('[data-register]').forEach(button=>button.addEventListener('click',()=>openAuth('register',button.dataset.register)));
  $('#account-open').addEventListener('click',()=>showDashboard(true));
  $('#logout').addEventListener('click',async()=>{ try { await api('/api/logout',{method:'POST'}); state.user=null; $('#account-content').innerHTML=''; await reloadUser(); window.scrollTo({top:0,behavior:'smooth'}); toast('Вы вышли из аккаунта.'); } catch(e) { toast(e.message,true); }});
  $('#jobs-filter').addEventListener('click',loadPublicJobs);
  $('#city-filter').addEventListener('keydown',e=>{if(e.key==='Enter')loadPublicJobs();});
  $('#account-content').addEventListener('click',handleDashboardClick);
  $('#account-content').addEventListener('submit',handleDashboardSubmit);
  await reloadUser();
  await loadPublicJobs();
  if (state.user) { state.tab = 'overview'; await showDashboard(); }
}
document.addEventListener('DOMContentLoaded',start);
