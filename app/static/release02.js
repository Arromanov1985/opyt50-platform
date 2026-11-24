'use strict';
(function initRelease02() {
  document.addEventListener('DOMContentLoaded', () => {
    const status = {applied:'Отправлен',reviewing:'На рассмотрении',interview:'Работодатель заинтересован',rejected:'Отказ',hired:'Положительный итог',withdrawn:'Отозван'};
    const req = (method, path, data) => api(path,{method, ...(data ? {body:JSON.stringify(data)} : {})});
    const introductionLabel = {sent:'Ожидается ваше решение',accepted:'Согласие получено',declined:'От знакомства отказались'};
    const eventLabels = {applied:'Отклик отправлен',reapplied:'Отклик отправлен повторно',withdrawn:'Отклик отозван',reviewing:'На рассмотрении',interview:'Работодатель заинтересован',rejected:'Получен отказ',hired:'Положительный итог'};
    function applicationIntroBadge(a) {
      if (!a.invitation_id) return '';
      if (a.contact_shared && a.status === 'hired') {
        return '<div class="interaction-note is-complete"><strong>Положительный итог знакомства</strong><span>Компания хочет продолжить общение. Это не подтверждение трудоустройства. Условия работы обсудите напрямую с компанией.</span></div><button class="btn btn-outline btn-tiny" data-v02-action="open-introductions" data-filter="closed" data-invitation-id="'+Number(a.invitation_id)+'">Открыть завершённое знакомство →</button>';
      }
      if (a.contact_shared && a.status === 'rejected') {
        return '<div class="interaction-note is-closed"><strong>Не договорились</strong><span>Знакомство завершено без продолжения.</span></div><button class="btn btn-outline btn-tiny" data-v02-action="open-introductions" data-filter="closed" data-invitation-id="'+Number(a.invitation_id)+'">Открыть завершённое знакомство →</button>';
      }
      if (a.contact_shared) {
        return '<div class="interaction-note is-complete"><strong>Знакомство состоялось</strong><span>Работодатель открыл контакт после вашего согласия. На СТАЖНО дополнительных действий не требуется.</span></div><button class="btn btn-outline btn-tiny" data-v02-action="open-introductions" data-filter="introduced" data-invitation-id="'+Number(a.invitation_id)+'">Открыть знакомство →</button>';
      }
      if (a.invitation_status === 'accepted') {
        return '<div class="interaction-note is-waiting"><strong>Согласие отправлено</strong><span>Теперь ждём работодателя. Повторно подтверждать знакомство не нужно.</span></div><button class="btn btn-outline btn-tiny" data-v02-action="open-introductions" data-filter="waiting" data-invitation-id="'+Number(a.invitation_id)+'">Посмотреть знакомство →</button>';
      }
      if (a.invitation_status === 'sent') {
        return '<div class="interaction-note is-ready"><strong>Работодатель предлагает знакомство</strong><span>Контакты останутся скрытыми, пока вы сами не согласитесь.</span></div><button class="btn btn-primary btn-tiny" data-v02-action="open-introductions" data-filter="decision" data-invitation-id="'+Number(a.invitation_id)+'">Ответить на запрос компании →</button>';
      }
      if (a.invitation_status === 'declined') {
        return '<div class="interaction-note is-closed"><strong>Вы отказались от знакомства</strong><span>Контакты компании не переданы. Дополнительных действий нет.</span></div>';
      }
      return '';
    }
    function employerApplicationStageLabel(a) {
      if (a.status === 'hired') return 'Положительный итог';
      if (a.status === 'rejected' && a.contact_shared) return 'Не договорились';
      if (a.contact_shared) return 'Знакомство состоялось';
      if (a.invitation_status === 'accepted') return 'Согласие получено';
      if (a.invitation_status === 'sent') return 'Ждём решения кандидата';
      if (a.invitation_status === 'declined') return 'Кандидат отказался';
      if (a.status === 'hired') return 'Положительный итог';
      if (a.status === 'rejected') return 'Отказ';
      if (a.status === 'withdrawn') return 'Отклик отозван';
      if (a.status === 'reviewing') return 'На рассмотрении';
      if (a.status === 'interview') return 'Интерес подтверждён';
      return 'Новый отклик';
    }
    function employerIntroBadge(a) {
      if (!a.invitation_id) return '';
      if (a.contact_shared && a.status === 'hired') {
        return '<div class="interaction-note is-complete"><strong>Положительный итог</strong><span>Компания хочет продолжить общение. Это не подтверждение трудоустройства.</span></div><button class="btn btn-outline btn-tiny" data-v02-action="open-introductions" data-filter="closed" data-invitation-id="'+Number(a.invitation_id)+'">Открыть завершённое знакомство →</button>';
      }
      if (a.contact_shared && a.status === 'rejected') {
        return '<div class="interaction-note is-closed"><strong>Не договорились</strong><span>Знакомство завершено без продолжения.</span></div><button class="btn btn-outline btn-tiny" data-v02-action="open-introductions" data-filter="closed" data-invitation-id="'+Number(a.invitation_id)+'">Открыть завершённое знакомство →</button>';
      }
      if (a.contact_shared) {
        return '<div class="interaction-note is-complete"><strong>Знакомство состоялось</strong><span>Контакт уже открыт. История и контакт доступны в разделе знакомств.</span></div><button class="btn btn-outline btn-tiny" data-v02-action="open-introductions" data-filter="introduced" data-invitation-id="'+Number(a.invitation_id)+'">Открыть контакт →</button>';
      }
      if (a.invitation_status === 'accepted') {
        return '<div class="interaction-note is-ready"><strong>Согласие получено</strong><span>Кандидат разрешил продолжить знакомство. Следующий шаг — открыть контакт.</span></div><button class="btn btn-primary btn-tiny" data-v02-action="open-introductions" data-filter="action" data-invitation-id="'+Number(a.invitation_id)+'">Продолжить знакомство →</button>';
      }
      if (a.invitation_status === 'sent') {
        return '<div class="interaction-note is-waiting"><strong>Запрос отправлен</strong><span>Ждём решения кандидата. Повторно отправлять запрос не нужно.</span></div>';
      }
      if (a.invitation_status === 'declined') {
        return '<div class="interaction-note is-closed"><strong>Кандидат отказался от знакомства</strong><span>Действий не требуется. Повторный запрос по этому знакомству не отправляется.</span></div>';
      }
      return '<div class="interaction-note"><strong>Знакомство создано</strong><span>Проверьте текущий этап в истории взаимодействия.</span></div>';
    }
    function searchValue(id) { return document.getElementById(id)?.value?.trim() || ''; }

    // Keep application status beside recommended vacancies, so clicking twice
    // never looks like a system failure. The server still enforces uniqueness.
    let applicationByVacancy = new Map();
    let favoriteVacancyIds = new Set();
    // A vacancy can have several CTA buttons (list, recommendation, dialog).
    // Prevent one fast sequence of clicks from dispatching duplicate POSTs.
    const pendingApplicationRequests = new Set();
    function setApplicationPending(jobId, pending) {
      if (!Number.isSafeInteger(jobId) || jobId <= 0) return;
      const buttons = document.querySelectorAll(
        `[data-v02-action="apply"][data-id="${jobId}"], [data-v02-action="reapply"][data-id="${jobId}"]`
      );
      buttons.forEach(button => {
        if (pending) {
          if (!button.dataset.originalApplyLabel) button.dataset.originalApplyLabel = button.textContent;
          button.textContent = 'Отправляем отклик…';
          button.disabled = true;
          button.setAttribute('aria-busy', 'true');
        } else {
          if (button.dataset.originalApplyLabel) {
            button.textContent = button.dataset.originalApplyLabel;
            delete button.dataset.originalApplyLabel;
          }
          button.disabled = false;
          button.removeAttribute('aria-busy');
        }
      });
    }
    function syncVisibleApplicationCards(jobId) {
      // A successful send changes every visible card for this vacancy, not
      // only the dialog from which the candidate submitted the application.
      const actionHtml = jobApplicationAction(jobId);
      const receiptHtml = jobApplicationReceipt(jobId);
      document.querySelectorAll(`.job-card[data-job-id="${jobId}"]`).forEach(card => {
        const action = card.querySelector('[data-v02-action="apply"], [data-v02-action="reapply"]');
        if (action) action.outerHTML = actionHtml;
        if (receiptHtml && !card.querySelector('.job-application-receipt')) {
          card.insertAdjacentHTML('beforeend', receiptHtml);
        }
      });
    }
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
      return `<button type="button" class="btn btn-outline btn-tiny" data-v02-action="see-applications" data-application-id="${Number(known.id || 0)}" data-vacancy-id="${Number(jobId)}">Отклик: ${esc(candidateWorkflowStatus(known,status[known.status] || known.status))} · история</button>`;
    }
    function jobApplicationReceipt(jobId, job = null) {
      const known = (job && job.application_status)
        ? {status:job.application_status, contact_shared:job.contact_shared}
        : applicationByVacancy.get(jobId);
      if (!known || known.status !== 'applied') return '';
      return '<div class="job-application-receipt" role="status"><strong>✓ Отклик отправлен</strong><span>Работодатель видит данные профиля для рассмотрения. Имя и контакты остаются скрытыми до отдельного согласия на знакомство.</span></div>';
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

    function matchScoreClass(score) {
      return Number(score) >= 90 ? 'excellent' : Number(score) >= 80 ? 'high' : Number(score) >= 70 ? 'medium' : 'basic';
    }
    function matchBreakdownMarkup(item, compact = false) {
      const factors = Array.isArray(item.score_breakdown) ? item.score_breakdown : [];
      const cautions = Array.isArray(item.cautions) ? item.cautions : [];
      if (!factors.length) return '';
      const rows = factors.map(factor => `<div class="match-factor-row ${esc(factor.state||'good')}">
        <div class="match-factor-head"><span>${esc(factor.label||factor.key||'Фактор')}</span><strong>${Number(factor.points||0).toLocaleString('ru-RU')} / ${Number(factor.max_points||0).toLocaleString('ru-RU')}</strong></div>
        <div class="match-factor-track"><span style="width:${Math.max(0,Math.min(100,Number(factor.percent||0)))}%"></span></div>
        <small>${esc(factor.text||'')}</small>
      </div>`).join('');
      const cautionMarkup = cautions.length ? `<div class="match-cautions"><strong>Что стоит уточнить</strong>${cautions.slice(0,compact?2:4).map(text=>`<span>! ${esc(text)}</span>`).join('')}</div>` : '';
      return `<div class="match-breakdown ${compact?'compact':''}">${rows}${cautionMarkup}<p class="match-method-note">Оценка основана только на профессии, навыках и условиях работы. Возраст и другие личные характеристики не используются. Итог округляется до 5% и помогает сортировать варианты, но не гарантирует приглашение.</p></div>`;
    }

    jobMarkup = function(job, personalized = false) {
      const id = Number(job.id), open = job.status !== 'closed';
      const saved = favoriteVacancyIds.has(id);
      const skills = String(job.skills || '').split(',').map(s=>s.trim()).filter(Boolean).slice(0,4);
      const preview = String(job.description || '').replace(/\s+/g,' ').trim().slice(0,180);
      const score = Number(job.score || 0);
      const scoreClass = matchScoreClass(score);
      const reasons = Array.isArray(job.strengths) ? job.strengths : (Array.isArray(job.reasons) ? job.reasons : []);
      const cautions = Array.isArray(job.cautions) ? job.cautions : [];
      const level = job.match_level || (score >= 90 ? 'Очень сильное совпадение' : score >= 80 ? 'Сильное совпадение' : score >= 70 ? 'Хорошее совпадение' : 'Подходит по основным условиям');
      const scoreBadge = personalized
        ? `<span class="job-category match-score ${scoreClass}"><span class="match-score-dot"></span><strong>${score}%</strong><small>${esc(level)}</small></span>`
        : `<span class="job-category">${open ? 'Открыта' : 'Закрыта'}</span>`;
      let roleActions = '';
      if (open && state.user?.role === 'candidate') {
        roleActions = `${jobApplicationAction(id, job)}<button class="btn btn-outline btn-tiny favorite-toggle" data-v02-action="${saved ? 'favorite-remove-inline' : 'favorite'}" data-id="${id}" aria-label="${saved ? 'Убрать вакансию из избранного' : 'Сохранить вакансию'}" aria-pressed="${saved ? 'true' : 'false'}">${saved ? '♥' : '♡'}</button>`;
      }
      const detailsPrimary = open && !state.user;
      return `<article class="job-card job-card-v08" data-job-id="${id}"><div class="job-top"><div class="job-company-wrap"><a class="job-company" href="/companies/${Number(job.employer_id)}" aria-label="О компании ${esc(job.company_name || 'Работодатель')}">${esc(job.company_name || 'Работодатель')}</a>${employerTrustBadges(job)}</div>${scoreBadge}</div>
        <h3>${esc(job.title)}</h3><div class="job-salary">${formatPay(job)}</div>
        <dl class="job-essential-facts"><div><dt>Город</dt><dd>${esc(job.city || 'Не указан')}</dd></div><div><dt>График</dt><dd>${esc(job.schedule || 'Уточняется')}</dd></div><div><dt>Занятость</dt><dd>${esc(job.employment || 'Уточняется')}</dd></div></dl>
        ${preview ? `<p class="job-preview">${esc(preview)}${String(job.description || '').replace(/\s+/g,' ').trim().length > 180 ? '…' : ''}</p>` : ''}
        ${skills.length ? `<div class="job-skill-tags">${skills.map(skill=>`<span>${esc(skill)}</span>`).join('')}</div>` : ''}
        ${personalized && reasons.length ? `<div class="match-reasons-preview">${reasons.slice(0,2).map(reason=>`<span>✓ ${esc(reason)}</span>`).join('')}</div>` : ''}
        ${personalized && cautions.length ? `<div class="match-caution-preview">${cautions.slice(0,1).map(text=>`<span>! ${esc(text)}</span>`).join('')}</div>` : ''}
        ${personalized ? `<details class="match-explanation"><summary>Как рассчитано совпадение?</summary>${matchBreakdownMarkup(job)}</details>` : ''}
        <div class="job-actions ${open && state.user?.role==='candidate' ? 'has-favorite' : ''}">${roleActions}<button type="button" class="btn ${detailsPrimary ? 'btn-primary' : 'btn-outline'} btn-tiny" data-v02-action="details" data-id="${id}">${detailsPrimary ? 'Условия и отклик' : 'Условия и описание'}</button></div><a class="job-share-link" href="/vacancies/${id}" aria-label="Открыть отдельную страницу вакансии ${esc(job.title)}">Открыть отдельной страницей <span aria-hidden="true">↗</span></a>${state.user?.role === 'candidate' ? jobApplicationReceipt(id, job) : ''}</article>`;
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
          if(value){ qs.set(param,value); active.push([label,value,input]); }
        }
        const sort=searchValue('sort-filter') || 'recent';
        qs.set('sort',sort);
        const result = await api('/api/jobs?'+qs);
        const jobs = result.jobs || [];
        $('#jobs-count').textContent = `Найдено: ${jobs.length}`;
        const sortLabels={salary_desc:'Сначала выше зарплата',salary_asc:'Сначала ниже зарплата'};
        if(sortLabels[sort]) active.push(['Сортировка',sortLabels[sort],'sort-filter']);
        $('#job-filter-summary').innerHTML = active.map(([label,value,input])=>`<button type="button" class="filter-chip filter-chip-action" data-v02-action="remove-public-job-filter" data-filter-id="${input}" aria-label="Убрать фильтр: ${esc(label)}, ${esc(value)}">${esc(label)}: ${esc(value)} <span aria-hidden="true">×</span></button>`).join('');
        const hasFilters = active.length > 0;
        $('#public-jobs').innerHTML = jobs.length
          ? jobs.map(j=>jobMarkup(j)).join('')
          : hasFilters
            ? '<div class="empty-state empty-state-action jobs-empty-state" role="status"><strong>По этим условиям вакансий пока нет.</strong><p>Попробуйте расширить поиск или посмотрите все доступные предложения.</p><button type="button" class="btn btn-outline" data-v02-action="reset-public-job-filters">Показать все вакансии</button></div>'
            : '<div class="empty-state empty-state-action jobs-empty-state" role="status"><strong>Открытых вакансий пока нет.</strong><p>Новые предложения появятся здесь после публикации работодателями. Пока можно посмотреть материалы о поиске работы.</p><a class="btn btn-outline" href="/journal">Перейти в журнал</a></div>';
      } catch(e) {
        toast(e.message,true);
        $('#public-jobs').innerHTML='<div class="empty-state empty-state-action jobs-empty-state" role="status"><strong>Не удалось загрузить вакансии.</strong><p>Проверьте подключение и повторите поиск.</p><button type="button" class="btn btn-outline" data-v02-action="retry-public-jobs">Повторить поиск</button></div>';
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
      const text=String(value ?? '').trim();
      return text || 'Не указано';
    }
    function vacancyChangeDate(raw) {
      const original=String(raw||'').trim();
      if(!original)return 'Дата не указана';
      const iso=original.replace(' ','T').replace(/([+-][0-9]{2})$/,'$1:00');
      const qualified=/(?:Z|[+-][0-9]{2}:?[0-9]{2})$/i.test(iso)?iso:iso+'Z';
      const date=new Date(qualified);
      if(Number.isNaN(date.getTime()))return 'Дата не указана';
      return new Intl.DateTimeFormat('ru-RU',{
        day:'numeric',month:'long',year:'numeric',hour:'2-digit',minute:'2-digit'
      }).format(date);
    }
    function vacancyChangeDetails(changes) {
      return Object.entries(changes||{}).flatMap(([field,pair])=>{
        if(!Object.hasOwn(changedFieldLabels,field)||!pair||typeof pair!=='object')return [];
        if(field==='description'){
          const splitter=window.OpytnovacancyWizard?.splitDescription;
          const oldParts=splitter?.(pair.before),newParts=splitter?.(pair.after);
          if(oldParts&&newParts){
            return [
              ['responsibilities','Обязанности'],['requirements','Требования'],['conditions','Условия работы']
            ].filter(([name])=>oldParts[name]!==newParts[name])
              .map(([name,label])=>({field:name,label,before:oldParts[name],after:newParts[name]}));
          }
        }
        return [{field,label:changedFieldLabels[field],before:pair.before,after:pair.after}];
      });
    }
    function vacancyChangesMarkup(changes) {
      return vacancyChangeDetails(changes).map(({field,label,before,after})=>`<div class="vacancy-change-detail">
          <strong>${esc(label)}</strong>
          <div class="vacancy-change-pair"><div><small>Было</small><p>${esc(displayChangeValue(field,before))}</p></div>
          <div><small>Стало</small><p>${esc(displayChangeValue(field,after))}</p></div></div></div>`).join('');
    }
    // Shared read-only markup for candidate notifications and employer history.
    window.StazhnoVacancyChanges=Object.freeze({
      markup:vacancyChangesMarkup,date:vacancyChangeDate,details:vacancyChangeDetails
    });
    function vacancyUpdateMarkup(update) {
      const fromInvitation=update.relationship==='invitation';
      const nextAction=fromInvitation?'open-introductions':'open-candidate-applications';
      const nextLabel=fromInvitation?'Открыть знакомство':'Посмотреть отклик';
      const details=vacancyChangeDetails(update.changes);
      return `<article class="item-card vacancy-change-item ${update.read_at ? 'is-read' : 'is-new'}" data-vacancy-update-id="${Number(update.id)}">
        <header><div><h4>${esc(update.title)}</h4>
          <p>${esc(update.company_name)} · ${esc(vacancyChangeDate(update.created_at))}</p></div>
          <span class="mini-badge ${update.read_at ? 'gray' : ''}">${update.read_at ? 'Прочитано' : 'Новое изменение'}</span></header>
        <p class="vacancy-change-context">Изменились условия вакансии после вашего отклика или приглашения.
        Сравните значения ниже. Изменено полей: ${details.length}.</p>
        <div class="vacancy-changes-list">${vacancyChangesMarkup(update.changes)}</div>
        <p class="vacancy-change-next">Следующий шаг: проверьте обновлённые условия и текущий статус ${fromInvitation?'знакомства':'отклика'}.</p>
        <div class="item-actions vacancy-change-actions">
          <button type="button" class="btn btn-outline btn-tiny" data-v02-action="${nextAction}" data-filter="all" data-vacancy-id="${Number(update.vacancy_id)}">${nextLabel} →</button>
          ${update.read_at ? '' : `<button type="button" class="btn btn-primary btn-tiny" data-v02-action="mark-vacancy-update-read" data-id="${Number(update.id)}">Отметить прочитанным</button>`}
        </div>
        ${update.read_at?'':`<p class="muted vacancy-change-read-help">Отметка подтверждает только прочтение, но не согласие с изменёнными условиями.</p>`}
      </article>`;
    }
    const vacancyUpdatesLimit = 20;
    let vacancyUpdatesFilter = 'all';
    let vacancyUpdatesNextCursor = null;
    let vacancyUpdatesLoading = false;
    const vacancyUpdatesFilters = ['all','unread','read'];
    function vacancyUpdatesEndpoint(filter, beforeId = null) {
      const params = new URLSearchParams({filter,limit:String(vacancyUpdatesLimit)});
      if(beforeId !== null) params.set('before_id',String(beforeId));
      return '/api/candidate/vacancy-updates?' + params.toString();
    }
    function vacancyUpdatesFilterControls(result) {
      const counts = {
        all:Number(result.total_count||0),
        unread:Number(result.unread_count||0),
        read:Number(result.read_count||0)
      };
      const names={all:'Все',unread:'Непрочитанные',read:'Прочитанные'};
      return vacancyUpdatesFilters.map(filter=>`<button type="button" class="btn btn-outline btn-tiny vacancy-update-filter ${vacancyUpdatesFilter===filter?'is-active':''}"
        data-v02-action="filter-vacancy-updates" data-filter="${filter}" aria-pressed="${vacancyUpdatesFilter===filter}">${names[filter]} (${counts[filter]})</button>`).join('');
    }
    function vacancyUpdatesPager(result) {
      return result.has_more && result.next_cursor
        ? '<button type="button" class="btn btn-outline" data-v02-action="more-vacancy-updates">Показать более ранние изменения</button>'
        : '';
    }
    function vacancyUpdatesEmpty(filter) {
      const headings={
        all:'Изменений пока нет',unread:'Все изменения прочитаны',read:'Прочитанных изменений пока нет'
      };
      return `<div class="empty-state empty-state-action"><strong>${headings[filter]}</strong>
        <p>${filter==='all'?'Если работодатель изменит условия вакансии после вашего отклика или приглашения, информация появится здесь.': 'Чтобы посмотреть другие уведомления, выберите «Все».'}</p></div>`;
    }

    // Release 0.5.20: a local, privacy-preserving queue for candidate applications.
    // Only company, vacancy and city are searchable. No API calls on typing.
    const candidateApplicationPageSize = 20;
    const candidateApplicationFilterLabels = {
      all: 'Все', reply: 'Требуют ответа', active: 'В работе', closed: 'Завершённые'
    };
    let candidateApplicationStageFilter = 'all';
    let candidateApplicationQuery = '';
    let candidateApplicationVisibleLimit = candidateApplicationPageSize;
    let candidateApplicationTarget = null;

    function navigationId(value) {
      const id = Number(value);
      return Number.isSafeInteger(id) && id > 0 ? id : null;
    }

    function focusApplicationDestination(selector) {
      const target = document.querySelector(selector) ||
        document.querySelector('#dashboard-main h3') || $('#dashboard-main');
      if (!target) return;
      target.tabIndex = -1;
      target.focus({preventScroll: true});
      target.scrollIntoView({block: 'nearest'});
    }

    async function openCandidateApplications(applicationId, vacancyId) {
      if (state.user?.role !== 'candidate' || !mayLeaveEditor()) return;
      const ownerId = state.user.id;
      const targetId = navigationId(applicationId);
      const targetVacancy = navigationId(vacancyId);
      candidateApplicationStageFilter = 'all';
      candidateApplicationQuery = '';
      candidateApplicationVisibleLimit = candidateApplicationPageSize;
      candidateApplicationTarget = targetId || targetVacancy
        ? {ownerId, applicationId: targetId, vacancyId: targetVacancy} : null;
      if ($('#job-dialog').open) $('#job-dialog').close();
      state.tab = 'applications';
      state.activeVacancy = null;
      try {
        await showDashboard();
      } finally {
        candidateApplicationTarget = null;
      }
      if (state.user?.id === ownerId && state.tab === 'applications') {
        focusApplicationDestination('.candidate-application-card.is-targeted');
      }
    }

    function candidateApplicationBucket(item) {
      if (item.invitation_status === 'sent' &&
          !['withdrawn','rejected','hired'].includes(item.status)) return 'reply';
      if (['withdrawn','rejected','hired'].includes(item.status) ||
          item.invitation_status === 'declined') return 'closed';
      return 'active';
    }

    function setupCandidateApplicationQueue(applications) {
      const root = document.querySelector('#dashboard-main');
      const list = root?.querySelector('.dashboard-list');
      const requested = candidateApplicationTarget?.ownerId === state.user?.id
        ? candidateApplicationTarget : null;
      candidateApplicationTarget = null;
      if (!list || !applications.length) {
        if (requested) toast('Этот отклик больше недоступен. Открыта ваша история откликов.');
        return;
      }
      const cards = Array.from(list.children).filter(node => node.matches('article.item-card'));
      if (cards.length !== applications.length) return;
      list.id = 'candidate-application-results';

      const priority = {reply: 0, active: 1, closed: 2};
      const entries = applications.map((item, index) => ({
        item, card: cards[index], bucket: candidateApplicationBucket(item)
      })).sort((left, right) =>
        priority[left.bucket] - priority[right.bucket] ||
        Number(right.item.id || 0) - Number(left.item.id || 0)
      );
      const selected = requested ? entries.find(entry => requested.applicationId
        ? Number(entry.item.id) === requested.applicationId
        : Number(entry.item.vacancy_id) === requested.vacancyId) : null;
      // A contextual link must reveal its record even beyond the first page.
      // Ordinary tab navigation and in-list filters retain their usual order.
      if (selected) {
        entries.splice(entries.indexOf(selected), 1);
        entries.unshift(selected);
      } else if (requested) {
        toast('Этот отклик больше недоступен. Показываем вашу историю откликов.');
      }
      const counts = {all: entries.length, reply: 0, active: 0, closed: 0};
      for (const entry of entries) {
        counts[entry.bucket] += 1;
        entry.card.classList.add('candidate-application-card');
        entry.card.classList.toggle('is-targeted', entry === selected);
        entry.card.dataset.applicationId = String(Number(entry.item.id));
        entry.card.dataset.candidateApplicationStage = entry.bucket;
        entry.card.dataset.candidateApplicationSearch =
          [entry.item.title, entry.item.company_name, entry.item.city]
            .map(value => String(value || '')).join(' ').toLocaleLowerCase('ru-RU');
        list.append(entry.card);
      }

      const buttons = Object.keys(candidateApplicationFilterLabels).map(value =>
        '<button type="button" class="btn btn-tiny candidate-application-filter" ' +
        'data-candidate-app-action="filter" data-filter="' + value + '" aria-pressed="' +
        (candidateApplicationStageFilter === value ? 'true' : 'false') + '">' +
        candidateApplicationFilterLabels[value] + ' · ' + counts[value] + '</button>'
      ).join('');
      list.insertAdjacentHTML('beforebegin',
        '<section class="candidate-application-toolbar" aria-label="Поиск и этапы откликов">' +
        '<div class="candidate-application-filters" role="group" aria-label="Фильтр откликов по этапу">' +
        buttons + '</div>' +
        '<label for="candidate-application-search">Поиск по вакансии, компании или городу</label>' +
        '<div class="candidate-application-search-row"><input id="candidate-application-search" ' +
        'type="search" autocomplete="off" placeholder="Например, кладовщик или Подольск">' +
        '<button class="btn btn-outline btn-tiny" type="button" ' +
        'data-candidate-app-action="clear">Очистить поиск</button></div>' +
        '<div class="candidate-application-counter" role="status" aria-live="polite">' +
        'Показываем <strong id="candidate-application-visible-count">0</strong> из ' +
        '<strong id="candidate-application-matched-count">0</strong> по выбранным условиям</div>' +
        '</section>'
      );
      list.insertAdjacentHTML('afterend',
        '<div class="candidate-application-empty empty-state" id="candidate-application-empty" hidden>' +
        '<strong>Откликов по этим условиям нет</strong>' +
        '<p>Попробуйте другой этап или поисковый запрос.</p>' +
        '<button class="btn btn-outline" type="button" data-candidate-app-action="reset">' +
        'Сбросить фильтры</button></div>' +
        '<div class="candidate-application-pagination" id="candidate-application-pagination" hidden>' +
        '<button class="btn btn-outline" type="button" data-candidate-app-action="more">' +
        'Показать следующие <span id="candidate-application-remaining">20</span> откликов</button></div>'
      );

      const toolbar = root.querySelector('.candidate-application-toolbar');
      const input = toolbar.querySelector('#candidate-application-search');
      const pager = root.querySelector('#candidate-application-pagination');
      const empty = root.querySelector('#candidate-application-empty');
      input.value = candidateApplicationQuery;
      function apply() {
        const query = candidateApplicationQuery.trim().toLocaleLowerCase('ru-RU');
        let matches = 0, visible = 0;
        for (const entry of entries) {
          const found = (candidateApplicationStageFilter === 'all' ||
            candidateApplicationStageFilter === entry.bucket) &&
            (!query || entry.card.dataset.candidateApplicationSearch.includes(query));
          if (found) matches++;
          entry.card.hidden = !found || matches > candidateApplicationVisibleLimit;
          if (!entry.card.hidden) visible++;
        }
        toolbar.querySelector('#candidate-application-visible-count').textContent = String(visible);
        toolbar.querySelector('#candidate-application-matched-count').textContent = String(matches);
        toolbar.querySelectorAll('[data-candidate-app-action="filter"]').forEach(button => {
          const selected = button.dataset.filter === candidateApplicationStageFilter;
          button.setAttribute('aria-pressed', String(selected));
          button.classList.toggle('btn-dark', selected);
          button.classList.toggle('btn-outline', !selected);
        });
        empty.hidden = matches > 0;
        pager.hidden = visible >= matches;
        root.querySelector('#candidate-application-remaining').textContent =
          String(Math.min(candidateApplicationPageSize, matches - visible));
      }
      input.addEventListener('input', () => {
        candidateApplicationQuery = input.value;
        candidateApplicationVisibleLimit = candidateApplicationPageSize;
        apply();
      });
      root.addEventListener('click', event => {
        const button = event.target.closest('[data-candidate-app-action]');
        if (!button || !root.contains(button)) return;
        const action = button.dataset.candidateAppAction;
        if (action === 'filter') {
          if (!Object.hasOwn(candidateApplicationFilterLabels, button.dataset.filter)) return;
          candidateApplicationStageFilter = button.dataset.filter;
          candidateApplicationVisibleLimit = candidateApplicationPageSize;
          apply();
          button.focus({preventScroll: true});
        } else if (action === 'clear') {
          candidateApplicationQuery = '';
          candidateApplicationVisibleLimit = candidateApplicationPageSize;
          input.value = '';
          apply();
          input.focus({preventScroll: true});
        } else if (action === 'reset') {
          candidateApplicationQuery = '';
          candidateApplicationStageFilter = 'all';
          candidateApplicationVisibleLimit = candidateApplicationPageSize;
          input.value = '';
          apply();
          input.focus({preventScroll: true});
        } else if (action === 'more') {
          const before = new Set(entries.filter(entry => !entry.card.hidden).map(entry => entry.card));
          candidateApplicationVisibleLimit += candidateApplicationPageSize;
          apply();
          const next = entries.find(entry => !entry.card.hidden && !before.has(entry.card));
          if (next) {
            next.card.tabIndex = -1;
            next.card.focus({preventScroll: true});
            next.card.scrollIntoView({block: 'nearest'});
          }
        }
      });
      apply();
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
        if (state.tab === 'offers' && candidateSearchReadiness(state.user?.profile || {}).ready) {
          const target = document.getElementById('dashboard-main');
          if (target) {
            try {
              const {jobs} = await api('/api/candidate/alternative-jobs');
              if (state.tab === 'offers' && jobs.length) {
                const markup = jobs.map(job => `<article class="item-card alternative-job-card">
                  <div class="alternative-job-head"><div><span class="card-eyebrow">БЛИЗКИЙ ВАРИАНТ</span><h4>${esc(job.title)}</h4><p>${esc(job.company_name)} · ${esc(job.city)} · ${formatPay(job)}</p></div><span class="near-fit-score">${Number(job.near_score||0)}%</span></div>
                  ${Array.isArray(job.strengths)&&job.strengths.length?`<div class="match-reasons-preview">${job.strengths.slice(0,2).map(reason=>`<span>✓ ${esc(reason)}</span>`).join('')}</div>`:''}
                  <div class="alternative-mismatches"><strong>Что не совпадает:</strong>${job.mismatch_reasons.map(reason => `<span>× ${esc(reason)}</span>`).join('')}</div>
                  <details class="match-explanation"><summary>Посмотреть факторы</summary>${matchBreakdownMarkup(job,true)}</details>
                  <p class="muted">Это не строгая рекомендация: есть несовместимый фактор. Решите самостоятельно, готовы ли вы его рассматривать.</p>
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
        return;
      }
      const nav = [{id:'overview',label:'Обзор'},{id:'profile',label:'Мой профиль'},{id:'offers',label:'Подходящие вакансии'},{id:'applications',label:'Отклики'},{id:'invitations',label:'Знакомства'},{id:'favorites',label:'Сохранённые'},{id:'changes',label:'Изменения'},{id:'email',label:'Email и доступ'},{id:'security',label:'Безопасность'}];
      $('#account-content').innerHTML=`<div class="dashboard-grid">${tabsMarkup(nav,'ДЛЯ СОИСКАТЕЛЯ','Ваша карьера')}<div id="dashboard-main"><div class="loading">Загрузка...</div></div></div>`;
      try {
        if(state.tab==='favorites'){
          const {jobs}=await api('/api/candidate/favorites');
          $('#dashboard-main').innerHTML=`<div class="panel"><div class="panel-title-row"><div><span class="section-kicker">СОХРАНЕНО</span><h3>Избранные вакансии</h3><p class="muted">Здесь собраны сохранённые варианты, к которым можно вернуться позже.</p></div></div><div class="dashboard-list">${jobs.length?jobs.map(j=>`<div class="saved-job">${jobMarkup(j)}<button class="btn btn-outline btn-tiny" data-v02-action="remove-favorite" data-id="${Number(j.id)}">Убрать из избранного</button></div>`).join(''):'<div class="empty-state empty-state-action"><span class="empty-state-icon" aria-hidden="true">♡</span><strong>Вы ещё не сохранили вакансий.</strong><p>Нажимайте ♡ на интересных вакансиях, чтобы вернуться к ним позже.</p><a class="btn btn-primary" href="#jobs">Посмотреть вакансии →</a></div>'}</div></div>`;
        }
        if(state.tab==='applications'){
          const {applications}=await api('/api/candidate/applications');
          const updateSummary = await api('/api/candidate/vacancy-updates');
          $('#dashboard-main').innerHTML=`<div class="panel"><div class="panel-title-row"><div><span class="section-kicker">ОТКЛИКИ</span><h3>История откликов</h3><p class="muted">Следите за этапом каждого отклика. Контакты не раскрываются работодателю автоматически.</p></div></div>${updateSummary.unread_count ? `<div class="vacancy-update-banner" role="status">По вакансиям, на которые вы откликались, есть изменения условий: ${Number(updateSummary.unread_count)}. <button type="button" class="btn btn-outline btn-tiny" data-tab="changes">Посмотреть изменения</button></div>` : ''}<div class="dashboard-list">${applications.length ? applications.map(a=>`<article class="item-card"><header><div><h4>${esc(a.title)}</h4><p>${esc(a.company_name)} · ${esc(a.city)} · ${formatPay(a)}</p></div><span class="mini-badge">${esc(candidateWorkflowStatus(a,status[a.status]||a.status))}</span></header><div class="application-card-meta"><span>Отклик отправлен</span><strong>${esc(a.created_at)}</strong></div>${interactionStageMarkup(a,'application')}${activityTimelineMarkup(a)}${applicationIntroBadge(a)}${['applied','reviewing','interview'].includes(a.status) && !a.invitation_id?`<button class="btn btn-outline btn-tiny" data-v02-action="withdraw" data-id="${Number(a.id)}">Отозвать отклик</button>`:a.status==='withdrawn'?`<button class="btn btn-primary btn-tiny" data-v02-action="reapply" data-id="${Number(a.vacancy_id)}">Откликнуться повторно</button>`:''}</article>`).join(''):'<div class="empty-state empty-state-action"><span class="empty-state-icon" aria-hidden="true">↗</span><strong>Вы ещё не откликались</strong><p>Найдите подходящую вакансию и отправьте первый отклик. Контакты работодателю автоматически не передаются.</p><a class="btn btn-primary" href="#jobs">Найти вакансию →</a></div>'}</div></div>`;
          setupCandidateApplicationQueue(applications);
        }
        if(state.tab==='changes'){
          const result=await api(vacancyUpdatesEndpoint(vacancyUpdatesFilter));
          vacancyUpdatesNextCursor=result.next_cursor;
          $('#dashboard-main').innerHTML=`<div class="panel vacancy-changes">
            <span class="section-kicker">ИЗМЕНЕНИЯ</span><h3>Изменения условий вакансий</h3>
            <p class="muted">История изменений вакансий, на которые вы откликались или получали приглашения. Можно посмотреть все старые уведомления. Письма не отправляются.</p>
            ${result.unread_count ? `<p class="vacancy-unread-count" role="status">Непрочитанных изменений: ${Number(result.unread_count)}</p>` : '<p class="muted">Новых изменений нет.</p>'}
            <div class="vacancy-update-filters" role="group" aria-label="Показать уведомления">
              ${vacancyUpdatesFilterControls(result)}
            </div>
            <div class="dashboard-list" id="vacancy-updates-list">${result.updates.length ? result.updates.map(vacancyUpdateMarkup).join('') : vacancyUpdatesEmpty(vacancyUpdatesFilter)}</div>
            <div class="vacancy-update-pagination" id="vacancy-updates-pagination">${vacancyUpdatesPager(result)}</div>
          </div>`;
        }
        if(state.tab==='email'){
          const result=await api('/api/account/email/status');
          $('#dashboard-main').innerHTML=`<div class="panel account-email-panel"><span class="section-kicker">EMAIL И ДОСТУП</span><h3>Подтверждение электронной почты</h3><p>${result.email_verified?'✓ Email подтверждён':'Email пока не подтверждён'}</p><p class="muted">Ссылка подтверждения будет отправлена на ваш email.</p><button class="btn btn-primary" data-v02-action="verify-email">Отправить письмо подтверждения</button></div>`;
        }
      } catch(e) { $('#dashboard-main').textContent=e.message;toast(e.message,true); }
    };

    function employerApplicationBucket(item) {
      if (item.contact_shared && ['hired','rejected'].includes(item.status)) return 'closed';
      if (item.contact_shared) return 'introduced';
      if (item.invitation_status === 'accepted') return 'ready';
      if (item.invitation_status === 'sent') return 'consent';
      if (item.invitation_status === 'declined' || ['rejected','hired','withdrawn'].includes(item.status)) return 'closed';
      return 'attention';
    }
    const employerApplicationFilterLabels = {
      all:'Все',
      attention:'Требуют внимания',
      consent:'Ждём решения кандидата',
      ready:'Есть согласие',
      introduced:'Ждут итога',
      closed:'Завершённые'
    };
    const employerApplicationPriority = {
      introduced:0,
      ready:1,
      attention:2,
      consent:3,
      closed:4
    };
    function sortEmployerApplications(items) {
      return [...items].sort((left,right)=>{
        const leftBucket=employerApplicationBucket(left);
        const rightBucket=employerApplicationBucket(right);
        const priority=(employerApplicationPriority[leftBucket]??99)-(employerApplicationPriority[rightBucket]??99);
        if(priority!==0)return priority;
        return Number(right.id||0)-Number(left.id||0);
      });
    }

    const employerApplicationPageSize = 20;
    let employerApplicationVisibleLimit = employerApplicationPageSize;
    // Optional one-at-a-time triage is local to the employer's session. It
    // changes only presentation, never application status or consent.
    let employerApplicationQuickMode = false;
    let employerApplicationQuickSelectedId = null;
    let employerApplicationQuickIndex = 0;
    let employerApplicationQuickCounts = {introduced:0,ready:0,attention:0,consent:0,closed:0};
    let employerApplicationQuickFocusOnRender = false;
    // Completed decisions stay visible in normal lists, but are skipped
    // for the remainder of the current one-by-one review pass.
    const employerApplicationQuickHandledIds = new Set();
    // Count only successful explicit decisions; keep this entirely in memory.
    const employerApplicationQuickDecisions = new Map();
    // Skip is session-only: map ID -> stage for local progress counters.
    const employerApplicationQuickSkipped = new Map();
    const employerQuickStageOrder = ['introduced','ready','attention','consent'];
    const employerQuickStageCalls = {
      introduced:'Завершить знакомства',
      ready:'Продолжить знакомства',
      attention:'Разобрать новые отклики',
      consent:'Посмотреть ожидающие ответы'
    };
    function employerQuickRecommendedStage(current = 'all') {
      return employerQuickStageOrder.find(stage =>
        stage !== current && Number(employerApplicationQuickCounts[stage] || 0) > 0
      ) || '';
    }

    function focusEmployerQuickCard() {
      const card = document.querySelector('#employer-application-results .application-review-card:not([hidden])');
      if (!card) {
        (document.querySelector('[data-v02-action="employer-quick-stage"]:not([hidden])')
          || document.querySelector('[data-v02-action="employer-quick-revisit"]:not([hidden])')
          || document.querySelector('[data-v02-action="employer-quick-toggle"]'))?.focus({preventScroll:true});
        return;
      }
      card.tabIndex = -1;
      card.focus({preventScroll:true});
      card.scrollIntoView({block:'nearest'});
    }

    function employerQuickNextAfterAction(currentId) {
      const query = String(state.employerApplicationsQuery || '').trim().toLocaleLowerCase('ru-RU');
      const cards = Array.from(document.querySelectorAll('#employer-application-results .application-review-card'))
        .filter(card => {
          const id = Number(card.dataset.applicationId);
          return id > 0 && !employerApplicationQuickHandledIds.has(id) &&
            !employerApplicationQuickSkipped.has(id) &&
            (!query || String(card.dataset.applicationSearch || '').toLocaleLowerCase('ru-RU').includes(query));
        });
      const index = cards.findIndex(card => Number(card.dataset.applicationId) === currentId);
      const next = cards.slice(Math.max(0,index + 1)).find(card => Number(card.dataset.applicationId) !== currentId)
        || cards.find(card => Number(card.dataset.applicationId) !== currentId);
      return next ? Number(next.dataset.applicationId) : null;
    }

    async function openEmployerApplications(filter, vacancyId, applicationId, startQuickReview = false) {
      if (state.user?.role !== 'employer' || !mayLeaveEditor()) return;
      const ownerId = state.user.id;
      const targetVacancy = navigationId(vacancyId);
      const targetApplication = navigationId(applicationId);
      state.employerApplicationsTargetId = targetApplication;
      state.employerApplicationsVacancyFilter = targetVacancy ? String(targetVacancy) : 'all';
      state.employerApplicationsStatusFilter = Object.hasOwn(employerApplicationFilterLabels, filter)
        ? filter : 'all';
      state.employerApplicationsQuery = '';
      employerApplicationVisibleLimit = employerApplicationPageSize;
      if (startQuickReview) {
        employerApplicationQuickMode = true;
        employerApplicationQuickHandledIds.clear();
        employerApplicationQuickDecisions.clear();
        employerApplicationQuickSkipped.clear();
        employerApplicationQuickSelectedId = targetApplication || null;
        employerApplicationQuickIndex = 0;
        employerApplicationQuickFocusOnRender = true;
      }
      state.tab = 'applications';
      state.activeVacancy = null;
      await showDashboard();
      if (state.user?.id === ownerId && state.tab === 'applications' && !startQuickReview) {
        const card = targetApplication
          ? document.querySelector('#employer-application-results .application-review-card[data-application-id="' + targetApplication + '"]')
          : null;
        if (card && !card.hidden) {
          card.tabIndex = -1;
          card.focus({preventScroll:true});
          card.scrollIntoView({block:'nearest'});
        } else {
          focusApplicationDestination('#dashboard-main h3');
        }
      }
      state.employerApplicationsTargetId = null;
    }

    function applyEmployerApplicationsSearch() {
      const list = document.querySelector('#employer-application-results');
      if (!list) return;
      const query = String(state.employerApplicationsQuery || '').trim().toLocaleLowerCase('ru-RU');
      const cards = Array.from(list.querySelectorAll('.application-review-card'));
      const matches = cards.filter(card =>
        (!query || String(card.dataset.applicationSearch || '').toLocaleLowerCase('ru-RU').includes(query)) &&
        (!employerApplicationQuickMode || (!employerApplicationQuickHandledIds.has(Number(card.dataset.applicationId)) &&
          !employerApplicationQuickSkipped.has(Number(card.dataset.applicationId))))
      );
      const matched = matches.length;
      // Remaining includes skipped matches, since skipping isn't a decision.
      // The cards are already scoped to the chosen vacancy and stage.
      const remaining = employerApplicationQuickMode
        ? cards.filter(card => {
            const id = Number(card.dataset.applicationId);
            return (!query || String(card.dataset.applicationSearch || '').toLocaleLowerCase('ru-RU').includes(query)) &&
              !employerApplicationQuickHandledIds.has(id);
          }).length
        : 0;
      let visible = 0;
      if (employerApplicationQuickMode) {
        const savedIndex = matches.findIndex(card =>
          Number(card.dataset.applicationId) === employerApplicationQuickSelectedId
        );
        employerApplicationQuickIndex = savedIndex >= 0
          ? savedIndex : Math.min(Math.max(0, employerApplicationQuickIndex), Math.max(0, matched - 1));
        const selected = matches[employerApplicationQuickIndex] || null;
        employerApplicationQuickSelectedId = selected ? Number(selected.dataset.applicationId) : null;
        for (const card of cards) card.hidden = card !== selected;
        visible = selected ? 1 : 0;
      } else {
        let matchingPosition = 0;
        for (const card of cards) {
          const found = !query || String(card.dataset.applicationSearch || '').toLocaleLowerCase('ru-RU').includes(query);
          if (found) matchingPosition += 1;
          card.hidden = !found || matchingPosition > employerApplicationVisibleLimit;
          if (!card.hidden) visible += 1;
        }
      }
      const count = document.querySelector('#employer-application-visible-count');
      if (count) count.textContent = String(visible);
      const total = document.querySelector('#employer-application-matched-count');
      if (total) total.textContent = String(matched);
      const empty = document.querySelector('#employer-application-search-empty');
      if (empty) empty.hidden = employerApplicationQuickMode || matched !== 0 || cards.length === 0 || !query;
      const pager = document.querySelector('#employer-application-pagination');
      if (pager) {
        pager.hidden = employerApplicationQuickMode || visible >= matched;
        const remaining = pager.querySelector('[data-employer-application-remaining]');
        if (remaining) remaining.textContent = String(Math.min(employerApplicationPageSize,matched-visible));
      }
      const toggle = document.querySelector('[data-v02-action="employer-quick-toggle"]');
      if (toggle) {
        toggle.setAttribute('aria-pressed', String(employerApplicationQuickMode));
        toggle.textContent = employerApplicationQuickMode ? 'Вернуться к списку откликов' : 'Разбирать по одному';
        toggle.disabled = !employerApplicationQuickMode && !matched;
      }
      const controls = document.querySelector('#employer-application-quick-controls');
      if (controls) controls.hidden = !employerApplicationQuickMode;
      const handledCount = document.querySelector('#employer-application-quick-handled');
      if (handledCount) handledCount.textContent = 'Обработано за проход: ' + employerApplicationQuickHandledIds.size;
      const reviewSummary = document.querySelector('#employer-quick-review-summary');
      if (reviewSummary) {
        const requestCount = [...employerApplicationQuickDecisions.values()]
          .filter(decision => decision === 'interest-created').length;
        const refusalCount = [...employerApplicationQuickDecisions.values()]
          .filter(decision => decision === 'rejected').length;
        const stats = {
          processed: employerApplicationQuickHandledIds.size,
          requests: requestCount,
          refusals: refusalCount,
          remaining
        };
        for (const [key,value] of Object.entries(stats)) {
          const count = reviewSummary.querySelector('[data-quick-summary="' + key + '"]');
          if (count) count.textContent = String(value);
        }
      }
      const skippedCount = document.querySelector('#employer-application-quick-skipped');
      if (skippedCount) skippedCount.textContent = 'Пропущено: ' + employerApplicationQuickSkipped.size;
      const skipButton = document.querySelector('[data-v02-action="employer-quick-skip"]');
      if (skipButton) skipButton.disabled = !employerApplicationQuickMode || !matched;
      const revisitButton = document.querySelector('[data-v02-action="employer-quick-revisit"]');
      if (revisitButton) {
        revisitButton.hidden = !employerApplicationQuickMode || !employerApplicationQuickSkipped.size;
        revisitButton.textContent = 'Вернуться к пропущенным (' + employerApplicationQuickSkipped.size + ')';
      }
      const position = document.querySelector('#employer-application-quick-position');
      if (position) position.textContent = !matched
        ? (employerApplicationQuickMode && employerApplicationQuickSkipped.size
            ? 'Других откликов по выбранным условиям нет. Можно вернуться к пропущенным.'
            : query ? 'По запросу откликов нет. Очистите поиск, чтобы продолжить.'
            : 'На этом этапе откликов больше нет.')
        : 'Отклик ' + (employerApplicationQuickIndex + 1) + ' из ' + matched;
      const nextStage = document.querySelector('[data-v02-action="employer-quick-stage"]');
      if (nextStage) {
        const stage = !query && employerApplicationQuickMode && !matched
          ? employerQuickRecommendedStage(state.employerApplicationsStatusFilter || 'all') : '';
        nextStage.hidden = !stage;
        nextStage.disabled = !stage;
        nextStage.dataset.stage = stage;
        if (stage) nextStage.textContent = employerQuickStageCalls[stage] +
          ' (' + Number(employerApplicationQuickCounts[stage]) + ') →';
      }
      const complete = document.querySelector('#employer-application-quick-complete');
      const hasOtherStages = Boolean(employerQuickRecommendedStage(state.employerApplicationsStatusFilter || 'all'));
      const showComplete = employerApplicationQuickMode && !matched && !query && !hasOtherStages && !employerApplicationQuickSkipped.size;
      if (complete) complete.hidden = !showComplete;
      const continuation = document.querySelector('.employer-quick-next-stage');
      if (continuation) continuation.hidden = !showComplete && (!nextStage || nextStage.hidden);
      const previous = document.querySelector('[data-v02-action="employer-quick-previous"]');
      if (previous) previous.disabled = !employerApplicationQuickMode || employerApplicationQuickIndex === 0 || !matched;
      const next = document.querySelector('[data-v02-action="employer-quick-next"]');
      if (next) next.disabled = !employerApplicationQuickMode || !matched || employerApplicationQuickIndex >= matched - 1;
    }

    renderEmployer = async function() {
      if(state.tab!=='applications'){
        employerApplicationVisibleLimit = employerApplicationPageSize;
        employerApplicationQuickMode = false;
        employerApplicationQuickSelectedId = null;
        employerApplicationQuickIndex = 0;
        employerApplicationQuickHandledIds.clear();
        employerApplicationQuickDecisions.clear();
        employerApplicationQuickSkipped.clear();
        employerApplicationQuickFocusOnRender = false;
        await oldEmployer();
        return;
      }
      const nav=[{id:'overview',label:'Обзор'},{id:'company',label:'Компания'},{id:'vacancies',label:'Мои вакансии'},{id:'create',label:'Новая вакансия'},{id:'applications',label:'Отклики'},{id:'invitations',label:'Знакомства и контакты'},{id:'security',label:'Безопасность'}];
      $('#account-content').innerHTML=`<div class="dashboard-grid">${tabsMarkup(nav,'ДЛЯ КОМПАНИИ',state.user.company?.company_name||'Работодатель')}<div id="dashboard-main"></div></div>`;
      try {
        const {applications}=await api('/api/employer/applications');
        const {jobs}=await api('/api/employer/vacancies');
        const selectedVacancy = state.employerApplicationsVacancyFilter || 'all';
        const selectedStatus = Object.hasOwn(employerApplicationFilterLabels,state.employerApplicationsStatusFilter)
          ? state.employerApplicationsStatusFilter
          : 'all';
        state.employerApplicationsStatusFilter = selectedStatus;
        const vacancyScoped = sortEmployerApplications(
          selectedVacancy === 'all'
            ? applications
            : applications.filter(a => String(a.vacancy_id) === selectedVacancy)
        );
        const bucketCounts = vacancyScoped.reduce((counts,item)=>{
          const bucket=employerApplicationBucket(item);
          counts[bucket]=(counts[bucket]||0)+1;
          return counts;
        },{attention:0,consent:0,ready:0,introduced:0,closed:0});
        const shown = selectedStatus === 'all'
          ? vacancyScoped
          : vacancyScoped.filter(item => employerApplicationBucket(item) === selectedStatus);
        // An overview work item can be past the first 20 applications.
        // Move only that existing record to the front; never change its status.
        const pinnedId = navigationId(state.employerApplicationsTargetId);
        const pinnedIndex = pinnedId
          ? shown.findIndex(item => Number(item.id) === pinnedId) : -1;
        if (pinnedIndex > 0) shown.unshift(shown.splice(pinnedIndex, 1)[0]);
        employerApplicationQuickCounts = employerApplicationQuickMode
          ? vacancyScoped.filter(item => !employerApplicationQuickHandledIds.has(Number(item.id)) &&
              !employerApplicationQuickSkipped.has(Number(item.id)))
              .reduce((counts,item) => {
                const bucket = employerApplicationBucket(item);
                counts[bucket] = (counts[bucket] || 0) + 1;
                return counts;
              }, {attention:0,consent:0,ready:0,introduced:0,closed:0})
          : {...bucketCounts};
        const nextQueue = ['introduced','ready','attention'].find(stage => bucketCounts[stage] > 0);
        const queueCopy = {
          introduced: ['Нужно завершить знакомство', 'Контакты открыты с согласия кандидата. Зафиксируйте результат общения.'],
          ready: ['Кандидат дал согласие', 'Перейдите к согласованному знакомству — контакты доступны по его разрешению.'],
          attention: ['Есть отклики для рассмотрения', 'Сравните опыт специалистов, затем примите решение о следующем шаге.'],
          consent: ['Ждём решения кандидата', 'Запрос на знакомство уже отправлен. Повторно отправлять его не нужно.'],
          closed: ['Новых действий нет', 'Все текущие отклики завершены. Можно вернуться к подбору по вакансиям.']
        };
        const queueStage = nextQueue || (bucketCounts.consent ? 'consent' : 'closed');
        const [queueTitle,queueDescription] = queueCopy[queueStage];
        const queueNext = nextQueue && selectedStatus !== nextQueue
          ? `<button type="button" class="btn btn-primary btn-tiny" data-v02-action="employer-application-priority" data-filter="${nextQueue}">Показать нужные отклики →</button>`
          : '';
        const queueGuide = vacancyScoped.length
          ? `<div class="employer-applications-guide" role="note"><div><span>ВАШ СЛЕДУЮЩИЙ ШАГ</span><strong>${esc(queueTitle)}</strong><p>${esc(queueDescription)}</p></div>${queueNext}</div>`
          : '';
        const options = jobs.map(j => `<option value="${Number(j.id)}" ${String(j.id) === selectedVacancy ? 'selected' : ''}>${esc(j.title)}</option>`).join('');
        const selector = `<div class="field"><label for="employer-applications-vacancy">Вакансия</label><select id="employer-applications-vacancy"><option value="all">Все вакансии</option>${options}</select></div>`;
        const filterButtons = [
          ['all',vacancyScoped.length],
          ['attention',bucketCounts.attention],
          ['consent',bucketCounts.consent],
          ['ready',bucketCounts.ready],
          ['introduced',bucketCounts.introduced],
          ['closed',bucketCounts.closed]
        ].map(([value,count]) => `<button type="button" class="btn btn-tiny ${selectedStatus===value?'btn-dark':'btn-outline'}" data-v02-action="employer-application-filter" data-filter="${value}" aria-pressed="${selectedStatus===value}">${esc(employerApplicationFilterLabels[value])} · ${Number(count)}</button>`).join('');
        const emptyFiltered = vacancyScoped.length
          ? `<div class="empty-state empty-state-action"><span class="empty-state-icon" aria-hidden="true">⌕</span><strong>В этом этапе откликов нет</strong><p>Попробуйте другой этап или сбросьте фильтры, чтобы увидеть всю воронку.</p><button class="btn btn-outline" data-v02-action="reset-application-filters">Сбросить фильтры</button></div>`
          : '<div class="empty-state empty-state-action"><span class="empty-state-icon" aria-hidden="true">＋</span><strong>Откликов пока нет</strong><p>Можно не ждать: запустите подбор и пригласите подходящих специалистов сами.</p><button class="btn btn-primary" data-tab="vacancies">Перейти к вакансиям →</button></div>';
        $('#dashboard-main').innerHTML=`<div class="panel employer-applications-panel">
          <div class="split-header"><div><span class="section-kicker">ОТКЛИКИ</span><h3>Отклики соискателей</h3><p class="muted">Сначала оценивайте опыт и навыки. Имя, телефон и email остаются скрытыми до отдельного согласия кандидата.</p></div><details class="employer-application-flow-details"><summary>Как проходит знакомство</summary><div class="application-flow-legend" aria-label="Этапы обработки отклика"><span>1. Отклик</span><b>→</b><span>2. Рассмотрение</span><b>→</b><span>3. Согласие</span><b>→</b><span>4. Знакомство</span><b>→</b><span>5. Итог</span></div></details></div>
          ${queueGuide}
          <div class="employer-application-toolbar"><div class="employer-application-vacancy-filter">${selector}</div><div class="employer-application-stage-filter" role="group" aria-label="Фильтр откликов по этапу">${filterButtons}</div></div>
          <div class="employer-application-search"><label for="employer-application-search">Поиск по профессии, вакансии, городу и навыкам</label><div class="employer-application-search-row"><input type="search" id="employer-application-search" data-employer-application-search autocomplete="off" placeholder="Например, бухгалтер или Excel" value="${esc(state.employerApplicationsQuery||'')}"><button class="btn btn-outline btn-tiny" type="button" data-v02-action="clear-employer-application-search">Очистить поиск</button></div></div>
          <div class="employer-application-result-line"><span role="status" aria-live="polite">Показываем <strong id="employer-application-visible-count">${shown.length}</strong> из <strong id="employer-application-matched-count">${shown.length}</strong> по текущему этапу (всего по вакансии: ${vacancyScoped.length})${selectedStatus==='all'&&vacancyScoped.length>1?' · сначала этапы, где нужен ваш следующий шаг':''}</span>${selectedVacancy!=='all'||selectedStatus!=='all'?'<button type="button" class="link-button" data-v02-action="reset-application-filters">Сбросить фильтры</button>':''}</div>
          <div class="employer-quick-toolbar" aria-label="Быстрый разбор откликов">
            <button type="button" class="btn btn-outline" data-v02-action="employer-quick-toggle" aria-pressed="false">Разбирать по одному</button>
            <div class="employer-quick-controls" id="employer-application-quick-controls" hidden>
              <span id="employer-application-quick-position" role="status" aria-live="polite"></span>
              <span class="employer-quick-handled muted" id="employer-application-quick-handled"></span>
              <span class="employer-quick-skipped muted" id="employer-application-quick-skipped"></span>
              <div class="employer-quick-summary" id="employer-quick-review-summary" role="group" aria-label="Сводка текущего прохода">
                <span><strong data-quick-summary="processed">0</strong><small>Обработано</small></span>
                <span><strong data-quick-summary="requests">0</strong><small>Запросов на знакомство</small></span>
                <span><strong data-quick-summary="refusals">0</strong><small>Отказов</small></span>
                <span><strong data-quick-summary="remaining">0</strong><small>Осталось по фильтру</small></span>
              </div>
              <p class="employer-quick-summary-note">Учитываются подтверждённые действия этого прохода. Запрос на знакомство ещё не означает согласия кандидата. В остатке учтены пропущенные анкеты.</p>
              <div class="employer-quick-navigation">
                <button type="button" class="btn btn-outline" data-v02-action="employer-quick-previous">← Предыдущий</button>
                <button type="button" class="btn btn-dark" data-v02-action="employer-quick-next">Следующий →</button>
                <button type="button" class="btn btn-outline" data-v02-action="employer-quick-skip" title="Пропуск не меняет статус отклика">Пропустить пока →</button>
              </div>
              <div class="employer-quick-revisit"><button type="button" class="btn btn-outline" data-v02-action="employer-quick-revisit" hidden>Вернуться к пропущенным</button><span class="muted">Пропуск действует только в текущем проходе и не меняет статус отклика.</span></div>
              <div class="employer-quick-next-stage" aria-label="Продолжить обработку">
                <button type="button" class="btn btn-primary" data-v02-action="employer-quick-stage" hidden></button>
                <p id="employer-application-quick-complete" hidden>Все активные этапы разобраны. Новые отклики появятся здесь, когда кандидаты откликнутся или ответят на запрос.</p>
              </div>
            </div>
          </div>
          <div class="dashboard-list" id="employer-application-results">${shown.length?shown.map(a=>`<article class="item-card application-review-card" data-application-id="${Number(a.id)}" data-application-bucket="${esc(employerApplicationBucket(a))}" data-application-search="${esc([a.profession,a.title,a.city,a.skills].join(' '))}"><header><div><h4>${esc(a.profession)}</h4><p>${esc(a.title)} · ${esc(a.city)} · ${esc(candidateSalaryText(a.expected_salary))}</p></div><span class="mini-badge">${esc(employerApplicationStageLabel(a))}</span></header>${interactionStageMarkup(a,'application')}<div class="application-profile-strip is-compact"><span><small>Навыки</small><strong>${esc(a.skills||'Не указаны')}</strong></span></div><details class="candidate-resume-details"><summary>Профессиональное резюме</summary>${professionalResumeMarkup(a)}</details>${activityTimelineMarkup(a)}${employerIntroBadge(a)}${['applied','reviewing','interview'].includes(a.status) && !a.invitation_id?`<div class="application-next-action"><span>Следующее действие</span><strong>${a.status==='applied'?'Проверьте профиль и переведите в рассмотрение':'Решите, хотите ли начать знакомство'}</strong></div><div class="item-actions">${a.status==='applied'?`<button class="btn btn-outline btn-tiny" data-v02-action="application-status" data-id="${Number(a.id)}" data-status="reviewing">Взять в рассмотрение</button>`:''}<button class="btn btn-primary btn-tiny" data-v02-action="express-interest" data-id="${Number(a.id)}">Запросить согласие на знакомство →</button><button class="btn btn-outline btn-tiny" data-v02-action="application-status" data-id="${Number(a.id)}" data-status="rejected">Отказать</button></div>`:''}</article>`).join(''):emptyFiltered}</div>
          <div id="employer-application-pagination" class="employer-application-pagination" hidden><button type="button" class="btn btn-outline" data-v02-action="more-employer-applications">Показать следующие <span data-employer-application-remaining>20</span> откликов</button></div>
          <div class="empty-state" id="employer-application-search-empty" hidden><strong>По вашему запросу откликов нет</strong><p>Попробуйте другую профессию, навык или город.</p><button type="button" class="btn btn-outline" data-v02-action="clear-employer-application-search">Очистить поиск</button></div>
        </div>`;
        applyEmployerApplicationsSearch();
        if (employerApplicationQuickMode && employerApplicationQuickFocusOnRender) {
          employerApplicationQuickFocusOnRender = false;
          focusEmployerQuickCard();
        }
      } catch(e) { $('#dashboard-main').textContent=e.message;toast(e.message,true); }
    };

    let adminSafetyFilter = 'new';
    let adminTaxonomyFilter = 'pending';
    const reportReasonLabels = {
      misleading:'Недостоверная информация',
      discrimination:'Дискриминационные требования',
      fraud:'Подозрение на мошенничество',
      contacts:'Обход безопасного знакомства',
      other:'Другая проблема'
    };
    const reportStatusLabels = {
      new:'Новая',
      reviewed:'В работе',
      dismissed:'Отклонена',
      actioned:'Меры приняты'
    };
    function moderationLabel(status){
      return status==='pending'?'На проверке':status==='rejected'?'Отклонена':'Одобрена';
    }

    renderAdmin = async function(){
      await oldAdmin();
      $('#account-content').insertAdjacentHTML('beforeend','<div class="panel admin-v02"><div class="item-actions"><button class="btn btn-outline" data-v02-action="admin-users">Пользователи</button><button class="btn btn-outline" data-v02-action="admin-jobs">Вакансии</button><button class="btn btn-outline" data-v02-action="admin-reports">Центр безопасности</button><button class="btn btn-outline" data-v02-action="admin-security">Безопасность</button><button class="btn btn-outline" data-v02-action="admin-taxonomy">Словарь</button><button class="btn btn-outline" data-v02-action="admin-mail">Почтовые события</button></div><div id="admin-v02-results"></div></div>');
    };

    async function adminView(kind){
      const root=$('#admin-v02-results');
      root.textContent='Загрузка...';
      if(kind==='users'){
        const {users}=await api('/api/admin/users');
        root.innerHTML='<h3>Пользователи и работодатели</h3><div class="dashboard-list">'+users.map(u=>`<article class="item-card admin-user-card"><header><div><h4>${esc(u.role==='employer' && u.company_name ? u.company_name : u.name)}</h4><p>${esc(u.email)} · ${esc(u.role)}</p></div><span class="mini-badge ${u.status==='active'?'':'gray'}">${u.status==='active'?'Активен':'Заблокирован'}</span></header>${u.role==='employer'?`<div class="admin-trust-row"><span class="${u.email_verified?'is-ok':'is-pending'}">${u.email_verified?'✓ Email':'Email не подтверждён'}</span><span class="${u.inn?'is-ok':'is-pending'}">${u.inn?'ИНН '+esc(u.inn):'ИНН не указан'}</span><span class="${u.employer_verified?'is-ok':'is-pending'}">${u.employer_verified?'✓ Компания проверена':'Не проверена'}</span></div><div class="item-actions"><button class="btn ${u.employer_verified?'btn-outline':'btn-primary'} btn-tiny" data-v02-action="admin-employer-verification" data-id="${Number(u.id)}" data-verified="${u.employer_verified?'false':'true'}" ${!u.employer_verified&&(!u.email_verified||!u.inn)?'disabled title="Нужны подтверждённый email и ИНН"':''}>${u.employer_verified?'Снять проверку':'Проверить компанию'}</button></div>`:''}${u.role==='admin'?'':`<div class="item-actions"><button class="btn btn-outline btn-tiny" data-v02-action="admin-user-status" data-id="${Number(u.id)}" data-status="${u.status==='active'?'disabled':'active'}">${u.status==='active'?'Заблокировать':'Разблокировать'}</button></div>`}</article>`).join('')+'</div>';
      } else if(kind==='jobs'){
        const {jobs}=await api('/api/admin/vacancies');
        root.innerHTML='<div class="split-header"><div><span class="section-kicker">ВАКАНСИИ</span><h3>Вакансии</h3><p class="muted">Публикация и операционный статус. Проверку жалоб проводите в Центре безопасности.</p></div><button class="btn btn-primary btn-tiny" data-v02-action="admin-reports">Центр безопасности →</button></div><div class="dashboard-list">'+jobs.map(j=>`<article class="item-card"><header><div><h4>${esc(j.title)}</h4><p>${esc(j.company_name)} · ${esc(j.city)}</p><div class="admin-moderation-inline ${esc(j.moderation_status)}"><strong>${moderationLabel(j.moderation_status)}</strong>${j.active_reports?'<span>Активных жалоб: '+Number(j.active_reports)+'</span>':''}</div></div><span class="mini-badge">${j.status==='open'?'Открыта':'Закрыта'}</span></header><div class="item-actions"><button class="btn btn-outline btn-tiny" data-v02-action="admin-job-status" data-id="${Number(j.id)}" data-status="${j.status==='open'?'closed':'open'}">${j.status==='open'?'Закрыть':'Открыть'}</button>${j.moderation_status!=='approved'?'<button class="btn btn-outline btn-tiny" data-v02-action="admin-reports">Проверить →</button>':''}</div></article>`).join('')+'</div>';
      } else if(kind==='reports'){
        const [{reports},{jobs}] = await Promise.all([api('/api/admin/reports'),api('/api/admin/vacancies')]);
        const newReports=reports.filter(r=>r.status==='new');
        const reviewReports=reports.filter(r=>r.status==='reviewed');
        const resolvedReports=reports.filter(r=>['dismissed','actioned'].includes(r.status));
        const pendingJobs=jobs.filter(j=>j.moderation_status==='pending');
        const rejectedJobs=jobs.filter(j=>j.moderation_status==='rejected');
        const filter=adminSafetyFilter;
        const filterButtons=[
          ['new','Новые',newReports.length],
          ['pending','На проверке',pendingJobs.length],
          ['reviewed','В работе',reviewReports.length],
          ['resolved','Обработано',resolvedReports.length],
          ['all','Все',reports.length]
        ];
        const visibleReports=filter==='new'?newReports:filter==='reviewed'?reviewReports:filter==='resolved'?resolvedReports:filter==='all'?reports:[];
        let content='';
        if(filter==='pending'){
          content=pendingJobs.length?pendingJobs.map(j=>`<article class="item-card safety-vacancy-card"><header><div><span class="card-eyebrow">ТРЕБУЕТ РЕШЕНИЯ</span><h4>${esc(j.title)}</h4><p>${esc(j.company_name)} · ${esc(j.city)} · жалоб: ${Number(j.active_reports||0)}</p></div><span class="mini-badge warning">На проверке</span></header>${j.moderation_reason?`<div class="safety-reason-note">${esc(j.moderation_reason)}</div>`:''}<div class="field"><label for="moderation-reason-${Number(j.id)}">Причина отклонения, если решите снять вакансию</label><textarea id="moderation-reason-${Number(j.id)}" data-moderation-reason="${Number(j.id)}" rows="3" maxlength="500" placeholder="Например: условия не соответствуют тексту объявления"></textarea></div><div class="item-actions"><button class="btn btn-primary btn-tiny" data-v02-action="admin-moderation" data-id="${Number(j.id)}" data-status="approved">Одобрить и вернуть в поиск</button><button class="btn btn-danger btn-tiny" data-v02-action="admin-moderation" data-id="${Number(j.id)}" data-status="rejected">Отклонить вакансию</button></div></article>`).join(''):'<div class="empty-state"><strong>Нет вакансий, ожидающих проверки.</strong><p>Здесь появятся вакансии, временно скрытые после сигналов пользователей или решения модератора.</p></div>';
        }else{
          content=visibleReports.length?visibleReports.map(r=>`<article class="item-card safety-report-card"><header><div><span class="card-eyebrow">${r.target_type==='employer'?'РАБОТОДАТЕЛЬ':'ВАКАНСИЯ'}</span><h4>${esc(r.title)}</h4><p>${esc(r.company_name)} · ${esc(reportReasonLabels[r.reason]||r.reason)}</p></div><span class="mini-badge ${r.status==='new'?'warning':r.status==='actioned'?'':'gray'}">${esc(reportStatusLabels[r.status]||r.status)}</span></header>${r.details?`<div class="safety-report-text">${esc(r.details)}</div>`:''}<div class="safety-report-meta">Получено: ${esc(r.created_at||'—')}</div>${['new','reviewed'].includes(r.status)?`<div class="item-actions">${r.status==='new'?'<button class="btn btn-outline btn-tiny" data-v02-action="admin-report-status" data-key="'+esc(r.report_key)+'" data-status="reviewed">Взять в работу</button>':''}<button class="btn btn-outline btn-tiny" data-v02-action="admin-report-status" data-key="${esc(r.report_key)}" data-status="dismissed">Не подтверждено</button><button class="btn btn-primary btn-tiny" data-v02-action="admin-report-status" data-key="${esc(r.report_key)}" data-status="actioned">Меры приняты</button></div>`:''}</article>`).join(''):'<div class="empty-state"><strong>В этой очереди пока пусто.</strong><p>Переключите фильтр выше, чтобы посмотреть другие обращения.</p></div>';
        }
        root.innerHTML=`<div class="safety-center"><div class="split-header"><div><span class="section-kicker">БЕЗОПАСНОСТЬ И МОДЕРАЦИЯ</span><h3>Центр безопасности</h3><p class="muted">Разбирайте сигналы пользователей и возвращайте в поиск только проверенные вакансии.</p></div></div><div class="safety-summary"><button data-v02-action="admin-safety-filter" data-filter="new"><strong>${newReports.length}</strong><span>Новые жалобы</span></button><button data-v02-action="admin-safety-filter" data-filter="pending"><strong>${pendingJobs.length}</strong><span>Вакансии на проверке</span></button><button data-v02-action="admin-safety-filter" data-filter="reviewed"><strong>${reviewReports.length}</strong><span>В работе</span></button><div><strong>${resolvedReports.length}</strong><span>Обработано</span></div></div><div class="safety-filter-row">${filterButtons.map(([value,label,count])=>`<button class="btn btn-tiny ${filter===value?'btn-dark':'btn-outline'}" data-v02-action="admin-safety-filter" data-filter="${value}">${label} · ${count}</button>`).join('')}</div><div class="dashboard-list safety-list">${content}</div>${rejectedJobs.length?`<div class="safety-footnote">Отклонённых вакансий вне активной очереди: <strong>${rejectedJobs.length}</strong></div>`:''}</div>`;
      } else if(kind==='security'){
        const [{events},{admin_mfa_mode,admin_mfa_enabled,admin_session_minutes,password_hash,secure_cookie,production_runtime,api_docs_enabled}] = await Promise.all([
          api('/api/admin/security-events'),
          api('/api/admin/security-status')
        ]);
        const labels={
          login_success:'Успешный вход',
          login_password_failed:'Неверный пароль',
          login_password_verified_mfa_required:'Пароль подтверждён · требуется 2FA',
          login_blocked_disabled_account:'Попытка входа в заблокированный аккаунт',
          admin_mfa_challenge_issued:'Отправлен код 2FA',
          admin_mfa_failed:'Неверный код 2FA',
          admin_mfa_success:'2FA подтверждена',
          admin_mfa_expired:'Код 2FA истёк',
          password_reset_completed:'Пароль изменён через восстановление'
        };
        const rows=events.length?events.map(event=>`<article class="security-event-row"><div><strong>${esc(labels[event.event_type]||event.event_type)}</strong><small>${esc(event.user_email||'Системное событие')}${event.detail?' · '+esc(event.detail):''}</small></div><time>${esc(event.created_at||'')}</time></article>`).join(''):'<div class="empty-state"><p>Security-событий пока нет.</p></div>';
        root.innerHTML=`<div class="admin-security-center">
          <div class="split-header"><div><span class="section-kicker">SECURITY</span><h3>Безопасность аккаунтов</h3><p class="muted">Ключевые защитные механизмы и последние события аутентификации.</p></div></div>
          <div class="admin-security-summary">
            <div class="${admin_mfa_enabled?'is-ok':'is-warning'}"><span>2FA администратора</span><strong>${admin_mfa_enabled?'Включена':'Не включена'}</strong><small>${admin_mfa_mode==='email'?'Одноразовый код по email':'Включите OPYT50_ADMIN_MFA_MODE=email после проверки admin email'}</small></div>
            <div class="is-ok"><span>Админ-сессия</span><strong>${Number(admin_session_minutes)} мин</strong><small>Новый вход отзывает предыдущую админ-сессию</small></div>
            <div class="is-ok"><span>Хэш паролей</span><strong>${esc(password_hash)}</strong><small>Старые PBKDF2 автоматически обновляются при входе</small></div>
            <div class="${secure_cookie?'is-ok':'is-warning'}"><span>Session cookie</span><strong>${secure_cookie?'Secure + Strict':'Dev mode'}</strong><small>${production_runtime?'Production runtime':'Локальная/тестовая среда'}</small></div>
            <div class="${api_docs_enabled?'is-warning':'is-ok'}"><span>API docs</span><strong>${api_docs_enabled?'Включены':'Выключены'}</strong><small>В production документация должна быть недоступна</small></div>
          </div>
          ${admin_mfa_enabled?'':`<div class="security-hardening-callout"><strong>Следующий обязательный шаг</strong><p>После того как в админ-аккаунте указан реальный доступный email и SMTP проверен, включите <code>OPYT50_ADMIN_MFA_MODE=email</code>. Пароль без второго фактора больше не создаст админ-сессию.</p></div>`}
          <div class="split-header security-events-title"><div><span class="section-kicker">АУДИТ</span><h3>Последние security-события</h3></div><span class="mini-badge">${events.length}</span></div>
          <div class="security-event-list">${rows}</div>
        </div>`;
      } else if(kind==='taxonomy'){
        const {terms,summary}=await api('/api/admin/taxonomy');
        const filter=adminTaxonomyFilter;
        const visible=terms.filter(term=>filter==='all'||term.status===filter);
        const filterButtons=[
          ['pending','Новые',summary.pending||0],
          ['approved','Добавленные',summary.approved||0],
          ['rejected','Отклонённые',summary.rejected||0],
          ['all','Все',terms.length]
        ];
        const cards=visible.length?visible.map(term=>`<article class="item-card taxonomy-admin-card">
          <header><div><span class="card-eyebrow">${term.kind==='profession'?'ПРОФЕССИЯ':'НАВЫК'}</span><h4>${esc(term.display_value)}</h4><p>В профилях: <strong>${Number(term.candidate_seen||0)}</strong> · В вакансиях: <strong>${Number(term.vacancy_seen||0)}</strong></p></div><span class="mini-badge ${term.status==='pending'?'warning':term.status==='approved'?'':'gray'}">${term.status==='pending'?'Новый':term.status==='approved'?'В подсказках':'Отклонён'}</span></header>
          <div class="taxonomy-admin-note">${term.kind==='profession'
            ? 'Добавление в подсказки не связывает эту профессию с существующей группой и не меняет matching.'
            : 'После подтверждения навык появится в подсказках как самостоятельный термин.'}</div>
          ${term.status==='pending'?`<div class="item-actions"><button class="btn btn-primary btn-tiny" data-v02-action="admin-taxonomy-status" data-key="${esc(term.term_key)}" data-status="approved">Добавить в подсказки</button><button class="btn btn-outline btn-tiny" data-v02-action="admin-taxonomy-status" data-key="${esc(term.term_key)}" data-status="rejected">Не добавлять</button></div>`:''}
        </article>`).join(''):'<div class="empty-state"><strong>В этой очереди пока пусто.</strong><p>Новые формулировки появятся здесь автоматически после заполнения профилей и вакансий.</p></div>';
        root.innerHTML=`<div class="taxonomy-admin-center"><div class="split-header"><div><span class="section-kicker">СЛОВАРЬ</span><h3>Новые профессии и навыки</h3><p class="muted">СТАЖНО собирает только текст терминов и агрегированную частоту. Пользователи и конкретные резюме здесь не показываются.</p></div></div><div class="taxonomy-admin-summary"><div><strong>${summary.pending||0}</strong><span>ждут решения</span></div><div><strong>${summary.approved||0}</strong><span>добавлено</span></div><div><strong>${summary.rejected||0}</strong><span>отклонено</span></div></div><div class="safety-filter-row">${filterButtons.map(([value,label,count])=>`<button class="btn btn-tiny ${filter===value?'btn-dark':'btn-outline'}" data-v02-action="admin-taxonomy-filter" data-filter="${value}">${label} · ${count}</button>`).join('')}</div><div class="dashboard-list">${cards}</div></div>`;
      } else {
        const {messages}=await api('/api/admin/mail-preview');
        root.innerHTML='<h3>Тестовая очередь</h3><p class="muted">Сообщения НЕ отправляются. Секретные ссылки здесь скрыты.</p>'+messages.map(m=>`<p>${esc(m.created_at)} · ${esc(m.event)} · ${esc(m.subject)}</p>`).join('');
      }
    }

    document.addEventListener('input', event => {
      if (!event.target?.matches('[data-employer-application-search]') ||
          state.user?.role !== 'employer' || state.tab !== 'applications') return;
      state.employerApplicationsQuery = event.target.value;
      employerApplicationVisibleLimit = employerApplicationPageSize;
      employerApplicationQuickSelectedId = null;
      employerApplicationQuickIndex = 0;
      applyEmployerApplicationsSearch();
    });

    document.addEventListener('change', event => {
      if (event.target?.id !== 'employer-applications-vacancy') return;
      state.employerApplicationsVacancyFilter = event.target.value;
      employerApplicationVisibleLimit = employerApplicationPageSize;
      employerApplicationQuickSelectedId = null;
      employerApplicationQuickIndex = 0;
      employerApplicationQuickHandledIds.clear();
      employerApplicationQuickDecisions.clear();
      employerApplicationQuickSkipped.clear();
      if (state.user?.role === 'employer' && state.tab === 'applications') {
        renderEmployer().then(() => {
          document.querySelector('#employer-applications-vacancy')?.focus({preventScroll:true});
        }).catch(error => toast(error.message,true));
      }
    });

    async function showJobDetails(id) {

          if($('#company-dialog').open) $('#company-dialog').close();
          const {job}=await api(`/api/jobs/${id}`);
          $('#job-dialog-title').textContent=job.title;
          const skills=String(job.skills||'').split(',').map(x=>x.trim()).filter(Boolean);
          const guestAction = `<p class="job-entry-note">${publicSignupClosed()
            ? 'Регистрация пока закрыта. Отклик доступен соискателям с существующим аккаунтом.'
            : 'Для отклика нужен профиль соискателя. После входа вы вернётесь к этой вакансии.'}</p>
            <button type="button" class="btn btn-primary" data-v02-action="apply" data-id="${Number(job.id)}">Войти и откликнуться</button>
            ${publicSignupClosed() ? '<a class="job-preparation-link" href="/journal/paths/nayti-rabotu">Подготовиться к поиску работы</a>' : ''}`;
          const action = state.user?.role === 'candidate'
            ? jobApplicationAction(Number(job.id), job) + jobApplicationReceipt(Number(job.id), job)
            : !state.user ? guestAction
            : `<span class="job-role-note">Вы вошли как ${state.user.role === 'employer' ? 'работодатель' : 'администратор'}. Отклики доступны только соискателям.</span>`;
          $('#job-dialog-content').innerHTML=`<div class="job-detail-v08">
            <div class="job-detail-company"><span class="section-kicker">ВАКАНСИЯ</span><strong>${esc(job.company_name)}</strong><button class="link-button" type="button" data-v02-action="company" data-id="${Number(job.employer_id)}">О компании</button>${employerTrustBadges(job,true)}</div>
            <div class="job-detail-pay"><small>Оплата</small>${formatPay(job)}</div>
            <div class="job-detail-facts"><span><small>Город</small><strong>${esc(job.city || 'Не указан')}</strong></span><span><small>График</small><strong>${esc(job.schedule || 'Уточняется')}</strong></span><span><small>Занятость</small><strong>${esc(job.employment || 'Уточняется')}</strong></span></div>
            ${skills.length ? `<div class="job-skill-tags">${skills.slice(0,8).map(skill=>`<span>${esc(skill)}</span>`).join('')}</div>` : ''}
            <div class="job-detail-privacy">Ваши контакты не передаются работодателю автоматически. Сначала отправляется отклик, а знакомство проходит только через отдельное согласие.</div>
            <div class="job-detail-action">${action}</div>
            <section class="job-detail-description"><h3>Обязанности и условия</h3><p>${esc(job.description || 'Подробности у работодателя').replace(/\n/g,'<br>')}</p></section>
            <div class="job-employer-trust-note"><strong>О работодателе</strong><p>${job.employer_verified ? 'Компания прошла проверку администратором СТАЖНО по заполненным реквизитам и подтверждённому email.' : job.employer_email_verified && job.employer_inn_provided ? 'Email подтверждён, реквизиты указаны. Статус проверки компании ещё не присвоен.' : job.employer_email_verified ? 'Email работодателя подтверждён. Реквизиты компании пока не указаны или не проверены.' : 'Статус проверки компании пока не подтверждён.'}</p></div>
            <div class="job-safety-actions"><a class="btn btn-outline btn-tiny" href="/vacancies/${Number(job.id)}">Отдельная страница вакансии</a><button class="btn btn-text btn-tiny" type="button" data-v02-action="report" data-id="${Number(job.id)}">Пожаловаться на вакансию или компанию</button></div>
          </div>`;
          $('#job-dialog').showModal();
    }
    // A guest who selected "Откликнуться" returns to this vacancy only
    // after login/profile save. Opening it must never POST an application.
    document.addEventListener('stazhno:resume-vacancy', event => {
      const id = Number(event.detail?.id);
      if (!Number.isSafeInteger(id) || id <= 0) return;
      showJobDetails(id).catch(error => toast(error.message, true));
    });
    // Opening a shared vacancy never submits an application. A guest must
    // still choose to sign in and click the explicit application action.
    document.addEventListener('stazhno:ready', () => {
      const url = new URL(location.href);
      const linkedVacancyId = Number(url.searchParams.get('vacancy'));
      if (Number.isSafeInteger(linkedVacancyId) && linkedVacancyId > 0) {
        // Consume the deep link once, preserving other query parameters.
        // A refresh or subsequent login must not reopen a dismissed dialog.
        url.searchParams.delete('vacancy');
        history.replaceState(null, '', url.pathname + url.search + url.hash);
        showJobDetails(linkedVacancyId).catch(error => toast(error.message, true));
      }
    }, {once:true});

    const pendingEmployerReviewRequests = new Set();
    const pendingCandidateWithdrawals = new Set();
    document.addEventListener('click',async(event)=>{
      const btn=event.target.closest('[data-v02-action]');
      if(!btn)return;
      const type=btn.dataset.v02Action,id=Number(btn.dataset.id);
      if (type === 'reset-public-job-filters') {
        event.preventDefault();
        $('#jobs-reset').click();
        return;
      }
      if (type === 'retry-public-jobs') {
        event.preventDefault();
        await loadPublicJobs();
        return;
      }
      if (type === 'remove-public-job-filter') {
        event.preventDefault();
        const allowed = ['profession-filter','city-filter','salary-filter','schedule-filter','employment-filter','sort-filter'];
        const fieldId = btn.dataset.filterId;
        if (!allowed.includes(fieldId)) return;
        const field = document.getElementById(fieldId);
        if (!field) return;
        field.value = fieldId === 'sort-filter' ? 'recent' : '';
        field.dispatchEvent(new Event('input',{bubbles:true}));
        await loadPublicJobs();
        field.focus({preventScroll:true});
        return;
      }
      if (btn.disabled) return;
      if (type==='application-status' && btn.dataset.status==='rejected' &&
          !window.confirm('Отказать по этому отклику? Кандидат увидит ваш отказ.')) return;
      if (type==='withdraw' &&
          !window.confirm('Отозвать отклик на вакансию? Работодатель увидит изменение статуса.')) return;
      const tracksCandidateWithdrawal = type==='withdraw' && state.user?.role==='candidate' &&
        Number.isSafeInteger(id) && id>0;
      if (tracksCandidateWithdrawal && pendingCandidateWithdrawals.has(id)) return;
      if (tracksCandidateWithdrawal) pendingCandidateWithdrawals.add(id);
      const tracksEmployerReview = ['application-status','express-interest'].includes(type) &&
        state.user?.role === 'employer' && Number.isSafeInteger(id) && id > 0;
      if (tracksEmployerReview && pendingEmployerReviewRequests.has(id)) return;
      if (tracksEmployerReview) pendingEmployerReviewRequests.add(id);
      const reviewCard = tracksEmployerReview ? btn.closest('.application-review-card') : null;
      const reviewActions = reviewCard ? Array.from(reviewCard.querySelectorAll('[data-v02-action="application-status"],[data-v02-action="express-interest"]')) : [];
      for (const action of reviewActions) {
        action.disabled = true;
        action.setAttribute('aria-busy','true');
      }
      const tracksApplication = (type==='apply' || type==='reapply') &&
        state.user?.role==='candidate' && Number.isSafeInteger(id) && id>0;
      if (tracksApplication && pendingApplicationRequests.has(id)) return;
      if (tracksApplication) pendingApplicationRequests.add(id);
      btn.disabled=true;
      if (tracksApplication) setApplicationPending(id, true);
      try{
        if(type==='details'){
          await showJobDetails(id);
        }else if(type==='company'){
  const result=await api('/api/companies/'+id);
  const c=result.company, jobs=result.jobs||[];
  $('#company-dialog-title').textContent=c.company_name;
  const trust={employer_verified:c.trust&&c.trust.verified,employer_email_verified:c.trust&&c.trust.email_verified,employer_inn_provided:c.trust&&c.trust.inn_provided,employer_created_at:c.created_at};
  const cards=jobs.map(j=>'<article class="item-card"><h4>'+esc(j.title)+'</h4><p>'+esc(j.city)+' · '+formatPay(j)+'</p><button class="btn btn-outline btn-tiny" data-v02-action="details" data-id="'+Number(j.id)+'">Подробнее</button></article>').join('');
  $('#company-dialog-content').innerHTML='<div class="company-public-card">'+employerTrustBadges(trust,true)+'<p class="company-public-about">'+esc(c.about||'Компания пока не добавила описание.')+'</p><div class="company-public-stats"><strong>'+Number(c.open_vacancies||0)+'</strong><span> активных вакансий</span></div><a class="btn btn-outline btn-tiny" href="/companies/'+Number(c.id)+'">Открыть страницу компании</a><div class="dashboard-list">'+cards+'</div></div>';
  if($('#job-dialog').open) $('#job-dialog').close();
  $('#company-dialog').showModal();
}else if(type==='report'){
          if(state.user?.role!=='candidate'){
            if($('#job-dialog').open)$('#job-dialog').close();
            openAuth('login','candidate');
            toast('Войдите как соискатель, чтобы отправить жалобу.');
            return;
          }
          const form=$('#report-form');
          form.reset();
          form.dataset.vacancyId=String(id);
          $('#report-details-count').textContent='0 / 800';
          $('#report-message').textContent='';
          $('#report-success').classList.add('hidden');
          form.classList.remove('hidden');
          if($('#job-dialog').open)$('#job-dialog').close();
          $('#report-dialog').showModal();
}else if(['apply','favorite'].includes(type)){
          if(state.user?.role!=='candidate'){
            if(state.user) throw Error('Действие доступно только соискателю');
            if(type==='apply') state.pendingApplicationVacancyId = id;
            if($('#job-dialog').open) $('#job-dialog').close();
            openAuth('login','candidate');
            if(type==='apply') $('#auth-guidance').textContent =
              'После входа снова покажем выбранную вакансию. Отклик отправите отдельной кнопкой.';
            return;
          }
          if(type==='apply'){
            const fromDialog = $('#job-dialog').open && $('#job-dialog').contains(btn);
            try {
              await req('POST','/api/candidate/applications',{vacancy_id:id});
              await refreshMyApplications();
              syncVisibleApplicationCards(id);
              if(fromDialog){
                // Preserve context and show the saved state instead of a second POST.
                const action = $('#job-dialog .job-detail-action');
                if(action){
                  action.innerHTML = jobApplicationAction(id) + jobApplicationReceipt(id);
                  const receipt = action.querySelector('.job-application-receipt');
                  if(receipt){
                    receipt.setAttribute('tabindex','-1');
                    receipt.focus({preventScroll:true});
                  }
                }
              } else if(state.tab === 'offers') await showDashboard();
              else await loadPublicJobs();
              toast('Отклик отправлен. Контакты остаются скрытыми до вашего согласия.');
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
        else if(type==='reapply'){const result=await req('POST','/api/candidate/applications',{vacancy_id:id});await refreshMyApplications();syncVisibleApplicationCards(id);await showDashboard();toast(result.reapplied?'Отклик отправлен повторно':'Отклик отправлен');}
        else if(type==='filter-vacancy-updates'){
          if(!vacancyUpdatesFilters.includes(btn.dataset.filter)||state.user?.role!=='candidate') return;
          vacancyUpdatesFilter=btn.dataset.filter;
          vacancyUpdatesNextCursor=null;
          await showDashboard();
        }
        else if(type==='more-vacancy-updates'){
          if(state.user?.role!=='candidate'||state.tab!=='changes'||vacancyUpdatesLoading||!vacancyUpdatesNextCursor) return;
          vacancyUpdatesLoading=true;
          const filter=vacancyUpdatesFilter,cursor=vacancyUpdatesNextCursor;
          try {
            const next=await api(vacancyUpdatesEndpoint(filter,cursor));
            if(state.tab!=='changes'||vacancyUpdatesFilter!==filter) return;
            const list=document.getElementById('vacancy-updates-list');
            if(!list) return;
            const existing=new Set(Array.from(list.querySelectorAll('[data-vacancy-update-id]')).map(el=>el.dataset.vacancyUpdateId));
            const items=next.updates.filter(update=>!existing.has(String(update.id)));
            list.insertAdjacentHTML('beforeend',items.map(vacancyUpdateMarkup).join(''));
            vacancyUpdatesNextCursor=next.next_cursor;
            const pager=document.getElementById('vacancy-updates-pagination');
            if(pager) pager.innerHTML=vacancyUpdatesPager(next);
          } finally {vacancyUpdatesLoading=false;}
        }
        else if(type==='mark-vacancy-update-read'){
          await req('POST',`/api/candidate/vacancy-updates/${id}/read`);
          await showDashboard();
          toast('Изменение отмечено прочитанным.');
        }
        else if(type==='open-candidate-applications' || type==='see-applications'){
          await openCandidateApplications(btn.dataset.applicationId, btn.dataset.vacancyId);
        }
        else if(type==='open-employer-applications'){
          const overviewQueue = btn.closest('#employer-workqueue');
          const queueVacancy = overviewQueue?.querySelector('[data-employer-workqueue-vacancy]')?.value || 'all';
          await openEmployerApplications(btn.dataset.filter,
            btn.dataset.vacancyId || queueVacancy, btn.dataset.applicationId, btn.dataset.quick === 'true');
        }
        else if(type==='employer-quick-toggle'){
          if (state.user?.role !== 'employer' || state.tab !== 'applications') return;
          employerApplicationQuickMode = !employerApplicationQuickMode;
          employerApplicationQuickSelectedId = null;
          employerApplicationQuickIndex = 0;
          employerApplicationQuickHandledIds.clear();
          employerApplicationQuickDecisions.clear();
          employerApplicationQuickSkipped.clear();
          if (employerApplicationQuickMode &&
              state.employerApplicationsStatusFilter === 'all' &&
              !String(state.employerApplicationsQuery || '').trim() &&
              employerQuickRecommendedStage()) {
            // Start with an outstanding agreed introduction or decision before
            // reviewing already-completed or waiting applications.
            state.employerApplicationsStatusFilter = employerQuickRecommendedStage();
            employerApplicationQuickFocusOnRender = true;
            await renderEmployer();
          } else {
            applyEmployerApplicationsSearch();
            if (employerApplicationQuickMode) focusEmployerQuickCard();
            else document.querySelector('[data-v02-action="employer-quick-toggle"]')?.focus({preventScroll:true});
          }
        }
        else if(type==='employer-quick-stage'){
          if (state.user?.role !== 'employer' || state.tab !== 'applications' || !employerApplicationQuickMode) return;
          const requested = btn.dataset.stage;
          if (!employerQuickStageOrder.includes(requested) ||
              !Number(employerApplicationQuickCounts[requested] || 0) ||
              String(state.employerApplicationsQuery || '').trim()) return;
          state.employerApplicationsStatusFilter = requested;
          employerApplicationQuickSelectedId = null;
          employerApplicationQuickIndex = 0;
          employerApplicationQuickFocusOnRender = true;
          await renderEmployer();
        }
        else if(type==='employer-quick-skip'){
          if (state.user?.role !== 'employer' || state.tab !== 'applications' || !employerApplicationQuickMode) return;
          const card = document.querySelector('#employer-application-results .application-review-card:not([hidden])');
          const currentId = Number(card?.dataset.applicationId);
          const bucket = String(card?.dataset.applicationBucket || '');
          if (!Number.isSafeInteger(currentId) || currentId <= 0 ||
              !Object.hasOwn(employerApplicationQuickCounts,bucket) ||
              employerApplicationQuickHandledIds.has(currentId) ||
              employerApplicationQuickSkipped.has(currentId)) return;
          const nextId = employerQuickNextAfterAction(currentId);
          employerApplicationQuickSkipped.set(currentId,bucket);
          employerApplicationQuickCounts[bucket] = Math.max(0,employerApplicationQuickCounts[bucket] - 1);
          employerApplicationQuickSelectedId = nextId;
          employerApplicationQuickIndex = 0;
          applyEmployerApplicationsSearch();
          focusEmployerQuickCard();
        }
        else if(type==='employer-quick-revisit'){
          if (state.user?.role !== 'employer' || state.tab !== 'applications' ||
              !employerApplicationQuickMode || !employerApplicationQuickSkipped.size) return;
          const skippedBuckets = new Set(employerApplicationQuickSkipped.values());
          const currentStage = state.employerApplicationsStatusFilter || 'all';
          if (currentStage !== 'all' && !skippedBuckets.has(currentStage)) {
            state.employerApplicationsStatusFilter =
              [...employerQuickStageOrder,'closed'].find(stage => skippedBuckets.has(stage)) || 'all';
          }
          employerApplicationQuickSkipped.clear();
          employerApplicationQuickSelectedId = null;
          employerApplicationQuickIndex = 0;
          employerApplicationQuickFocusOnRender = true;
          await renderEmployer();
        }
        else if(type==='employer-quick-previous' || type==='employer-quick-next'){
          if (state.user?.role !== 'employer' || state.tab !== 'applications' || !employerApplicationQuickMode) return;
          employerApplicationQuickSelectedId = null;
          employerApplicationQuickIndex += type === 'employer-quick-next' ? 1 : -1;
          applyEmployerApplicationsSearch();
          focusEmployerQuickCard();
        }
        else if(type==='employer-application-filter' || type==='employer-application-priority'){
          if(!Object.hasOwn(employerApplicationFilterLabels,btn.dataset.filter))return;
          state.employerApplicationsStatusFilter=btn.dataset.filter;
          employerApplicationVisibleLimit=employerApplicationPageSize;
          employerApplicationQuickSelectedId = null;
          employerApplicationQuickIndex = 0;
          await renderEmployer();
          document.querySelector('[data-v02-action="employer-application-filter"][data-filter="' + state.employerApplicationsStatusFilter + '"]')?.focus({preventScroll:true});
        }
        else if(type==='more-employer-applications'){
          if (state.user?.role !== 'employer' || state.tab !== 'applications') return;
          const list = document.querySelector('#employer-application-results');
          const before = new Set(Array.from(list?.querySelectorAll('.application-review-card:not([hidden])') || []));
          employerApplicationVisibleLimit += employerApplicationPageSize;
          applyEmployerApplicationsSearch();
          const firstNew = Array.from(list?.querySelectorAll('.application-review-card:not([hidden])') || [])
            .find(card => !before.has(card));
          if (firstNew) {
            firstNew.setAttribute('tabindex','-1');
            firstNew.focus({preventScroll:true});
            firstNew.scrollIntoView({block:'nearest'});
          }
        }
        else if(type==='reset-application-filters'){
          state.employerApplicationsVacancyFilter='all';
          state.employerApplicationsStatusFilter='all';
          state.employerApplicationsQuery='';
          employerApplicationVisibleLimit=employerApplicationPageSize;
          employerApplicationQuickSelectedId = null;
          employerApplicationQuickIndex = 0;
          await renderEmployer();
        }
        else if(type==='clear-employer-application-search'){
          state.employerApplicationsQuery='';
          employerApplicationVisibleLimit=employerApplicationPageSize;
          employerApplicationQuickSelectedId = null;
          employerApplicationQuickIndex = 0;
          const input=document.querySelector('#employer-application-search');
          if(input){input.value='';input.focus({preventScroll:true});}
          applyEmployerApplicationsSearch();
        }
        else if(type==='application-status'){
          const nextId = employerApplicationQuickMode ? employerQuickNextAfterAction(id) : null;
          await req('PATCH',`/api/employer/applications/${id}/status`,{status:btn.dataset.status});
          if (employerApplicationQuickMode) {
            // Count an application as handled only after successful confirmation.
            // Even "Взять в рассмотрение" advances instead of showing it twice.
            employerApplicationQuickHandledIds.add(id);
            employerApplicationQuickDecisions.set(id, btn.dataset.status === 'rejected' ? 'rejected' : 'reviewing');
            employerApplicationQuickSelectedId = nextId;
            employerApplicationQuickIndex = 0;
            employerApplicationQuickFocusOnRender = true;
          }
          await showDashboard();
          toast('Статус обновлён');
        }
        else if(type==='express-interest'){
          const nextId = employerApplicationQuickMode ? employerQuickNextAfterAction(id) : null;
          const data=await req('POST',`/api/employer/applications/${id}/interest`);
          if (employerApplicationQuickMode) {
            employerApplicationQuickHandledIds.add(id);
            employerApplicationQuickDecisions.set(id, data.created === true ? 'interest-created' : 'interest-existing');
            employerApplicationQuickSelectedId = nextId;
            employerApplicationQuickIndex = 0;
            employerApplicationQuickFocusOnRender = true;
          } else {
            state.employerApplicationsStatusFilter='consent';
          }
          await showDashboard();
          toast(data.created?'Кандидату направлен запрос на знакомство (демо)':'Запрос уже существует — повторно не отправлен');
        }
        else if(type==='open-introductions'){
          if (!mayLeaveEditor()) return;
          if(state.user?.role==='candidate') {
            const ownerId = state.user.id;
            let targetId = navigationId(btn.dataset.invitationId);
            const vacancyId = navigationId(btn.dataset.vacancyId);
            if (!targetId && vacancyId) {
              const result = await api('/api/candidate/invitations');
              if (state.user?.id !== ownerId) return;
              targetId = navigationId((result.invitations || [])
                .find(item => Number(item.vacancy_id) === vacancyId)?.id);
              if (!targetId) toast('Это знакомство больше недоступно. Открыта ваша история знакомств.');
            }
            state.candidateInvitationsFilter=btn.dataset.filter||'decision';
            state.candidateInvitationTargetId=targetId;
            state.candidateInvitationPinnedId=null;
            state.candidateInvitationsQuery='';
            state.candidateInvitationsData=null;
          } else if (state.user?.role === 'employer') {
            state.employerInvitationsFilter=btn.dataset.filter||'all';
            const targetId=Number(btn.dataset.invitationId||0);
            state.employerInvitationsTargetId=Number.isSafeInteger(targetId)&&targetId>0?targetId:null;
            state.employerInvitationsVacancyFilter='all';
            state.employerInvitationsQuery='';
            state.employerInvitationsData=null;
          } else return;
          state.tab='invitations';
          await showDashboard();
        }
        else if(type==='verify-email'){await req('POST','/api/account/email/request');toast('Письмо подтверждения отправлено, если почтовая доставка настроена');}
        else if(type==='recover'){$('#auth-dialog').close();$('#reset-dialog').showModal();}
        else if(type==='admin-users')await adminView('users');
        else if(type==='admin-jobs')await adminView('jobs');
        else if(type==='admin-reports'){adminSafetyFilter='new';await adminView('reports');}
        else if(type==='admin-security')await adminView('security');
        else if(type==='admin-taxonomy'){adminTaxonomyFilter='pending';await adminView('taxonomy');}
        else if(type==='admin-mail')await adminView('mail');
        else if(type==='admin-employer-verification'){await req('PATCH',`/api/admin/employers/${id}/verification`,{verified:btn.dataset.verified==='true'});await adminView('users');await loadPublicJobs();toast(btn.dataset.verified==='true'?'Компания отмечена как проверенная':'Статус проверки снят');}
                else if(type==='admin-user-status'){await req('PATCH',`/api/admin/users/${id}/status`,{status:btn.dataset.status});await adminView('users');toast('Статус пользователя изменён');}
        else if(type==='admin-job-status'){await req('PATCH',`/api/admin/vacancies/${id}/status`,{status:btn.dataset.status});await adminView('jobs');await loadPublicJobs();toast('Вакансия обновлена');}
        else if(type==='admin-safety-filter'){adminSafetyFilter=btn.dataset.filter||'new';await adminView('reports');}
        else if(type==='admin-moderation'){const status=btn.dataset.status;const field=document.querySelector(`[data-moderation-reason="${id}"]`);const reason=status==='rejected'?(field?.value.trim()||''):'';if(status==='rejected'&&!reason)throw Error('Укажите причину отклонения в поле выше');await req('PATCH',`/api/admin/vacancies/${id}/moderation`,{status,reason});await adminView('reports');await loadPublicJobs();toast(status==='approved'?'Вакансия одобрена и возвращена в поиск':'Вакансия отклонена');}
        else if(type==='admin-report-status'){await req('PATCH',`/api/admin/reports/${btn.dataset.key}/status`,{status:btn.dataset.status});await adminView('reports');toast('Жалоба обработана');}
        else if(type==='admin-taxonomy-filter'){adminTaxonomyFilter=btn.dataset.filter||'pending';await adminView('taxonomy');}
        else if(type==='admin-taxonomy-status'){await req('PATCH',`/api/admin/taxonomy/${btn.dataset.key}`,{status:btn.dataset.status});await adminView('taxonomy');toast(btn.dataset.status==='approved'?'Термин добавлен в подсказки':'Термин отклонён');}
      }catch(e){toast(e.message,true);}
      finally{
        if (tracksEmployerReview) {
          pendingEmployerReviewRequests.delete(id);
          for (const action of reviewActions) {
            if (action.isConnected) {
              action.disabled = false;
              action.removeAttribute('aria-busy');
            }
          }
        }
        if (tracksCandidateWithdrawal) pendingCandidateWithdrawals.delete(id);
        if (tracksApplication) {
          pendingApplicationRequests.delete(id);
          setApplicationPending(id, false);
        }
        if (btn.isConnected) {
          if (type === 'employer-quick-skip') {
            btn.disabled = !employerApplicationQuickMode ||
              !document.querySelector('#employer-application-results .application-review-card:not([hidden])');
          } else btn.disabled = false;
        }
      }
    });
    $('#job-dialog-close').addEventListener('click',()=>$('#job-dialog').close());
    $('#company-dialog-close').addEventListener('click',()=>$('#company-dialog').close());
    $('#report-dialog-close').addEventListener('click',()=>$('#report-dialog').close());
    $('#report-cancel').addEventListener('click',()=>$('#report-dialog').close());
    $('#report-success-close').addEventListener('click',()=>$('#report-dialog').close());
    $('#report-details').addEventListener('input',event=>{
      $('#report-details-count').textContent=event.target.value.length+' / 800';
    });
    $('#report-form').addEventListener('submit',async event=>{
      event.preventDefault();
      const form=event.currentTarget;
      const submit=$('#report-submit');
      const reason=form.elements.namedItem('reason').value;
      if(!reason){$('#report-message').textContent='Выберите причину жалобы.';return;}
      submit.disabled=true;
      $('#report-message').textContent='';
      try{
        const result=await req('POST','/api/reports',{
          vacancy_id:Number(form.dataset.vacancyId),
          target_type:form.elements.namedItem('target_type').value,
          reason,
          details:form.elements.namedItem('details').value.trim()
        });
        form.classList.add('hidden');
        const success=$('#report-success');
        success.classList.remove('hidden');
        const text=success.querySelector('p');
        if(text) text.textContent=result.vacancy_pending_review
          ? 'Жалоба принята. Вакансия временно скрыта из поиска до проверки модератором.'
          : 'Спасибо. Жалоба передана модератору СТАЖНО.';
        await loadPublicJobs();
      }catch(e){
        $('#report-message').textContent=e.message;
      }finally{
        submit.disabled=false;
      }
    });
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
