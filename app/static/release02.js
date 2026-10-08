'use strict';
(function initRelease02() {
  document.addEventListener('DOMContentLoaded', () => {
    const status = {applied:'Отправлен',reviewing:'На рассмотрении',interview:'Работодатель заинтересован',rejected:'Отказ',hired:'Принят',withdrawn:'Отозван'};
    const req = (method, path, data) => api(path,{method, ...(data ? {body:JSON.stringify(data)} : {})});
    function searchValue(id) { return document.getElementById(id)?.value?.trim() || ''; }

    jobMarkup = function(job, personalized = false) {
      const id = Number(job.id), open = job.status !== 'closed';
      return `<article class="job-card"><div class="job-top"><span class="job-company">${esc(job.company_name || 'Работодатель')}</span><span class="job-category">${personalized ? 'Совпадение '+Number(job.score)+'%' : (open ? 'Вакансия' : 'Закрыта')}</span></div>
        <h3>${esc(job.title)}</h3><div class="job-salary">${formatPay(job)}</div>
        <div class="job-meta"><span>⌖ ${esc(job.city)}</span><span>${esc(job.schedule)}</span><span>${esc(job.employment)}</span></div>
        <p>${esc(job.skills || 'Подробности в описании вакансии')}</p>
        <div class="job-actions"><button class="btn btn-outline btn-tiny" data-v02-action="details" data-id="${id}">Подробнее</button>
        ${open ? `<button class="btn btn-primary btn-tiny" data-v02-action="apply" data-id="${id}">Откликнуться</button><button class="btn btn-outline btn-tiny" data-v02-action="favorite" data-id="${id}" aria-label="Сохранить вакансию">♡</button>` : ''}</div></article>`;
    };
    loadPublicJobs = async function() {
      try {
        const qs = new URLSearchParams();
        for (const [input,param] of [['profession-filter','q'],['city-filter','city'],['salary-filter','salary_min'],['schedule-filter','schedule']]) {
          const value=searchValue(input); if(value) qs.set(param,value);
        }
        const {jobs} = await api('/api/jobs'+(qs.size ? '?'+qs : ''));
        $('#jobs-count').textContent = `Найдено: ${jobs.length}`;
        $('#public-jobs').innerHTML = jobs.length ? jobs.map(j=>jobMarkup(j)).join('') : '<div class="empty-state">Вакансий по запросу нет. Попробуйте изменить условия.</div>';
      } catch(e) { toast(e.message,true); $('#public-jobs').innerHTML='<div class="empty-state">Ошибка загрузки вакансий.</div>'; }
    };

    const oldCandidate = renderCandidate;
    const oldEmployer = renderEmployer;
    const oldAdmin = renderAdmin;
    const oldUpdateAuth = updateAuth;

    updateAuth = function() {
      oldUpdateAuth();
      if(state.mode==='login') $('#auth-switch').insertAdjacentHTML('beforeend',' · <button type="button" data-v02-action="recover">Забыли пароль?</button>');
    };
    const candidateExtra = [{id:'favorites',label:'Избранное'},{id:'applications',label:'Мои отклики'},{id:'email',label:'Моя почта'}];
    const employerExtra = [{id:'applications',label:'Отклики соискателей'}];

    renderCandidate = async function() {
      if (!candidateExtra.some(t=>t.id===state.tab)) {
        await oldCandidate();
        const nav=$('.dashboard-tabs');
        if (nav) nav.insertAdjacentHTML('beforeend',candidateExtra.map(t=>`<button type="button" data-tab="${t.id}">${t.label}</button>`).join(''));
        return;
      }
      const nav = [{id:'profile',label:'Мой профиль'},{id:'offers',label:'Подходящие вакансии'},{id:'invitations',label:'Приглашения'},...candidateExtra];
      $('#account-content').innerHTML=`<div class="dashboard-grid">${tabsMarkup(nav,'ДЛЯ СОИСКАТЕЛЯ','Ваша карьера')}<div id="dashboard-main"><div class="loading">Загрузка...</div></div></div>`;
      try {
        if(state.tab==='favorites'){
          const {jobs}=await api('/api/candidate/favorites');
          $('#dashboard-main').innerHTML=`<div class="panel"><h3>Избранные вакансии</h3><div class="dashboard-list">${jobs.length?jobs.map(j=>jobMarkup(j)).join(''):'<div class="empty-state">Вы ещё не сохранили вакансий.</div>'}</div></div>`;
        }
        if(state.tab==='applications'){
          const {applications}=await api('/api/candidate/applications');
          $('#dashboard-main').innerHTML=`<div class="panel"><h3>История откликов</h3><p class="muted">Ваши контакты не раскрываются работодателю автоматически.</p><div class="dashboard-list">${applications.length ? applications.map(a=>`<article class="item-card"><header><div><h4>${esc(a.title)}</h4><p>${esc(a.company_name)} · ${esc(a.city)} · ${formatPay(a)}</p></div><span class="mini-badge">${esc(status[a.status]||a.status)}</span></header><p>Дата отклика: ${esc(a.created_at)}</p>${['applied','reviewing','interview'].includes(a.status)?`<button class="btn btn-outline btn-tiny" data-v02-action="withdraw" data-id="${Number(a.id)}">Отозвать отклик</button>`:''}</article>`).join(''):'<div class="empty-state">Откликов пока нет.</div>'}</div></div>`;
        }
        if(state.tab==='email'){
          const result=await api('/api/account/email/status');
          $('#dashboard-main').innerHTML=`<div class="panel"><h3>Подтверждение электронной почты</h3><p>${result.email_verified?'✓ Email подтверждён':'Email пока не подтверждён'}</p><p class="muted">Сейчас действует тестовая очередь: реальные письма не отправляются. Не вводите личные данные.</p><button class="btn btn-primary" data-v02-action="verify-email">Запросить подтверждение (демо)</button></div>`;
        }
      } catch(e) { $('#dashboard-main').textContent=e.message;toast(e.message,true); }
    };

    renderEmployer = async function() {
      if(state.tab!=='applications'){
        await oldEmployer();
        const nav=$('.dashboard-tabs');
        if(nav) nav.insertAdjacentHTML('beforeend','<button type="button" data-tab="applications">Отклики соискателей</button>');
        return;
      }
      const nav=[{id:'vacancies',label:'Мои вакансии'},{id:'create',label:'Новая вакансия'},{id:'invitations',label:'Приглашения и контакты'},...employerExtra];
      $('#account-content').innerHTML=`<div class="dashboard-grid">${tabsMarkup(nav,'ДЛЯ КОМПАНИИ',state.user.company?.company_name||'Работодатель')}<div id="dashboard-main"></div></div>`;
      try {
        const {applications}=await api('/api/employer/applications');
        $('#dashboard-main').innerHTML=`<div class="panel"><h3>Отклики соискателей</h3><p class="muted">Профили обезличены. Контакты — только через отдельное согласие кандидата и действующий процесс знакомства.</p><div class="dashboard-list">${applications.length?applications.map(a=>`<article class="item-card"><header><div><h4>${esc(a.profession)}</h4><p>${esc(a.title)} · ${esc(a.city)} · зарплатные ожидания от ${money(a.expected_salary)}</p></div><span class="mini-badge">${esc(status[a.status]||a.status)}</span></header><p>${esc(a.skills||'Навыки не указаны')}</p>${['applied','reviewing','interview'].includes(a.status)?`<div class="item-actions"><button class="btn btn-outline btn-tiny" data-v02-action="application-status" data-id="${Number(a.id)}" data-status="reviewing">Рассмотреть</button><button class="btn btn-outline btn-tiny" data-v02-action="application-status" data-id="${Number(a.id)}" data-status="interview">Заинтересован</button><button class="btn btn-outline btn-tiny" data-v02-action="application-status" data-id="${Number(a.id)}" data-status="rejected">Отказать</button></div>`:''}</article>`).join(''):'<div class="empty-state">Откликов пока нет.</div>'}</div></div>`;
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
        root.innerHTML='<h3>Пользователи</h3><div class="dashboard-list">'+users.map(u=>`<article class="item-card"><header><div><h4>${esc(u.name)}</h4><p>${esc(u.email)} · ${esc(u.role)}</p></div><span class="mini-badge">${u.status==='active'?'Активен':'Заблокирован'}</span></header>${u.role==='admin'?'':`<button class="btn btn-outline btn-tiny" data-v02-action="admin-user-status" data-id="${Number(u.id)}" data-status="${u.status==='active'?'disabled':'active'}">${u.status==='active'?'Заблокировать':'Разблокировать'}</button>`}</article>`).join('')+'</div>';
      } else if(kind==='jobs'){
        const {jobs}=await api('/api/admin/vacancies');
        root.innerHTML='<h3>Вакансии</h3><div class="dashboard-list">'+jobs.map(j=>`<article class="item-card"><header><div><h4>${esc(j.title)}</h4><p>${esc(j.company_name)} · ${esc(j.city)}</p></div><span class="mini-badge">${j.status==='open'?'Открыта':'Закрыта'}</span></header><button class="btn btn-outline btn-tiny" data-v02-action="admin-job-status" data-id="${Number(j.id)}" data-status="${j.status==='open'?'closed':'open'}">${j.status==='open'?'Закрыть':'Открыть'}</button></article>`).join('')+'</div>';
      } else {
        const {messages}=await api('/api/admin/mail-preview');
        root.innerHTML='<h3>Тестовая очередь</h3><p class="muted">Сообщения НЕ отправляются. Секретные ссылки здесь скрыты.</p>'+messages.map(m=>`<p>${esc(m.created_at)} · ${esc(m.event)} · ${esc(m.subject)}</p>`).join('');
      }
    }

    document.addEventListener('click',async(event)=>{
      const btn=event.target.closest('[data-v02-action]');
      if(!btn)return;
      const type=btn.dataset.v02Action,id=Number(btn.dataset.id);
      btn.disabled=true;
      try{
        if(type==='details'){
          const {job}=await api(`/api/jobs/${id}`);
          $('#job-dialog-title').textContent=job.title;
          $('#job-dialog-content').innerHTML=`<p><strong>${esc(job.company_name)}</strong> · ${esc(job.city)}</p><p class="job-salary">${formatPay(job)}</p><p>График: ${esc(job.schedule)} · Занятость: ${esc(job.employment)}</p><p><strong>Навыки:</strong> ${esc(job.skills||'По договорённости')}</p><p class="detail-description">${esc(job.description||'Подробности у работодателя')}</p><button class="btn btn-primary" data-v02-action="apply" data-id="${Number(job.id)}">Откликнуться</button>`;
          $('#job-dialog').showModal();
        }else if(['apply','favorite'].includes(type)){
          if(state.user?.role!=='candidate'){ if($('#job-dialog').open) $('#job-dialog').close(); if(state.user)throw Error('Действие доступно только соискателю');openAuth('login','candidate');return; }
          if(type==='apply'){await req('POST','/api/candidate/applications',{vacancy_id:id});toast('Отклик отправлен, статус появится в кабинете');if($('#job-dialog').open)$('#job-dialog').close();}
          else {await req('POST',`/api/candidate/favorites/${id}`);toast('Вакансия сохранена');}
        }else if(type==='withdraw'){await req('POST',`/api/candidate/applications/${id}/withdraw`);await showDashboard();toast('Отклик отозван');}
        else if(type==='application-status'){await req('PATCH',`/api/employer/applications/${id}/status`,{status:btn.dataset.status});await showDashboard();toast('Статус обновлён');}
        else if(type==='verify-email'){await req('POST','/api/account/email/request');toast('Запрос сохранён в тестовой очереди; реальное письмо не отправлено');}
        else if(type==='recover'){$('#auth-dialog').close();$('#reset-dialog').showModal();}
        else if(type==='admin-users')await adminView('users');
        else if(type==='admin-jobs')await adminView('jobs');
        else if(type==='admin-mail')await adminView('mail');
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
        $('#reset-dialog').close();toast('Запрос сохранён в тестовой очереди; письмо не отправлено');
      }catch(e){toast(e.message,true);}
    });
    ['profession-filter','salary-filter'].forEach(id=>$('#'+id).addEventListener('keydown',e=>{if(e.key==='Enter')loadPublicJobs();}));
    $('#schedule-filter').addEventListener('change',loadPublicJobs);
  });
})();
