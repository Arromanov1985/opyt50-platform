'use strict';
(function initRelease02() {
  document.addEventListener('DOMContentLoaded', () => {
    const status = {applied:'Отправлен',reviewing:'На рассмотрении',interview:'Работодатель заинтересован',rejected:'Отказ',hired:'Принят',withdrawn:'Отозван'};
    const req = (method, path, data) => api(path,{method, ...(data ? {body:JSON.stringify(data)} : {})});
    const introductionLabel = {sent:'Ожидается ваше решение',accepted:'Согласие получено',declined:'От знакомства отказались'};
    const eventLabels = {applied:'Отклик отправлен',reapplied:'Отклик отправлен повторно',withdrawn:'Отклик отозван',reviewing:'На рассмотрении',interview:'Работодатель заинтересован',rejected:'Получен отказ',hired:'Принят'};
    function applicationIntroBadge(a) {
      if (!a.invitation_id) return '';
      const label = a.contact_shared ? 'Знакомство состоялось (демо)' : (introductionLabel[a.invitation_status] || 'Запрос отправлен');
      return '<div class="interaction-note">Знакомство: ' + esc(label) + '</div>' +
        (a.invitation_status === 'sent' ? '<button class="btn btn-outline btn-tiny" data-v02-action="open-introductions">Ответить на запрос компании</button>' : '');
    }
    function employerIntroBadge(a) {
      if (!a.invitation_id) return '';
      const label = a.contact_shared ? 'Знакомство состоялось (демо)' : (a.invitation_status==='sent' ? 'Запрос отправлен — ждём согласия кандидата' : a.invitation_status==='accepted' ? 'Согласие получено — контакт ещё закрыт' : 'Кандидат отказался от знакомства');
      return '<div class="interaction-note">' + esc(label) + '</div><button class="btn btn-outline btn-tiny" data-v02-action="open-introductions">Открыть знакомства</button>';
    }
    function searchValue(id) { return document.getElementById(id)?.value?.trim() || ''; }

    // Keep application status beside recommended vacancies, so clicking twice
    // never looks like a system failure. The server still enforces uniqueness.
    let applicationByVacancy = new Map();
    let favoriteVacancyIds = new Set();
    async function refreshFavorites() {
      if (state.user?.role !== 'candidate') { favoriteVacancyIds = new Set(); return; }
      const result = await api('/api/candidate/favorites');
      favoriteVacancyIds = new Set((result.jobs || []).map(job => Number(job.id)));
    }
    async function refreshMyApplications() {
      if (state.user?.role !== 'candidate') { applicationByVacancy = new Map(); return; }
      const result = await api('/api/candidate/applications');
      applicationByVacancy = new Map((result.applications || []).map(a => [Number(a.vacancy_id), a]));
    }
    function jobApplicationAction(jobId, job = null) {
      // Prefer the server-annotated vacancy status; use separately fetched
      // applications only for routes that return unannotated public jobs.
      const known = (job && job.application_status)
        ? {status:job.application_status, id:job.application_id, introduction_stage:job.introduction_stage, contact_shared:job.contact_shared}
        : applicationByVacancy.get(jobId);
      if (!known) return `<button type="button" class="btn btn-primary btn-tiny" data-v02-action="apply" data-id="${jobId}">Откликнуться</button>`;
      if (known.status === 'withdrawn') return `<button type="button" class="btn btn-primary btn-tiny" data-v02-action="reapply" data-id="${jobId}">Откликнуться повторно</button>`;
      return `<button type="button" class="btn btn-outline btn-tiny" data-v02-action="see-applications">Отклик: ${esc(workflowStatus(known,status[known.status] || known.status))} · история</button>`;
    }
    function employerTrustBadges(job, detailed = false) {
      const badges = [];
      if (job.employer_verified) badges.push('<span class="employer-trust-badge verified">✓ Компания проверена</span>');
      else {
        if (job.employer_email_verified) badges.push('<span class="employer-trust-badge">✓ Email подтверждён</span>');
        if (job.employer_inn_provided) badges.push('<span class="employer-trust-badge">Реквизиты указаны</span>');
      }
      if (detailed && job.employer_created_at) {
        const year = String(job.employer_created_at).slice(0,4);
        if (/^\d{4}$/.test(year)) badges.push(`<span class="employer-trust-badge neutral">На СТАЖНО с ${esc(year)} года</span>`);
      }
      return badges.length ? `<div class="employer-trust-badges">${badges.join('')}</div>` : '';
    }

    jobMarkup = function(job, personalized = false) {
      const id = Number(job.id), open = job.status !== 'closed';
      const saved = favoriteVacancyIds.has(id);
      const skills = String(job.skills || '').split(',').map(s=>s.trim()).filter(Boolean).slice(0,4);
      const preview = String(job.description || '').replace(/\s+/g,' ').trim().slice(0,180);
      const score = Number(job.score || 0);
      const scoreClass = score >= 80 ? 'high' : 'medium';
      const reasons = Array.isArray(job.reasons) ? job.reasons : [];
      const scoreBadge = personalized
        ? `<span class="job-category match-score ${scoreClass}"><span class="match-score-dot"></span>${score}% совпадение</span>`
        : `<span class="job-category">${open ? 'Открыта' : 'Закрыта'}</span>`;
      let roleActions = '';
      if (open && state.user?.role === 'candidate') {
        roleActions = `${jobApplicationAction(id, job)}<button class="btn btn-outline btn-tiny favorite-toggle" data-v02-action="${saved ? 'favorite-remove-inline' : 'favorite'}" data-id="${id}" aria-label="${saved ? 'Убрать вакансию из избранного' : 'Сохранить вакансию'}" aria-pressed="${saved ? 'true' : 'false'}">${saved ? '♥' : '♡'}</button>`;
      } else if (open && !state.user) {
        roleActions = `<button type="button" class="btn btn-primary btn-tiny" data-v02-action="apply" data-id="${id}">Откликнуться</button>`;
      }
      return `<article class="job-card job-card-v08" data-job-id="${id}"><div class="job-top"><div class="job-company-wrap"><span class="job-company">${esc(job.company_name || 'Работодатель')}</span>${employerTrustBadges(job)}</div>${scoreBadge}</div>
        <h3>${esc(job.title)}</h3><div class="job-salary">${formatPay(job)}</div>
        <div class="job-meta"><span>⌖ ${esc(job.city)}</span><span>${esc(job.schedule)}</span><span>${esc(job.employment)}</span></div>
        ${preview ? `<p class="job-preview">${esc(preview)}${String(job.description || '').replace(/\s+/g,' ').trim().length > 180 ? '…' : ''}</p>` : ''}
        ${skills.length ? `<div class="job-skill-tags">${skills.map(skill=>`<span>${esc(skill)}</span>`).join('')}</div>` : ''}
        ${personalized && reasons.length ? `<div class="match-reasons-preview">${reasons.slice(0,2).map(reason=>`<span>✓ ${esc(reason)}</span>`).join('')}</div>` : ''}
        ${personalized ? `<details class="match-explanation"><summary>Почему эта вакансия в рекомендациях?</summary><ul>${reasons.map(reason => `<li>${esc(reason)}</li>`).join('') || '<li>Подходят основные условия вашего профиля</li>'}</ul><p class="muted">Совпадение рассчитывается по данным профиля и помогает сортировать варианты. Оно не гарантирует приглашение.</p></details>` : ''}
        <div class="job-actions"><button class="btn btn-outline btn-tiny" data-v02-action="details" data-id="${id}">Подробнее</button>${roleActions}</div></article>`;
    };

    loadPublicJobs = async function() {
      try {
        await Promise.all([refreshMyApplications(), refreshFavorites()]);
        const qs = new URLSearchParams();
        const filters = [
          ['profession-filter','q','Профессия'],
          ['city-filter','city','Город'],
          ['salary-filter','salary_min','Зарплата от'],
          ['schedule-filter','schedule','График'],
          ['employment-filter','employment','Занятость']
        ];
        const active = [];
        for (const [input,param,label] of filters) {
          const value=searchValue(input);
          if(value){ qs.set(param,value); active.push([label,value]); }
        }
        const sort=searchValue('sort-filter') || 'recent';
        qs.set('sort',sort);
        const result = await api('/api/jobs?'+qs);
        const jobs = result.jobs || [];
        $('#jobs-count').textContent = `Найдено: ${jobs.length}`;
        const sortLabels={salary_desc:'Сначала выше зарплата',salary_asc:'Сначала ниже зарплата'};
        if(sortLabels[sort]) active.push(['Сортировка',sortLabels[sort]]);
        $('#job-filter-summary').innerHTML = active.map(([label,value])=>`<span class="filter-chip">${esc(label)}: ${esc(value)}</span>`).join('');
        $('#public-jobs').innerHTML = jobs.length
          ? jobs.map(j=>jobMarkup(j)).join('')
          : '<div class="empty-state"><strong>По этим условиям вакансий нет.</strong><p>Уберите один из фильтров или сбросьте поиск, чтобы увидеть больше вариантов.</p></div>';
      } catch(e) {
        toast(e.message,true);
        $('#public-jobs').innerHTML='<div class="empty-state">Не удалось загрузить вакансии. Попробуйте ещё раз.</div>';
      }
    };

    const oldCandidate = renderCandidate;
    const oldEmployer = renderEmployer;
    const oldAdmin = renderAdmin;
    const oldUpdateAuth = updateAuth;

    updateAuth = function() {
      oldUpdateAuth();
      if(state.mode==='login') $('#auth-switch').insertAdjacentHTML('beforeend',' · <button type="button" data-v02-action="recover">Забыли пароль?</button>');
    };
    const candidateExtra = [{id:'favorites',label:'Сохранённые'},{id:'applications',label:'Отклики'},{id:'changes',label:'Изменения'},{id:'email',label:'Email и доступ'}];
    const changedFieldLabels = {
      title:'Должность',city:'Город',salary_min:'Зарплата от',
      salary_max:'Зарплата до',schedule:'График',employment:'Занятость',
      skills:'Ключевые навыки',description:'Описание и условия работы'
    };
    function displayChangeValue(field,value) {
      if(field==='salary_min'||field==='salary_max')return money(value);
      return String(value ?? 'Не указано');
    }
    function vacancyChangesMarkup(changes) {
      return Object.entries(changes || {}).filter(([key])=>Object.hasOwn(changedFieldLabels,key))
        .map(([field,pair])=>`<div class="vacancy-change-detail">
          <strong>${esc(changedFieldLabels[field])}</strong>
          <div class="vacancy-change-pair"><div><small>Было</small><p>${esc(displayChangeValue(field,pair.before))}</p></div>
          <div><small>Стало</small><p>${esc(displayChangeValue(field,pair.after))}</p></div></div></div>`).join('');
    }
    function vacancyUpdateMarkup(update) {
      return `<article class="item-card vacancy-change-item ${update.read_at ? 'is-read' : 'is-new'}">
        <header><div><h4>${esc(update.title)}</h4>
          <p>${esc(update.company_name)} · ${esc(update.created_at)}</p></div>
          <span class="mini-badge ${update.read_at ? 'gray' : ''}">${update.read_at ? 'Прочитано' : 'Новое изменение'}</span></header>
        <p class="vacancy-change-context">Работодатель изменил условия этой вакансии после вашего отклика или приглашения.
        Проверьте новые условия перед продолжением общения.</p>
        <div class="vacancy-changes-list">${vacancyChangesMarkup(update.changes)}</div>
        ${update.read_at ? '' : `<button class="btn btn-outline btn-tiny" data-v02-action="mark-vacancy-update-read" data-id="${Number(update.id)}">Отметить прочитанным</button>`}
      </article>`;
    }
    const employerExtra = [{id:'applications',label:'Отклики'}];

    renderCandidate = async function() {
      if (!candidateExtra.some(t=>t.id===state.tab)) {
        if (state.tab === 'offers' || state.tab === 'overview') {
          try { await Promise.all([refreshMyApplications(), refreshFavorites()]); }
          catch (e) {
            applicationByVacancy = new Map();
            favoriteVacancyIds = new Set();
            // Recommended jobs still return application_status, so a temporary
            // auxiliary-list failure must not hide the main recommendations.
          }
        }
        await oldCandidate();
        if (state.tab === 'offers') {
          const target = document.getElementById('dashboard-main');
          if (target) {
            try {
              const {jobs} = await api('/api/candidate/alternative-jobs');
              if (state.tab === 'offers' && jobs.length) {
                const markup = jobs.map(job => `<article class="item-card">
                  <h4>${esc(job.title)}</h4>
                  <p>${esc(job.company_name)} · ${esc(job.city)} · ${formatPay(job)}</p>
                  <p><strong>Что не совпадает:</strong></p>
                  <ul>${job.mismatch_reasons.map(reason => `<li>${esc(reason)}</li>`).join('')}</ul>
                  <p class="muted">Это не персональная рекомендация. Вы самостоятельно решаете, рассматривать ли вакансию.</p>
                  <button type="button" class="btn btn-outline btn-tiny" data-v02-action="details" data-id="${Number(job.id)}">Подробнее</button>
                </article>`).join('');
                target.insertAdjacentHTML('beforeend',
                  `<section class="panel" aria-label="Другие вакансии"><h3>Другие вакансии, которые могут вас заинтересовать</h3>
                  <p class="muted">Они не прошли строгий подбор. Посмотрите различия перед откликом.</p>
                  <div class="dashboard-list">${markup}</div></section>`);
              }
            } catch (error) {
              // Optional alternatives must never hide or break strict recommendations.
              console.warn('Alternative vacancies unavailable', error);
            }
          }
        }
        const nav=$('.dashboard-tabs');
        if (nav) { const icons={favorites:'♡',applications:'✓',changes:'↻',email:'@'}; nav.insertAdjacentHTML('beforeend',candidateExtra.map(t=>`<button type="button" data-tab="${t.id}"><span class="dashboard-tab-icon" aria-hidden="true">${icons[t.id]||'•'}</span><span>${t.label}</span></button>`).join('')); }
        return;
      }
      const nav = [{id:'overview',label:'Обзор'},{id:'profile',label:'Мой профиль'},{id:'offers',label:'Подходящие вакансии'},{id:'invitations',label:'Приглашения'},...candidateExtra];
      $('#account-content').innerHTML=`<div class="dashboard-grid">${tabsMarkup(nav,'ДЛЯ СОИСКАТЕЛЯ','Ваша карьера')}<div id="dashboard-main"><div class="loading">Загрузка...</div></div></div>`;
      try {
        if(state.tab==='favorites'){
          const {jobs}=await api('/api/candidate/favorites');
          $('#dashboard-main').innerHTML=`<div class="panel"><div class="panel-title-row"><div><span class="section-kicker">СОХРАНЕНО</span><h3>Избранные вакансии</h3><p class="muted">Здесь собраны сохранённые варианты, к которым можно вернуться позже.</p></div></div><div class="dashboard-list">${jobs.length?jobs.map(j=>`<div class="saved-job">${jobMarkup(j)}<button class="btn btn-outline btn-tiny" data-v02-action="remove-favorite" data-id="${Number(j.id)}">Убрать из избранного</button></div>`).join(''):'<div class="empty-state empty-state-action"><span class="empty-state-icon" aria-hidden="true">♡</span><strong>Вы ещё не сохранили вакансий.</strong><p>Нажимайте ♡ на интересных вакансиях, чтобы вернуться к ним позже.</p><a class="btn btn-primary" href="#jobs">Посмотреть вакансии →</a></div>'}</div></div>`;
        }
        if(state.tab==='applications'){
          const {applications}=await api('/api/candidate/applications');
          const updateSummary = await api('/api/candidate/vacancy-updates');
          $('#dashboard-main').innerHTML=`<div class="panel"><div class="panel-title-row"><div><span class="section-kicker">ОТКЛИКИ</span><h3>История откликов</h3><p class="muted">Следите за этапом каждого отклика. Контакты не раскрываются работодателю автоматически.</p></div></div>${updateSummary.unread_count ? `<div class="vacancy-update-banner" role="status">По вакансиям, на которые вы откликались, есть изменения условий: ${Number(updateSummary.unread_count)}. <button type="button" class="btn btn-outline btn-tiny" data-tab="changes">Посмотреть изменения</button></div>` : ''}<div class="dashboard-list">${applications.length ? applications.map(a=>`<article class="item-card"><header><div><h4>${esc(a.title)}</h4><p>${esc(a.company_name)} · ${esc(a.city)} · ${formatPay(a)}</p></div><span class="mini-badge">${esc(workflowStatus(a,status[a.status]||a.status))}</span></header><div class="application-card-meta"><span>Отклик отправлен</span><strong>${esc(a.created_at)}</strong></div>${interactionStageMarkup(a,'application')}${activityTimelineMarkup(a)}${applicationIntroBadge(a)}${['applied','reviewing','interview'].includes(a.status) && !a.invitation_id?`<button class="btn btn-outline btn-tiny" data-v02-action="withdraw" data-id="${Number(a.id)}">Отозвать отклик</button>`:a.status==='withdrawn'?`<button class="btn btn-primary btn-tiny" data-v02-action="reapply" data-id="${Number(a.vacancy_id)}">Откликнуться повторно</button>`:''}</article>`).join(''):'<div class="empty-state empty-state-action"><span class="empty-state-icon" aria-hidden="true">↗</span><strong>Вы ещё не откликались</strong><p>Найдите подходящую вакансию и отправьте первый отклик. Контакты работодателю автоматически не передаются.</p><a class="btn btn-primary" href="#jobs">Найти вакансию →</a></div>'}</div></div>`;
        }
        if(state.tab==='changes'){
          const result=await api('/api/candidate/vacancy-updates');
          $('#dashboard-main').innerHTML=`<div class="panel vacancy-changes">
            <span class="section-kicker">ИЗМЕНЕНИЯ</span><h3>Изменения условий вакансий</h3>
            <p class="muted">Здесь отображаются изменения вакансий, на которые вы откликнулись или получили приглашение. Реальные письма не отправляются.</p>
            ${result.unread_count ? `<p class="vacancy-unread-count" role="status">Непрочитанных изменений: ${Number(result.unread_count)}</p>` : '<p class="muted">Новых изменений нет.</p>'}
            <div class="dashboard-list">${result.updates.length ? result.updates.map(vacancyUpdateMarkup).join('') : '<div class="empty-state empty-state-action"><span class="empty-state-icon" aria-hidden="true">✓</span><strong>Изменений нет</strong><p>Если работодатель изменит условия вакансии после вашего отклика, информация появится здесь.</p></div>'}</div>
          </div>`;
        }
        if(state.tab==='email'){
          const result=await api('/api/account/email/status');
          $('#dashboard-main').innerHTML=`<div class="panel account-email-panel"><span class="section-kicker">EMAIL И ДОСТУП</span><h3>Подтверждение электронной почты</h3><p>${result.email_verified?'✓ Email подтверждён':'Email пока не подтверждён'}</p><p class="muted">Ссылка подтверждения будет отправлена на ваш email.</p><button class="btn btn-primary" data-v02-action="verify-email">Отправить письмо подтверждения</button></div>`;
        }
      } catch(e) { $('#dashboard-main').textContent=e.message;toast(e.message,true); }
    };

    renderEmployer = async function() {
      if(state.tab!=='applications'){
        await oldEmployer();
        const nav=$('.dashboard-tabs');
        if(nav) nav.insertAdjacentHTML('beforeend','<button type="button" data-tab="applications"><span class="dashboard-tab-icon" aria-hidden="true">✓</span><span>Отклики</span></button>');
        return;
      }
      const nav=[{id:'overview',label:'Обзор'},{id:'company',label:'Компания'},{id:'vacancies',label:'Мои вакансии'},{id:'create',label:'Новая вакансия'},{id:'invitations',label:'Приглашения и контакты'},...employerExtra];
      $('#account-content').innerHTML=`<div class="dashboard-grid">${tabsMarkup(nav,'ДЛЯ КОМПАНИИ',state.user.company?.company_name||'Работодатель')}<div id="dashboard-main"></div></div>`;
      try {
        const {applications}=await api('/api/employer/applications');
        const {jobs}=await api('/api/employer/vacancies');
        const selected = state.employerApplicationsVacancyFilter || 'all';
        const shown = selected === 'all' ? applications : applications.filter(a => String(a.vacancy_id) === selected);
        const options = jobs.map(j => `<option value="${Number(j.id)}" ${String(j.id) === selected ? 'selected' : ''}>${esc(j.title)}</option>`).join('');
        const selector = `<div class="field"><label for="employer-applications-vacancy">Вакансия</label><select id="employer-applications-vacancy"><option value="all">Все вакансии</option>${options}</select></div>`;
        $('#dashboard-main').innerHTML=`<div class="panel employer-applications-panel"><div class="split-header"><div><span class="section-kicker">ОТКЛИКИ</span><h3>Отклики соискателей</h3><p class="muted">Сначала оценивайте опыт и навыки. Имя, телефон и email остаются скрытыми до отдельного согласия кандидата.</p></div><div class="application-flow-legend" aria-label="Этапы обработки отклика"><span>1. Отклик</span><b>→</b><span>2. Рассмотрение</span><b>→</b><span>3. Согласие</span><b>→</b><span>4. Знакомство</span></div></div><div class="form-grid">${selector}</div><p class="muted" role="status">Найдено откликов: ${shown.length}</p><div class="dashboard-list">${shown.length?shown.map(a=>`<article class="item-card application-review-card"><header><div><h4>${esc(a.profession)}</h4><p>${esc(a.title)} · ${esc(a.city)} · ожидания от ${money(a.expected_salary)}</p></div><span class="mini-badge">${esc(workflowStatus(a,status[a.status]||a.status))}</span></header>${interactionStageMarkup(a,'application')}<div class="application-profile-strip"><span><small>Навыки</small><strong>${esc(a.skills||'Не указаны')}</strong></span><span><small>Этап</small><strong>${a.contact_shared?'Контакт открыт':a.invitation_status==='accepted'?'Есть согласие':a.invitation_status==='sent'?'Ждём решения кандидата':a.status==='reviewing'?'На рассмотрении':'Новый отклик'}</strong></span></div>${activityTimelineMarkup(a)}${employerIntroBadge(a)}${['applied','reviewing','interview'].includes(a.status) && !a.invitation_id?`<div class="application-next-action"><span>Следующее действие</span><strong>${a.status==='applied'?'Проверьте профиль и переведите в рассмотрение':'Решите, хотите ли начать знакомство'}</strong></div><div class="item-actions"><button class="btn btn-outline btn-tiny" data-v02-action="application-status" data-id="${Number(a.id)}" data-status="reviewing">${a.status==='applied'?'Взять в рассмотрение':'Оставить на рассмотрении'}</button><button class="btn btn-primary btn-tiny" data-v02-action="express-interest" data-id="${Number(a.id)}">Запросить согласие на знакомство →</button><button class="btn btn-outline btn-tiny" data-v02-action="application-status" data-id="${Number(a.id)}" data-status="rejected">Отказать</button></div>`:''}</article>`).join(''):'<div class="empty-state empty-state-action"><span class="empty-state-icon" aria-hidden="true">＋</span><strong>Откликов пока нет</strong><p>Можно не ждать: запустите подбор и пригласите подходящих специалистов сами.</p><button class="btn btn-primary" data-tab="vacancies">Перейти к вакансиям →</button></div>'}</div></div>`;
      } catch(e) { $('#dashboard-main').textContent=e.message;toast(e.message,true); }
    };

    renderAdmin = async function(){
      await oldAdmin();
      $('#account-content').insertAdjacentHTML('beforeend','<div class="panel admin-v02"><div class="item-actions"><button class="btn btn-outline" data-v02-action="admin-users">Пользователи</button><button class="btn btn-outline" data-v02-action="admin-jobs">Вакансии</button><button class="btn btn-outline" data-v02-action="admin-mail">Почтовые события</button></div><div id="admin-v02-results"></div></div>');
    };

    async function adminView(kind){
      const root=$('#admin-v02-results');
      root.textContent='Загрузка...';
      if(kind==='users'){
        const {users}=await api('/api/admin/users');
        root.innerHTML='<h3>Пользователи и работодатели</h3><div class="dashboard-list">'+users.map(u=>`<article class="item-card admin-user-card"><header><div><h4>${esc(u.role==='employer' && u.company_name ? u.company_name : u.name)}</h4><p>${esc(u.email)} · ${esc(u.role)}</p></div><span class="mini-badge ${u.status==='active'?'':'gray'}">${u.status==='active'?'Активен':'Заблокирован'}</span></header>${u.role==='employer'?`<div class="admin-trust-row"><span class="${u.email_verified?'is-ok':'is-pending'}">${u.email_verified?'✓ Email':'Email не подтверждён'}</span><span class="${u.inn?'is-ok':'is-pending'}">${u.inn?'ИНН '+esc(u.inn):'ИНН не указан'}</span><span class="${u.employer_verified?'is-ok':'is-pending'}">${u.employer_verified?'✓ Компания проверена':'Не проверена'}</span></div><div class="item-actions"><button class="btn ${u.employer_verified?'btn-outline':'btn-primary'} btn-tiny" data-v02-action="admin-employer-verification" data-id="${Number(u.id)}" data-verified="${u.employer_verified?'false':'true'}" ${!u.employer_verified&&(!u.email_verified||!u.inn)?'disabled title="Нужны подтверждённый email и ИНН"':''}>${u.employer_verified?'Снять проверку':'Проверить компанию'}</button></div>`:''}${u.role==='admin'?'':`<div class="item-actions"><button class="btn btn-outline btn-tiny" data-v02-action="admin-user-status" data-id="${Number(u.id)}" data-status="${u.status==='active'?'disabled':'active'}">${u.status==='active'?'Заблокировать':'Разблокировать'}</button></div>`}</article>`).join('')+'</div>';
      } else if(kind==='jobs'){
        const {jobs}=await api('/api/admin/vacancies');
        root.innerHTML='<h3>Вакансии</h3><div class="dashboard-list">'+jobs.map(j=>`<article class="item-card"><header><div><h4>${esc(j.title)}</h4><p>${esc(j.company_name)} · ${esc(j.city)}</p></div><span class="mini-badge">${j.status==='open'?'Открыта':'Закрыта'}</span></header><button class="btn btn-outline btn-tiny" data-v02-action="admin-job-status" data-id="${Number(j.id)}" data-status="${j.status==='open'?'closed':'open'}">${j.status==='open'?'Закрыть':'Открыть'}</button></article>`).join('')+'</div>';
      } else {
        const {messages}=await api('/api/admin/mail-preview');
        root.innerHTML='<h3>Тестовая очередь</h3><p class="muted">Сообщения НЕ отправляются. Секретные ссылки здесь скрыты.</p>'+messages.map(m=>`<p>${esc(m.created_at)} · ${esc(m.event)} · ${esc(m.subject)}</p>`).join('');
      }
    }

    document.addEventListener('change', event => {
      if (event.target?.id !== 'employer-applications-vacancy') return;
      state.employerApplicationsVacancyFilter = event.target.value;
      if (state.user?.role === 'employer' && state.tab === 'applications') renderEmployer().catch(error => toast(error.message,true));
    });

    document.addEventListener('click',async(event)=>{
      const btn=event.target.closest('[data-v02-action]');
      if(!btn)return;
      const type=btn.dataset.v02Action,id=Number(btn.dataset.id);
      btn.disabled=true;
      try{
        if(type==='details'){
          const {job}=await api(`/api/jobs/${id}`);
          $('#job-dialog-title').textContent=job.title;
          const skills=String(job.skills||'').split(',').map(x=>x.trim()).filter(Boolean);
          $('#job-dialog-content').innerHTML=`<div class="job-detail-v08"><div class="job-detail-company"><span class="section-kicker">ВАКАНСИЯ</span><strong>${esc(job.company_name)}</strong><span>⌖ ${esc(job.city)}</span>${employerTrustBadges(job,true)}</div><div class="job-detail-pay">${formatPay(job)}</div><div class="job-detail-facts"><span><small>График</small><strong>${esc(job.schedule)}</strong></span><span><small>Занятость</small><strong>${esc(job.employment)}</strong></span></div>${skills.length?`<div class="job-skill-tags">${skills.slice(0,8).map(skill=>`<span>${esc(skill)}</span>`).join('')}</div>`:''}<div class="job-detail-description">${esc(job.description||'Подробности у работодателя').replace(/\n/g,'<br>')}</div><div class="job-employer-trust-note"><strong>О работодателе</strong><p>${job.employer_verified?'Компания прошла проверку администратором СТАЖНО по заполненным реквизитам и подтверждённому email.':job.employer_email_verified&&job.employer_inn_provided?'Email подтверждён, реквизиты указаны. Статус проверки компании ещё не присвоен.':job.employer_email_verified?'Email работодателя подтверждён. Реквизиты компании пока не указаны или не проверены.':'Статус проверки компании пока не подтверждён.'}</p></div><div class="job-detail-privacy">Ваши контакты не передаются работодателю автоматически. Сначала отправляется отклик, а знакомство проходит только через отдельное согласие.</div><div class="job-detail-action">${state.user?.role==='candidate' ? jobApplicationAction(Number(job.id), job) : !state.user ? `<button class="btn btn-primary" data-v02-action="apply" data-id="${Number(job.id)}">Откликнуться на вакансию →</button>` : `<span class="job-role-note">Вы вошли как ${state.user.role==='employer'?'работодатель':'администратор'}. Отклики доступны только соискателям.</span>`}</div></div>`;
          $('#job-dialog').showModal();
        }else if(['apply','favorite'].includes(type)){
          if(state.user?.role!=='candidate'){ if($('#job-dialog').open) $('#job-dialog').close(); if(state.user)throw Error('Действие доступно только соискателю');openAuth('login','candidate');return; }
          if(type==='apply'){
            try {
              await req('POST','/api/candidate/applications',{vacancy_id:id});
              await refreshMyApplications();
              toast('Отклик отправлен, статус появится в кабинете');
              if($('#job-dialog').open)$('#job-dialog').close();
              if(state.tab === 'offers') await showDashboard();
              else await loadPublicJobs();
            } catch(err) {
              if(/уже откликались|уже существует/.test(err.message)){
                await refreshMyApplications();
                if($('#job-dialog').open)$('#job-dialog').close();
                state.tab='applications'; await showDashboard(true);
                toast('Заявка уже существует. Открыта ваша история откликов.');
              } else throw err;
            }
          }
          else {
            await req('POST',`/api/candidate/favorites/${id}`);
            favoriteVacancyIds.add(id);
            toast('Вакансия сохранена в избранном');
            await loadPublicJobs();
          }
        }else if(type==='favorite-remove-inline'){
          await req('DELETE',`/api/candidate/favorites/${id}`);
          favoriteVacancyIds.delete(id);
          toast('Вакансия удалена из избранного');
          await loadPublicJobs();
        }else if(type==='remove-favorite'){
          await req('DELETE',`/api/candidate/favorites/${id}`);
          favoriteVacancyIds.delete(id);
          await showDashboard();
          toast('Вакансия удалена из избранного');
        }
        else if(type==='withdraw'){await req('POST',`/api/candidate/applications/${id}/withdraw`);await showDashboard();toast('Отклик отозван');}
        else if(type==='reapply'){const result=await req('POST','/api/candidate/applications',{vacancy_id:id});await refreshMyApplications();await showDashboard();toast(result.reapplied?'Отклик отправлен повторно':'Отклик отправлен');}
        else if(type==='mark-vacancy-update-read'){await req('POST',`/api/candidate/vacancy-updates/${id}/read`);await showDashboard();toast('Изменение отмечено прочитанным.');}
        else if(type==='see-applications'){state.tab='applications';await showDashboard(true);}
        else if(type==='application-status'){await req('PATCH',`/api/employer/applications/${id}/status`,{status:btn.dataset.status});await showDashboard();toast('Статус обновлён');}
        else if(type==='express-interest'){const data=await req('POST',`/api/employer/applications/${id}/interest`);await showDashboard();toast(data.created?'Кандидату направлен запрос на знакомство (демо)':'Запрос уже существует — повторно не отправлен');}
        else if(type==='open-introductions'){state.tab='invitations';await showDashboard();}
        else if(type==='verify-email'){await req('POST','/api/account/email/request');toast('Письмо подтверждения отправлено, если почтовая доставка настроена');}
        else if(type==='recover'){$('#auth-dialog').close();$('#reset-dialog').showModal();}
        else if(type==='admin-users')await adminView('users');
        else if(type==='admin-jobs')await adminView('jobs');
        else if(type==='admin-mail')await adminView('mail');
        else if(type==='admin-employer-verification'){await req('PATCH',`/api/admin/employers/${id}/verification`,{verified:btn.dataset.verified==='true'});await adminView('users');await loadPublicJobs();toast(btn.dataset.verified==='true'?'Компания отмечена как проверенная':'Статус проверки снят');}
                else if(type==='admin-user-status'){await req('PATCH',`/api/admin/users/${id}/status`,{status:btn.dataset.status});await adminView('users');toast('Статус пользователя изменён');}
        else if(type==='admin-job-status'){await req('PATCH',`/api/admin/vacancies/${id}/status`,{status:btn.dataset.status});await adminView('jobs');await loadPublicJobs();toast('Вакансия обновлена');}
      }catch(e){toast(e.message,true);}
      finally{if(btn.isConnected)btn.disabled=false;}
    });
    $('#job-dialog-close').addEventListener('click',()=>$('#job-dialog').close());
    $('#reset-dialog-close').addEventListener('click',()=>$('#reset-dialog').close());
    $('#reset-request-form').addEventListener('submit',async event=>{
      event.preventDefault();
      try{
        await req('POST','/api/account/password/request',{email:$('#reset-email').value.trim()});
        $('#reset-dialog').close();toast('Если такой аккаунт существует, ссылка для сброса отправлена на email');
      }catch(e){toast(e.message,true);}
    });
    $('#reset-complete-form').addEventListener('submit',async event=>{
      event.preventDefault();
      try{
        await req('POST','/api/account/password/reset',{token:$('#reset-token').value.trim(),password:$('#reset-new-password').value});
        $('#reset-dialog').close();toast('Пароль изменён. Войдите с новым паролем.');openAuth('login');
      }catch(e){toast(e.message,true);}
    });
    const params=new URLSearchParams(window.location.search);
    const action=params.get('account_action'),token=params.get('token');
    if(action && token){
      params.delete('account_action');params.delete('token');
      history.replaceState(null,'',window.location.pathname+(params.size?'?'+params:'')+window.location.hash);
      if(action==='reset'){$('#reset-token').value=token;$('#reset-dialog').showModal();}
      if(action==='verify'){req('POST','/api/account/email/confirm',{token}).then(()=>toast('Email подтверждён.')).catch(e=>toast(e.message,true));}
    }
    ['profession-filter','city-filter','salary-filter'].forEach(id=>$('#'+id).addEventListener('keydown',e=>{if(e.key==='Enter')loadPublicJobs();}));
    ['schedule-filter','employment-filter','sort-filter'].forEach(id=>$('#'+id).addEventListener('change',loadPublicJobs));
    $('#jobs-reset').addEventListener('click',()=>{
      ['profession-filter','city-filter','salary-filter'].forEach(id=>$('#'+id).value='');
      $('#schedule-filter').value='';
      $('#employment-filter').value='';
      $('#sort-filter').value='recent';
      loadPublicJobs();
    });
  });
})();
