/* ОПЫТ 50+ — progressive vanilla JS client; no tracking or external dependencies. */
'use strict';
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const state = { user: null, mode: 'register', role: 'candidate', tab: 'profile', activeVacancy: null };
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money = value => Number(value || 0).toLocaleString('ru-RU') + ' ₽';
const formatPay = job => job.salary_min === job.salary_max ? money(job.salary_min) : `${money(job.salary_min)} — ${money(job.salary_max)}`;
const statusTitle = {sent:'Ожидает ответа',accepted:'Согласие получено',declined:'Не заинтересован'};
const statusBadge = {sent:'orange',accepted:'',declined:'gray'};
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
  $('#auth-email').focus();
}
function updateAuth() {
  const reg = state.mode === 'register';
  $('#auth-title').textContent = reg ? 'Создать аккаунт' : 'Войти в аккаунт';
  $('#signup-role').classList.toggle('hidden', !reg);
  $('#auth-name-row').classList.toggle('hidden', !reg);
  $('#auth-company-row').classList.toggle('hidden', !(reg && state.role === 'employer'));
  $('#password-hint').classList.toggle('hidden', !reg);
  $('#auth-password').autocomplete = reg ? 'new-password' : 'current-password';
  $('#auth-submit').textContent = reg ? 'Зарегистрироваться →' : 'Войти →';
  $$('.role-btn').forEach(b => b.classList.toggle('active', b.dataset.role === state.role));
  $('#auth-switch').innerHTML = reg ? 'Уже есть аккаунт? <button type="button" data-switch="login">Войти</button>' : 'Ещё нет аккаунта? <button type="button" data-switch="register">Создать профиль</button>';
}
async function submitAuth(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const body = {email:$('#auth-email').value.trim(), password:$('#auth-password').value};
  if (state.mode === 'register') {
    body.role = state.role; body.name = $('#auth-name').value.trim();
    if (body.role === 'employer') body.company_name = $('#auth-company').value.trim();
  }
  const btn = $('#auth-submit'); btn.disabled = true;
  try {
    const data = await api(state.mode === 'register' ? '/api/register' : '/api/login', {method:'POST', body:JSON.stringify(body)});
    $('#auth-dialog').close(); state.user = data.user; state.tab = data.user.role === 'employer' ? 'vacancies' : 'profile';
    await showDashboard(true); toast('Готово! Добро пожаловать в ОПЫТ.');
  } catch(e) { toast(e.message, true); } finally { btn.disabled = false; }
}
async function reloadUser() {
  try { const data = await api('/api/me'); state.user = data.user; } catch { state.user = null; }
  $('#guest-actions').classList.toggle('hidden', !!state.user);
  $('#member-actions').classList.toggle('hidden', !state.user);
  $('#dashboard').classList.toggle('hidden', !state.user);
}
async function showDashboard(scroll = false) {
  await reloadUser(); if (!state.user) { openAuth('login'); return; }
  $('#welcome').textContent = `Здравствуйте, ${state.user.name.split(' ')[0]}!`;
  $('#account-subtitle').textContent = ({candidate:'Ваши навыки — ваша сильная сторона.',employer:'Управляйте вакансиями и приглашениями.',admin:'Обзор работы платформы.'})[state.user.role];
  if (state.user.role === 'candidate') await renderCandidate();
  if (state.user.role === 'employer') await renderEmployer();
  if (state.user.role === 'admin') await renderAdmin();
  if (scroll) $('#dashboard').scrollIntoView({behavior:'smooth',block:'start'});
}
function tabsMarkup(items, heading, subtitle) {
  return `<aside class="panel side-panel"><span class="section-kicker">${esc(heading)}</span><h3 class="tab-heading">${esc(subtitle)}</h3><nav class="dashboard-tabs" aria-label="Разделы личного кабинета">${items.map(t => `<button type="button" data-tab="${esc(t.id)}" class="${state.tab === t.id ? 'active' : ''}">${esc(t.label)}</button>`).join('')}</nav></aside>`;
}
function profileMarkup(profile = {}, user = {}) {
  return `<div class="panel"><h3>Мой профессиональный профиль</h3><p class="muted">Чем точнее условия, тем релевантнее приглашения. Данные не публикуются целиком до вашего согласия.</p>
    <form id="profile-form"><div class="form-grid">
    <div class="field"><label>Профессия</label><input name="profession" value="${esc(profile.profession)}" placeholder="Например, кладовщик" required minlength="2" maxlength="120"></div>
    <div class="field"><label>Город</label><input name="city" value="${esc(profile.city)}" placeholder="Например, Подольск" required minlength="2" maxlength="100"></div>
    <div class="field wide"><label>Ключевые навыки (через запятую)</label><input name="skills" value="${esc(profile.skills)}" placeholder="1С, инвентаризация, склад" maxlength="300"></div>
    <div class="field"><label>Зарплата от, ₽</label><input name="salary_min" type="number" value="${profile.salary_min || 0}" min="0" max="10000000" required></div>
    <div class="field"><label>Телефон для связи (виден после подтверждения и тестовой оплаты)</label><input name="phone" type="tel" value="${esc(user.phone)}" maxlength="30" placeholder="+7 ..."></div>
    <div class="field"><label>График</label><select name="schedule">${optList(schedules,profile.schedule)}</select></div>
    <div class="field"><label>Тип занятости</label><select name="employment">${optList(employment,profile.employment)}</select></div>
    <div class="field wide"><label>О себе (не указывайте здесь контакты)</label><textarea name="about" maxlength="700" placeholder="Чем вы гордитесь и что умеете">${esc(profile.about)}</textarea></div>
    <div class="field wide"><label class="checks"><input type="checkbox" name="is_active" ${profile.is_active !== 0 ? 'checked':''}> Мой профиль активен и может участвовать в подборе</label></div>
    </div><button class="btn btn-primary" type="submit">Сохранить профиль ↗</button></form></div>`;
}
async function renderCandidate() {
  const nav = [{id:'profile',label:'Мой профиль'},{id:'offers',label:'Подходящие вакансии'},{id:'invitations',label:'Приглашения'}];
  $('#account-content').innerHTML = `<div class="dashboard-grid">${tabsMarkup(nav,'ДЛЯ СОИСКАТЕЛЯ','Ваша карьера')}<div id="dashboard-main"><div class="loading">Загрузка...</div></div></div>`;
  const target = $('#dashboard-main');
  try {
    if (state.tab === 'profile') target.innerHTML = profileMarkup(state.user.profile, state.user);
    else if (state.tab === 'offers') {
      const {jobs} = await api('/api/candidate/jobs');
      target.innerHTML = `<div class="panel"><h3>Подходящие вакансии</h3><p class="muted">Алгоритм учитывает навыки, город, график и ожидания по зарплате. Совпадение — рекомендация, не решение о трудоустройстве.</p><div class="dashboard-list">${jobs.length ? jobs.map(x => jobMarkup(x,true)).join('') : '<div class="empty-state">Пока нет совпадений. Заполните профиль полностью или вернитесь позже.</div>'}</div></div>`;
    } else {
      const {invitations} = await api('/api/candidate/invitations');
      target.innerHTML = `<div class="panel"><h3>Приглашения от компаний</h3><p class="muted">Откройте контакт только тем компаниям, с которыми вы хотите познакомиться.</p><div class="dashboard-list">${invitations.length ? invitations.map(invitationCandidateMarkup).join('') : '<div class="empty-state">Приглашений пока нет. Заполните профиль, и работодатели смогут найти вас.</div>'}</div></div>`;
    }
  } catch(e) { target.innerHTML = `<div class="panel">${esc(e.message)}</div>`; toast(e.message,true); }
}
function invitationCandidateMarkup(x) {
  return `<article class="item-card"><header><div><h4>${esc(x.title)}</h4><p>${esc(x.company_name)} · ${esc(x.city)} · ${formatPay(x)}</p></div><span class="mini-badge ${statusBadge[x.status]}">${esc(statusTitle[x.status])}</span></header>
   <p>${esc(x.description || 'Подробности на собеседовании.')}</p>${x.status === 'sent' ? `<div class="item-actions"><label class="checks"><input type="checkbox" id="consent-${x.id}"> Согласен(-на) передать мои имя и контакты этой компании после тестового подтверждения знакомства</label></div><div class="item-actions"><button class="btn btn-primary btn-tiny" data-action="accept" data-id="${x.id}">Интересно, согласен(-на)</button><button class="btn btn-outline btn-tiny" data-action="decline" data-id="${x.id}">Отказаться</button></div>` : (x.contact_shared ? '<div class="info-box">Контакты были открыты работодателю в демонстрационном режиме.</div>' : '')}</article>`;
}
async function renderEmployer() {
  const nav = [{id:'vacancies',label:'Мои вакансии'},{id:'create',label:'Новая вакансия'},{id:'invitations',label:'Приглашения и контакты'}];
  if (!nav.some(t => t.id === state.tab)) state.tab = 'vacancies';
  $('#account-content').innerHTML = `<div class="dashboard-grid">${tabsMarkup(nav,'ДЛЯ КОМПАНИИ',state.user.company?.company_name || 'Работодатель')}<div id="dashboard-main"><div class="loading">Загрузка...</div></div></div>`;
  const target = $('#dashboard-main');
  try {
    if (state.tab === 'create') target.innerHTML = vacancyFormMarkup();
    else if (state.tab === 'vacancies') await loadEmployerVacancies();
    else await loadEmployerInvitations();
  } catch(e) { target.innerHTML = `<div class="panel">${esc(e.message)}</div>`; toast(e.message,true); }
}
function vacancyFormMarkup() {
  return `<div class="panel"><h3>Разместить вакансию</h3><p class="muted">Публикация бесплатна. Контакты кандидатов передаются только после их согласия.</p><form id="vacancy-form"><div class="form-grid">
    <div class="field wide"><label>Должность</label><input name="title" placeholder="Например, инженер по эксплуатации" minlength="3" maxlength="120" required></div>
    <div class="field"><label>Город</label><input name="city" placeholder="Москва или Удалённо" minlength="2" maxlength="100" required></div>
    <div class="field"><label>Обязательные навыки (через запятую)</label><input name="skills" placeholder="1С, Excel" maxlength="300"></div>
    <div class="field"><label>Зарплата от, ₽</label><input name="salary_min" type="number" min="0" max="10000000" value="50000" required></div>
    <div class="field"><label>Зарплата до, ₽</label><input name="salary_max" type="number" min="0" max="10000000" value="100000" required></div>
    <div class="field"><label>График</label><select name="schedule">${optList(schedules,'Любой')}</select></div>
    <div class="field"><label>Занятость</label><select name="employment">${optList(employment,'Любая')}</select></div>
    <div class="field wide"><label>Описание и условия работы</label><textarea name="description" maxlength="1200" placeholder="Обязанности, требования, условия оплаты"></textarea></div>
    </div><button class="btn btn-primary" type="submit">Опубликовать вакансию ↗</button></form></div>`;
}
async function loadEmployerVacancies() {
  const {jobs} = await api('/api/employer/vacancies');
  const view = $('#dashboard-main');
  view.innerHTML = `<div class="panel"><div class="split-header"><div><h3>Мои вакансии</h3><p class="muted">После размещения получите список обезличенных профилей.</p></div><button class="btn btn-primary btn-tiny" data-action="new-job">+ Добавить</button></div><div class="dashboard-list">${jobs.length ? jobs.map(jobEmployerMarkup).join('') : '<div class="empty-state">Вакансий пока нет. Опубликуйте первую, чтобы начать подбор.</div>'}</div></div><div id="employer-matches" class="hidden"></div>`;
  if (state.activeVacancy && jobs.some(j=>j.id===state.activeVacancy)) await loadMatches(state.activeVacancy);
}
function jobEmployerMarkup(x) {
  return `<article class="item-card"><header><div><h4>${esc(x.title)}</h4><p>${esc(x.city)} · ${formatPay(x)} · ${esc(x.schedule)}</p></div><span class="mini-badge ${x.status === 'open' ? '' : 'gray'}">${x.status === 'open' ? 'Открыта' : 'Закрыта'}</span></header><div class="item-actions"><button class="btn btn-dark btn-tiny" data-action="matches" data-id="${x.id}" ${x.status === 'closed' ? 'disabled':''}>Подобрать кандидатов →</button><button class="btn btn-outline btn-tiny" data-action="job-status" data-id="${x.id}" data-status="${x.status === 'open' ? 'closed' : 'open'}">${x.status === 'open' ? 'Закрыть' : 'Открыть'}</button></div></article>`;
}
async function loadMatches(jobId) {
  const target = $('#employer-matches');
  target.classList.remove('hidden');
  target.innerHTML = '<div class="panel"><div class="loading">Подбираем кандидатов...</div></div>';
  state.activeVacancy = jobId;
  try {
    const {matches} = await api(`/api/employer/vacancies/${jobId}/matches`);
    target.innerHTML = `<div class="panel"><div class="split-header"><h3>Подходящие кандидаты</h3><span class="mini-badge blue">${matches.length} совпадений</span></div><p class="muted">Контакты скрыты. Пригласите кандидата, дождитесь его согласия и используйте демонстрационную оплату.</p><div class="dashboard-list">${matches.length ? matches.map(m => `<article class="item-card"><header><div><h4>${esc(m.profession)}</h4><p>Город: ${esc(m.city)} · Ожидания от ${money(m.salary_min)}</p></div><span class="mini-badge">${m.score}% совпадение</span></header><p class="candidate-skills">${esc(m.skills || 'Навыки не указаны')}</p><p>${m.reasons.map(esc).join(' · ')}</p><button class="btn btn-primary btn-tiny" data-action="invite" data-job="${jobId}" data-id="${m.candidate_id}">Пригласить кандидата →</button></article>`).join('') : '<div class="empty-state">Пока нет совпадений. Попробуйте расширить условия поиска.</div>'}</div></div>`;
  } catch(e) { target.innerHTML = `<div class="panel">${esc(e.message)}</div>`; toast(e.message,true); }
}
async function loadEmployerInvitations() {
  const {invitations} = await api('/api/employer/invitations');
  $('#dashboard-main').innerHTML = `<div class="panel"><h3>Приглашения и контакты</h3><div class="banner">Демонстрационные платежи не списывают деньги. В промышленной версии до раскрытия контакта требуется настоящий платёж и подтверждение согласия кандидата.</div><div class="dashboard-list">${invitations.length ? invitations.map(invitationEmployerMarkup).join('') : '<div class="empty-state">Вы ещё не отправляли приглашений.</div>'}</div></div>`;
}
function invitationEmployerMarkup(x) {
  return `<article class="item-card"><header><div><h4>${esc(x.candidate_profession)}</h4><p>Вакансия: ${esc(x.vacancy_title)} · кандидат #${x.candidate_id}</p></div><span class="mini-badge ${statusBadge[x.status]}">${esc(statusTitle[x.status])}</span></header>
  <p>Демо-стоимость знакомства: <span class="price">${money(x.price_rub)}</span></p>
  ${x.contact ? `<div class="info-box"><strong>Контакт открыт (демо)</strong><div>Имя: ${esc(x.contact.name)}</div><div>Email: ${esc(x.contact.email)}</div><div>Телефон: ${esc(x.contact.phone || 'не указан')}</div></div>` : (x.status === 'accepted' ? `<button class="btn btn-primary btn-tiny" data-action="demo-pay" data-id="${x.id}">Тестовая оплата и открытие контакта ↗</button>` : '')}</article>`;
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
  if (form.id === 'vacancy-form') {
    event.preventDefault();
    const body = {title:formValue(form,'title'),city:formValue(form,'city'),skills:formValue(form,'skills'),salary_min:parseNumber(form,'salary_min'),salary_max:parseNumber(form,'salary_max'),schedule:formValue(form,'schedule'),employment:formValue(form,'employment'),description:formValue(form,'description')};
    try { await api('/api/employer/vacancies',{method:'POST',body:JSON.stringify(body)}); state.tab='vacancies'; await showDashboard(); await loadPublicJobs(); toast('Вакансия опубликована.'); } catch(e) { toast(e.message,true); }
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
    if (action === 'new-job') { state.tab='create'; await showDashboard(); }
    if (action === 'matches') { await loadMatches(id); }
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
  await loadPublicJobs();
  await reloadUser();
  if (state.user) { state.tab = state.user.role==='employer'?'vacancies':'profile'; await showDashboard(); }
}
document.addEventListener('DOMContentLoaded',start);
