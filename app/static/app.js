/* СТАЖНО — progressive vanilla JS client; no tracking or external dependencies. */
'use strict';
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const state = { user: null, mode: 'register', role: 'candidate', tab: 'overview', activeVacancy: null, editVacancy: null, activeDraft: null, employerVacancyFilter: 'all', employerVacancySearch: '', employerApplicationsVacancyFilter: 'all', employerApplicationsStatusFilter: 'all', employerApplicationsQuery: '', employerInvitationsFilter: 'all', employerInvitationsVacancyFilter: 'all', employerInvitationsQuery: '', employerInvitationsData: null, candidateInvitationsFilter: 'all', candidateInvitationsQuery: '', candidateInvitationsData: null, pendingApplicationVacancyId: null, mfaChallenge: null, mfaMethod: null, mfaCodeLength: 8, mfaPublicKey: null, mfaTotpFallback: false, actionSummary: null, employerWorkQueueView: null };
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money = value => Number(value || 0).toLocaleString('ru-RU') + ' ₽';
const candidateSalaryText = value => Number(value) > 0
  ? `от ${money(value)}` : 'Зарплата не указана';
const formatPay = job => {
  const low = Math.max(0, Number(job.salary_min) || 0);
  const high = Math.max(0, Number(job.salary_max) || 0);
  if (low > 0 && low === high) return money(low);
  if (low > 0 && high > low) return `${money(low)} — ${money(high)}`;
  if (low > 0) return `от ${money(low)}`;
  if (high > 0) return `до ${money(high)}`;
  return 'По договорённости';
};
const statusTitle = {sent:'Ожидает ответа',accepted:'Согласие получено',declined:'Не заинтересован'};
const statusBadge = {sent:'orange',accepted:'',declined:'gray'};
const activityLabels = {
  applied:'Отклик отправлен',reapplied:'Отклик отправлен повторно',
  withdrawn:'Отклик отозван',reviewing:'На рассмотрении',
  interview:'Работодатель заинтересован',rejected:'Отказ',hired:'Положительный итог',
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
function invitationFinalOutcome(x = {}) {
  if (['hired','rejected'].includes(x.direct_outcome)) return x.direct_outcome;
  const applicationStatus = x.application_status || x.status;
  return ['hired','rejected'].includes(applicationStatus) ? applicationStatus : null;
}
function candidateWorkflowStatus(x, fallback='') {
  const stage = x.introduction_stage;
  const shared = stage==='introduced' || x.contact_shared;
  const outcome = invitationFinalOutcome(x);
  if (outcome === 'hired') return shared ? 'Положительный итог знакомства' : 'Положительный итог';
  if (outcome === 'rejected') return shared ? 'Не договорились' : 'Получен отказ';
  if (stage==='introduced' || x.contact_shared) return 'Знакомство состоялось';
  if (stage==='consented' || x.invitation_status==='accepted') return 'Согласие отправлено';
  if (stage==='awaiting_consent' || x.invitation_status==='sent') return 'Требует вашего ответа';
  if (stage==='declined' || x.invitation_status==='declined') return 'Вы отказались от знакомства';
  if (x.status==='reviewing') return 'На рассмотрении';
  if (x.status==='interview') return 'Работодатель заинтересован';
  if (x.status==='withdrawn') return 'Отозван';
  if (x.status==='applied') return 'Отправлен';
  return fallback;
}
function formatActivityTimestamp(value) {
  const text = String(value || '').trim();
  const match = text.match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/);
  if (!match) return text;
  return `${match[3]}.${match[2]}.${match[1]} · ${match[4]}:${match[5]}`;
}
function activityTimelineMarkup(x) {
  const entries = Array.isArray(x.timeline) ? x.timeline : [];
  if (!entries.length) return '';
  const recent = entries.slice(-4);
  return '<details class="application-timeline" aria-label="История взаимодействия"><summary>История взаимодействия</summary>' +
    recent.map(e=>'<span>'+esc(activityLabels[e.event]||e.event)+' · '+esc(formatActivityTimestamp(e.created_at))+'</span>').join('')+'</details>';
}
function interactionStageMarkup(x, kind='application') {
  const introduced = x.introduction_stage === 'introduced' || x.contact_shared;
  const consented = x.introduction_stage === 'consented' || x.status === 'accepted';
  const awaiting = x.introduction_stage === 'awaiting_consent' || x.invitation_status === 'sent' || x.status === 'interview';
  const finalOutcome =
    ['hired','rejected','withdrawn'].includes(x.application_status) ||
    ['hired','rejected'].includes(x.direct_outcome) ||
    ['hired','rejected','withdrawn'].includes(x.status) ||
    (kind === 'invitation' && x.status === 'declined');
  const reviewing = ['reviewing','interview'].includes(x.status) || awaiting || consented || introduced;
  const applied = Boolean(x.application_id || x.vacancy_id || ['applied','reviewing','interview','withdrawn','rejected','hired'].includes(x.status));
  const invitationSteps = [
    ['Приглашение', true],
    ['Согласие', consented || introduced],
    ['Контакт', introduced]
  ];
  if (x.application_id || x.status === 'declined' || x.direct_outcome) invitationSteps.push(['Итог', finalOutcome]);
  const steps = kind === 'invitation'
    ? invitationSteps
    : [
        ['Отклик', applied],
        ['Рассмотрение', reviewing],
        ['Согласие', consented || introduced],
        ['Знакомство', introduced],
        ['Итог', finalOutcome]
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
  let response;
  try {
    response = await fetch(path, {...options, credentials:'same-origin', headers});
  } catch (cause) {
    const err = new Error('Нет связи с сервером. Проверьте подключение к интернету.');
    err.networkFailure = true;
    throw err;
  }
  let data;
  try { data = await response.json(); } catch { data = {}; }
  if (!response.ok) {
    const issue = data.detail;
    const msg = Array.isArray(issue) ? issue.map(x => x.msg).join('; ') : (typeof issue === 'string' ? issue : `Ошибка ${response.status}`);
    const error = new Error(msg);
    error.httpStatus = response.status;
    throw error;
  }
  return data;
}
// Unsaved editor values stay in memory only. Never write profile text,
// contact details, company information or vacancy drafts to browser storage.
const editorBaselines = new WeakMap();
const editorSubmitting = new WeakSet();
const DRAFT_INPUTS = ['title','city','salary_min','salary_max','schedule','employment','skills','responsibilities','requirements','conditions'];
const DRAFT_LABELS = {
  title:'Должность', city:'Город', salary_min:'Зарплата от',
  salary_max:'Зарплата до', schedule:'График', employment:'Занятость',
  skills:'Навыки', responsibilities:'Обязанности',
  requirements:'Требования', conditions:'Условия работы'
};
function draftFields(form) {
  return Object.fromEntries(DRAFT_INPUTS.map(name => [name, formValue(form,name)]));
}
function normalizedDraftFields(fields = {}) {
  return Object.fromEntries(DRAFT_INPUTS.map(name => [name,
    String(fields[name] ?? (name === 'schedule' ? 'Любой' : name === 'employment' ? 'Любая' : '')).trim()
  ]));
}
const DRAFT_REQUIRED_FIELDS = ['title','city','salary_min','salary_max','responsibilities','requirements','conditions'];
function draftCompletion(draft) {
  const fields = draft?.fields || {};
  const filled = DRAFT_REQUIRED_FIELDS.filter(name => String(fields[name] ?? '').trim() !== '').length;
  return {filled, total:DRAFT_REQUIRED_FIELDS.length};
}
function draftSavedAt(value) {
  const raw = String(value || '').trim();
  if (!raw) return 'время не указано';
  // Database values are UTC; render them in the browser's local timezone.
  const iso = raw.replace(' ', 'T');
  // PostgreSQL may stringify the UTC offset as "+00" rather than "+00:00".
  const normalized = iso.replace(/([+-][0-9]{2})$/, '$1:00');
  const qualified = /(?:Z|[+-][0-9]{2}:?[0-9]{2})$/i.test(normalized) ? normalized : normalized + 'Z';
  const date = new Date(qualified);
  if (Number.isNaN(date.getTime())) return 'время не указано';
  return new Intl.DateTimeFormat('ru-RU', {day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'}).format(date);
}
function employerDraftCard(draft) {
  const {filled,total} = draftCompletion(draft);
  const name = String(draft?.fields?.title || '').trim() || 'Без названия';
  const city = String(draft?.fields?.city || '').trim();
  return `<article class="item-card employer-draft-card">
    <header class="employer-draft-card-head"><div><span class="card-eyebrow">НЕ ОПУБЛИКОВАНО</span><h4>${esc(name)}</h4>${city ? `<p class="muted">${esc(city)}</p>` : ''}</div></header>
    <div class="employer-draft-progress"><span>Обязательные поля: <strong>${filled} из ${total}</strong></span>
      <progress max="${total}" value="${filled}" aria-label="Заполнено обязательных полей"></progress></div>
    <p class="muted employer-draft-updated">Последнее сохранение: ${esc(draftSavedAt(draft.updated_at))}</p>
    <div class="item-actions"><button type="button" class="btn btn-primary btn-tiny" data-action="resume-vacancy-draft" data-id="${Number(draft.id)}">Продолжить заполнение</button>
      <button type="button" class="btn btn-outline btn-tiny" data-action="delete-vacancy-draft" data-id="${Number(draft.id)}">Удалить</button></div>
  </article>`;
}
// One random request key per NEW form, kept only in memory/DOM. Never persist
// draft text or the key in browser storage. Key survives network retries in this tab.
function newDraftCreateKey() {
  if (typeof window.crypto?.randomUUID === 'function') return window.crypto.randomUUID();
  const bytes = new Uint8Array(16);
  window.crypto.getRandomValues(bytes);
  bytes[6] = (bytes[6] & 15) | 64;
  bytes[8] = (bytes[8] & 63) | 128;
  const hex = Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`;
}
// Only drafts explicitly saved on the server are automatically updated.
// Values are never written to browser storage. Timers belong to a live form.
const draftAutoTimers = new WeakMap();
const draftAutoSaving = new WeakSet();
const draftAutoBlocked = new WeakSet();
const draftAutoWarnings = new WeakMap();
// Original server snapshot is essential to a three-way merge. DOM only, no storage.
const draftServerBaselines = new WeakMap();
const draftConflictSessions = new WeakMap();
// Published edits are never autosaved. These snapshots live only while a
// single editing form exists. Selection is staged locally until new preview.
const publishedVacancyBaselines = new WeakMap();
const publishedVacancyConflictSessions = new WeakMap();
const publishedVacancyPending = new WeakSet();
const PUBLISHED_EDIT_FIELDS = ['title','city','salary_min','salary_max','schedule','employment','skills','description'];
const PUBLISHED_FIELD_LABELS = {
  title:'Должность',city:'Город',salary_min:'Зарплата от',
  salary_max:'Зарплата до',schedule:'График',employment:'Занятость',
  skills:'Ключевые навыки',description:'Описание вакансии',
  responsibilities:'Обязанности',requirements:'Требования',conditions:'Условия работы'
};
function publishedJobSnapshot(job) {
  return Object.fromEntries([...PUBLISHED_EDIT_FIELDS,'status','revision','id'].map(key => [key, job[key]]));
}
function publishedFormValues(form) {
  const describe = window.OpytnovacancyWizard?.describe;
  if (!describe) throw new Error('Не удалось проверить описание. Перезагрузите страницу.');
  return {
    title: formValue(form,'title'),city:formValue(form,'city'),
    salary_min:parseNumber(form,'salary_min'),salary_max:parseNumber(form,'salary_max'),
    schedule:formValue(form,'schedule'),employment:formValue(form,'employment'),
    skills:formValue(form,'skills'),description:describe(form)
  };
}
function publishedMergeDescription(parts) {
  return ['Обязанности:', parts.responsibilities, '', 'Требования:',
    parts.requirements, '', 'Условия работы:', parts.conditions].join('\n');
}
function publishedConflictDifference(base, local, server) {
  const parse = window.OpytnovacancyWizard?.splitDescription;
  const b = parse?.(base.description), l = parse?.(local.description), r = parse?.(server.description);
  const detailed = Boolean(b && l && r);
  const names = [...PUBLISHED_EDIT_FIELDS.filter(key => key !== 'description'),
    ...(detailed ? ['responsibilities','requirements','conditions'] : ['description'])];
  const baseFields = {...base,...(detailed ? b : {})};
  const localFields = {...local,...(detailed ? l : {})};
  const serverFields = {...server,...(detailed ? r : {})};
  const differences = names.filter(key => String(localFields[key]) !== String(serverFields[key])).map(name => {
    const localChanged = String(localFields[name]) !== String(baseFields[name]);
    const serverChanged = String(serverFields[name]) !== String(baseFields[name]);
    return {
      name, baseValue:String(baseFields[name] ?? ''), localValue:String(localFields[name] ?? ''),
      serverValue:String(serverFields[name] ?? ''), localChanged, serverChanged,
      suggested: localChanged && serverChanged ? '' : localChanged ? 'local' : 'server'
    };
  });
  return {differences,detailed,parts:r || null};
}

function cancelDraftAutosave(form) {
  const timer = draftAutoTimers.get(form);
  if (timer) clearTimeout(timer);
  draftAutoTimers.delete(form);
}
function scheduleVacancyAutosave(form) {
  if (!form || form.id !== 'vacancy-form' || !form.dataset.draftId || form.dataset.editId) return;
  cancelDraftAutosave(form);
  if (draftAutoBlocked.has(form)) {
    setEditorStatus(form, draftAutoWarnings.get(form) || 'Автосохранение остановлено после ошибки. Нажмите «Сохранить сейчас» или откройте черновик заново.', true);
    return;
  }
  if (!editorIsDirty(form)) {
    if (!draftAutoSaving.has(form)) setEditorStatus(form, 'Черновик сохранён на сервере. Автосохранение включено.');
    return;
  }
  setEditorStatus(form, 'Есть изменения — автоматически сохраним через секунду…');
  draftAutoTimers.set(form, setTimeout(() => {
    draftAutoTimers.delete(form);
    if (form.isConnected && editorIsDirty(form)) void saveVacancyDraft(form, true);
  }, 1400));
}
async function saveVacancyDraft(form, automatic = false) {
  if (draftConflictSessions.has(form)) {
    setEditorStatus(form, 'Сначала выберите варианты в сравнении изменений ниже.', true);
    form.querySelector('[data-draft-conflict-panel]')?.scrollIntoView({block:'nearest'});
    return;
  }
  const button = form.querySelector('[data-action="save-vacancy-draft"]');
  if (editorSubmitting.has(form) || draftAutoSaving.has(form) || (automatic && (draftAutoBlocked.has(form) || !form.dataset.draftId))) return;
  cancelDraftAutosave(form);
  const submit = automatic ? null : beginEditorSave(form);
  if (automatic) draftAutoSaving.add(form);
  if (button) button.disabled = true;
  if (automatic) setEditorStatus(form, 'Автоматически сохраняем черновик…');
  const snapshot = editorFingerprint(form);
  const fields = draftFields(form);
  const id = Number(form.dataset.draftId || 0);
  try {
    // The first POST keeps the same unpredictable idempotency key until
    // confirmed. If its reply is lost, repeating it cannot create a duplicate.
    const requestKey = id ? null : (form.dataset.draftCreateKey || (form.dataset.draftCreateKey = newDraftCreateKey()));
    let result;
    try {
      result = await api(id ? `/api/employer/vacancy-drafts/${id}` : '/api/employer/vacancy-drafts', {
        method: id ? 'PUT' : 'POST',
        body: JSON.stringify(id ? {fields, expected_version:Number(form.dataset.draftVersion)} : {fields, request_key:requestKey})
      });
    } catch (error) {
      if (id || error?.httpStatus !== 409 || !requestKey) throw error;
      // The user edited the form after the FIRST POST was saved but its
      // response was lost. Recover the owned original; never create another.
      const recovered = await api(`/api/employer/vacancy-drafts/by-request/${requestKey}`);
      if (recovered.published_vacancy_id != null || recovered.version !== 1) {
        throw new Error('Черновик уже изменился. Откройте его из «Мои вакансии», чтобы избежать перезаписи.');
      }
      result = await api(`/api/employer/vacancy-drafts/${recovered.id}`, {
        method:'PUT', body:JSON.stringify({fields, expected_version:recovered.version})
      });
    }
    // A replay can return a draft changed on another device; never mark
    // this form as saved unless the server confirms the exact submitted fields.
    if (!Object.entries(fields).every(([name, value]) => result.fields?.[name] === value)) {
      throw new Error('Черновик уже изменён на другом устройстве. Откройте его заново перед сохранением.');
    }
    form.dataset.draftId = result.id;
    form.dataset.draftVersion = result.version;
    delete form.dataset.draftCreateKey;
    if (button) button.textContent = 'Сохранить сейчас';
    state.activeDraft = result;
    draftServerBaselines.set(form, normalizedDraftFields(result.fields));
    draftConflictSessions.delete(form);
    form.querySelector('[data-draft-conflict-panel]')?.remove();
    draftAutoBlocked.delete(form);
    draftAutoWarnings.delete(form);
    // Mark only the exact submitted snapshot as saved, never newer keystrokes.
    editorBaselines.set(form, snapshot);
    if (editorFingerprint(form) === snapshot) {
      setEditorStatus(form, 'Черновик сохранён на сервере. Автосохранение включено.');
    } else {
      setEditorStatus(form, 'Появились новые изменения. Автосохранение продолжится…');
    }
    if (!automatic) toast('Черновик сохранён. Дальнейшие изменения сохраняются автоматически.');
  } catch(e) {
    // On a network failure the HTTP request might have committed. Stop
    // automatic retries; explicit save can safely retry versioned PUT.
    draftAutoBlocked.add(form);
    if (id && e?.httpStatus === 409) {
      try {
        await showDraftConflictResolution(form);
        if (!automatic) toast('Найдены изменения на другом устройстве. Сравните варианты ниже.', true);
      } catch(readError) {
        const warning = 'Не удалось получить новую версию черновика: ' + readError.message + '. Ваш текст остался в форме.';
        draftAutoWarnings.set(form, warning);
        setEditorStatus(form, warning, true);
        if (!automatic) toast(warning, true);
      }
      return;
    }
    const warning = e?.httpStatus === 409
      ? 'Черновик изменён на другом устройстве. Автосохранение остановлено; проверьте черновик перед повторной записью.'
      : e?.networkFailure
        ? (id
          ? 'Не удалось подтвердить сохранение из-за потери связи. Текст остался на экране. После восстановления сети нажмите «Сохранить сейчас».'
          : 'Связь прервалась: первый черновик мог сохраниться. Повторите сохранение — дубликат не создастся. Текст остаётся на экране.')
        : 'Не удалось сохранить черновик: ' + e.message + '. Текст остался на экране; автосохранение остановлено.';
    draftAutoWarnings.set(form, warning);
    setEditorStatus(form, warning, true);
    if (!automatic) toast(warning, true);
  } finally {
    if (automatic) draftAutoSaving.delete(form);
    else {
      endEditorSave(form, submit);
      // Saving a draft does not approve its publication. Only the
      // separate preview step may enable the publish button.
      if (submit?.isConnected && form.querySelector('#vacancy-preview')?.hidden) {
        submit.disabled = true;
      }
    }
    if (button?.isConnected) button.disabled = false;
  }
  if (!draftAutoBlocked.has(form) && editorIsDirty(form) && form.isConnected) scheduleVacancyAutosave(form);
}

function draftDifference(base, local, server) {
  return DRAFT_INPUTS.filter(name => local[name] !== server[name]).map(name => {
    const localChanged = local[name] !== base[name];
    const serverChanged = server[name] !== base[name];
    return {
      name, localChanged, serverChanged,
      suggested: localChanged && serverChanged ? '' : (localChanged ? 'local' : 'server')
    };
  });
}
async function showDraftConflictResolution(form) {
  const id = Number(form?.dataset.draftId || 0);
  const base = draftServerBaselines.get(form);
  if (!id || !base) throw new Error('Не удалось установить исходную версию. Откройте черновик снова.');
  cancelDraftAutosave(form);
  draftAutoBlocked.add(form);
  const latest = await api('/api/employer/vacancy-drafts/' + id);
  if (latest.published_vacancy_id != null) {
    throw new Error('Черновик уже опубликован. Он не будет перезаписан.');
  }
  const local = draftFields(form);
  const server = normalizedDraftFields(latest.fields);
  const differences = draftDifference(base, local, server);
  const snapshot = editorFingerprint(form);
  draftConflictSessions.set(form, {id, version:latest.version, base, local, server, differences, snapshot});
  const warning = 'Черновик изменён на другом устройстве. Автосохранение остановлено. Проверьте варианты и подтвердите, что оставить.';
  draftAutoWarnings.set(form, warning);
  setEditorStatus(form, warning, true);
  const old = form.querySelector('[data-draft-conflict-panel]');
  if (old) old.remove();
  const panel = document.createElement('section');
  panel.className = 'draft-conflict-panel';
  panel.dataset.draftConflictPanel = 'true';
  panel.setAttribute('role', 'region');
  panel.setAttribute('aria-labelledby', 'draft-conflict-title');
  const overlap = differences.filter(d => d.localChanged && d.serverChanged).length;
  const details = differences.map(d => {
    const label = DRAFT_LABELS[d.name] || d.name;
    const description = d.localChanged && d.serverChanged
      ? 'Изменено на обоих устройствах — выберите вариант.'
      : d.localChanged ? 'Менялось только здесь. Предлагаем оставить вашу версию.'
        : 'Менялось на другом устройстве. Предлагаем сохранить серверную версию.';
    return '<div class="draft-conflict-field">' +
      '<strong>' + esc(label) + '</strong><small>' + esc(description) + '</small>' +
      '<div class="draft-conflict-versions"><div><span>На этом устройстве</span><div class="draft-conflict-value">' +
      esc(local[d.name] || '— Не заполнено —') + '</div></div>' +
      '<div><span>Последняя версия на сервере</span><div class="draft-conflict-value">' +
      esc(server[d.name] || '— Не заполнено —') + '</div></div></div>' +
      '<label for="draft-conflict-' + d.name + '">Какой вариант сохранить?</label>' +
      '<select id="draft-conflict-' + d.name + '" data-draft-conflict-choice="' + d.name + '">' +
      '<option value=""' + (!d.suggested ? ' selected' : '') + '>Выберите вариант</option>' +
      '<option value="local"' + (d.suggested === 'local' ? ' selected' : '') + '>Мои изменения</option>' +
      '<option value="server"' + (d.suggested === 'server' ? ' selected' : '') + '>С сервера</option>' +
      '</select></div>';
  }).join('');
  panel.innerHTML = '<div class="draft-conflict-heading"><span class="section-kicker">СРАВНЕНИЕ ИЗМЕНЕНИЙ</span>' +
    '<h3 id="draft-conflict-title">Черновик изменился на другом устройстве</h3>' +
    '<p>Ваш текст остался в форме. Данные на сервере не перезаписаны. Проверьте выбор для каждого различающегося поля.</p>' +
    '<p class="muted">' + (overlap ? 'Совпадающих правок с разными значениями: ' + overlap + '. ' : '') +
    'Ни одно объединение не сохранится без вашего подтверждения.</p></div>' +
    (differences.length ? '<div class="draft-conflict-fields">' + details + '</div>' :
      '<p class="muted">Значения совпадают. Можно подтвердить актуальную версию.</p>') +
    '<div class="draft-conflict-actions"><button type="button" class="btn btn-primary" data-action="apply-draft-conflict">Сохранить выбранные изменения</button>' +
    '<button type="button" class="btn btn-outline" data-action="refresh-draft-conflict">Обновить сравнение</button></div>' +
    '<p class="draft-conflict-note" role="status" aria-live="polite">После сохранения проверьте вакансию в предпросмотре перед публикацией.</p>';
  (form.querySelector('.vacancy-draft-actions') || form.querySelector('.vacancy-publish-actions')).before(panel);
  const preview = form.querySelector('#vacancy-preview');
  if (preview) preview.hidden = true;
  const publish = form.querySelector('#vacancy-publish');
  if (publish) publish.disabled = true;
}
async function applyDraftConflictResolution(form) {
  const session = draftConflictSessions.get(form);
  const panel = form?.querySelector('[data-draft-conflict-panel]');
  if (!session || !panel || editorSubmitting.has(form) || draftAutoSaving.has(form)) return;
  if (editorFingerprint(form) !== session.snapshot) {
    await showDraftConflictResolution(form);
    toast('В форме появились новые правки. Сравнение обновлено — проверьте варианты снова.', true);
    return;
  }
  const merged = {...session.server};
  for (const difference of session.differences) {
    const select = panel.querySelector('[data-draft-conflict-choice="' + difference.name + '"]');
    const choice = select?.value;
    if (choice !== 'local' && choice !== 'server') {
      setEditorStatus(form, 'Выберите, какой вариант оставить для поля «' + DRAFT_LABELS[difference.name] + '».', true);
      select?.focus();
      return;
    }
    merged[difference.name] = choice === 'local' ? session.local[difference.name] : session.server[difference.name];
  }
  const button = panel.querySelector('[data-action="apply-draft-conflict"]');
  const submit = beginEditorSave(form);
  if (!submit) return;
  if (button) button.disabled = true;
  try {
    const saved = await api('/api/employer/vacancy-drafts/' + session.id, {
      method:'PUT',
      body:JSON.stringify({fields:merged, expected_version:session.version})
    });
    if (!DRAFT_INPUTS.every(name => String(saved.fields?.[name] ?? '') === merged[name])) {
      throw new Error('Сервер не подтвердил выбранные значения. Текст остаётся в форме.');
    }
    for (const name of DRAFT_INPUTS) {
      const control = form.elements.namedItem(name);
      if (control) control.value = merged[name];
    }
    // Invalidate an earlier publication preview, without scheduling autosave.
    form.elements.namedItem('title')?.dispatchEvent(new Event('input', {bubbles:true}));
    form.dataset.draftVersion = saved.version;
    state.activeDraft = saved;
    draftServerBaselines.set(form, {...merged});
    editorBaselines.set(form, editorFingerprint(form));
    draftConflictSessions.delete(form);
    draftAutoBlocked.delete(form);
    draftAutoWarnings.delete(form);
    panel.remove();
    setEditorStatus(form, 'Выбранные изменения сохранены. Автосохранение снова работает.');
    toast('Черновик объединён и сохранён. Перед публикацией повторите предпросмотр.');
  } catch(error) {
    draftAutoBlocked.add(form);
    if (error?.httpStatus === 409) {
      try {
        await showDraftConflictResolution(form);
        toast('За время сравнения черновик снова изменился. Выберите варианты ещё раз.', true);
      } catch(readError) {
        setEditorStatus(form, 'Не удалось обновить сравнение: ' + readError.message + '. Локальные данные сохранены на экране.', true);
      }
    } else {
      setEditorStatus(form, 'Не удалось сохранить выбор: ' + error.message + '. Ваш текст остался в форме.', true);
      toast('Изменения не сохранены. Проверьте соединение и повторите попытку.', true);
    }
  } finally {
    endEditorSave(form, submit);
    if (submit?.isConnected && (draftConflictSessions.has(form) || form.querySelector('#vacancy-preview')?.hidden)) submit.disabled = true;
    if (button?.isConnected) button.disabled = false;
  }
}

async function showPublishedVacancyConflict(form) {
  const jobId = Number(form?.dataset.editId || 0);
  const base = publishedVacancyBaselines.get(form);
  if (!jobId || !base) throw new Error('Неизвестна исходная версия. Откройте вакансию заново.');
  const local = publishedFormValues(form);
  const response = await api('/api/employer/vacancies/' + jobId);
  const server = publishedJobSnapshot(response.job);
  const {differences,detailed,parts} = publishedConflictDifference(base,local,server);
  const statusChanged = String(base.status) !== String(server.status);
  const snapshot = editorFingerprint(form);
  publishedVacancyConflictSessions.set(form,{
    jobId,base,local,server,differences,detailed,parts,statusChanged,snapshot
  });
  const previous = form.querySelector('[data-published-conflict-panel]');
  if (previous) previous.remove();
  const panel = document.createElement('section');
  panel.dataset.publishedConflictPanel = 'true';
  panel.className = 'draft-conflict-panel published-vacancy-conflict-panel';
  panel.setAttribute('role','region');
  panel.setAttribute('aria-labelledby','published-conflict-title');
  const overlap = differences.filter(d => d.localChanged && d.serverChanged).length;
  const fieldsHtml = differences.map(d => {
    const label = PUBLISHED_FIELD_LABELS[d.name] || d.name;
    const hint = d.localChanged && d.serverChanged
      ? 'Поле изменено на обоих устройствах. Выберите нужный вариант.'
      : d.localChanged ? 'Изменено только здесь. Предлагаем ваш вариант.'
        : 'Изменено на другом устройстве. Предлагаем вариант сервера.';
    const value = (heading,contents) => '<div><span>' + esc(heading) +
      '</span><div class="draft-conflict-value">' + esc(contents || '— Не заполнено —') + '</div></div>';
    return '<div class="draft-conflict-field"><strong>' + esc(label) + '</strong><small>' +
      esc(hint) + '</small><div class="draft-conflict-versions">' +
      value('При открытии формы',d.baseValue) +
      value('На этом устройстве',d.localValue) +
      value('Последняя версия сервера',d.serverValue) + '</div>' +
      '<label for="published-conflict-' + d.name + '">Какой вариант оставить?</label>' +
      '<select id="published-conflict-' + d.name +
      '" data-published-conflict-choice="' + d.name + '">' +
      '<option value=""' + (!d.suggested ? ' selected' : '') + '>Выберите вариант</option>' +
      '<option value="local"' + (d.suggested === 'local' ? ' selected' : '') + '>Мои изменения</option>' +
      '<option value="server"' + (d.suggested === 'server' ? ' selected' : '') + '>С сервера</option>' +
      '</select></div>';
  }).join('');
  const statusHtml = statusChanged
    ? '<div class="published-vacancy-status-warning"><strong>Статус вакансии изменился:</strong> ' +
      esc(String(base.status)) + ' → ' + esc(String(server.status)) +
      '<label><input type="checkbox" data-published-conflict-status-ack> ' +
      'Я понимаю, что статус останется таким, как на сервере.</label></div>'
    : '';
  panel.innerHTML = '<span class="section-kicker">СОГЛАСОВАНИЕ УСЛОВИЙ</span>' +
    '<h3 id="published-conflict-title">Вакансия изменилась на другом устройстве</h3>' +
    '<p>На экране осталась ваша версия. Сравните условия, затем примените выбранные значения в форму. ' +
    '<strong>Вакансия пока не изменится.</strong> Для сохранения потребуется новый предпросмотр.</p>' +
    (overlap ? '<p class="muted">Одновременно изменённых полей: ' + overlap + '.</p>' : '') +
    (differences.length ? '<div class="draft-conflict-fields">' + fieldsHtml + '</div>' :
      '<p class="muted">Содержимое совпадает. Сервер обновил другие данные вакансии.</p>') +
    statusHtml +
    '<div class="draft-conflict-actions">' +
    '<button type="button" class="btn btn-primary" data-action="apply-published-conflict">Применить выбранные значения к форме</button>' +
    '<button type="button" class="btn btn-outline" data-action="refresh-published-conflict">Обновить сравнение</button>' +
    '</div><p class="draft-conflict-note" role="status" aria-live="polite">' +
    'Отклики и история сохраняются. Изменения не попадут в опубликованную вакансию до вашего нового подтверждения.</p>';
  const insertion = form.querySelector('.vacancy-preview-intro');
  if (!insertion) throw new Error('Не удалось открыть сравнение полей');
  insertion.before(panel);
  const preview = form.querySelector('#vacancy-preview');
  if (preview) preview.hidden = true;
  const submit = form.querySelector('#vacancy-publish');
  if (submit) submit.disabled = true;
  setEditorStatus(form,'Вакансия изменилась на другом устройстве. Выберите условия в блоке сравнения.',true);
}
async function applyPublishedVacancyConflict(form) {
  const session = publishedVacancyConflictSessions.get(form);
  const panel = form?.querySelector('[data-published-conflict-panel]');
  if (!session || !panel || editorSubmitting.has(form)) return;
  if (editorFingerprint(form) !== session.snapshot) {
    await showPublishedVacancyConflict(form);
    toast('Пока вы сравнивали версии, форма изменилась. Проверьте варианты заново.',true);
    return;
  }
  if (session.statusChanged && !panel.querySelector('[data-published-conflict-status-ack]')?.checked) {
    setEditorStatus(form,'Подтвердите, что заметили изменение статуса вакансии.',true);
    panel.querySelector('[data-published-conflict-status-ack]')?.focus();
    return;
  }
  const merged = {...session.server};
  const parts = session.detailed ? {...session.parts} : null;
  for (const difference of session.differences) {
    const selection = panel.querySelector('[data-published-conflict-choice="' + difference.name + '"]');
    const choice = selection?.value;
    if (choice !== 'local' && choice !== 'server') {
      setEditorStatus(form,'Выберите вариант поля «' + PUBLISHED_FIELD_LABELS[difference.name] + '».',true);
      selection?.focus();
      return;
    }
    const value = choice === 'local' ? difference.localValue : difference.serverValue;
    if (parts && ['responsibilities','requirements','conditions'].includes(difference.name)) {
      parts[difference.name] = value;
    } else if (['salary_min','salary_max'].includes(difference.name)) {
      merged[difference.name] = Number(value);
    } else {
      merged[difference.name] = value;
    }
  }
  if (parts) merged.description = publishedMergeDescription(parts);
  // Do not change the published vacancy yet. Also confirm the server has not
  // changed while the user was choosing values.
  const action = panel.querySelector('[data-action="apply-published-conflict"]');
  if (action) action.disabled = true;
  try {
    const response = await api('/api/employer/vacancies/' + session.jobId);
    if (response.job.revision !== session.server.revision) {
      await showPublishedVacancyConflict(form);
      toast('На другом устройстве сохранили новые изменения. Сравнение обновлено.',true);
      return;
    }
    const nextJob = {...response.job,...merged,revision:response.job.revision,status:response.job.status};
    const main = $('#dashboard-main');
    main.innerHTML = vacancyFormMarkup(nextJob);
    prepareEditorForms();
    const nextForm = main.querySelector('#vacancy-form');
    if (!nextForm) throw new Error('Не удалось построить форму для объединённых условий');
    publishedVacancyBaselines.set(nextForm,publishedJobSnapshot(response.job));
    publishedVacancyPending.add(nextForm);
    setEditorStatus(nextForm,'Выбранные значения подготовлены, но ещё НЕ сохранены. Откройте новый предпросмотр и нажмите «Сохранить изменения».');
    const publish = nextForm.querySelector('#vacancy-publish');
    if (publish) publish.disabled = true;
    toast('Изменения объединены в форме. Перед сохранением обязательно проверьте предпросмотр.');
    nextForm.querySelector('#vacancy-show-preview')?.focus({preventScroll:true});
  } catch(error) {
    setEditorStatus(form,'Сравнение не завершено: ' + error.message + '. Ваш текст остался на экране.',true);
    toast('Не удалось завершить сравнение. Проверьте соединение и повторите попытку.',true);
  } finally {
    if (action?.isConnected) action.disabled = false;
  }
}
const EDITOR_IDS = new Set(['profile-form', 'company-form', 'vacancy-form']);
function candidateProfileFormData(form) {
  const work_history = Array.from(form.querySelectorAll('[data-resume-role]')).map(entry => ({
    position: String(entry.querySelector('[data-role-position]')?.value || '').trim(),
    period: String(entry.querySelector('[data-role-period]')?.value || '').trim(),
    duties: String(entry.querySelector('[data-role-duties]')?.value || '').trim()
  })).filter(entry => entry.position || entry.period || entry.duties);
  const courses = Array.from(form.querySelectorAll('[data-resume-course]')).map(entry => ({
    title: String(entry.querySelector('[data-course-title]')?.value || '').trim(),
    provider: String(entry.querySelector('[data-course-provider]')?.value || '').trim(),
    year: entry.querySelector('[data-course-year]')?.value
      ? Number(entry.querySelector('[data-course-year]').value) : null,
    has_certificate: Boolean(entry.querySelector('[data-course-certificate]')?.checked)
  })).filter(course => course.title || course.provider || course.year || course.has_certificate);
  return {
    profession: formValue(form, 'profession'), city: formValue(form, 'city'),
    skills: formValue(form, 'skills'), salary_min: parseNumber(form, 'salary_min'),
    phone: formValue(form, 'phone'), schedule: formValue(form, 'schedule'),
    employment: formValue(form, 'employment'), about: formValue(form, 'about'),
    is_active: form.elements.namedItem('is_active').checked,
    experience_years: parseNumber(form, 'experience_years') || 0,
    education: formValue(form, 'education'), achievements: formValue(form, 'achievements'),
    specializations: formValue(form, 'specializations'), work_history, courses
  };
}
function editorFingerprint(form) {
  if (form.id === 'profile-form') {
    // Work history and course controls have no names and are absent from
    // FormData. Track raw values and empty rows too, without persisting them
    // anywhere outside this open editor. Helper answers are not profile fields.
    return JSON.stringify(Array.from(form.elements)
      .filter(control => control.matches('input,textarea,select') && !control.closest('#experience-helper'))
      .map(control => [control.type, control.type === 'checkbox' ? control.checked : control.value]));
  }
  return JSON.stringify([...new FormData(form).entries()]);
}
function revealProfileField(field) {
  for (let details = field?.closest('details'); details; details = details.parentElement?.closest('details')) {
    details.open = true;
  }
}
function profileFieldError(form, field, message) {
  revealProfileField(field);
  setEditorStatus(form, message, true);
  field?.focus();
  toast(message, true);
  return false;
}
function validateCandidateProfileRows(form) {
  for (const name of ['profession', 'city']) {
    const field = form.elements.namedItem(name);
    if (String(field.value || '').trim().length < 2) {
      return profileFieldError(form, field, name === 'profession'
        ? 'Укажите профессию: не меньше двух символов.' : 'Укажите город: не меньше двух символов.');
    }
  }
  for (const entry of form.querySelectorAll('[data-resume-role]')) {
    const position = entry.querySelector('[data-role-position]');
    const period = entry.querySelector('[data-role-period]');
    const duties = entry.querySelector('[data-role-duties]');
    if (![position, period, duties].some(field => field.value.trim())) continue;
    if (position.value.trim().length < 2 || period.value.trim().length < 2) {
      return profileFieldError(form, position.value.trim().length < 2 ? position : period,
        'В каждом месте работы укажите должность и период. Либо удалите незаполненную запись.');
    }
  }
  for (const entry of form.querySelectorAll('[data-resume-course]')) {
    const title = entry.querySelector('[data-course-title]');
    const hasData = [...entry.querySelectorAll('input')].some(field =>
      field.type === 'checkbox' ? field.checked : field.value.trim());
    if (hasData && title.value.trim().length < 2) {
      return profileFieldError(form, title, 'Для каждого курса укажите название либо удалите пустую запись.');
    }
  }
  return true;
}
document.addEventListener('invalid', event => {
  if (event.target.form?.id === 'profile-form') revealProfileField(event.target);
}, true);
function editorForControl(control) {
  const form = control?.form || control?.closest?.('form');
  return form && EDITOR_IDS.has(form.id) ? form : null;
}
function currentEditor() {
  return $('#dashboard-main #profile-form, #dashboard-main #company-form, #dashboard-main #vacancy-form');
}
function editorIsDirty(form) {
  return Boolean(form && (publishedVacancyPending.has(form) ||
    (editorBaselines.has(form) && editorBaselines.get(form) !== editorFingerprint(form))));
}
function setEditorStatus(form, message, isError = false) {
  const status = form?.querySelector('.editor-save-status');
  if (!status) return;
  status.textContent = message;
  status.classList.toggle('is-error', isError);
  status.classList.toggle('is-dirty', !isError && editorIsDirty(form));
}
function prepareEditorForms() {
  document.querySelectorAll('#dashboard-main #profile-form, #dashboard-main #company-form, #dashboard-main #vacancy-form').forEach(form => {
    if (editorBaselines.has(form)) return;
    editorBaselines.set(form, editorFingerprint(form));
    const status = document.createElement('p');
    status.className = 'editor-save-status';
    status.setAttribute('role', 'status');
    status.setAttribute('aria-live', 'polite');
    const submit = form.querySelector('button[type="submit"]');
    if (submit) submit.before(status);
    form.dataset.editorReady = '1';
    if (form.id === 'profile-form') updateCandidateProfilePreview(form);
    if (form.id === 'vacancy-form' && form.dataset.draftId) {
      draftServerBaselines.set(form, draftFields(form));
      setEditorStatus(form, 'Черновик на сервере. Дальнейшие изменения сохраняются автоматически.');
    }
  });
}
function editorChanged(form) {
  if (!form || !editorBaselines.has(form) || editorSubmitting.has(form)) return;
  if (form.id === 'vacancy-form' && form.dataset.draftId && !form.dataset.editId) {
    scheduleVacancyAutosave(form);
    return;
  }
  setEditorStatus(form, editorIsDirty(form)
    ? 'Есть несохранённые изменения. Нажмите «Сохранить», прежде чем уходить из раздела.'
    : '');
  if (form.id === 'profile-form') updateCandidateProfilePreview(form);
}
function editorSaved(form) {
  editorBaselines.set(form, editorFingerprint(form));
  setEditorStatus(form, 'Изменения сохранены.');
}
function mayLeaveEditor() {
  const form = currentEditor();
  if (!form) return true;
  if (editorSubmitting.has(form) || draftAutoSaving.has(form)) {
    toast('Сохранение ещё выполняется. Дождитесь результата.', true);
    return false;
  }
  if (!editorIsDirty(form)) {
    cancelDraftAutosave(form);
    return true;
  }
  const confirmed = confirm('В форме остались несохранённые изменения. Выйти без сохранения?');
  if (confirmed) cancelDraftAutosave(form);
  return confirmed;
}
function beginEditorSave(form) {
  if (editorSubmitting.has(form)) return null;
  editorSubmitting.add(form);
  const submit = form.querySelector('button[type="submit"]');
  if (submit) {
    submit.disabled = true;
    submit.setAttribute('aria-busy', 'true');
  }
  setEditorStatus(form, 'Сохраняем изменения…');
  // Prevent edits to the submitted snapshot while the request is pending.
  // Unlike disabling inputs, inert does not change the FormData fingerprint.
  form.inert = true;
  return submit;
}
function endEditorSave(form, submit) {
  editorSubmitting.delete(form);
  form.inert = false;
  if (submit?.isConnected) {
    submit.disabled = false;
    submit.removeAttribute('aria-busy');
  }
}
function editorSaveFailure(form, error, isNewVacancy = false) {
  const lostConnection = error?.networkFailure;
  const text = lostConnection
    ? (isNewVacancy
      ? 'Соединение прервалось. Вакансия могла сохраниться. Проверьте «Мои вакансии» перед повторной публикацией. Поля остались заполнены.'
      : 'Соединение прервалось. Данные в форме сохранены на экране, но результат сервера неизвестен. Проверьте соединение перед повтором.')
    : 'Не удалось сохранить: ' + String(error?.message || 'Ошибка сервера') +
      '. Введённые данные остались в форме.';
  setEditorStatus(form, text, true);
  toast(text, true);
}
window.addEventListener('beforeunload', event => {
  if (!editorIsDirty(currentEditor())) return;
  event.preventDefault();
  event.returnValue = '';
});

function base64urlToBuffer(value) {
  const text = String(value || '');
  const padded = text.replace(/-/g,'+').replace(/_/g,'/') + '='.repeat((4 - (text.length % 4)) % 4);
  const binary = atob(padded);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return bytes.buffer;
}
function bufferToBase64url(value) {
  const bytes = new Uint8Array(value || new ArrayBuffer(0));
  let binary = '';
  for (let i = 0; i < bytes.length; i += 1) binary += String.fromCharCode(bytes[i]);
  return btoa(binary).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');
}
function decodeWebAuthnOptions(raw) {
  const options = JSON.parse(JSON.stringify(raw || {}));
  options.challenge = base64urlToBuffer(options.challenge);
  if (options.user?.id) options.user.id = base64urlToBuffer(options.user.id);
  if (Array.isArray(options.excludeCredentials)) {
    options.excludeCredentials = options.excludeCredentials.map(item => ({...item,id:base64urlToBuffer(item.id)}));
  }
  if (Array.isArray(options.allowCredentials)) {
    options.allowCredentials = options.allowCredentials.map(item => ({...item,id:base64urlToBuffer(item.id)}));
  }
  return options;
}
function webAuthnCredentialPayload(credential) {
  const response = credential.response || {};
  const payload = {
    id: credential.id,
    rawId: bufferToBase64url(credential.rawId),
    type: credential.type,
    authenticatorAttachment: credential.authenticatorAttachment || null,
    clientExtensionResults: credential.getClientExtensionResults ? credential.getClientExtensionResults() : {},
    response: {clientDataJSON: bufferToBase64url(response.clientDataJSON)}
  };
  if (response.attestationObject) {
    payload.response.attestationObject = bufferToBase64url(response.attestationObject);
    payload.response.transports = response.getTransports ? response.getTransports() : [];
  } else {
    payload.response.authenticatorData = bufferToBase64url(response.authenticatorData);
    payload.response.signature = bufferToBase64url(response.signature);
    payload.response.userHandle = response.userHandle ? bufferToBase64url(response.userHandle) : null;
  }
  return payload;
}
function resetMfaState() {
  state.mfaChallenge = null;
  state.mfaMethod = null;
  state.mfaCodeLength = 8;
  state.mfaPublicKey = null;
  state.mfaTotpFallback = false;
}
async function completeAdminPasskeyLogin() {
  const btn = $('#auth-submit');
  btn.disabled = true;
  try {
    if (!window.PublicKeyCredential || !navigator.credentials?.get) throw new Error('Этот браузер не поддерживает passkey/WebAuthn.');
    if (!state.mfaChallenge || !state.mfaPublicKey) throw new Error('Passkey-запрос устарел. Войдите заново.');
    const credential = await navigator.credentials.get({publicKey:decodeWebAuthnOptions(state.mfaPublicKey)});
    const data = await api('/api/admin/mfa/webauthn/verify',{
      method:'POST',
      body:JSON.stringify({challenge_id:state.mfaChallenge,credential:webAuthnCredentialPayload(credential)})
    });
    resetMfaState();
    $('#auth-dialog').close();
    state.user = data.user;
    state.tab = 'overview';
    await showDashboard(true);
    await loadPublicJobs();
    toast('Вход администратора подтверждён passkey.');
  } catch(e) {
    const message = e?.name === 'NotAllowedError'
      ? 'Подтверждение passkey отменено или не завершено.'
      : (e.message || 'Не удалось подтвердить passkey.');
    $('#auth-message').textContent = message;
  } finally {
    btn.disabled = false;
  }
}
async function switchAdminMfaToTotp() {
  if (!state.mfaChallenge) return;
  const data = await api('/api/admin/mfa/webauthn/fallback-totp',{
    method:'POST',
    body:JSON.stringify({challenge_id:state.mfaChallenge})
  });
  state.mfaChallenge = data.challenge_id;
  state.mfaMethod = 'totp';
  state.mfaCodeLength = 6;
  state.mfaPublicKey = null;
  state.mfaTotpFallback = false;
  updateAuth();
  $('#auth-mfa-code')?.focus();
}
async function registerAdminPasskey() {
  if (!window.PublicKeyCredential || !navigator.credentials?.create) throw new Error('Этот браузер не поддерживает passkey/WebAuthn.');
  const start = await api('/api/admin/passkeys/register/options',{method:'POST'});
  const credential = await navigator.credentials.create({publicKey:decodeWebAuthnOptions(start.public_key)});
  await api('/api/admin/passkeys/register/verify',{
    method:'POST',
    body:JSON.stringify({
      challenge_id:start.challenge_id,
      credential:webAuthnCredentialPayload(credential),
      label:'Passkey администратора'
    })
  });
  toast('Passkey администратора зарегистрирован.');
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
function publicSignupClosed() {
  return document.querySelector('meta[name="prelaunch-signup-closed"]')?.content === 'yes';
}
function openAuth(mode = 'register', role = 'candidate') {
  if (mode === 'register' && publicSignupClosed()) {
    toast('Регистрация временно закрыта до утверждения юридических документов.', true);
    return;
  }
  state.mode = mode;
  state.role = role;
  resetMfaState();
  $('#auth-form').reset();
  updateAuth();
  $('#auth-dialog').showModal();
  (mode === 'register' ? $('#auth-name') : $('#auth-email')).focus();
}
function updateAuth() {
  const reg = state.mode === 'register';
  const employer = state.role === 'employer';
  const mfa = Boolean(state.mfaChallenge);
  $('.auth-fields')?.classList.toggle('hidden', mfa);
  $('#auth-mfa-panel')?.classList.toggle('hidden', !mfa);
  if (mfa) {
    $('#signup-role').classList.add('hidden');
    $('#auth-name-row').classList.add('hidden');
    $('#auth-company-row').classList.add('hidden');
    $('#password-hint').classList.add('hidden');
    $('#auth-route').classList.add('hidden');
    const totp = state.mfaMethod === 'totp';
    const passkey = state.mfaMethod === 'webauthn';
    $('#auth-kicker').textContent = passkey ? 'PASSKEY' : 'ДВУХФАКТОРНЫЙ ВХОД';
    $('#auth-title').textContent = 'Подтвердите вход';
    $('#auth-intro').textContent = passkey
      ? 'Пароль принят. Подтвердите вход через Windows Hello, Touch ID, телефон или аппаратный ключ.'
      : totp
        ? 'Пароль принят. Введите код из приложения Authenticator.'
        : 'Пароль принят. Для входа администратора нужен второй фактор.';
    $('#auth-guidance').textContent = passkey
      ? 'Passkey привязан к домену СТАЖНО и не передаёт биометрию на сервер.'
      : totp
        ? 'Введите текущий 6-значный код. Он меняется примерно каждые 30 секунд.'
        : 'Код одноразовый и действует 5 минут.';
    const mfaText = $('#auth-mfa-text');
    if (mfaText) mfaText.textContent = passkey
      ? 'Нажмите кнопку ниже и подтвердите вход на своём устройстве.'
      : totp
        ? 'Откройте приложение Authenticator и введите текущий 6-значный код.'
        : 'Мы отправили одноразовый 8-значный код на email администратора. Код действует 5 минут.';
    $('#auth-mfa-code-field')?.classList.toggle('hidden', passkey);
    $('#auth-mfa-totp-fallback')?.classList.toggle('hidden', !(passkey && state.mfaTotpFallback));
    const mfaNote = $('#auth-mfa-note');
    if (mfaNote) mfaNote.textContent = passkey
      ? 'Приватный ключ остаётся на вашем устройстве.'
      : 'После 5 неверных попыток код будет аннулирован.';
    const mfaCode = $('#auth-mfa-code');
    if (mfaCode && !passkey) {
      const length = totp ? 6 : 8;
      mfaCode.minLength = length;
      mfaCode.maxLength = length;
      mfaCode.pattern = '[0-9]{' + length + '}';
      mfaCode.placeholder = totp ? '000000' : '00000000';
    }
    $('#auth-submit').textContent = passkey ? 'Подтвердить passkey →' : 'Подтвердить вход →';
    $('#auth-switch').innerHTML = '<button type="button" data-mfa-cancel>Вернуться ко входу по email и паролю</button>';
    const message = $('#auth-message'); if (message) message.textContent = '';
    return;
  }
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
  const legallyApproved = document.querySelector('meta[name="legal-profile-ready"]')?.content === 'yes';
  $('#auth-terms-row')?.classList.toggle('hidden', !(reg && legallyApproved));
  if (!reg) {
    const checkbox = $('#auth-terms-accepted');
    if (checkbox) checkbox.checked = false;
  }
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
  $('#auth-switch').innerHTML = reg
    ? 'Уже есть аккаунт? <button type="button" data-switch="login">Войти</button>'
    : publicSignupClosed()
      ? 'Новая регистрация временно закрыта до юридического утверждения.'
      : 'Ещё нет аккаунта? <button type="button" data-switch="register">Зарегистрироваться</button>';
}
async function submitAuth(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const message = $('#auth-message');
  const showError = (text, field = null) => {
    if (message) message.textContent = text;
    if (field) field.focus();
  };
  if (state.mfaChallenge) {
    if (state.mfaMethod === 'webauthn') {
      await completeAdminPasskeyLogin();
      return;
    }
    const code = ($('#auth-mfa-code')?.value || '').trim();
    const expectedLength = state.mfaMethod === 'totp' ? 6 : 8;
    const codePattern = expectedLength === 6 ? /^\d{6}$/ : /^\d{8}$/;
    if (!codePattern.test(code)) {
      showError(
        state.mfaMethod === 'totp'
          ? 'Введите 6 цифр из приложения Authenticator.'
          : 'Введите 8 цифр из письма.',
        $('#auth-mfa-code')
      );
      return;
    }
    const btn = $('#auth-submit');
    btn.disabled = true;
    if (message) message.textContent = '';
    try {
      const data = await api('/api/admin/mfa/verify', {
        method:'POST',
        body:JSON.stringify({challenge_id:state.mfaChallenge, code})
      });
      resetMfaState();
      $('#auth-dialog').close();
      state.user = data.user;
      state.tab = 'overview';
      await showDashboard(true);
      await loadPublicJobs();
      toast('Вход администратора подтверждён.');
    } catch(e) {
      showError(e.message || 'Не удалось подтвердить код.', $('#auth-mfa-code'));
    } finally {
      btn.disabled = false;
    }
    return;
  }

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
    const approved = document.querySelector('meta[name="legal-profile-ready"]')?.content === 'yes';
    if (approved && !$('#auth-terms-accepted')?.checked) {
      showError('Примите актуальное Пользовательское соглашение для создания аккаунта.', $('#auth-terms-accepted'));
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
    if (document.querySelector('meta[name="legal-profile-ready"]')?.content === 'yes') {
      body.terms_accepted = Boolean($('#auth-terms-accepted')?.checked);
      body.terms_version = document.querySelector('meta[name="legal-terms-version"]')?.content || '';
    }
  }
  const btn = $('#auth-submit'); btn.disabled = true;
  if (message) message.textContent = '';
  try {
    const data = await api(state.mode === 'register' ? '/api/register' : '/api/login', {method:'POST', body:JSON.stringify(body)});
    if (data.mfa_required) {
      state.mfaChallenge = data.challenge_id;
      state.mfaMethod = data.mfa_method || 'email';
      state.mfaCodeLength = Number(data.code_length || (state.mfaMethod === 'totp' ? 6 : 8));
      state.mfaPublicKey = data.public_key || null;
      state.mfaTotpFallback = Boolean(data.totp_fallback);
      updateAuth();
      $('#auth-mfa-code').value = '';
      if (state.mfaMethod === 'webauthn') $('#auth-submit').focus();
      else $('#auth-mfa-code').focus();
      return;
    }
    $('#auth-dialog').close(); state.user = data.user;
    state.tab = state.mode === 'register'
      ? (data.user.role === 'candidate' ? 'profile' : data.user.role === 'employer' ? 'create' : 'overview')
      : 'overview';
    await showDashboard(true);
    // Public cards are role-dependent too. Refresh before reopening the
    // chosen vacancy so guest actions never survive a successful login.
    await loadPublicJobs();
    // Resume only the chosen vacancy after login, never submit an application
    // without a new explicit click. Newly registered candidates finish their
    // short profile first; profile save resumes the same vacancy below.
    if (data.user.role === 'candidate' && state.mode === 'login') {
      resumePendingApplicationVacancy();
    } else if (data.user.role !== 'candidate') {
      state.pendingApplicationVacancyId = null;
    }
    toast(state.mode === 'register'
      ? (data.user.role === 'candidate' ? 'Аккаунт создан. Заполните короткий профиль.' : data.user.role === 'employer' ? 'Аккаунт создан. Можно разместить первую вакансию.' : 'Аккаунт создан.')
      : 'Вы вошли в аккаунт.');
  } catch(e) {
    showError(e.message || 'Не удалось выполнить вход. Проверьте данные и попробуйте ещё раз.');
  } finally { btn.disabled = false; }
}
let lastActionRefreshAt = 0;
function actionCountForTab(tab) {
  const summary = state.actionSummary;
  if (!summary || summary.role !== state.user?.role) return 0;
  if (summary.role === 'candidate') {
    if (tab === 'invitations') return Number(summary.invitations_pending || 0);
    if (tab === 'changes') return Number(summary.vacancy_changes_unread || 0);
  }
  if (summary.role === 'employer') {
    if (tab === 'applications') return Number(summary.applications_to_review || 0);
    if (tab === 'invitations') return Number(summary.consents_to_continue || 0) +
      Number(summary.introductions_to_finish || 0);
  }
  return 0;
}
function updateActionBadges() {
  const total = state.user && state.actionSummary && state.user.role === state.actionSummary.role
    ? Number(state.actionSummary.action_count || 0) : 0;
  const account = $('#account-open');
  const badge = $('#account-action-count');
  if (account && badge) {
    badge.hidden = total <= 0;
    badge.textContent = total > 99 ? '99+' : String(total);
    if (total > 0) account.setAttribute('aria-label', 'Мой кабинет, действий требуют внимания: ' + total);
    else account.removeAttribute('aria-label');
  }
  document.querySelectorAll('[data-action-count-for]').forEach(badge => {
    const count = actionCountForTab(badge.dataset.actionCountFor);
    badge.hidden = count <= 0;
    badge.textContent = count > 99 ? '99+' : String(count);
    badge.setAttribute('aria-label', 'Требует действия: ' + count);
  });
  document.querySelectorAll('[data-dashboard-tab-select] option[data-base-label]').forEach(option => {
    const count = actionCountForTab(option.value);
    option.textContent = option.dataset.baseLabel + (count ? ' · ' + count : '');
  });
}
async function refreshActionSummary() {
  const ownerId = state.user?.id;
  if (!ownerId) {
    state.actionSummary = null;
    updateActionBadges();
    return;
  }
  try {
    const summary = await api('/api/account/action-summary');
    if (state.user?.id !== ownerId) return;
    state.actionSummary = summary.role === state.user.role ? summary : null;
  } catch {
    // A notification-count error must not prevent using the account.
    if (state.user?.id !== ownerId) return;
    state.actionSummary = null;
  }
  lastActionRefreshAt = Date.now();
  updateActionBadges();
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
  const previousUser = state.user;
  const previousUserId = previousUser?.id;
  try { const data = await api('/api/me'); state.user = data.user; }
  catch (error) {
    // A temporary outage must not erase an open form or falsely log the
    // user out. A real 401/403 still clears the session immediately.
    state.user = previousUser && (error.networkFailure || error.httpStatus >= 500)
      ? previousUser : null;
  }
  if (state.user?.id !== previousUserId) {
    state.actionSummary = null;
    state.employerWorkQueueView = null;
  }
  syncEmployerMatchAccount();
  updateActionBadges();
  $('#guest-actions').classList.toggle('hidden', !!state.user);
  $('#member-actions').classList.toggle('hidden', !state.user);
  $('#mobile-guest-actions')?.classList.toggle('hidden', !!state.user);
  $('#mobile-member-actions')?.classList.toggle('hidden', !state.user);
  $('#dashboard').classList.toggle('hidden', !state.user);
  // Signed-in phones already have a bottom action bar and a dashboard selector.
  // Keep the extra public quick-nav for guests only to avoid three menus at once.
  document.body.classList.toggle('member-logged-in', Boolean(state.user));
}
async function showDashboard(scroll = false) {
  if (state.user?.role !== 'employer' || state.tab !== 'vacancies' || !state.activeVacancy) {
    resetEmployerCandidateComparison();
  }
  // A new destination supersedes any queued search in the previous view.
  clearTimeout(employerInvitationSearchTimer);
  clearTimeout(candidateInvitationSearchTimer);
  await reloadUser(); if (!state.user) { openAuth('login'); return; }
  await refreshActionSummary();
  $('#welcome').textContent = `Здравствуйте, ${state.user.name.split(' ')[0]}!`;
  $('#account-subtitle').textContent = ({candidate:'Вакансии, отклики и приглашения — в одном месте.',employer:'Вакансии, отклики и знакомства с кандидатами — в одном месте.',admin:'Обзор работы платформы.'})[state.user.role];
  if (state.user.role === 'candidate') await renderCandidate();
  if (state.user.role === 'employer') await renderEmployer();
  if (state.user.role === 'admin') await renderAdmin();
  prepareEditorForms();
  const returningToQueue = state.user.role === 'employer' && state.tab === 'overview' &&
    state.employerWorkQueueView?.returnPending === true;
  if (returningToQueue) {
    const view = state.employerWorkQueueView;
    view.returnPending = false;
    requestAnimationFrame(() => {
      if (Number(state.user?.id) !== view.ownerId || state.user?.role !== 'employer' || state.tab !== 'overview') return;
      const queue = document.querySelector('#employer-workqueue');
      if (!queue) return;
      const top = window.scrollY + queue.getBoundingClientRect().top;
      const maximum = Math.max(0,document.documentElement.scrollHeight - window.innerHeight);
      window.scrollTo({top:Math.max(0,Math.min(maximum,top + (Number(view.scrollOffset) || 0))),behavior:'auto'});
    });
  } else if (scroll) $('#dashboard').scrollIntoView({behavior:'smooth',block:'start'});
}
function resumePendingApplicationVacancy() {
  const id = Number(state.pendingApplicationVacancyId);
  if (!Number.isSafeInteger(id) || id <= 0 || state.user?.role !== 'candidate') return;
  state.pendingApplicationVacancyId = null;
  // Opening the vacancy is read-only: user must choose "Откликнуться" again.
  document.dispatchEvent(new CustomEvent('stazhno:resume-vacancy', {detail:{id}}));
}
function tabsMarkup(items, heading, subtitle) {
  const icons = {
    overview:'⌂',profile:'●',offers:'↗',invitations:'✉',favorites:'♡',
    applications:'✓',changes:'↻',email:'@',vacancies:'▤',create:'＋',edit:'✎',company:'◆',security:'🔒'
  };
  const roleLabel = state.user?.role === 'employer' ? 'Работодатель' : state.user?.role === 'candidate' ? 'Соискатель' : 'Администратор';
  return `<aside class="panel side-panel">
    <div class="dashboard-identity"><span class="dashboard-avatar" aria-hidden="true">${esc((state.user?.name||roleLabel).trim().charAt(0).toUpperCase())}</span><div><span>${esc(roleLabel)}</span><strong>${esc(subtitle)}</strong></div></div>
    <span class="section-kicker dashboard-menu-kicker">${esc(heading)}</span>
    <label class="dashboard-mobile-switch"><span>Раздел кабинета</span><select data-dashboard-tab-select aria-label="Раздел личного кабинета">${items.map(t => `<option value="${esc(t.id)}" ${state.tab === t.id ? 'selected' : ''} data-base-label="${esc(t.label)}">${esc(t.label)}${actionCountForTab(t.id) ? ' · '+actionCountForTab(t.id) : ''}</option>`).join('')}</select></label>
    <nav class="dashboard-tabs" aria-label="Разделы личного кабинета">${items.map(t => `<button type="button" data-tab="${esc(t.id)}" class="${state.tab === t.id ? 'active' : ''}"><span class="dashboard-tab-icon" aria-hidden="true">${icons[t.id]||'•'}</span><span>${esc(t.label)}</span><span class="dashboard-action-count" data-action-count-for="${esc(t.id)}" ${actionCountForTab(t.id) ? '' : 'hidden'} aria-label="Требует действия: ${actionCountForTab(t.id)}">${actionCountForTab(t.id) || ''}</span></button>`).join('')}</nav>
    <div class="dashboard-side-note"><span>Профессиональное сообщество</span><small><a href="/community">Участники и обмен опытом</a></small><small><a href="/community/connections">Мои профессиональные связи</a></small>${state.user?.role === 'candidate' ? '<small><a href="/community/profile">Мой публичный профиль</a></small>' : ''}</div><div class="dashboard-side-note"><span>Приватность</span><small>Контакты открываются только в сценарии знакомства.</small></div>
  </aside>`;
}
function candidateProfileHealth(profile = {}) {
  // Only profession and city are required. Optional biography, salary and
  // qualifications must never make a searchable profile look incomplete.
  const hasProfession = Boolean(String(profile.profession || '').trim());
  const hasCity = Boolean(String(profile.city || '').trim());
  const percent = (Number(hasProfession) + Number(hasCity)) * 50;
  const next = !hasProfession ? 'Укажите профессию, чтобы начать подбор.'
    : !hasCity ? 'Укажите город, чтобы начать подбор.'
    : 'Профессия и город сохранены. Можно искать вакансии.';
  const hasProfessionalDetails = Boolean(
    String(profile.skills || '').trim() ||
    String(profile.specializations || '').trim() ||
    String(profile.about || '').trim() ||
    String(profile.achievements || '').trim() ||
    Number(profile.experience_years || 0) > 0 ||
    (Array.isArray(profile.work_history) && profile.work_history.some(role =>
      String(role?.position || role?.period || role?.duties || '').trim()))
  );
  return {percent, next, hasProfessionalDetails};
}
function candidateWorkSectionSummary(profile = {}) {
  const roles = Array.isArray(profile.work_history) ? profile.work_history.filter(role =>
    String(role?.position || role?.period || role?.duties || '').trim()) : [];
  if (roles.length) return `Мест работы: ${roles.length}`;
  if (Number(profile.experience_years || 0) > 0 ||
      String(profile.achievements || '').trim() || String(profile.about || '').trim()) {
    return 'Опыт описан';
  }
  return 'Можно заполнить позже';
}
function candidateTrainingSectionSummary(profile = {}) {
  const courses = Array.isArray(profile.courses) ? profile.courses.filter(course =>
    String(course?.title || course?.provider || course?.year || '').trim() || course?.has_certificate) : [];
  if (courses.length) return `Курсов и сертификатов: ${courses.length}`;
  if (String(profile.education || '').trim() || String(profile.specializations || '').trim()) {
    return 'Сведения добавлены';
  }
  return 'Можно заполнить позже';
}
function candidateSearchReadiness(profile = {}) {
  const missingFields = ['profession','city'].filter(field => !String(profile[field] || '').trim());
  const active = profile.is_active !== 0 && profile.is_active !== false;
  const hasRequiredFields = missingFields.length === 0;
  let title = 'Профиль участвует в подборе';
  let description = 'Профессия и город указаны. Остальные сведения можно дополнить по желанию.';
  if (!active) {
    title = 'Подбор на паузе';
    description = 'Профиль скрыт из подбора. Можно смотреть все вакансии и продолжать уже начатые знакомства.';
  } else if (!hasRequiredFields) {
    title = missingFields.length === 2 ? 'Укажите профессию и город'
      : missingFields[0] === 'profession' ? 'Укажите профессию' : 'Укажите город';
    description = 'Профессия и город нужны для подбора вакансий и отправки откликов. Остальные сведения можно дополнить позже.';
  }
  return {
    ready: active && hasRequiredFields,
    active,
    hasRequiredFields,
    missingFields,
    nextField: !active ? 'is_active' : missingFields[0] || null,
    title,
    description
  };
}
function candidateOffersEmptyMarkup(readiness, compact = false) {
  const buttonClass = compact ? 'btn btn-outline btn-tiny' : 'btn btn-outline';
  if (!readiness.ready) {
    return `<div class="empty-state"><strong>${esc(readiness.title)}</strong><p>${esc(readiness.description)}</p><button type="button" class="${buttonClass}" data-action="open-candidate-profile" data-profile-field="${esc(readiness.nextField)}">${readiness.active ? 'Дополнить профиль' : 'Настроить подбор'}</button> <a class="${buttonClass}" href="#jobs">Посмотреть все вакансии</a></div>`;
  }
  return `<div class="empty-state"><p>${compact ? 'Точных совпадений пока нет.' : 'Подходящих вакансий пока нет. Можно уточнить условия поиска или посмотреть все открытые вакансии.'}</p>${compact ? '' : `<button type="button" class="${buttonClass}" data-tab="profile">Уточнить профиль</button> `}<a class="${buttonClass}" href="#jobs">Посмотреть все вакансии</a></div>`;
}
const accountSecurityLabels = {
  login_success:'Вход в аккаунт',
  login_failed:'Неудачная попытка входа',
  password_reset_completed:'Пароль восстановлен',
  email_verified_via_password_reset:'Email подтверждён через восстановление пароля',
  password_change_failed:'Неверный текущий пароль при смене',
  password_changed_all_sessions_revoked:'Пароль изменён, старые сессии завершены',
  other_sessions_revoked:'Другие сессии завершены',
  pending_auth_challenges_revoked:'Незавершённые проверки входа аннулированы',
  session_idle_expired:'Сессия завершена по неактивности',
  admin_mfa_success:'Второй фактор администратора подтверждён',
  admin_mfa_failed:'Ошибка второго фактора администратора',
  admin_passkey_registered:'Passkey администратора зарегистрирован',
  admin_passkey_deleted:'Passkey администратора удалён',
  admin_passkey_success:'Вход администратора подтверждён passkey',
  admin_passkey_failed:'Ошибка подтверждения passkey',
  admin_passkey_fallback_totp:'Выбран резервный код Authenticator',
  new_device_login:'Вход с нового устройства',
  admin_email_migrated:'Email администратора изменён'
};
function accountSecurityEventMarkup(item) {
  const label = accountSecurityLabels[item.event_type] || 'Событие безопасности';
  return `<div class="account-security-event"><span class="account-security-event-dot" aria-hidden="true"></span><div><strong>${esc(label)}</strong><small>${esc(item.created_at || '')}</small></div></div>`;
}
function accountSecuritySessionMarkup(item) {
  const seen = item.last_seen_at || item.authenticated_at || '';
  const device = item.device_label || 'Неизвестное устройство';
  return `<div class="account-security-session">
    <div><strong>${item.current ? 'Этот браузер' : esc(device)}</strong><small>${item.current ? esc(device) + ' · ' : ''}Последняя активность: ${esc(seen)}</small></div>
    ${item.current ? '<span class="status success">Текущая</span>' : `<button type="button" class="btn btn-outline btn-small" data-action="revoke-session" data-session-id="${esc(item.id)}">Завершить</button>`}
  </div>`;
}
const rightsKindLabels = Object.freeze({
  access: 'Получить сведения об обработке',
  correction: 'Исправить неточные данные',
  deletion: 'Запросить удаление данных',
  stop_processing: 'Запросить прекращение обработки'
});
const rightsStatusLabels = Object.freeze({
  received: 'Получено',
  in_review: 'Рассматривается',
  completed: 'Решение принято',
  declined: 'Отказ после рассмотрения'
});
function rightsDate(value) { return esc(String(value || '').slice(0, 10)); }
function accountPrivacyRightsMarkup(requests, available) {
  const rows = Array.isArray(requests) ? requests.slice(0, 50) : [];
  const options = Object.entries(rightsKindLabels).map(([value,label]) =>
    '<option value="' + esc(value) + '">' + esc(label) + '</option>'
  ).join('');
  const history = !available ? '<p class="muted">Не удалось загрузить историю запросов.</p>' :
    rows.length ? rows.map(item =>
      '<div class="privacy-rights-record"><span><strong>' +
      esc(rightsKindLabels[item.kind] || 'Обращение') +
      '</strong><small>От ' + rightsDate(item.submitted_at) +
      ' · № ' + esc(String(item.request_key || '').slice(0, 8)) +
      '</small></span><span class="status">' +
      esc(rightsStatusLabels[item.status] || 'Обрабатывается') +
      '</span></div>'
    ).join('') : '<p class="muted">Обращений пока нет.</p>';
  return '<section class="panel account-privacy-rights">' +
    '<span class="section-kicker">МОИ ПЕРСОНАЛЬНЫЕ ДАННЫЕ</span>' +
    '<h3>Обращение к оператору</h3>' +
    '<p class="muted">Можно запросить сведения об обработке, исправление, удаление или прекращение обработки данных. Заявка сохраняется в кабинете. Оператор рассматривает её вручную с учётом закона — отправка запроса не удаляет аккаунт автоматически.</p>' +
    '<p class="muted">Если не можете войти, используйте контакт из <a href="/privacy" target="_blank" rel="noopener">Политики персональных данных</a>. Пока там тестовые реквизиты, раздел предназначен только для проверки интерфейса.</p>' +
    '<p><a href="/api/account/data-export" class="btn btn-outline" download>Скачать основные данные аккаунта (JSON)</a></p>' +
    '<p class="muted">Выгрузка доступна только после входа. Она содержит основные данные вашего аккаунта и историю работы, но не является полным юридическим ответом. Для полного запроса выберите «Получить сведения об обработке». Скачанный файл хранится на вашем устройстве: берегите его от посторонних.</p>' +
    '<form id="privacy-rights-request-form" class="account-security-form">' +
      '<div class="field"><label for="privacy-rights-kind">Какое действие требуется?</label>' +
      '<select id="privacy-rights-kind" name="kind" required><option value="">Выберите вид обращения</option>' +
      options + '</select></div>' +
      '<p class="auth-message" id="privacy-rights-message" role="status" aria-live="polite"></p>' +
      '<button type="submit" class="btn btn-outline">Отправить запрос оператору</button>' +
    '</form><h4>История обращений</h4>' +
    '<div id="privacy-rights-history" aria-live="polite">' + history + '</div></section>';
}
async function renderAccountSecurity(target) {
  const [data, privacyRequests] = await Promise.all([
    api('/api/account/security'),
    api('/api/account/privacy-requests').catch(() => null)
  ]);
  const events = Array.isArray(data.events) ? data.events : [];
  const sessions = Array.isArray(data.sessions) ? data.sessions : [];
  target.innerHTML = `<div class="account-security-stack">
    <section class="panel account-security-hero">
      <span class="section-kicker">БЕЗОПАСНОСТЬ АККАУНТА</span>
      <h3>Контроль доступа</h3>
      <p class="muted">Смена пароля завершает все старые сессии. Другие устройства можно отключить отдельно, не выходя из текущего браузера.</p>
      <div class="account-security-summary">
        <div><strong>${Number(data.active_sessions || 0)}</strong><span>активных сессий</span></div>
        <div><strong>${data.email_verified ? '✓' : '!'}</strong><span>${data.email_verified ? 'Email подтверждён' : 'Email не подтверждён'}</span></div>
        <div><strong>15+</strong><span>минимум символов пароля</span></div>
      </div>
      <button type="button" class="btn btn-outline" data-action="revoke-other-sessions">Завершить все другие сессии</button>
    </section>
    <section class="panel account-security-sessions">
      <span class="section-kicker">АКТИВНЫЕ СЕССИИ</span>
      <h3>Устройства с доступом к аккаунту</h3>
      <p class="muted">Текущий браузер отмечен отдельно. Любую другую сессию можно завершить точечно.</p>
      <div class="account-security-session-list">${sessions.length ? sessions.map(accountSecuritySessionMarkup).join('') : '<div class="empty-state">Активных сессий не найдено.</div>'}</div>
    </section>
    <section class="panel account-security-password">
      <span class="section-kicker">ПАРОЛЬ</span>
      <h3>Сменить пароль</h3>
      <p class="muted">Нужен текущий пароль. После успешной смены этот браузер получит новую сессию, а остальные устройства потеряют доступ.</p>
      <form id="security-password-form" class="account-security-form">
        <div class="field"><label for="security-current-password">Текущий пароль</label><input id="security-current-password" name="current_password" type="password" autocomplete="current-password" maxlength="128" required></div>
        <div class="field"><label for="security-new-password">Новый пароль</label><input id="security-new-password" name="new_password" type="password" autocomplete="new-password" minlength="15" maxlength="128" required><small class="field-help">Не менее 15 символов. Лучше использовать длинную уникальную фразу.</small></div>
        <div class="field"><label for="security-new-password-confirm">Повторите новый пароль</label><input id="security-new-password-confirm" name="new_password_confirm" type="password" autocomplete="new-password" minlength="15" maxlength="128" required></div>
        <p class="auth-message" id="security-password-message" role="alert" aria-live="polite"></p>
        <button type="submit" class="btn btn-primary">Сменить пароль и завершить старые сессии →</button>
      </form>
    </section>
    ${accountPrivacyRightsMarkup(privacyRequests?.requests, Boolean(privacyRequests))}
    <section class="panel account-security-events">
      <span class="section-kicker">ЖУРНАЛ</span>
      <h3>Последние события безопасности</h3>
      <div class="account-security-event-list">${events.length ? events.map(accountSecurityEventMarkup).join('') : '<div class="empty-state">Событий безопасности пока нет.</div>'}</div>
    </section>
  </div>`;
}
function resumeRoleFields(item = {}, index = 0) {
  return `<fieldset class="resume-work-entry" data-resume-role>
    <legend>Место работы ${index + 1}</legend>
    <div class="form-grid">
      <div class="field"><label>Должность<input data-role-position maxlength="120" value="${esc(item.position || '')}" placeholder="Например, бухгалтер" autocomplete="off"></label></div>
      <div class="field"><label>Период работы<input data-role-period maxlength="80" value="${esc(item.period || '')}" placeholder="Например, 2016–2024" autocomplete="off"></label></div>
      <div class="field wide"><label>Обязанности и результаты<textarea data-role-duties maxlength="350" rows="3" placeholder="Что делали и каких результатов достигли">${esc(item.duties || '')}</textarea></label></div>
    </div>
    <button type="button" class="btn btn-outline btn-tiny" data-action="remove-resume-role">Удалить эту запись</button>
  </fieldset>`;
}
function resumeCourseFields(item = {}, index = 0) {
  return `<fieldset class="resume-course-entry" data-resume-course>
    <legend>Обучение ${index + 1}</legend>
    <div class="form-grid">
      <div class="field"><label>Название курса или программы<input data-course-title maxlength="140" value="${esc(item.title || '')}" placeholder="Например, Бухгалтерский учёт в 1С" autocomplete="off"></label></div>
      <div class="field"><label>Организация (необязательно)<input data-course-provider maxlength="120" value="${esc(item.provider || '')}" placeholder="Например, учебный центр" autocomplete="off"></label></div>
      <div class="field"><label>Год завершения (необязательно)<input data-course-year type="number" inputmode="numeric" min="1950" max="2100" value="${item.year == null ? '' : Number(item.year)}" placeholder="Например, 2021"></label></div>
      <div class="field"><label class="resume-certificate-check"><input data-course-certificate type="checkbox" ${item.has_certificate ? 'checked' : ''}>Есть сертификат или удостоверение</label></div>
    </div>
    <button type="button" class="btn btn-outline btn-tiny" data-action="remove-resume-course">Удалить эту запись</button>
  </fieldset>`;
}
function professionalResumeMarkup(profile = {}) {
  const positions = Array.isArray(profile.work_history) ? profile.work_history.slice(0,5) : [];
  const courses = Array.isArray(profile.courses) ? profile.courses.slice(0,6) : [];
  const hasInfo = Number(profile.experience_years || 0) > 0 || profile.education ||
    profile.achievements || positions.length || profile.specializations || courses.length;
  if (!hasInfo) return '<p class="muted">Добавьте историю работы, образование и достижения, чтобы резюме было содержательнее.</p>';
  return `<div class="resume-professional-summary">
    ${Number(profile.experience_years || 0) > 0 ? `<p><strong>Общий стаж:</strong> ${Number(profile.experience_years)} лет</p>` : ''}
    ${profile.education ? `<p><strong>Образование:</strong> ${esc(profile.education)}</p>` : ''}
    ${profile.specializations ? `<p><strong>Специализации:</strong> ${esc(profile.specializations)}</p>` : ''}
    ${positions.length ? `<div class="resume-public-history"><strong>Опыт работы</strong>${positions.map(r=>`<div class="resume-public-job"><b>${esc(r.position)}</b> <span>${esc(r.period)}</span>${r.duties ? `<p>${esc(r.duties)}</p>` : ''}</div>`).join('')}</div>` : ''}
    ${profile.achievements ? `<p><strong>Достижения:</strong> ${esc(profile.achievements)}</p>` : ''}
    ${courses.length ? `<div class="resume-public-courses"><strong>Курсы и повышение квалификации</strong>${courses.map(course=>`<div class="resume-public-course"><b>${esc(course.title)}</b>${course.provider ? `<span>${esc(course.provider)}</span>` : ''}${course.year ? `<span>${Number(course.year)}</span>` : ''}${course.has_certificate ? '<small>Есть документ об обучении (со слов соискателя, не проверен)</small>' : ''}</div>`).join('')}</div>` : ''}
  </div>`;
}
// Printing never calls a server or sends the resume to an external PDF provider.
// Free-text fields are masked even in contact-enabled exports: the opt-in only
// adds the account's verified-visible name, email and saved telephone explicitly.
function resumePrintSafeText(value) {
  return String(value ?? '')
    .replace(/[^\s@]+@[^\s@]+\.[^\s@]+/gi, '[контакт скрыт]')
    .replace(/(?:https?:\/\/|www\.|t\.me\/|wa\.me\/|vk\.com\/|max\.ru\/)\S+/gi, '[ссылка скрыта]')
    .replace(/@[A-Za-z0-9_]{4,}/g, '[контакт скрыт]')
    .replace(/(?:\+?\d[\s().-]*){10,15}/g, '[телефон скрыт]');
}
function resumePrintData(profile = {}) {
  const clean = resumePrintSafeText;
  return {
    ...profile,
    profession: clean(profile.profession),
    city: clean(profile.city),
    skills: clean(profile.skills),
    schedule: clean(profile.schedule),
    employment: clean(profile.employment),
    about: clean(profile.about),
    education: clean(profile.education),
    achievements: clean(profile.achievements),
    specializations: clean(profile.specializations),
    work_history: (Array.isArray(profile.work_history) ? profile.work_history : []).slice(0,5)
      .map(item=>({position:clean(item.position),period:clean(item.period),duties:clean(item.duties)})),
    courses: (Array.isArray(profile.courses) ? profile.courses : []).slice(0,6)
      .map(item=>({...item,title:clean(item.title),provider:clean(item.provider)})),
  };
}
function resumePrintDocumentMarkup(profile = {}, user = {}, includeContacts = false) {
  const saved = resumePrintData(profile);
  const skills = String(saved.skills || '').split(',').map(x=>x.trim()).filter(Boolean);
  const contacts = includeContacts
    ? [user.name ? '<p><strong>Имя:</strong> '+esc(user.name)+'</p>' : '',
       user.email ? '<p><strong>Email:</strong> '+esc(user.email)+'</p>' : '',
       user.phone ? '<p><strong>Телефон:</strong> '+esc(user.phone)+'</p>' : ''].join('')
    : '<p class="resume-print-private">Без имени и контактных данных</p>';
  return '<article class="resume-print-sheet" aria-label="Резюме для печати">' +
    '<header class="resume-print-heading"><span class="resume-print-brand">СТАЖНО.РУ</span>' +
    '<h1>'+esc(saved.profession || 'Профессиональное резюме')+'</h1>' +
    '<p>'+esc(saved.city || 'Город не указан')+'</p></header>' +
    '<div class="resume-print-meta">' +
    '<p><strong>Зарплатные ожидания:</strong> '+(Number(saved.salary_min) > 0 ? esc(candidateSalaryText(saved.salary_min)) : 'не указаны')+'</p>' +
    '<p><strong>График:</strong> '+esc(saved.schedule || 'Любой')+'</p>' +
    (saved.employment ? '<p><strong>Занятость:</strong> '+esc(saved.employment)+'</p>' : '') +
    '</div>' +
    (skills.length ? '<section><h2>Профессиональные навыки</h2><p>'+skills.map(esc).join(' · ')+'</p></section>' : '') +
    '<section><h2>Опыт, образование и квалификация</h2>'+professionalResumeMarkup(saved)+'</section>' +
    (saved.about ? '<section><h2>О себе</h2><p class="resume-print-about">'+esc(saved.about)+'</p></section>' : '') +
    (includeContacts ? '<section class="resume-print-contacts"><h2>Контакты</h2>'+contacts+'</section>' : contacts) +
    '<footer class="resume-print-footer">Сформировано в СТАЖНО.РУ. Сведения об опыте и обучении предоставлены соискателем.</footer>' +
    '</article>';
}
function openResumePrintPreview() {
  if (state.user?.role !== 'candidate' || !state.user.profile) {
    toast('Сначала сохраните резюме.',true);
    return;
  }
  if (editorSubmitting.has(currentEditor())) {
    toast('Профиль ещё сохраняется. Дождитесь результата.', true);
    return;
  }
  document.querySelector('#resume-print-dialog')?.remove();
  const dialog = document.createElement('dialog');
  dialog.id = 'resume-print-dialog';
  dialog.className = 'resume-print-dialog';
  dialog.innerHTML = '<div class="resume-print-actions">' +
    '<h2>Печать или сохранение PDF</h2>' +
    '<p>' + (editorIsDirty(currentEditor())
      ? 'В форме есть несохранённые изменения. В PDF попадёт последняя сохранённая версия. Вернитесь к резюме и сохраните правки, чтобы добавить их в документ.'
      : 'Используются последние сохранённые данные профиля.') + '</p>' +
    '<label class="resume-print-consent"><input type="checkbox" id="resume-print-include-contacts">' +
    '<span>Добавить моё имя, email и телефон в печатное резюме</span></label>' +
    '<p class="resume-print-privacy">По умолчанию контакты скрыты. Проверьте свободные описания на личные сведения перед сохранением PDF. Если включите контакты, они попадут в документ.</p>' +
    '<div class="resume-print-buttons">' +
    '<button type="button" class="btn btn-primary" data-resume-print="print">Печать / сохранить PDF</button>' +
    '<button type="button" class="btn btn-outline" data-resume-print="close">Вернуться к резюме</button>' +
    '</div></div><div id="resume-print-document" class="resume-print-document"></div>';
  const preview = () => {
    const contacts = Boolean(dialog.querySelector('#resume-print-include-contacts')?.checked);
    dialog.querySelector('#resume-print-document').innerHTML =
      resumePrintDocumentMarkup(state.user.profile, state.user, contacts);
  };
  dialog.addEventListener('change', event => {
    if (event.target.id === 'resume-print-include-contacts') preview();
  });
  dialog.addEventListener('click', event => {
    const action = event.target.closest('[data-resume-print]')?.dataset.resumePrint;
    if (action === 'close') dialog.close();
    if (action === 'print') {
      document.body.classList.add('resume-printing');
      window.print();
    }
  });
  dialog.addEventListener('close', () => {
    document.body.classList.remove('resume-printing');
    dialog.remove();
  });
  document.body.append(dialog);
  preview();
  dialog.showModal();
  dialog.querySelector('#resume-print-include-contacts')?.focus();
}
window.addEventListener('afterprint', () => document.body.classList.remove('resume-printing'));

function candidateProfilePreviewMarkup(profile = {}) {
  const safe = resumePrintData(profile);
  const skills = String(safe.skills || '').split(',').map(value => value.trim()).filter(Boolean);
  const texts = [profile.profession, profile.city, profile.skills, profile.about,
    profile.education, profile.achievements, profile.specializations,
    ...(profile.work_history || []).flatMap(item => [item.position, item.period, item.duties]),
    ...(profile.courses || []).flatMap(item => [item.title, item.provider])];
  const hasMaskedContacts = texts.some(value => resumePrintSafeText(value) !== String(value ?? ''));
  return `<div class="split-header"><div><span class="section-kicker">ПРОФЕССИОНАЛЬНАЯ ЧАСТЬ ПРОФИЛЯ</span><h4>${esc(safe.profession || 'Профессия пока не указана')}</h4></div><span class="privacy-chip">Контакты скрыты</span></div>
    ${hasMaskedContacts ? '<p class="candidate-profile-contact-notice">В тексте найдены сведения, похожие на контакты. Они замаскированы только в этом предпросмотре и PDF. Маска не удаляет их из полей профиля: уберите контакты из профессии, города, навыков и описаний перед сохранением.</p>' : ''}
    <div class="profile-preview-meta"><span>Город: ${esc(safe.city || 'не указан')}</span><span>${esc(candidateSalaryText(safe.salary_min))}</span><span>График: ${esc(safe.schedule || 'Любой')}</span>${safe.employment ? `<span>Занятость: ${esc(safe.employment)}</span>` : ''}</div>
    <div class="job-skill-tags">${skills.slice(0, 10).map(skill => `<span>${esc(skill)}</span>`).join('') || '<span>Навыки пока не указаны</span>'}</div>
    ${professionalResumeMarkup(safe)}
    ${safe.about ? `<section class="candidate-profile-preview-about"><h5>О вашем опыте</h5><p>${esc(safe.about)}</p></section>` : ''}
    <div class="profile-preview-hidden"><span aria-hidden="true">🔒</span><div><strong>Имя, телефон и email аккаунта скрыты</strong><small>Контакты открываются только после отдельного согласия на знакомство. Перед сохранением проверьте свободные описания: в них не должно быть личных контактов.</small></div></div>`;
}
function updateCandidateProfilePreview(form) {
  if (!form || form.id !== 'profile-form' || !form.isConnected) return;
  const panel = form.closest('.candidate-profile');
  const content = panel?.querySelector('#candidate-profile-preview-content');
  if (!content) return;
  const draft = candidateProfileFormData(form);
  content.innerHTML = candidateProfilePreviewMarkup(draft);
  const dirty = editorIsDirty(form);
  const status = panel.querySelector('#candidate-profile-preview-state');
  if (status) {
    const message = dirty ? 'Есть несохранённые изменения' : 'Последняя сохранённая версия';
    if (status.textContent !== message) status.textContent = message;
    status.classList.toggle('is-dirty', dirty);
  }
  const switchLabel = form.querySelector('[data-profile-active-label]');
  if (switchLabel) switchLabel.textContent = draft.is_active ? 'Включён' : 'Выключен';
  const intent = form.querySelector('[data-profile-search-intent]');
  if (intent) {
    const changed = draft.is_active !== (form.dataset.savedActive === 'true');
    intent.textContent = changed
      ? (draft.is_active ? 'После сохранения подбор будет включён.' : 'После сохранения подбор будет на паузе.')
      : 'Изменение настройки применяется после сохранения профиля.';
    intent.classList.toggle('is-dirty', changed);
  }
  const historyCount = form.querySelector('[data-profile-history-count]');
  if (historyCount) historyCount.textContent = candidateWorkSectionSummary(draft);
  const courseCount = form.querySelector('[data-profile-course-count]');
  if (courseCount) courseCount.textContent = candidateTrainingSectionSummary(draft);
}
function updateCandidateProfileSavedState(profile) {
  const panel = document.querySelector('#dashboard-main .candidate-profile');
  if (!panel) return;
  const health = candidateProfileHealth(profile || {});
  const readiness = candidateSearchReadiness(profile || {});
  const setText = (selector, value) => {
    const target = panel.querySelector(selector);
    if (target) target.textContent = value;
  };
  setText('[data-profile-saved-percent]', `${health.percent}%`);
  setText('[data-profile-saved-next]', health.next);
  const progress = panel.querySelector('[data-profile-saved-progress]');
  if (progress) progress.style.width = `${health.percent}%`;
  setText('[data-profile-saved-title]', readiness.title);
  setText('[data-profile-saved-description]', readiness.ready
    ? 'Работодатели могут увидеть профессиональную часть профиля без ваших контактов.'
    : readiness.description);
  panel.querySelector('[data-profile-saved-dot]')?.classList.toggle('is-active', readiness.ready);
  const form = panel.querySelector('#profile-form');
  if (form) {
    form.dataset.savedActive = String(readiness.active);
    updateCandidateProfilePreview(form);
  }
}
function openCandidateProfilePreview() {
  const form = document.querySelector('#dashboard-main #profile-form');
  if (!form) return;
  updateCandidateProfilePreview(form);
  const preview = document.querySelector('#candidate-profile-preview');
  preview?.scrollIntoView({block:'start'});
  preview?.focus({preventScroll:true});
}

function profileMarkup(profile = {}, user = {}) {
  const health = candidateProfileHealth(profile);
  const readiness = candidateSearchReadiness(profile);
  // Additional details stay optional; open them explicitly when the candidate is ready.
  return `<div class="panel candidate-profile">
    <div class="candidate-profile-heading"><div><span class="section-kicker">ВАШ ПРОФЕССИОНАЛЬНЫЙ ОПЫТ</span>
    <h3>Расскажите, какую работу вы ищете</h3></div><button type="button" class="btn btn-outline" data-action="open-candidate-profile-preview" aria-controls="candidate-profile-preview">Посмотреть профиль</button></div>
    <p class="muted">Для начала поиска достаточно профессии и города. Остальные сведения помогают точнее подобрать вакансии; большое резюме не требуется.</p>
    <div class="profile-health" role="status" aria-label="Основные сведения для подбора">
      <div class="profile-health-copy"><span>Основа профиля: профессия и город</span><strong data-profile-saved-percent>${health.percent}%</strong></div>
      <div class="profile-health-track"><span data-profile-saved-progress style="width:${health.percent}%"></span></div>
      <small data-profile-saved-next>${esc(health.next)}</small>
    </div>
    <form id="profile-form" data-saved-active="${String(readiness.active)}">
    <div class="profile-visibility">
      <div class="candidate-profile-saved-readiness"><span data-profile-saved-dot class="profile-visibility-dot ${readiness.ready ? 'is-active' : ''}"></span><div><small>Сейчас по сохранённому профилю</small><strong data-profile-saved-title>${esc(readiness.title)}</strong><small data-profile-saved-description>${readiness.ready ? 'Работодатели могут увидеть профессиональную часть профиля без ваших контактов.' : esc(readiness.description)}</small></div></div>
      <div class="candidate-profile-search-control"><label class="switch-control"><input type="checkbox" id="profile-active" name="is_active" aria-label="Участвовать в подборе" aria-describedby="profile-search-intent" ${readiness.active ? 'checked':''}><span aria-hidden="true"></span><b data-profile-active-label>${readiness.active ? 'Включён' : 'Выключен'}</b></label><small id="profile-search-intent" data-profile-search-intent>Изменение настройки применяется после сохранения профиля.</small></div>
    </div>
    <div class="profile-progress" role="note"><span class="profile-progress-step">1</span><div><strong>Начните с профессии и города</strong><small>Отмечены звёздочкой. Остальное можно добавить позже.</small></div></div>
      <div class="form-grid">
        <div class="field"><label for="profile-profession">Ваша профессия <span class="required-mark">*</span></label>
          <input id="profile-profession" name="profession" value="${esc(profile.profession)}" placeholder="Например, бухгалтер" required minlength="2" maxlength="120" autocomplete="organization-title">
          <small class="field-help">Укажите привычное название профессии.</small></div>
        <div class="field"><label for="profile-city">В каком городе ищете работу? <span class="required-mark">*</span></label>
          <input id="profile-city" name="city" value="${esc(profile.city)}" placeholder="Например, Москва" required minlength="2" maxlength="100" autocomplete="address-level2"></div>
        <div class="field wide"><label for="profile-skills">Что вы хорошо умеете? (необязательно)</label>
          <input id="profile-skills" name="skills" value="${esc(profile.skills)}" placeholder="Например: 1С, учёт, Excel" maxlength="300" aria-describedby="profile-skills-help">
          <small class="field-help" id="profile-skills-help">Напишите несколько навыков через запятую. Это поможет точнее подобрать работу.</small></div>
        <div class="field"><label for="profile-salary">Желаемая зарплата от, ₽ (необязательно)</label>
          <input id="profile-salary" name="salary_min" type="number" inputmode="numeric" value="${Number(profile.salary_min || 0) > 0 ? Number(profile.salary_min) : ''}" min="0" max="10000000" placeholder="Например, 60 000" aria-describedby="profile-salary-help"><small class="field-help" id="profile-salary-help">Можно оставить пустым, если пока не определились.</small></div>
        <div class="field"><label for="profile-schedule">Удобный график</label>
          <select id="profile-schedule" name="schedule">${optList(schedules,profile.schedule)}</select></div>
        <div class="field wide">
          <details class="resume-history-section" id="resume-history-section">
            <summary>Опыт работы и достижения <small data-profile-history-count>${esc(candidateWorkSectionSummary(profile))}</small></summary>
            <p class="field-help">Расскажите о своём опыте. Эти сведения можно показать работодателю без раскрытия контактов. Указывать названия компаний необязательно.</p>
            <div class="form-grid">
              <div class="field"><label for="resume-years">Общий стаж, лет</label>
                <input id="resume-years" name="experience_years" type="number" inputmode="numeric" min="0" max="70" value="${Number(profile.experience_years || 0) || ''}" placeholder="Например, 20"></div>
              <div class="field wide"><label for="resume-achievements">Чем гордитесь в работе?</label>
                <textarea id="resume-achievements" name="achievements" maxlength="500" rows="3" placeholder="Например, наладил учёт склада, обучил сотрудников">${esc(profile.achievements || '')}</textarea></div>
            </div>
            <div class="resume-work-list" id="resume-work-list">${(Array.isArray(profile.work_history) ? profile.work_history : []).map(resumeRoleFields).join('')}</div>
            <button type="button" class="btn btn-outline" data-action="add-resume-role" id="resume-add-role">Добавить место работы</button>
            <p class="field-help">До 5 мест работы. Можно указать только должность, период и основные задачи. Не добавляйте телефон, email или ссылки.</p>
            <div class="field wide"><label for="profile-about">Коротко о себе как о специалисте (по желанию)</label>
                <textarea id="profile-about" name="about" maxlength="700" placeholder="Например: умею организовать работу склада и обучать новых сотрудников. Не указывайте контакты.">${esc(profile.about)}</textarea>
                <div class="experience-help-action">
                  <span>Трудно подобрать слова? Ответьте на три коротких вопроса.</span>
                  <button type="button" class="btn btn-outline" id="experience-start" aria-controls="experience-helper" aria-expanded="false">Помочь описать опыт</button>
                </div>
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
                  <p class="field-help">Помощник дополняет только поле выше, не создавая отдельного резюме. После проверки нажмите «Сохранить профиль».</p>
                </details>
            </div>
          </details>
        </div>
        <div class="field wide">
          <details class="resume-training-section" id="resume-training-section">
            <summary>Образование и квалификация (по желанию) <small data-profile-course-count>${esc(candidateTrainingSectionSummary(profile))}</small></summary>
            <p class="field-help">Укажите образование, специализации и пройденные курсы, если хотите. Документы загружать не нужно; платформа их не проверяет.</p>
              <div class="field"><label for="resume-education">Образование, квалификация</label>
                <input id="resume-education" name="education" maxlength="240" value="${esc(profile.education || '')}" placeholder="Например, среднее специальное, бухгалтерский учёт"></div>
            <div class="field"><label for="resume-specializations">В каких направлениях специализируетесь?</label>
              <textarea id="resume-specializations" name="specializations" maxlength="240" rows="2" placeholder="Например: кадровый учёт, зарплата, отчётность">${esc(profile.specializations || '')}</textarea></div>
            <div class="resume-course-list" id="resume-course-list">${(Array.isArray(profile.courses) ? profile.courses : []).map(resumeCourseFields).join('')}</div>
            <button type="button" class="btn btn-outline" data-action="add-resume-course" id="resume-add-course">Добавить курс или сертификат</button>
            <p class="field-help">Можно добавить до шести записей. Достаточно названия курса; организация и год необязательны. Не указывайте контакты и ссылки.</p>
          </details>
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
            </div>
          </details>
        </div>
      </div>
      <p class="form-note">* Профессия и город нужны для подбора. Все изменения вступят в силу после сохранения. Ваши контакты не передаются автоматически.</p>
      <div class="candidate-profile-save-bar"><button class="btn btn-primary btn-lg" type="submit">Сохранить профиль</button></div>
    </form>
    <details class="profile-preapply-guide">
      <summary>Проверьте профиль перед первым откликом</summary>
      <ol>
        <li>Профессия и город соответствуют тому, что вы ищете сейчас.</li>
        <li>Навыки и достижения описывают конкретные задачи, а не общие качества.</li>
        <li>В свободных описаниях нет телефона, адреса и личной почты.</li>
      </ol>
      <p>Отклик отправляет профессиональный профиль без открытия личных контактов. Для знакомства требуется отдельное согласие.</p>
      <a href="/journal/kak-pokazat-opyt-v-profile">Как лучше рассказать о своём опыте →</a>
    </details>
    <section class="profile-public-preview" id="candidate-profile-preview" tabindex="-1" aria-label="Предпросмотр вашего резюме">
      <div class="candidate-profile-preview-heading"><h4>Предпросмотр профиля</h4><p id="candidate-profile-preview-state" role="status" aria-live="polite">Последняя сохранённая версия</p></div>
      <p class="candidate-profile-preview-help">Проверьте своё резюме перед сохранением. Здесь видны и текущие правки — их пока видите только вы. Это не точная копия карточки работодателя: состав сведений зависит от этапа знакомства.</p>
      <div id="candidate-profile-preview-content">${candidateProfilePreviewMarkup(profile)}</div>
    </section>
    <div class="profile-next-actions" aria-label="Следующие шаги">
      <strong>После сохранения:</strong>
      <button type="button" class="btn btn-outline" data-action="open-resume-print">Печать / сохранить PDF</button>
      <button type="button" class="btn btn-outline" data-tab="offers">Посмотреть подходящие вакансии →</button>
      <button type="button" class="btn btn-outline" data-tab="applications">Проверить мои отклики</button>
    </div>
  </div>`;
}
function candidateOverviewApplicationCard(item) {
  const statusText = candidateWorkflowStatus(item, statusTitle[item.status] || item.status);
  return `<article class="candidate-overview-item">
    <div class="candidate-overview-item-head"><div><span class="card-eyebrow">ОТКЛИК</span><strong>${esc(item.title)}</strong><small>${esc(item.company_name)} · ${esc(item.city)}</small></div><span class="mini-badge">${esc(statusText)}</span></div>
    ${interactionStageMarkup(item,'application')}
    <button type="button" class="btn btn-outline btn-tiny" data-v02-action="open-candidate-applications" data-application-id="${Number(item.id)}">Открыть историю →</button>
  </article>`;
}
function candidateOverviewInvitationCard(item) {
  return `<article class="candidate-overview-item is-invitation">
    <div class="candidate-overview-item-head"><div><span class="card-eyebrow">ПРИГЛАШЕНИЕ</span><strong>${esc(item.title)}</strong><small>${esc(item.company_name)} · ${esc(item.city)}</small></div><span class="mini-badge ${statusBadge[item.status]||''}">${esc(candidateWorkflowStatus(item,statusTitle[item.status]||item.status))}</span></div>
    ${employerPublicTrustMarkup(item)}
    <button type="button" class="btn btn-primary btn-tiny" data-action="open-candidate-invitations" data-filter="decision" data-invitation-id="${Number(item.id)}">Ответить на приглашение →</button>
  </article>`;
}
function candidateApplicationStageOverview(applications = []) {
  // Match the existing application list's buckets, counting each server record once.
  const seen = new Set();
  const counts = {all:0,reply:0,active:0,closed:0};
  for (const item of applications) {
    const id = Number(item.id);
    if (!Number.isSafeInteger(id) || id <= 0 || seen.has(id)) continue;
    seen.add(id);
    let bucket = 'active';
    if (item.invitation_status === 'sent' &&
        !['withdrawn','rejected','hired'].includes(item.status)) bucket = 'reply';
    else if (['withdrawn','rejected','hired'].includes(item.status) ||
             item.invitation_status === 'declined') bucket = 'closed';
    counts.all += 1;
    counts[bucket] += 1;
  }
  const stages = [
    ['reply','Требуют ответа','Проверьте запросы на знакомство'],
    ['active','В работе','Работодатель рассматривает отклики'],
    ['closed','Завершённые','Отказы, итоги и отозванные отклики']
  ];
  return `<section class="panel candidate-stage-overview" aria-label="Мои отклики по этапам">
    <div class="split-header"><div><span class="section-kicker">МОЯ ВОРОНКА</span><h3>Отклики по этапам</h3>
      <p class="muted">Текущее состояние ваших откликов. Прямые приглашения без отклика смотрите в разделе «Знакомства».</p></div>
      <button type="button" class="btn btn-outline btn-tiny" data-v02-action="open-candidate-applications">Все отклики · ${counts.all}</button></div>
    <div class="candidate-stage-grid">${stages.map(([key,label,hint]) =>
      `<button type="button" class="candidate-stage-card" data-v02-action="open-candidate-applications" data-filter="${key}" aria-label="${label}: ${counts[key]}. Открыть список">
        <strong>${counts[key]}</strong><span>${label}</span><small>${hint}</small>
      </button>`).join('')}</div>
    <p class="candidate-stage-note">Это не историческая статистика: этапы меняются вместе со статусами записей. Контактные данные здесь не отображаются.</p>
  </section>`;
}
function candidateInteractionFeedMarkup(applications = [], invitations = []) {
  // Display one most recent server-side event per record. Do not infer events from dates,
  // combine unrelated records, or copy any contact fields into the overview.
  const entries = [];
  const seen = new Set();
  function add(item, type) {
    const id = Number(item?.id);
    if (!Number.isSafeInteger(id) || id <= 0 || seen.has(type + ':' + id)) return;
    seen.add(type + ':' + id);
    const timeline = Array.isArray(item.timeline) ? item.timeline : [];
    const last = timeline.length ? timeline[timeline.length - 1] : null;
    const rawDate = last?.created_at || item.updated_at || item.created_at || '';
    const iso = String(rawDate).trim().replace(' ', 'T');
    const parsed = Date.parse(iso && /(?:Z|[+-]\d{2}:?\d{2})$/i.test(iso) ? iso : iso + 'Z');
    const activity = Number.isFinite(parsed) ? parsed : 0;
    const status = type === 'application'
      ? candidateWorkflowStatus(item,statusTitle[item.status] || item.status || 'В процессе')
      : candidateWorkflowStatus(item,statusTitle[item.status] || item.status || 'Знакомство');
    const button = type === 'application'
      ? `<button type="button" class="btn btn-outline btn-tiny" data-v02-action="open-candidate-applications" data-application-id="${id}">Открыть отклик</button>`
      : `<button type="button" class="btn btn-outline btn-tiny" data-action="open-candidate-invitations" data-invitation-id="${id}">Открыть знакомство</button>`;
    entries.push({id,type,activity,rawDate,status,title:String(item.title || item.vacancy_title || 'Вакансия'),
      company:String(item.company_name || ''),event:last?.event ? String(activityLabels[last.event] || last.event) : '',button});
  }
  for (const item of applications) add(item,'application');
  // Application-linked invitations already share the same unified timeline.
  // Keep one canonical row for that relationship; only direct invitations are separate.
  for (const item of invitations) {
    const applicationId = Number(item?.application_id);
    if (Number.isSafeInteger(applicationId) && applicationId > 0) continue;
    add(item,'invitation');
  }
  entries.sort((a,b) => b.activity - a.activity || b.id - a.id);
  const recent = entries.slice(0,6);
  return `<section class="panel candidate-interaction-feed" aria-label="Последние взаимодействия">
    <div class="split-header"><div><span class="section-kicker">ИСТОРИЯ ВЗАИМОДЕЙСТВИЙ</span><h3>Последние события</h3>
    <p class="muted">Отклики и знакомства в одной хронологии. Полная история доступна внутри каждой записи.</p></div></div>
    ${recent.length ? `<ol class="candidate-interaction-list">${recent.map(entry => `<li class="candidate-interaction-entry">
      <span class="candidate-interaction-type">${entry.type === 'application' ? 'Отклик' : 'Знакомство'}</span>
      <div class="candidate-interaction-info"><strong>${esc(entry.title)}</strong><small>${esc(entry.company)}</small>
      <span>${esc(entry.status)}${entry.event ? ' · ' + esc(entry.event) : ''}</span>
      ${entry.activity ? `<time>${esc(formatActivityTimestamp(entry.rawDate))}</time>` : ''}</div>
      ${entry.button}
    </li>`).join('')}</ol>` :
    '<div class="empty-state"><strong>Взаимодействий пока нет</strong><p>После первых откликов или приглашений они появятся здесь.</p><button type="button" class="btn btn-outline" data-tab="offers">Подходящие вакансии</button></div>'}
    ${entries.length > 6 ? '<p class="candidate-interaction-note">Показаны 6 последних записей. Для полной истории откройте «Отклики» или «Знакомства».</p>' : ''}
  </section>`;
}
function overviewTaskListMarkup(title, items) {
  // Actions are markup assembled only from fixed, local buttons. Text from
  // user-owned content is always escaped before rendering.
  const visible = items.slice(0, 4);
  if (!visible.length) return '';
  return `<section class="panel overview-action-center" aria-label="${esc(title)}">
    <div class="split-header"><div><span class="section-kicker">НЕСКОЛЬКО ДЕЙСТВИЙ</span><h3>${esc(title)}</h3></div></div>
    <div class="overview-action-list">${visible.map((item, index) => `
      <div class="overview-action-item ${item.urgent ? 'is-urgent' : ''}">
        <span class="overview-action-step" aria-hidden="true">${index+1}</span>
        <div><strong>${esc(item.title)}</strong><p>${esc(item.description)}</p></div>
        ${item.action}
      </div>`).join('')}</div>
  </section>`;
}
function candidateStatusChip(ok, yes, no) {
  return `<span class="candidate-status-chip ${ok?'is-ok':'is-pending'}"><i aria-hidden="true">${ok?'✓':'!'}</i>${esc(ok?yes:no)}</span>`;
}

async function renderCandidate() {
  const nav = [{id:'overview',label:'Обзор'},{id:'profile',label:'Мой профиль'},{id:'offers',label:'Подходящие вакансии'},{id:'applications',label:'Отклики'},{id:'invitations',label:'Знакомства'},{id:'favorites',label:'Сохранённые'},{id:'changes',label:'Изменения'},{id:'email',label:'Email и доступ'},{id:'security',label:'Безопасность'}];
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
      const readiness = candidateSearchReadiness(state.user.profile || {});
      const jobs = jobsResult.jobs || [];
      const applications = applicationsResult.applications || [];
      const invitations = invitationsResult.invitations || [];
      const favorites = favoritesResult.jobs || [];
      const pendingInvitationsList = invitations.filter(item => candidateInvitationBucket(item) === 'decision');
      const pendingInvitations = pendingInvitationsList.length;
      const waitingEmployerInvitations = invitations.filter(item => candidateInvitationBucket(item) === 'waiting');
      const openedIntroductions = invitations.filter(item => candidateInvitationBucket(item) === 'introduced');
      const completedIntroductions = invitations
        .filter(item => invitationFinalOutcome(item))
        .sort((a,b) => invitationLastActivity(b) - invitationLastActivity(a));
      const latestCompletedIntroduction = completedIntroductions.find(item =>
        Date.now() - invitationLastActivity(item) <= 14 * 24 * 60 * 60 * 1000
      ) || null;
      const latestCompletedOutcome = latestCompletedIntroduction ? invitationFinalOutcome(latestCompletedIntroduction) : null;
      const activeIntroductions = pendingInvitations + waitingEmployerInvitations.length + openedIntroductions.length;
      const introductionOverviewFilter = pendingInvitations ? 'decision'
        : waitingEmployerInvitations.length ? 'waiting' : openedIntroductions.length ? 'introduced' : 'all';
      const activeApplicationsList = applications.filter(item =>
        ['applied','reviewing','interview'].includes(item.status) && !item.invitation_id
      );
      const activeApplications = activeApplicationsList.length;
      const unreadChanges = Number(updatesResult.unread_count || 0);
      const emailVerified = Boolean(emailResult.email_verified);
      let nextTitle = 'Посмотрите подходящие вакансии';
      let nextText = 'Профиль уже может участвовать в подборе. Проверьте новые рекомендации.';
      let nextAction = '<button class="btn btn-primary" data-tab="offers">Открыть рекомендации →</button>';
      // Pending invitations and changed vacancy terms are time-sensitive.
      // Profile completion and email verification remain visible below as
      // account-health reminders, but must not hide an action from the company.
      if (pendingInvitations > 0) {
        nextTitle = 'Ответьте на приглашение работодателя';
        nextText = `Ожидают решения: ${pendingInvitations}. Контакты не откроются без вашего согласия.`;
        nextAction = '<button class="btn btn-primary" data-action="open-candidate-invitations" data-filter="decision">Ответить →</button>';
      } else if (unreadChanges > 0) {
        nextTitle = 'Проверьте изменения условий';
        nextText = `Работодатели изменили условия по ${unreadChanges} вакансии(ям), с которыми вы уже взаимодействовали.`;
        nextAction = '<button class="btn btn-primary" data-tab="changes">Посмотреть изменения →</button>';
      } else if (!emailVerified) {
        nextTitle = 'Подтвердите email';
        nextText = 'Это защитит доступ к аккаунту и поможет надёжно получать сервисные уведомления.';
        nextAction = '<button class="btn btn-primary" data-tab="email">Подтвердить email →</button>';
      } else if (!readiness.ready) {
        nextTitle = readiness.title;
        nextText = readiness.description;
        nextAction = `<button class="btn btn-primary" data-action="open-candidate-profile" data-profile-field="${esc(readiness.nextField)}">${readiness.active ? 'Дополнить профиль' : 'Настроить подбор'} →</button>`;
      } else if (waitingEmployerInvitations.length > 0) {
        nextTitle = 'Согласие отправлено — ждём работодателя';
        nextText = `Знакомств в ожидании продолжения: ${waitingEmployerInvitations.length}. Повторно подтверждать согласие не нужно.`;
        nextAction = '<button class="btn btn-outline" data-action="open-candidate-invitations" data-filter="waiting">Посмотреть статус →</button>';
      } else if (openedIntroductions.length > 0) {
        nextTitle = 'Контакты уже переданы работодателю';
        nextText = `Состоявшихся знакомств: ${openedIntroductions.length}. Компания может связаться с вами напрямую. Повторно подтверждать согласие не нужно.`;
        nextAction = '<button class="btn btn-outline" data-action="open-candidate-invitations" data-filter="introduced">Посмотреть знакомства →</button>';
      } else if (activeApplications > 0) {
        nextTitle = 'Проверьте статус откликов';
        nextText = `Активных откликов: ${activeApplications}. Посмотрите, на каком этапе каждый из них.`;
        nextAction = '<button class="btn btn-primary" data-v02-action="open-candidate-applications">Открыть отклики →</button>';
      } else if (!jobs.length) {
        nextTitle = 'Расширьте поиск';
        nextText = 'Строгих совпадений пока нет — можно посмотреть все открытые вакансии.';
        nextAction = '<a class="btn btn-primary" href="#jobs">Все вакансии →</a>';
      }
      const candidateTasks = [];
      if (pendingInvitations) candidateTasks.push({
        title: 'Приглашения, ожидающие ответа',
        description: `Ожидают решения: ${pendingInvitations}. Контакты не открываются без согласия.`,
        action: '<button class="btn btn-outline btn-tiny" data-action="open-candidate-invitations" data-filter="decision">Ответить</button>',
        urgent: true
      });
      if (unreadChanges) candidateTasks.push({
        title: 'Изменения условий вакансий',
        description: `Новых изменений: ${unreadChanges}. Проверьте их до дальнейшего общения.`,
        action: '<button class="btn btn-outline btn-tiny" data-tab="changes">Проверить</button>',
        urgent: true
      });
      if (!emailVerified) candidateTasks.push({
        title: 'Подтвердить электронную почту',
        description: 'Для восстановления доступа и получения важных уведомлений.',
        action: '<button class="btn btn-outline btn-tiny" data-tab="email">К подтверждению</button>'
      });
      if (!readiness.ready) candidateTasks.push({
        title: readiness.title,
        description: readiness.description,
        action: `<button class="btn btn-outline btn-tiny" data-action="open-candidate-profile" data-profile-field="${esc(readiness.nextField)}">${readiness.active ? 'Дополнить профиль' : 'Настроить подбор'}</button>`
      });
      if (waitingEmployerInvitations.length) candidateTasks.push({
        title: 'Проверить согласованные знакомства',
        description: `Ожидается продолжение работодателем: ${waitingEmployerInvitations.length}.`,
        action: '<button class="btn btn-outline btn-tiny" data-action="open-candidate-invitations" data-filter="waiting">Статус</button>'
      });
      if (openedIntroductions.length) candidateTasks.push({
        title: 'Посмотреть состоявшиеся знакомства',
        description: `Контакты переданы с вашего согласия: ${openedIntroductions.length}. Дальнейшее общение — напрямую с компанией.`,
        action: '<button class="btn btn-outline btn-tiny" data-action="open-candidate-invitations" data-filter="introduced">К знакомствам</button>'
      });
      if (activeApplications) candidateTasks.push({
        title: 'Просмотреть активные отклики',
        description: `Сейчас в процессе: ${activeApplications}.`,
        action: '<button class="btn btn-outline btn-tiny" data-v02-action="open-candidate-applications">К откликам</button>'
      });
      // An optional biography must never replace the primary action: find work.
      // Only suggest enrichment when there is no pending decision or other task.
      if (!candidateTasks.length) {
        candidateTasks.push({
          title: jobs.length ? 'Выбрать подходящую вакансию' : 'Посмотреть доступные вакансии',
          description: jobs.length ? `Рекомендаций по профилю: ${jobs.length}.` : 'Можно расширить поиск и посмотреть все открытые предложения.',
          action: jobs.length ? '<button class="btn btn-outline btn-tiny" data-tab="offers">Рекомендации</button>' : '<a class="btn btn-outline btn-tiny" href="#jobs">Открыть поиск</a>'
        });
        if (readiness.ready && !health.hasProfessionalDetails) candidateTasks.push({
          title: 'Указать навыки или опыт (необязательно)',
          description: 'Поиск уже доступен. Можно добавить несколько навыков или одно место работы — не нужно писать второе резюме.',
          action: '<button class="btn btn-outline btn-tiny" data-tab="profile">Дополнить профиль</button>'
        });
      }
      target.innerHTML = `<div class="overview-stack">
        <section class="panel dashboard-overview-hero">
          <span class="section-kicker">ВАШ СЛЕДУЮЩИЙ ШАГ</span>
          <div class="overview-priority"><div><h3>${esc(nextTitle)}</h3><p class="muted">${esc(nextText)}</p></div>${nextAction}</div>
          <div class="overview-health"><span>Основные сведения</span><div class="profile-health-track"><span style="width:${health.percent}%"></span></div><strong>${health.percent}%</strong></div>
          <div class="candidate-status-row">
            ${candidateStatusChip(emailVerified,'Email подтверждён','Подтвердите email')}
            ${candidateStatusChip(readiness.ready,'Профиль участвует в подборе',readiness.title)}
            <span class="candidate-status-chip is-private"><i aria-hidden="true">🔒</i>Контакты скрыты по умолчанию</span>
          </div>
        </section>
        ${unreadChanges ? `<section class="overview-alert" role="status"><div><strong>Изменились условия вакансий</strong><span>Непрочитанных изменений: ${unreadChanges}</span></div><button class="btn btn-outline btn-tiny" data-tab="changes">Проверить изменения</button></section>` : ''}
        ${latestCompletedIntroduction ? `<section class="overview-alert candidate-outcome-alert ${latestCompletedOutcome==='hired'?'is-positive':'is-neutral'}" role="status"><div><strong>${latestCompletedOutcome==='hired'?'Положительный итог знакомства':'Знакомство завершено'}</strong><span>${latestCompletedOutcome==='hired'?'Компания хочет продолжить общение. Это не подтверждение трудоустройства.':'По итогам знакомства договориться не удалось.'}</span></div><button class="btn btn-outline btn-tiny" data-action="open-candidate-invitations" data-filter="closed" data-invitation-id="${Number(latestCompletedIntroduction.id)}">Посмотреть итог</button></section>` : ''}
        <section class="overview-stat-grid" aria-label="Сводка соискателя">
          <button type="button" class="overview-stat-card" data-tab="offers"><strong>${jobs.length}</strong><span>Подходящие вакансии</span><small>${readiness.ready ? 'По вашему профилю' : readiness.active ? 'Нужны профессия и город' : 'Подбор на паузе'}</small></button>
          <button type="button" class="overview-stat-card" data-v02-action="open-candidate-applications"><strong>${activeApplications}</strong><span>Активные отклики</span><small>В процессе</small></button>
          <button type="button" class="overview-stat-card" data-action="open-candidate-invitations" data-filter="${introductionOverviewFilter}"><strong>${activeIntroductions}</strong><span>Знакомства</span><small>${pendingInvitations ? `Требуют ответа: ${pendingInvitations}` : waitingEmployerInvitations.length ? `Ждём работодателя: ${waitingEmployerInvitations.length}` : openedIntroductions.length ? `Контакты переданы: ${openedIntroductions.length}` : 'Новых действий нет'}</small></button>
          <button type="button" class="overview-stat-card" data-tab="favorites"><strong>${favorites.length}</strong><span>Избранное</span><small>Сохранённые вакансии</small></button>
        </section>
        ${overviewTaskListMarkup('Что сделать дальше', candidateTasks)}
        ${candidateApplicationStageOverview(applications)}
        ${candidateInteractionFeedMarkup(applications,invitations)}
        ${pendingInvitationsList.length ? `<section class="panel candidate-overview-section candidate-invitations-preview"><div class="split-header"><div><span class="section-kicker">ТРЕБУЕТ ОТВЕТА</span><h3>Новые приглашения</h3><p class="muted">Решение за вами: контакты остаются закрытыми, пока вы не согласитесь.</p></div><button class="btn btn-outline btn-tiny" data-tab="invitations">Все знакомства</button></div><div class="candidate-overview-list">${pendingInvitationsList.slice(0,2).map(candidateOverviewInvitationCard).join('')}</div></section>` : ''}
        <section class="candidate-overview-grid">
          <div class="panel candidate-overview-section">
            <div class="split-header"><div><span class="section-kicker">РЕКОМЕНДАЦИИ</span><h3>Вакансии для вас</h3><p class="muted">Сначала варианты с лучшим совпадением по вашему профилю.</p></div><button class="btn btn-outline btn-tiny" data-tab="offers">Все рекомендации</button></div>
            <div class="candidate-mini-jobs">${jobs.length ? jobs.slice(0,2).map(job=>jobMarkup(job,true)).join('') : candidateOffersEmptyMarkup(readiness, true)}</div>
          </div>
          <div class="panel candidate-overview-section">
            <div class="split-header"><div><span class="section-kicker">ОТКЛИКИ</span><h3>Сейчас в процессе</h3><p class="muted">Последние активные отклики и их текущий этап.</p></div><button class="btn btn-outline btn-tiny" data-v02-action="open-candidate-applications">Все отклики</button></div>
            <div class="candidate-overview-list">${activeApplicationsList.length ? activeApplicationsList.slice(0,2).map(candidateOverviewApplicationCard).join('') : '<div class="empty-state"><p>Активных откликов пока нет.</p><button class="btn btn-primary btn-tiny" data-tab="offers">Выбрать вакансию →</button></div>'}</div>
          </div>
        </section>
        ${favorites.length ? `<section class="candidate-saved-strip"><div><span class="section-kicker">СОХРАНЕНО</span><strong>${favorites.length} вакансий в избранном</strong><small>Можно вернуться к ним позже и сравнить условия.</small></div><button class="btn btn-outline btn-tiny" data-tab="favorites">Открыть сохранённые →</button></section>` : ''}
      </div>`;
    } else if (state.tab === 'profile') target.innerHTML = profileMarkup(state.user.profile, state.user);
    else if (state.tab === 'offers') {
      const {jobs} = await api('/api/candidate/jobs');
      const readiness = candidateSearchReadiness(state.user.profile || {});
      target.innerHTML = `<div class="panel"><h3>Подходящие вакансии</h3><p class="muted">Алгоритм учитывает навыки, город, график и ожидания по зарплате. Совпадение — рекомендация, не решение о трудоустройстве.</p><div class="dashboard-list">${jobs.length ? jobs.map(x => jobMarkup(x,true)).join('') : candidateOffersEmptyMarkup(readiness)}</div></div>`;
    } else if (state.tab === 'security') {
      await renderAccountSecurity(target);
    } else {
      await loadCandidateInvitations(target,true);
    }
  } catch(e) { target.innerHTML = `<div class="panel">${esc(e.message)}</div>`; toast(e.message,true); }
}
const candidateInvitationPageSize = 20;
let candidateInvitationVisibleLimit = candidateInvitationPageSize;
const pendingCandidateInvitationActions = new Set();
function candidateInvitationSavedReceipt(button, accepted) {
  const card = button.closest('.candidate-introduction-card');
  if (!card) return;
  const consent = card.querySelector('.consent-box');
  const actions = card.querySelector('.invitation-actions');
  const receipt = document.createElement('div');
  receipt.className = 'candidate-introduction-saved-receipt candidate-introduction-note ' +
    (accepted ? 'is-waiting' : 'is-closed');
  receipt.setAttribute('role', 'status');
  receipt.innerHTML = accepted
    ? '<strong>Согласие отправлено</strong>' +
      '<span>Ваш ответ сохранён. Контакты смогут открыть только после вашего согласия. ' +
      'Сейчас ждём работодателя.</span>'
    : '<strong>Отказ сохранён</strong>' +
      '<span>Вы отказались от знакомства. Контакты компании не переданы.</span>';
  receipt.insertAdjacentHTML('beforeend',
    '<button type="button" class="btn btn-outline btn-tiny" ' +
    'data-action="refresh-candidate-introductions">Обновить список</button>');
  if (consent) consent.replaceWith(receipt);
  else if (actions) actions.replaceWith(receipt);
  if (actions && actions.isConnected) actions.remove();
}
async function loadCandidateInvitations(target=$('#dashboard-main'), force=false) {
  if (force || !Array.isArray(state.candidateInvitationsData)) {
    const result = await api('/api/candidate/invitations');
    state.candidateInvitationsData = result.invitations || [];
  }
  const invitations = state.candidateInvitationsData;
  const selected = Object.hasOwn(candidateInvitationFilterLabels,state.candidateInvitationsFilter)
    ? state.candidateInvitationsFilter
    : 'all';
  state.candidateInvitationsFilter = selected;
  const query = String(state.candidateInvitationsQuery || '').trim().toLocaleLowerCase('ru-RU');
  const searchScoped = query
    ? invitations.filter(item => [item.company_name,item.title,item.city]
        .map(value => String(value || '').toLocaleLowerCase('ru-RU'))
        .join(' ')
        .includes(query))
    : invitations;
  const counts = {decision:0,waiting:0,introduced:0,closed:0};
  searchScoped.forEach(item => { counts[candidateInvitationBucket(item)] += 1; });
  const ordered = [...searchScoped].sort((a,b) => {
    const priority = {decision:0,waiting:1,introduced:2,closed:3};
    const diff = priority[candidateInvitationBucket(a)] - priority[candidateInvitationBucket(b)];
    return diff || invitationLastActivity(b) - invitationLastActivity(a);
  });
  const shown = selected === 'all' ? ordered : ordered.filter(item => candidateInvitationBucket(item) === selected);
  // Links from an application or preview must bring the selected invitation
  // directly into view even when it is beyond the first page.
  const requestedInvitationId = Number(state.candidateInvitationTargetId || 0);
  if (requestedInvitationId > 0) state.candidateInvitationPinnedId = requestedInvitationId;
  const selectedInvitationId = Number(state.candidateInvitationPinnedId || 0);
  const selectedIndex = selectedInvitationId > 0
    ? shown.findIndex(item => Number(item.id) === selectedInvitationId)
    : -1;
  if (selectedIndex > 0) shown.unshift(shown.splice(selectedIndex, 1)[0]);
  const visible = shown.slice(0, candidateInvitationVisibleLimit);
  const filters = [
    ['all',searchScoped.length],
    ['decision',counts.decision],
    ['waiting',counts.waiting],
    ['introduced',counts.introduced],
    ['closed',counts.closed]
  ].map(([value,count]) => `<button type="button" class="btn btn-tiny ${selected===value?'btn-dark':'btn-outline'}" data-action="filter-candidate-invitations" data-filter="${value}" aria-pressed="${selected===value}">${esc(candidateInvitationFilterLabels[value])} · ${Number(count)}</button>`).join('');
  const empty = invitations.length
    ? (query
      ? '<div class="empty-state empty-state-action"><span class="empty-state-icon" aria-hidden="true">⌕</span><strong>По этому запросу знакомств нет</strong><p>Измените поиск или используйте «Сбросить фильтры» выше.</p></div>'
      : '<div class="empty-state empty-state-action"><span class="empty-state-icon" aria-hidden="true">⌕</span><strong>В этом этапе знакомств нет</strong><p>Выберите другой этап или покажите все знакомства.</p><button class="btn btn-outline" data-action="filter-candidate-invitations" data-filter="all">Показать все</button></div>')
    : '<div class="empty-state"><strong>Знакомств пока нет.</strong><p>Заполните профиль, откликайтесь на вакансии — работодатели смогут предложить знакомство.</p></div>';
  target.innerHTML = `<div class="panel candidate-introduction-center">
    <div class="split-header"><div><span class="section-kicker">ЗНАКОМСТВА</span><h3>Знакомства с компаниями</h3><p class="muted">Здесь собраны запросы на знакомство и их дальнейший статус. Имя и контакты не передаются без вашего явного согласия.</p></div><label class="candidate-introduction-search"><span>Поиск</span><input type="search" value="${esc(state.candidateInvitationsQuery)}" placeholder="Компания, вакансия или город" data-candidate-introduction-search autocomplete="off"></label></div>
    <div class="candidate-introduction-stage-filter" role="group" aria-label="Фильтр знакомств по этапу">${filters}</div>
    <div class="candidate-introduction-result-line"><span role="status" aria-live="polite">Показываем <strong>${visible.length}</strong> из <strong>${shown.length}</strong> по выбранному этапу (всего по поиску: ${searchScoped.length})${selected==='all'&&counts.decision?' · сначала знакомства, где нужен ваш ответ':''}</span>${selected!=='all'||query?'<button type="button" class="link-button" data-action="reset-candidate-invitation-filters">Сбросить фильтры</button>':''}</div>
    <div class="dashboard-list" id="candidate-invitation-results">${visible.length ? visible.map(invitationCandidateMarkup).join('') : empty}</div>
    ${visible.length < shown.length ? `<div class="candidate-introduction-pagination"><button type="button" class="btn btn-outline" data-action="more-candidate-invitations">Показать следующие ${Math.min(candidateInvitationPageSize, shown.length - visible.length)} знакомств</button></div>` : ''}
  </div>`;
  const targetId = Number(state.candidateInvitationTargetId || 0);
  if (targetId > 0) {
    const card = target.querySelector('.candidate-introduction-card[data-invitation-id="' + targetId + '"]');
    if (card) {
      card.tabIndex = -1;
      card.focus({preventScroll:true});
      card.scrollIntoView({block:'nearest'});
    }
  }
  state.candidateInvitationTargetId = null;
}
const candidateInvitationFilterLabels = {
  all:'Все',
  decision:'Требуют ответа',
  waiting:'Ждём работодателя',
  introduced:'Знакомство состоялось',
  closed:'Завершённые'
};
function candidateInvitationBucket(x) {
  if (['hired','rejected'].includes(x.application_status) || ['hired','rejected'].includes(x.direct_outcome)) return 'closed';
  if (x.contact_shared) return 'introduced';
  if (x.status === 'sent') return 'decision';
  if (x.status === 'accepted') return 'waiting';
  return 'closed';
}
function candidateInvitationStageLabel(x) {
  const bucket = candidateInvitationBucket(x);
  const outcome = invitationFinalOutcome(x);
  if (bucket === 'decision') return 'Требует ответа';
  if (bucket === 'waiting') return 'Согласие отправлено';
  if (bucket === 'introduced') return 'Знакомство состоялось';
  if (outcome === 'hired') return 'Положительный итог';
  if (outcome === 'rejected') return 'Не договорились';
  if (x.status === 'declined') return 'Вы отказались';
  return workflowStatus(x,statusTitle[x.status] || x.status);
}
function invitationCandidateMarkup(x) {
  const bucket = candidateInvitationBucket(x);
  const outcome = invitationFinalOutcome(x);
  let action = '';
  if (bucket === 'decision') {
    action = `<div class="consent-box"><strong>Хотите познакомиться с компанией?</strong><p>Имя и контакты не будут переданы, пока вы явно не согласитесь.</p><label class="checks"><input type="checkbox" id="consent-${x.id}"> Да, я разрешаю открыть мои имя и контакты этой компании после подтверждения знакомства</label></div><div class="item-actions invitation-actions"><button class="btn btn-primary" data-action="accept" data-id="${x.id}">Да, интересно →</button><button class="btn btn-outline" data-action="decline" data-id="${x.id}">Нет, спасибо</button></div>`;
  } else if (bucket === 'waiting') {
    action = '<div class="candidate-introduction-note is-waiting"><strong>Согласие отправлено</strong><span>Теперь ждём работодателя. Повторно подтверждать знакомство или передавать контакты не нужно.</span></div>';
  } else if (bucket === 'introduced') {
    action = '<div class="info-box contact-opened-note"><strong>✓ Знакомство состоялось</strong><span>Работодатель получил ваши контакты после вашего согласия и теперь может связаться с вами напрямую. На СТАЖНО дополнительных действий не требуется.</span></div>';
  } else if (outcome === 'hired') {
    action = '<div class="candidate-introduction-note is-complete"><strong>Положительный итог знакомства</strong><span>Компания хочет продолжить общение. Это не подтверждение трудоустройства. Условия работы обсудите напрямую с компанией.</span></div>';
  } else if (outcome === 'rejected') {
    action = '<div class="candidate-introduction-note is-closed"><strong>По итогам знакомства не договорились</strong><span>Это знакомство завершено. Дополнительных действий на СТАЖНО не требуется.</span></div>';
  } else if (x.status === 'declined') {
    action = '<div class="candidate-introduction-note is-closed"><strong>Вы отказались от знакомства</strong><span>Контакты этой компании не переданы. Дополнительных действий нет.</span></div>';
  }
  const description = String(x.description || 'Подробности на собеседовании.').trim();
  if (bucket === 'decision') {
    const preview = description.length > 200 ? description.slice(0, 200).trimEnd() + '…' : description;
    const fullConditions = description.length > 200
      ? `<details class="candidate-invitation-conditions"><summary>Прочитать полные условия вакансии</summary><p>${esc(description)}</p></details>`
      : '';
    // The candidate sees who invites them and a readable job summary before
    // consent. The detailed timeline stays available without burying the CTA.
    return `<article class="item-card invitation-card candidate-introduction-card is-decision" data-invitation-id="${Number(x.id)}"><header><div><span class="card-eyebrow">ЗНАКОМСТВО</span><h4>${esc(x.title)}</h4><p>${esc(x.company_name)} · ${esc(x.city)} · ${formatPay(x)}</p>${employerPublicTrustMarkup(x)}</div><span class="mini-badge">${esc(candidateInvitationStageLabel(x))}</span></header>
      <div class="candidate-invitation-summary"><strong>Условия вакансии</strong><p>${esc(preview)}</p>${fullConditions}</div>
      ${action}
      <details class="candidate-invitation-history"><summary>Этапы знакомства и история</summary>${interactionStageMarkup(x,'invitation')}${activityTimelineMarkup(x)}</details>
    </article>`;
  }
  return `<article class="item-card invitation-card candidate-introduction-card is-${bucket}" data-invitation-id="${Number(x.id)}"><header><div><span class="card-eyebrow">ЗНАКОМСТВО</span><h4>${esc(x.title)}</h4><p>${esc(x.company_name)} · ${esc(x.city)} · ${formatPay(x)}</p>${employerPublicTrustMarkup(x)}</div><span class="mini-badge ${bucket==='closed'?'gray':''}">${esc(candidateInvitationStageLabel(x))}</span></header>
   ${interactionStageMarkup(x,'invitation')}
   <p class="invitation-description">${esc(description)}</p>
   ${activityTimelineMarkup(x)}
   ${action}</article>`;
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
    ${state.user?.id ? `<p class="company-public-link"><a class="btn btn-outline btn-tiny" href="/companies/${Number(state.user.id)}">Посмотреть публичную страницу компании</a> <small>Этой ссылкой можно делиться с кандидатами.</small></p>` : ''}
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

function employerWorkQueueEntries(applications, invitations) {
  const tasks = [], seen = new Set();
  const validId = value => {
    const number = Number(value);
    return Number.isSafeInteger(number) && number > 0 ? number : 0;
  };
  for (const item of invitations || []) {
    const id = validId(item.id);
    const outcomeNeeded = Boolean(item.contact) && employerInvitationNeedsOutcome(item);
    if (!id || (!outcomeNeeded && employerInvitationBucket(item) !== 'action') || seen.has('invitation:' + id)) continue;
    seen.add('invitation:' + id);
    tasks.push({
      kind: 'invitation', id, vacancyId: validId(item.vacancy_id),
      profession: String(item.candidate_profession || 'Профессия не указана'),
      vacancy: String(item.vacancy_title || 'Вакансия не указана'),
      priority: outcomeNeeded ? 0 : 1,
      stage: outcomeNeeded ? 'Ждёт итога' : 'Есть согласие',
      detail: outcomeNeeded
        ? 'Контакт открыт с согласия кандидата. После разговора зафиксируйте итог.'
        : 'Согласие получено. Откройте знакомство для продолжения.',
      actionLabel: outcomeNeeded ? 'Зафиксировать итог' : 'Продолжить знакомство',
      filter: outcomeNeeded ? 'introduced' : 'action',
      activity: invitationLastActivity(item)
    });
  }
  for (const item of applications || []) {
    const id = validId(item.id);
    if (!id || validId(item.invitation_id) || item.invitation_status ||
        !['applied', 'reviewing', 'interview'].includes(item.status) || seen.has('application:' + id)) continue;
    seen.add('application:' + id);
    const createdAt = Date.parse(String(item.created_at || ''));
    tasks.push({
      kind: 'application', id, vacancyId: validId(item.vacancy_id),
      profession: String(item.profession || 'Профессия не указана'),
      vacancy: String(item.title || 'Вакансия не указана'),
      priority: item.status === 'applied' ? 2 : 3,
      stage: item.status === 'applied' ? 'Новый отклик' : 'На рассмотрении',
      detail: item.status === 'applied'
        ? 'Изучите профессиональный профиль и выберите следующий шаг.'
        : 'Продолжите рассмотрение или запросите согласие на знакомство.',
      actionLabel: 'Рассмотреть отклик',
      filter: 'attention',
      activity: Number.isFinite(createdAt) ? createdAt : id
    });
  }
  return tasks.sort((a, b) => a.priority - b.priority || b.activity - a.activity || b.id - a.id);
}
function ensureEmployerWorkQueueView() {
  if (state.user?.role !== 'employer') return null;
  const ownerId = Number(state.user.id);
  if (!Number.isSafeInteger(ownerId) || ownerId <= 0) return null;
  const previous = state.employerWorkQueueView;
  if (previous?.ownerId === ownerId) return previous;
  const view = {
    ownerId, stage: 'all', vacancy: 'all', query: '', visibleLimit: 10,
    returnPending: false, scrollOffset: 0
  };
  state.employerWorkQueueView = view;
  return view;
}
function rememberEmployerWorkQueueView(queue) {
  if (!queue || state.tab !== 'overview') return;
  const view = ensureEmployerWorkQueueView();
  if (!view) return;
  view.stage = queue.querySelector('[data-action="employer-workqueue-filter"][aria-pressed="true"]')?.dataset.filter || 'all';
  view.vacancy = queue.querySelector('[data-employer-workqueue-vacancy]')?.value || 'all';
  view.query = String(queue.querySelector('[data-employer-workqueue-search]')?.value || '');
  view.visibleLimit = Math.max(10, Math.min(10000, Number(queue.dataset.visibleLimit) || 10));
}
function restoreEmployerWorkQueueView(queue) {
  if (!queue || state.tab !== 'overview') return;
  const view = ensureEmployerWorkQueueView();
  if (!view) return;
  const stage = ['all','outcome','consent','applications'].includes(view.stage) ? view.stage : 'all';
  for (const button of queue.querySelectorAll('[data-action="employer-workqueue-filter"]')) {
    const active = button.dataset.filter === stage;
    button.setAttribute('aria-pressed', String(active));
    button.classList.toggle('btn-dark',active);
    button.classList.toggle('btn-outline',!active);
  }
  const select = queue.querySelector('[data-employer-workqueue-vacancy]');
  if (select) {
    const vacancy = String(view.vacancy || 'all');
    select.value = [...select.options].some(option => option.value === vacancy) ? vacancy : 'all';
  }
  const search = queue.querySelector('[data-employer-workqueue-search]');
  if (search) search.value = String(view.query || '');
  queue.dataset.visibleLimit = String(Math.max(10, Math.min(10000, Number(view.visibleLimit) || 10)));
  applyEmployerWorkQueueFilters(queue);
  rememberEmployerWorkQueueView(queue);
}
function captureEmployerWorkQueueNavigation(event) {
  if (state.user?.role !== 'employer' || state.tab !== 'overview') return;
  const button = event.target.closest('[data-action="open-employer-invitations"],[data-v02-action="open-employer-applications"]');
  const queue = button?.closest('#employer-workqueue');
  if (!queue || button.disabled) return;
  rememberEmployerWorkQueueView(queue);
  const view = ensureEmployerWorkQueueView();
  if (!view) return;
  view.returnPending = true;
  view.scrollOffset = Math.max(0, Math.round(-queue.getBoundingClientRect().top));
}

function employerWorkQueueMarkup(tasks, jobs = []) {
  const total = tasks.length;
  const visible = Math.min(total, 10);
  const count = priority => tasks.filter(task => task.priority === priority).length;
  const vacancyNames = new Map();
  for (const job of jobs || []) {
    const id = Number(job.id);
    if (Number.isSafeInteger(id) && id > 0) vacancyNames.set(id,String(job.title || 'Вакансия №'+id));
  }
  for (const task of tasks) {
    if (task.vacancyId && !vacancyNames.has(task.vacancyId)) vacancyNames.set(task.vacancyId,task.vacancy);
  }
  const vacancies = [...vacancyNames.entries()]
    .sort((a,b) => String(a[1]).localeCompare(String(b[1]), 'ru'));
  const vacancyOptions = vacancies.map(([id,title]) =>
    `<option value="${id}">${esc(title)}</option>`).join('');
  const stageOptions = [
    ['all', 'Все задачи', total],
    ['outcome', 'Ждут итога', count(0)],
    ['consent', 'Есть согласие', count(1)],
    ['applications', 'Отклики', count(2)+count(3)]
  ];
  const stageButtons = stageOptions.map(([value,label,amount]) =>
    `<button type="button" class="btn btn-tiny ${value === 'all' ? 'btn-dark' : 'btn-outline'}" data-action="employer-workqueue-filter" data-filter="${value}" aria-pressed="${value === 'all'}">${label} · ${amount}</button>`).join('');
  const cards = tasks.map((task, index) => {
    const target = task.kind === 'invitation'
      ? `data-action="open-employer-invitations" data-invitation-id="${task.id}" data-vacancy-id="${task.vacancyId || ''}" data-filter="${task.filter}"`
      : `data-v02-action="open-employer-applications" data-application-id="${task.id}" data-vacancy-id="${task.vacancyId || ''}" data-filter="attention"`;
    const stage = task.priority === 0 ? 'outcome' : task.priority === 1 ? 'consent' : 'applications';
    const searchText = [task.profession, task.vacancy].join(' ');
    return `<article class="employer-workqueue-item" data-employer-workqueue-item data-workqueue-kind="${task.kind}" data-workqueue-id="${task.id}" data-workqueue-stage="${stage}" data-workqueue-vacancy="${task.vacancyId || ''}" data-workqueue-search="${esc(searchText)}" ${index >= 10 ? 'hidden' : ''}>
        <div class="employer-workqueue-content"><span class="employer-workqueue-stage">${esc(task.stage)}</span>
          <h4>${esc(task.profession)} <small>№${task.id}</small></h4>
          <p class="employer-workqueue-vacancy">Вакансия: ${esc(task.vacancy)}</p>
          <p class="muted">${esc(task.detail)}</p>
        </div>
        <button type="button" class="btn btn-primary btn-tiny" ${target}>${esc(task.actionLabel)} →</button>
      </article>`;
  }).join('');
  return `<section class="panel employer-workqueue" id="employer-workqueue" aria-label="Единая рабочая очередь работодателя" data-visible-limit="10">
    <div class="split-header"><div><span class="section-kicker">РАБОЧАЯ ОЧЕРЕДЬ</span><h3>Требуют действия: ${total}</h3>
      <p class="muted">Отклики и знакомства в одном списке. Сначала завершите начатые знакомства, затем обработайте согласия и новые отклики. Каждый переход открывает нужную запись.</p></div></div>
    <div class="employer-workqueue-summary" aria-label="Состав очереди">
      <span><strong>${count(0)}</strong> Ждут итога</span><span><strong>${count(1)}</strong> Есть согласие</span>
      <span><strong>${count(2) + count(3)}</strong> Отклики на разбор</span>
    </div>
    ${count(2) + count(3) > 0 ? `<div class="employer-workqueue-quick-start">
      <div><strong>Разобрать отклики подряд</strong><p class="muted">Показываем по одному кандидату. После вашего решения — следующий, без возврата в общий список.</p></div>
      <button type="button" class="btn btn-primary" data-v02-action="open-employer-applications" data-filter="attention" data-quick="true">Начать разбор откликов →</button>
    </div>` : ''}
    ${total ? `
      <div class="employer-workqueue-tools">
        <div class="employer-workqueue-stage-filter" role="group" aria-label="Фильтр задач по этапу">${stageButtons}</div>
        <div class="employer-workqueue-fields">
          <label><span>Вакансия</span><select data-employer-workqueue-vacancy><option value="all">Все вакансии</option>${vacancyOptions}</select></label>
          <label><span>Поиск по профессии или вакансии</span><input type="search" data-employer-workqueue-search autocomplete="off" placeholder="Например, кладовщик"></label>
        </div>
      </div>
      <div class="employer-workqueue-list">${cards}</div>
      <div class="employer-workqueue-empty" data-employer-workqueue-empty hidden>
        <strong>По выбранным условиям задач нет</strong><p>Измените поиск или этап, либо сбросьте фильтры.</p>
        <button type="button" class="btn btn-outline btn-tiny" data-action="employer-workqueue-reset">Сбросить фильтры</button>
      </div>
      <div class="employer-workqueue-footer">
        <span role="status" aria-live="polite">Показано <strong id="employer-workqueue-visible">${visible}</strong> из <strong id="employer-workqueue-matched">${total}</strong> по фильтрам (всего ${total})</span>
        <button type="button" class="btn btn-outline" data-action="employer-workqueue-more" ${total <= 10 ? 'hidden' : ''}>Показать ещё ${Math.min(10,total - visible)} задач</button>
      </div>`
      : '<div class="empty-state"><strong>Срочных действий сейчас нет</strong><p>Новые отклики и согласия появятся в этой очереди. Можно продолжить подбор по вакансиям.</p><button type="button" class="btn btn-outline" data-tab="vacancies">К вакансиям →</button></div>'}
  </section>`;
}
function applyEmployerWorkQueueFilters(queue) {
  if (!queue || state.user?.role !== 'employer' || state.tab !== 'overview') return;
  const stage = queue.querySelector('[data-action="employer-workqueue-filter"][aria-pressed="true"]')?.dataset.filter || 'all';
  const vacancy = queue.querySelector('[data-employer-workqueue-vacancy]')?.value || 'all';
  const query = String(queue.querySelector('[data-employer-workqueue-search]')?.value || '').trim().toLocaleLowerCase('ru-RU');
  const limit = Math.max(10, Number(queue.dataset.visibleLimit) || 10);
  let matching = 0, visible = 0;
  for (const card of queue.querySelectorAll('[data-employer-workqueue-item]')) {
    const matches = (stage === 'all' || card.dataset.workqueueStage === stage) &&
      (vacancy === 'all' || card.dataset.workqueueVacancy === vacancy) &&
      (!query || String(card.dataset.workqueueSearch || '').toLocaleLowerCase('ru-RU').includes(query));
    if (matches) matching += 1;
    card.hidden = !matches || matching > limit;
    if (!card.hidden) visible += 1;
  }
  const visibleText = queue.querySelector('#employer-workqueue-visible');
  const matchingText = queue.querySelector('#employer-workqueue-matched');
  if (visibleText) visibleText.textContent = String(visible);
  if (matchingText) matchingText.textContent = String(matching);
  const empty = queue.querySelector('[data-employer-workqueue-empty]');
  if (empty) empty.hidden = matching !== 0;
  const more = queue.querySelector('[data-action="employer-workqueue-more"]');
  if (more) {
    const remaining = matching - visible;
    more.hidden = remaining <= 0;
    if (remaining > 0) more.textContent = 'Показать ещё ' + Math.min(10,remaining) + ' задач';
  }
}

function employerVacancyAnalyticsRows(jobs = [], applications = [], invitations = [], workQueue = []) {
  const rows = new Map();
  const validId = value => {
    const id = Number(value);
    return Number.isSafeInteger(id) && id > 0 ? id : 0;
  };
  function ensure(id, title = '', status = '') {
    const key = validId(id);
    if (!rows.has(key)) {
      rows.set(key, {
        id:key, title:key ? 'Вакансия №' + key : 'Без привязки к вакансии',
        status:'archive', applications:0, invitations:0, agreements:0,
        contacts:0, outcomes:0, hired:0, rejected:0, actions:0
      });
    }
    const row = rows.get(key);
    if (title && (row.title.startsWith('Вакансия №') || row.title === 'Без привязки к вакансии')) {
      row.title = String(title);
    }
    if (status) row.status = status === 'open' ? 'open' : 'closed';
    return row;
  }
  for (const job of jobs || []) {
    const id = validId(job.id);
    if (id) ensure(id,job.title,job.status);
  }
  const seenApplications = new Set();
  for (const app of applications || []) {
    const id = validId(app.id);
    if (!id || seenApplications.has(id)) continue;
    seenApplications.add(id);
    ensure(app.vacancy_id,app.title).applications += 1;
  }
  const seenInvitations = new Set();
  for (const invite of invitations || []) {
    const id = validId(invite.id);
    if (!id || seenInvitations.has(id)) continue;
    seenInvitations.add(id);
    const row = ensure(invite.vacancy_id,invite.vacancy_title);
    row.invitations += 1;
    const shared = Boolean(invite.contact_shared || invite.contact);
    if (invite.status === 'accepted' || shared) row.agreements += 1;
    if (shared) row.contacts += 1;
    const outcome = invitationFinalOutcome(invite);
    if (outcome === 'hired' || outcome === 'rejected') {
      row.outcomes += 1;
      row[outcome] += 1;
    }
  }
  for (const task of workQueue || []) {
    ensure(task.vacancyId,task.vacancy).actions += 1;
  }
  return [...rows.values()].sort((a,b) =>
    Number(b.status === 'open') - Number(a.status === 'open') ||
    b.actions - a.actions ||
    b.applications - a.applications ||
    a.title.localeCompare(b.title,'ru')
  );
}
function employerVacancyInsight(row) {
  // These are event ratios, not a candidate journey: direct invitations need no application.
  const ratio = (count,total) => total > 0 ? Math.round(100 * count / total) + '%' : '—';
  const agreementRate = ratio(row.agreements,row.invitations);
  const outcomeRate = ratio(row.outcomes,row.contacts);
  const positiveRate = ratio(row.hired,row.outcomes);
  const flags = [];
  if (row.invitations >= 5 && row.agreements === 0) flags.push('Нет согласий при 5+ запросах');
  if (row.contacts >= 5 && row.outcomes === 0) flags.push('Нет итогов при 5+ открытых контактах');
  if (row.applications >= 10 && row.invitations === 0) flags.push('10+ откликов без запросов на знакомство');
  return {agreementRate,outcomeRate,positiveRate,flags,
    priority:flags.length ? 1 : 0,
    effectiveness:row.outcomes > 0 ? row.hired / row.outcomes : -1};
}
function employerVacancyAnalyticsMarkup(jobs, applications, invitations, workQueue) {
  const rows = employerVacancyAnalyticsRows(jobs,applications,invitations,workQueue);
  const open = rows.filter(row => row.status === 'open').length;
  const closed = rows.length - open;
  const filters = [['all','Все',rows.length],['open','Открытые',open],['closed','Остальные',closed]]
    .map(([value,label,count]) => `<button type="button" class="btn btn-tiny ${value === 'all' ? 'btn-dark' : 'btn-outline'}" data-action="employer-analytics-filter" data-filter="${value}" aria-pressed="${value === 'all'}">${label} · ${count}</button>`).join('');
  const metrics = [
    ['applications','Отклики'],
    ['invitations','Запросы'],
    ['agreements','Согласия'],
    ['contacts','Контакты'],
    ['outcomes','Итоги'],
    ['actions','Требуют действия']
  ];
  const sorting = [['activity','По активности'],['results','По положительным итогам'],['attention','Требуют внимания']]
    .map(([value,label]) => `<button type="button" class="btn btn-tiny ${value === 'activity' ? 'btn-dark' : 'btn-outline'}" data-action="employer-analytics-sort" data-sort="${value}" aria-pressed="${value === 'activity'}">${label}</button>`).join('');
  const cards = rows.map(row => {
    const insight = employerVacancyInsight(row);
    const status = row.status === 'open' ? 'Открыта' : row.status === 'closed' ? 'Закрыта' : 'В архиве';
    const values = metrics.map(([key,label]) => `<span class="employer-analytics-metric"><strong data-analytics-metric="${key}">${row[key]}</strong><small>${label}</small></span>`).join('');
    const action = row.applications && row.id
      ? `<button type="button" class="btn btn-outline btn-tiny" data-v02-action="open-employer-applications" data-filter="all" data-vacancy-id="${row.id}">Посмотреть отклики</button>`
      : '';
    const invitationsAction = row.invitations && row.id
      ? `<button type="button" class="btn btn-outline btn-tiny" data-action="open-employer-invitations" data-filter="all" data-vacancy-id="${row.id}">Посмотреть знакомства</button>`
      : '';
    const fallbackAction = !action && !invitationsAction
      ? '<button type="button" class="btn btn-outline btn-tiny" data-tab="vacancies">Мои вакансии</button>'
      : '';
    const insightMarkup = `<div class="employer-analytics-conversions" aria-label="Конверсия событий">
      <span><strong>${insight.agreementRate}</strong><small>Согласия / запросы</small></span>
      <span><strong>${insight.outcomeRate}</strong><small>Итоги / открытые контакты</small></span>
      <span><strong>${insight.positiveRate}</strong><small>Положительные / итоги</small></span>
    </div>`;
    const attention = insight.flags.length ? `<p class="employer-analytics-attention"><strong>Обратите внимание:</strong> ${insight.flags.join('; ')}.</p>` : '';
    return `<article class="employer-analytics-vacancy" data-analytics-row data-analytics-vacancy-id="${row.id}" data-analytics-status="${row.status}" data-analytics-positive="${row.hired}" data-analytics-attention="${insight.priority}" data-analytics-order="${rows.indexOf(row)}">
      <div class="employer-analytics-heading"><div><h4>${esc(row.title)}</h4><span class="employer-analytics-status">${status}</span></div><div class="employer-analytics-actions">${action}${invitationsAction}${fallbackAction}</div></div>
      <div class="employer-analytics-metrics" aria-label="Показатели вакансии">${values}</div>
      ${insightMarkup}${attention}
      <p class="employer-analytics-outcomes">Из ${row.outcomes} итогов: положительных — ${row.hired}, не договорились — ${row.rejected}.${row.outcomes ? ' Доля положительных: ' + Math.round(100 * row.hired / row.outcomes) + '%.' : ''}</p>
    </article>`;
  }).join('');
  return `<section class="panel employer-vacancy-analytics" id="employer-vacancy-analytics" aria-label="Аналитика по вакансиям">
    <div class="split-header"><div><span class="section-kicker">АНАЛИТИКА ПО ВАКАНСИЯМ</span><h3>Результаты по каждой вакансии</h3>
      <p class="muted">Текущий срез записей компании, включая закрытые вакансии. Данные обновляются при открытии кабинета, отдельно от быстрого разбора откликов.</p></div></div>
    ${rows.length ? `<div class="employer-analytics-filters" role="group" aria-label="Статус вакансии">${filters}</div>
      <div class="employer-analytics-sorting" role="group" aria-label="Сортировка вакансий">${sorting}</div>
      <p class="employer-analytics-visible" role="status" aria-live="polite">Показано <strong id="employer-analytics-visible-count">${rows.length}</strong> из ${rows.length} вакансий</p>
      <div class="employer-analytics-list">${cards}</div>
      <div class="employer-analytics-empty" hidden>По выбранному статусу вакансий пока нет. Выберите «Все».</div>`
      : '<div class="empty-state"><strong>Вакансий пока нет</strong><p>Создайте вакансию, чтобы здесь появилась аналитика.</p><button type="button" class="btn btn-primary" data-tab="create">Создать вакансию</button></div>'}
    <p class="employer-analytics-note">Проценты рассчитываются только при наличии событий в знаменателе; «—» означает отсутствие базы для расчёта. Сигналы показывают возможные узкие места, а не качество кандидатов. Это текущий срез, не исторический тренд.</p>
    <p class="employer-analytics-note">Отклик и приглашение — разные события: компания может направить запрос без предварительного отклика, поэтому числа по этапам не обязательно убывают. Итог означает зафиксированный результат знакомства, а не подтверждённое трудоустройство.</p>
  </section>`;
}

async function renderEmployer() {
  const nav = [{id:'overview',label:'Обзор'},{id:'company',label:'Компания'},{id:'vacancies',label:'Мои вакансии'},{id:'create',label:'Новая вакансия'},{id:'applications',label:'Отклики'},{id:'invitations',label:'Знакомства и контакты'},{id:'security',label:'Безопасность'}];
  if (state.tab === 'edit') nav.splice(2, 0, {id:'edit',label:'Редактирование'});
  if (!nav.some(t => t.id === state.tab)) state.tab = 'overview';
  $('#account-content').innerHTML = `<div class="dashboard-grid">${tabsMarkup(nav,'ДЛЯ КОМПАНИИ',state.user.company?.company_name || 'Работодатель')}<div id="dashboard-main"><div class="loading">Загрузка...</div></div></div>`;
  const target = $('#dashboard-main');
  try {
    if (state.tab === 'overview') {
      const [jobsResult, applicationsResult, invitationsResult, companyResult, draftsResult] = await Promise.all([
        api('/api/employer/vacancies'),
        api('/api/employer/applications'),
        api('/api/employer/invitations'),
        api('/api/employer/company'),
        api('/api/employer/vacancy-drafts')
      ]);
      const drafts = draftsResult.drafts || [];
      const recentDraft = drafts[0];
      const jobs = jobsResult.jobs || [];
      const applications = applicationsResult.applications || [];
      const invitations = invitationsResult.invitations || [];
      const companyTrust = companyResult.trust || {};
      const openJobs = jobs.filter(job => job.status === 'open');
      const actionableApplications = applications.filter(item =>
        !item.invitation_id && ['applied','reviewing','interview'].includes(item.status)
      );
      const acceptedInvitations = invitations.filter(item => employerInvitationBucket(item) === 'action');
      const activeOpenedContacts = invitations.filter(employerInvitationNeedsOutcome);
      const consentedInvitations = invitations.filter(item => item.status === 'accepted' || item.contact_shared).length;
      const openedContacts = invitations.filter(item => item.contact_shared).length;
      const hiredIntroductions = invitations.filter(item => invitationFinalOutcome(item) === 'hired').length;
      const rejectedIntroductions = invitations.filter(item => invitationFinalOutcome(item) === 'rejected').length;
      const completedIntroductions = hiredIntroductions + rejectedIntroductions;
      const hireConversion = completedIntroductions ? Math.round(hiredIntroductions / completedIntroductions * 100) : 0;
      let nextTitle = 'Создайте первую вакансию';
      let nextText = 'После публикации можно получать отклики и запускать подбор кандидатов.';
      let nextAction = '<button class="btn btn-primary" data-tab="create">Создать вакансию →</button>';
      if (activeOpenedContacts.length) {
        nextTitle = 'Зафиксируйте итог знакомства';
        nextText = `Открытых контактов без финального решения: ${activeOpenedContacts.length}.`;
        nextAction = '<button class="btn btn-primary" data-action="open-employer-invitations" data-filter="introduced">Зафиксировать итог →</button>';
      } else if (acceptedInvitations.length) {
        nextTitle = 'Есть согласие кандидата';
        nextText = `Можно продолжить знакомство по ${acceptedInvitations.length} кандидатам.`;
        nextAction = '<button class="btn btn-primary" data-action="open-employer-invitations" data-filter="action">Продолжить знакомство →</button>';
      } else if (actionableApplications.length) {
        nextTitle = 'Разберите новые отклики';
        nextText = `Требуют внимания: ${actionableApplications.length}.`;
        nextAction = '<button class="btn btn-primary" data-v02-action="open-employer-applications" data-filter="attention">Открыть отклики →</button>';
      } else if (openJobs.length) {
        nextTitle = 'Запустите подбор по открытой вакансии';
        nextText = 'Посмотрите подходящие обезличенные профили и пригласите тех, кто подходит.';
        nextAction = `<button type="button" class="btn btn-primary" data-action="open-employer-matches" data-id="${Number(openJobs[0].id)}">Посмотреть кандидатов →</button>`;
      } else if (recentDraft) {
        nextTitle = 'Продолжите черновик вакансии';
        nextText = `Последняя незавершённая вакансия: ${String(recentDraft.fields?.title || '').trim() || 'без названия'}. Она пока не видна соискателям.`;
        nextAction = `<button class="btn btn-primary" data-action="resume-vacancy-draft" data-id="${Number(recentDraft.id)}">Продолжить заполнение →</button>`;
      }
      const showDraftReminder = drafts.length && nextTitle !== 'Продолжите черновик вакансии';
      const workQueue = employerWorkQueueEntries(applications, invitations);
      target.innerHTML = `<div class="overview-stack">
        <section class="panel dashboard-overview-hero employer-overview-hero">
          <span class="section-kicker">ПРИОРИТЕТ СЕЙЧАС</span>
          <div class="overview-priority"><div><h3>${esc(nextTitle)}</h3><p class="muted">${esc(nextText)}</p></div>${nextAction}</div>
        </section>
        ${employerWorkQueueMarkup(workQueue, jobs)}
        ${showDraftReminder ? `<section class="panel employer-draft-reminder">
          <div><span class="section-kicker">НЕЗАВЕРШЁННАЯ ВАКАНСИЯ</span><h3>Черновики: ${drafts.length}</h3>
          <p class="muted">${esc(String(recentDraft.fields?.title || '').trim() || 'Без названия')} · Последнее сохранение: ${esc(draftSavedAt(recentDraft.updated_at))}</p>
          <p class="muted">Они доступны только вашей компании и не опубликованы.</p></div>
          <button type="button" class="btn btn-outline" data-action="resume-vacancy-draft" data-id="${Number(recentDraft.id)}">Продолжить последний</button>
        </section>` : ''}
        <section class="panel employer-trust-overview">
          <div class="split-header"><div><span class="section-kicker">ДОВЕРИЕ К КОМПАНИИ</span><h3>${esc(companyResult.company?.company_name || 'Компания')}</h3></div><button class="btn btn-outline btn-tiny" data-tab="company">Настроить компанию →</button></div>
          ${companyTrustMarkup(companyTrust)}
        </section>
        <section class="overview-stat-grid employer-overview-stats" aria-label="Сводка работодателя">
          <button type="button" class="overview-stat-card" data-tab="vacancies"><strong>${openJobs.length}</strong><span>Открытые вакансии</span><small>Сейчас в работе</small></button>
          <button type="button" class="overview-stat-card" data-v02-action="open-employer-applications" data-filter="attention"><strong>${actionableApplications.length}</strong><span>Отклики требуют внимания</span><small>Нужен ваш следующий шаг</small></button>
          <button type="button" class="overview-stat-card" data-action="open-employer-invitations" data-filter="action"><strong>${acceptedInvitations.length}</strong><span>Есть согласие</span><small>Можно открыть контакт</small></button>
          <button type="button" class="overview-stat-card" data-action="open-employer-invitations" data-filter="introduced"><strong>${activeOpenedContacts.length}</strong><span>Ждут итога</span><small>Контакт уже открыт</small></button>
        </section>
        <section class="panel overview-funnel employer-outcome-funnel">
          <div class="split-header"><div><span class="section-kicker">ВОРОНКА</span><h3>От вакансии до результата</h3></div><button class="btn btn-outline btn-tiny" data-tab="vacancies">Управлять вакансиями</button></div>
          <div class="overview-funnel-steps">
            <div><strong>${jobs.length}</strong><span>Вакансии</span></div><b>→</b>
            <div><strong>${applications.length}</strong><span>Отклики</span></div><b>→</b>
            <div><strong>${consentedInvitations}</strong><span>Согласия</span></div><b>→</b>
            <div><strong>${openedContacts}</strong><span>Контакты</span></div><b>→</b>
            <div><strong>${completedIntroductions}</strong><span>Итоги</span></div>
          </div>
          <div class="employer-outcome-summary" aria-label="Результаты знакомств">
            <div><strong>${hiredIntroductions}</strong><span>Положительные итоги</span></div>
            <div><strong>${rejectedIntroductions}</strong><span>Не договорились</span></div>
            <div><strong>${activeOpenedContacts.length}</strong><span>Ждут итога</span></div>
          </div>
          <p class="employer-outcome-rate">Доля положительных итогов среди завершённых знакомств: <strong>${hireConversion}%</strong></p>
        </section>
        ${employerVacancyAnalyticsMarkup(jobs,applications,invitations,workQueue)}
      </div>`;
      restoreEmployerWorkQueueView(target.querySelector('#employer-workqueue'));
    } else if (state.tab === 'company') {
      const result = await api('/api/employer/company');
      target.innerHTML = employerCompanyMarkup(result);
    } else if (state.tab === 'create') {
      const draft = state.activeDraft;
      target.innerHTML = vacancyFormMarkup(null, draft);
    }
    else if (state.tab === 'edit') await loadEmployerVacancyEdit();
    else if (state.tab === 'vacancies') await loadEmployerVacancies();
    else if (state.tab === 'security') await renderAccountSecurity(target);
    else await loadEmployerInvitations(true);
  } catch(e) { target.innerHTML = `<div class="panel">${esc(e.message)}</div>`; toast(e.message,true); }
}
function vacancyFormMarkup(job = null, draft = null) {
  if (draft && !job) job = {...draft.fields, draft_only: true};
  const isEdit = Boolean(job && !job.draft_only);
  const draftValues = draft?.fields || {};
  const sections = isEdit ? window.OpytnovacancyWizard?.splitDescription(job.description) : (draft ? draftValues : null);
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
    <form id="vacancy-form" data-edit-id="${isEdit ? job.id : ''}" data-revision="${isEdit ? esc(job.revision) : ''}" data-edit-mode="${legacy ? 'legacy' : 'structured'}" data-draft-id="${draft?.id || ''}" data-draft-version="${draft?.version || ''}">
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
          <div class="field"><label for="vacancy-salary-min">Зарплата от, ₽ *</label><input id="vacancy-salary-min" name="salary_min" type="number" inputmode="numeric" min="0" max="10000000" value="${draft ? esc(draftValues.salary_min ?? '') : (isEdit ? Number(job.salary_min) : '')}" placeholder="Например, 60000" required></div>
          <div class="field"><label for="vacancy-salary-max">Зарплата до, ₽ *</label><input id="vacancy-salary-max" name="salary_max" type="number" inputmode="numeric" min="0" max="10000000" value="${draft ? esc(draftValues.salary_max ?? '') : (isEdit ? Number(job.salary_max) : '')}" placeholder="Например, 90000" required></div>
          <p class="field-help vacancy-salary-hint wide">Введите фактическую зарплату. Суммы не подставляются автоматически; если оплата фиксированная, можно указать одинаковое значение «от» и «до».</p>
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
      ${!isEdit ? `<div class="vacancy-draft-actions"><button type="button" class="btn btn-outline" data-action="save-vacancy-draft">${draft ? 'Сохранить сейчас' : 'Сохранить черновик'}</button><small>${draft ? 'Дальнейшие правки автоматически сохраняются на сервере. При ошибке можно сохранить вручную.' : 'Сначала сохраните черновик. После этого правки будут сохраняться автоматически и станут доступны на планшете.'}</small></div>` : ''}
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
  const form = $('#dashboard-main #vacancy-form');
  if (form) publishedVacancyBaselines.set(form, publishedJobSnapshot(job));
}
function employerVacancyPriority(job, stats = {}) {
  if (Number(stats.outcome || 0) > 0) return 0;
  if (job.status === 'open' && Number(stats.ready || 0) > 0) return 1;
  if (job.status === 'open' && Number(stats.attention || 0) > 0) return 2;
  if (job.status === 'open' && Number(stats.waiting || 0) > 0) return 3;
  return job.status === 'open' ? 4 : 5;
}
function applyEmployerVacancySearch() {
  const list = $('#employer-vacancy-results');
  if (!list) return;
  const query = String(state.employerVacancySearch || '').trim().toLocaleLowerCase('ru-RU');
  const cards = Array.from(list.querySelectorAll('.employer-vacancy-card'));
  let count = 0;
  for (const card of cards) {
    const haystack = String(card.dataset.vacancySearch || '').toLocaleLowerCase('ru-RU');
    card.hidden = Boolean(query && !haystack.includes(query));
    if (!card.hidden) count += 1;
  }
  const summary = $('#employer-vacancy-count');
  if (summary) summary.textContent = 'Показываем ' + count + ' из ' + cards.length + ' вакансий.';
  const empty = $('#employer-vacancy-empty');
  if (empty) empty.hidden = count !== 0;
  // A search may hide the vacancy owning the currently expanded match panel.
  const panel = $('#employer-matches');
  if (panel && !panel.classList.contains('hidden')) {
    const owner = panel.previousElementSibling;
    if (!owner?.matches('.employer-vacancy-card') || owner.hidden) {
      panel.classList.add('hidden');
      panel.innerHTML = '';
      state.activeVacancy = null;
      resetEmployerCandidateComparison();
    }
  }
}
async function loadEmployerVacancies() {
  const ownerId = state.user?.id;
  const target = $('#dashboard-main');
  const loadSequence = ++employerVacancyLoadSequence;
  const [jobsResult, applicationsResult, invitationsResult, draftsResult] = await Promise.all([
    api('/api/employer/vacancies'),
    api('/api/employer/applications'),
    api('/api/employer/invitations'),
    api('/api/employer/vacancy-drafts')
  ]);
  if (state.user?.role !== 'employer' || state.user.id !== ownerId || state.tab !== 'vacancies' ||
      !target?.isConnected || target !== $('#dashboard-main') || loadSequence !== employerVacancyLoadSequence) return;
  syncEmployerMatchAccount();
  const drafts = draftsResult.drafts || [];
  const jobs = jobsResult.jobs || [];
  employerOwnedVacancies.clear();
  for (const job of jobs) {
    const jobId = positiveRecordId(job.id);
    if (jobId) employerOwnedVacancies.set(jobId,Object.fromEntries(
      ['id','title','city','salary_min','salary_max','schedule','employment','skills','status'].map(key=>[key,job[key]])
    ));
  }
  const applications = applicationsResult.applications || [];
  const invitations = invitationsResult.invitations || [];
  const applicationsByJob = new Map();
  for (const a of applications) {
    const id = Number(a.vacancy_id);
    if (!applicationsByJob.has(id)) applicationsByJob.set(id, {total: 0, interested: 0, attention: 0, ready: 0, waiting: 0, outcome: 0, hired: 0, rejected: 0});
    const stats = applicationsByJob.get(id);
    stats.total += 1;
    if (a.status === 'interview' || a.invitation_id) stats.interested += 1;
    if (!a.invitation_id && ['applied','reviewing','interview'].includes(a.status)) stats.attention += 1;
  }
  for (const invitation of invitations) {
    const id = Number(invitation.vacancy_id);
    if (!applicationsByJob.has(id)) applicationsByJob.set(id, {total: 0, interested: 0, attention: 0, ready: 0, waiting: 0, outcome: 0, hired: 0, rejected: 0});
    const stats = applicationsByJob.get(id);
    const bucket = employerInvitationBucket(invitation);
    const outcome = invitationFinalOutcome(invitation);
    if (bucket === 'action') stats.ready += 1;
    if (bucket === 'waiting') stats.waiting += 1;
    if (invitation.contact_shared && outcome === 'hired') stats.hired += 1;
    else if (invitation.contact_shared && outcome === 'rejected') stats.rejected += 1;
    else if (employerInvitationNeedsOutcome(invitation)) stats.outcome += 1;
  }
  const view = $('#dashboard-main');
  const openCount = jobs.filter(job => job.status === 'open').length;
  const closedCount = jobs.length - openCount;
  const filter = ['all', 'open', 'closed', 'attention'].includes(state.employerVacancyFilter) ? state.employerVacancyFilter : 'all';
  const attentionCount = jobs.filter(job => employerVacancyPriority(job, applicationsByJob.get(Number(job.id))) <= 2).length;
  const filteredJobs = jobs.filter(job => filter === 'all' ||
    (filter === 'attention'
      ? employerVacancyPriority(job, applicationsByJob.get(Number(job.id))) <= 2
      : job.status === filter));
  const visibleJobs = filteredJobs.map((job,index)=>({job,index})).sort((a,b)=>
    employerVacancyPriority(a.job, applicationsByJob.get(Number(a.job.id))) -
    employerVacancyPriority(b.job, applicationsByJob.get(Number(b.job.id))) ||
    a.index - b.index).map(entry=>entry.job);
  const invitationCount = invitations.length;
  const introducedCount = invitations.filter(item => item.contact_shared).length;
  const activeOpenedContacts = invitations.filter(employerInvitationNeedsOutcome);
  const actionableApplications = applications.filter(a => !a.invitation_id && ['applied','reviewing','interview'].includes(a.status));
  const readyIntroductions = invitations.filter(item => employerInvitationBucket(item) === 'action');
  const waitingIntroductions = invitations.filter(item => employerInvitationBucket(item) === 'waiting');
  const firstOpenJob = jobs.find(job => job.status === 'open');
  const firstActionableApplication = actionableApplications[0];
  let nextAction = '<div class="employer-next"><div><span>Следующий шаг</span><strong>Создайте первую вакансию</strong><small>После публикации можно получать отклики и запускать подбор.</small></div><button class="btn btn-primary btn-tiny" data-action="new-job">Создать вакансию →</button></div>';
  if (activeOpenedContacts.length) {
    nextAction = `<div class="employer-next"><div><span>Требует внимания</span><strong>Зафиксируйте итог знакомства</strong><small>Открытых контактов без финального решения: ${activeOpenedContacts.length}.</small></div><button class="btn btn-primary btn-tiny" data-action="open-employer-invitations" data-filter="introduced">Зафиксировать итог →</button></div>`;
  } else if (readyIntroductions.length) {
    nextAction = `<div class="employer-next"><div><span>Требует внимания</span><strong>Есть согласие кандидата</strong><small>Можно открыть контакт по ${readyIntroductions.length} знакомству(ам).</small></div><button class="btn btn-primary btn-tiny" data-action="open-employer-invitations" data-filter="action">Продолжить знакомство →</button></div>`;
  } else if (actionableApplications.length && firstActionableApplication) {
    nextAction = `<div class="employer-next"><div><span>Требует внимания</span><strong>Разберите новые отклики</strong><small>Нужен ваш следующий шаг по ${actionableApplications.length} отклику(ам).</small></div><button class="btn btn-primary btn-tiny" data-v02-action="open-employer-applications" data-filter="attention" data-vacancy-id="${Number(firstActionableApplication.vacancy_id)}">Открыть отклики →</button></div>`;
  } else if (waitingIntroductions.length) {
    nextAction = `<div class="employer-next employer-next-ok"><div><span>Сейчас действий нет</span><strong>Ждём решения кандидата</strong><small>Запрос отправлен по ${waitingIntroductions.length} знакомству(ам). Повторно отправлять его не нужно.</small></div><button class="btn btn-outline btn-tiny" data-action="open-employer-invitations" data-filter="waiting">Посмотреть ожидание →</button></div>`;
  } else if (jobs.length && applications.length === 0 && firstOpenJob) {
    nextAction = `<div class="employer-next"><div><span>Следующий шаг</span><strong>Запустите подбор кандидатов</strong><small>Открытая вакансия уже есть — посмотрите подходящие профили.</small></div><button class="btn btn-dark btn-tiny" data-action="matches" data-id="${Number(firstOpenJob.id)}">Подобрать кандидатов →</button></div>`;
  } else if (jobs.length) {
    nextAction = '<div class="employer-next employer-next-ok"><div><span>Воронка под контролем</span><strong>Продолжайте работу с вакансиями</strong><small>Статусы и следующие действия собраны в одном кабинете.</small></div></div>';
  }
  const draftsMarkup = drafts.length
    ? `<section class="panel employer-draft-workspace"><div class="split-header"><div><span class="section-kicker">СОХРАНЁННЫЕ НА СЕРВЕРЕ</span><h3>Черновики (${drafts.length})</h3></div></div>
        <p class="muted">Сначала самые недавно изменённые. Черновики видны только вам; соискатели увидят вакансию после публикации.</p>
        <div class="dashboard-list">${drafts.map(employerDraftCard).join('')}</div>
      </section>`
    : '';
  view.innerHTML = draftsMarkup + `<div class="panel">${nextAction}<div class="split-header"><div><h3>Мои вакансии</h3><p class="muted">После размещения получите список обезличенных профилей.</p></div><button class="btn btn-primary btn-tiny" data-action="new-job">+ Добавить</button></div><div class="employer-vacancy-totals"><strong>${openCount} открытых</strong><span>·</span><span>${attentionCount} требуют внимания</span><span>·</span><span>${jobs.length} всего</span></div><details class="employer-vacancy-report"><summary>Подробная статистика вакансий и откликов</summary><div class="employer-vacancy-report-body"><div class="stat-grid" aria-label="Статистика вакансий"><div class="stat-tile"><strong>${jobs.length}</strong><span>Всего вакансий</span></div><div class="stat-tile"><strong>${openCount}</strong><span>Открыты</span></div><div class="stat-tile"><strong>${closedCount}</strong><span>Закрыты</span></div></div><div class="stat-grid" aria-label="Воронка подбора"><div class="stat-tile"><strong>${applications.length}</strong><span>Отклики</span></div><div class="stat-tile"><strong>${invitationCount}</strong><span>Запросы на знакомство</span></div><div class="stat-tile"><strong>${introducedCount}</strong><span>Открытые контакты</span></div></div></div></details><div class="item-actions" role="group" aria-label="Фильтр вакансий"><button type="button" class="btn btn-tiny ${filter === 'all' ? 'btn-dark' : 'btn-outline'}" data-action="filter-employer-jobs" data-filter="all" aria-pressed="${filter === 'all'}">Все (${jobs.length})</button><button type="button" class="btn btn-tiny ${filter === 'open' ? 'btn-dark' : 'btn-outline'}" data-action="filter-employer-jobs" data-filter="open" aria-pressed="${filter === 'open'}">Открытые (${openCount})</button><button type="button" class="btn btn-tiny ${filter === 'closed' ? 'btn-dark' : 'btn-outline'}" data-action="filter-employer-jobs" data-filter="closed" aria-pressed="${filter === 'closed'}">Закрытые (${closedCount})</button><button type="button" class="btn btn-tiny ${filter === 'attention' ? 'btn-dark' : 'btn-outline'}" data-action="filter-employer-jobs" data-filter="attention" aria-pressed="${filter === 'attention'}">Требуют внимания (${attentionCount})</button></div><div class="employer-vacancy-find">
    <label for="employer-vacancy-search">Поиск по названию и городу</label>
    <div class="employer-vacancy-find-row">
      <input id="employer-vacancy-search" type="search" data-employer-vacancy-search
        autocomplete="off" value="${esc(state.employerVacancySearch)}"
        placeholder="Например, кладовщик или Подольск">
      <button type="button" class="btn btn-outline btn-tiny" data-action="clear-employer-job-search">Сбросить поиск</button>
    </div>
    <p class="muted employer-vacancy-result-count" id="employer-vacancy-count" role="status" aria-live="polite"></p>
  </div>
  <div class="dashboard-list" id="employer-vacancy-results">${visibleJobs.map(job =>
    jobEmployerMarkup(job, applicationsByJob.get(Number(job.id)))).join('')}</div>
  <div class="empty-state" id="employer-vacancy-empty" hidden>Вакансий по выбранным условиям не найдено. Измените поиск или фильтр.</div></div><div id="employer-matches" class="hidden"></div>`;
  applyEmployerVacancySearch();
  if (state.activeVacancy && visibleJobs.some(job => Number(job.id) === Number(state.activeVacancy))) {
    await loadMatches(state.activeVacancy);
  }
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
function jobEmployerMarkup(x, stats = {total: 0, interested: 0, attention: 0, ready: 0, waiting: 0, outcome: 0, hired: 0, rejected: 0}) {
  const needsOutcome = stats.outcome > 0;
  const hasReadyIntroduction = x.status === 'open' && stats.ready > 0;
  const needsAttention = x.status === 'open' && stats.attention > 0;
  const nextLabel = needsOutcome ? 'Нужно зафиксировать итог' : hasReadyIntroduction ? 'Есть согласие кандидата' : needsAttention ? 'Есть отклики для разбора' : stats.waiting > 0 ? 'Ждём решения кандидата' : (x.status === 'open' ? 'Ищем кандидатов' : 'Вакансия закрыта');
  const quality = vacancyQuality(x);
  const qualityClass = quality.percent >= 88 ? 'high' : quality.percent >= 63 ? 'medium' : 'low';
  const jobId = Number(x.id);
  const primaryAction = needsOutcome
    ? `<button type="button" class="btn btn-primary" data-action="open-employer-invitations" data-filter="introduced" data-vacancy-id="${jobId}">Зафиксировать итог →</button>`
    : hasReadyIntroduction
    ? `<button type="button" class="btn btn-primary" data-action="open-employer-invitations" data-filter="action" data-vacancy-id="${jobId}">Продолжить знакомство →</button>`
    : needsAttention
    ? `<button type="button" class="btn btn-primary" data-action="vacancy-applications-primary" data-id="${jobId}">Разобрать отклики →</button>`
    : x.status === 'open'
    ? `<button type="button" class="btn btn-dark" data-action="matches-primary" data-id="${jobId}">Подобрать кандидатов →</button>`
    : `<button type="button" class="btn btn-outline" data-action="job-status" data-id="${jobId}" data-status="open">Открыть для подбора →</button>`;
  return `<article class="item-card employer-vacancy-card ${(needsAttention || hasReadyIntroduction || needsOutcome) ? 'needs-attention' : ''}" data-employer-vacancy-id="${jobId}" data-vacancy-search="${esc(x.title + ' ' + x.city)}">
    <header><div><span class="card-eyebrow">${esc(nextLabel)}</span><h4>${esc(x.title)}</h4><p>${esc(x.city)} · ${formatPay(x)} · ${esc(x.schedule)}</p><div class="vacancy-moderation-state ${esc(x.moderation_status||'approved')}"><strong>${x.moderation_status==='pending'?'На проверке':x.moderation_status==='rejected'?'Отклонена модератором':'Опубликована'}</strong>${x.moderation_reason?`<small>${esc(x.moderation_reason)}</small>`:''}</div></div><span class="mini-badge ${x.status === 'open' ? '' : 'gray'}">${x.status === 'open' ? 'Открыта' : 'Закрыта'}</span></header>
    <div class="employer-vacancy-countline"><span>Откликов: <strong>${stats.total}</strong></span>${stats.attention ? `<span>Нужен ответ: <strong>${stats.attention}</strong></span>` : ''}${stats.ready ? `<span>Согласия: <strong>${stats.ready}</strong></span>` : ''}${stats.outcome ? `<span>Ждут итога: <strong>${stats.outcome}</strong></span>` : ''}</div>
    <div class="employer-vacancy-primary">${primaryAction}</div>
    <div class="item-actions employer-vacancy-secondary">
      <button type="button" class="btn btn-outline btn-tiny" data-action="vacancy-applications" data-id="${jobId}">Посмотреть отклики</button>
      <button type="button" class="btn btn-outline btn-tiny" data-action="matches" data-id="${jobId}" ${x.status === 'closed' ? 'disabled':''}>Подбор кандидатов</button>
      <button type="button" class="btn btn-outline btn-tiny" data-action="edit-job" data-id="${jobId}">Редактировать</button>
    </div>
    <details class="employer-vacancy-more">
      <summary>Дополнительно: показатели и управление</summary>
      <div class="employer-vacancy-more-body">
        <div class="vacancy-pipeline-mini"><span><strong>${stats.total}</strong><small>Отклики</small></span><span><strong>${stats.outcome}</strong><small>Ждут итога</small></span><span><strong>${stats.hired}</strong><small>Выбраны</small></span><span><strong>${stats.rejected}</strong><small>Не договорились</small></span></div>
        <div class="vacancy-quality ${qualityClass}"><div class="vacancy-quality-head"><span>Качество объявления</span><strong>${quality.percent}%</strong></div><div class="vacancy-quality-track"><span style="width:${quality.percent}%"></span></div>${quality.suggestions.length?`<p>${esc(quality.suggestions.slice(0,2).join(' · '))}</p>`:'<p>Основные условия заполнены хорошо.</p>'}</div>
        <div class="item-actions employer-vacancy-extra-actions">${x.status==='open' && (x.moderation_status||'approved')==='approved' ? `<a class="btn btn-outline btn-tiny" href="/vacancies/${jobId}">Ссылка на вакансию</a>` : ''}<button type="button" class="btn btn-outline btn-tiny" data-action="vacancy-history" data-id="${jobId}" aria-expanded="false" aria-controls="employer-vacancy-history-${jobId}">История условий</button><button type="button" class="btn btn-outline btn-tiny" data-action="job-status" data-id="${jobId}" data-status="${x.status === 'open' ? 'closed' : 'open'}">${x.status === 'open' ? 'Закрыть вакансию' : 'Открыть вакансию'}</button></div>
        <section class="employer-vacancy-history" id="employer-vacancy-history-${jobId}" aria-label="История изменений условий вакансии" hidden></section>
      </div>
    </details>
  </article>`;
}
// Comparison stays in this tab's memory and only uses the public professional DTO.
const employerOwnedVacancies = new Map();
const pendingEmployerMatchInvitations = new Set();
const savedEmployerMatchInvitations = new Map();
let employerMatchAccountId = null;
let employerMatchAccountVersion = 0;
let employerMatchRequestSequence = 0;
let employerVacancyLoadSequence = 0;
const employerCandidateComparison = {
  ownerId: null, vacancyId: null, vacancy: null, matches: [],
  selected: new Set(), visible: false, differencesOnly: false, returnFocusId: null
};
function positiveRecordId(value) {
  const id = Number(value);
  return Number.isSafeInteger(id) && id > 0 ? id : null;
}
function resetEmployerCandidateComparison() {
  employerMatchRequestSequence += 1;
  employerCandidateComparison.ownerId = null;
  employerCandidateComparison.vacancyId = null;
  employerCandidateComparison.vacancy = null;
  employerCandidateComparison.matches = [];
  employerCandidateComparison.selected.clear();
  employerCandidateComparison.visible = false;
  employerCandidateComparison.differencesOnly = false;
  employerCandidateComparison.returnFocusId = null;
}
function syncEmployerMatchAccount() {
  const ownerId = state.user?.role === 'employer' ? positiveRecordId(state.user.id) : null;
  if (ownerId === employerMatchAccountId) return;
  resetEmployerCandidateComparison();
  employerOwnedVacancies.clear();
  savedEmployerMatchInvitations.clear();
  employerMatchAccountVersion += 1;
  employerMatchAccountId = ownerId;
}
function employerMatchText(value) {
  return String(value || '')
    .replaceAll('в вашем профиле', 'в профиле кандидата')
    .replaceAll('вашей указанной профессии', 'указанной профессии кандидата')
    .replaceAll('Ваш минимум', 'Минимум кандидата')
    .replaceAll('ваших ожиданий', 'ожиданий кандидата')
    .replaceAll('Уточните специализацию в профиле — сейчас профессия указана слишком широко',
      'Профессия кандидата указана широко — уточните специализацию');
}
function employerMatchSnapshot(item = {}) {
  const textFields = ['profession','city','skills','schedule','employment','education','achievements','specializations','match_level'];
  const result = Object.fromEntries(textFields.map(key => [key, String(item[key] || '')]));
  result.candidate_id = positiveRecordId(item.candidate_id);
  result.invitation_id = positiveRecordId(item.invitation_id);
  result.invitation_status = ['sent','accepted','declined'].includes(item.invitation_status) ? item.invitation_status : null;
  result.contact_shared = item.contact_shared === true || Number(item.contact_shared) === 1;
  result.salary_min = Math.max(0, Number(item.salary_min) || 0);
  result.experience_years = Math.max(0, Number(item.experience_years) || 0);
  result.score = Math.max(0, Math.min(100, Number(item.score) || 0));
  for (const key of ['strengths','reasons','cautions']) {
    result[key] = Array.isArray(item[key]) ? item[key].map(employerMatchText).filter(Boolean) : [];
  }
  result.score_breakdown = (Array.isArray(item.score_breakdown) ? item.score_breakdown : [])
    .filter(factor => factor && typeof factor === 'object')
    .map(factor => ({
      key: String(factor.key || ''), label: String(factor.label || ''),
      text: employerMatchText(factor.text), caution: employerMatchText(factor.caution),
      state: ['strong','good','weak'].includes(factor.state) ? factor.state : 'good',
      points: Number(factor.points) || 0, max_points: Number(factor.max_points) || 0,
      percent: Math.max(0, Math.min(100, Number(factor.percent) || 0))
    }));
  result.work_history = (Array.isArray(item.work_history) ? item.work_history : []).slice(0,5)
    .filter(entry => entry && typeof entry === 'object')
    .map(entry => ({position:String(entry.position || ''), period:String(entry.period || ''), duties:String(entry.duties || '')}));
  result.courses = (Array.isArray(item.courses) ? item.courses : []).slice(0,6)
    .filter(entry => entry && typeof entry === 'object')
    .map(entry => ({title:String(entry.title || ''), provider:String(entry.provider || ''),
      year:Number(entry.year) || null, has_certificate:entry.has_certificate === true}));
  return result;
}
function employerMatchHasResume(item) {
  return Boolean(item.experience_years > 0 || item.education || item.achievements ||
    item.specializations || item.work_history.length || item.courses.length);
}
function employerMatchResumeMarkup(item) {
  return employerMatchHasResume(item) ? professionalResumeMarkup(item)
    : '<p class="muted">Не указано в резюме.</p>';
}
function employerMatchBreakdownMarkup(item) {
  const factors = Array.isArray(item.score_breakdown) ? item.score_breakdown : [];
  const cautions = Array.isArray(item.cautions) ? item.cautions : [];
  if (!factors.length) return '';
  const rows = factors.map(factor => `<div class="match-factor-row ${esc(factor.state||'good')}">
    <div class="match-factor-head"><span>${esc(factor.label||factor.key||'Фактор')}</span><strong>${Number(factor.points||0).toLocaleString('ru-RU')} / ${Number(factor.max_points||0).toLocaleString('ru-RU')}</strong></div>
    <div class="match-factor-track"><span style="width:${Math.max(0,Math.min(100,Number(factor.percent||0)))}%"></span></div>
    <small>${esc(employerMatchText(factor.text))}</small>
  </div>`).join('');
  const cautionMarkup = cautions.length ? `<div class="match-cautions"><strong>Что уточнить до приглашения</strong>${cautions.map(text=>`<span>! ${esc(employerMatchText(text))}</span>`).join('')}</div>` : '';
  return `<div class="match-breakdown compact">${rows}${cautionMarkup}<p class="match-method-note">Процент отражает совпадение профессии, навыков и условий вакансии. Опыт и достижения в этот расчёт не входят. Возраст не используется.</p></div>`;
}
function employerMatchInvitationKey(ownerId, jobId, candidateId) {
  return `${ownerId}:${jobId}:${candidateId}`;
}
function employerMatchInvitationMarkup(item, jobId) {
  const candidateId = positiveRecordId(item.candidate_id);
  if (!candidateId || !positiveRecordId(jobId)) return '';
  if (item.invitation_id || item.invitation_status === 'sent') {
    const label = item.contact_shared ? 'Контакт уже открыт →'
      : item.invitation_status === 'accepted' ? 'Согласие получено · продолжить →'
      : item.invitation_status === 'sent' ? 'Приглашение отправлено · ожидаем ответ'
      : item.invitation_status === 'declined' ? 'Кандидат отказался · история →' : 'Открыть знакомство →';
    return `<button type="button" class="btn ${!item.contact_shared && item.invitation_status === 'accepted' ? 'btn-primary' : 'btn-outline'} btn-tiny" data-action="open-employer-invitations" data-filter="all" data-vacancy-id="${jobId}" data-invitation-id="${item.invitation_id || ''}">${label}</button>`;
  }
  const busy = pendingEmployerMatchInvitations.has(employerMatchInvitationKey(state.user?.id, jobId, candidateId));
  return `<button type="button" class="btn btn-primary btn-tiny" data-action="invite" data-job="${jobId}" data-id="${candidateId}" ${busy ? 'disabled aria-busy="true"' : ''}>${busy ? 'Отправляем приглашение…' : 'Пригласить кандидата →'}</button>`;
}
function employerMatchInvitationSlot(item, jobId) {
  return `<div class="candidate-match-invitation-action" data-match-invitation-candidate="${item.candidate_id}" data-match-invitation-vacancy="${jobId}">${employerMatchInvitationMarkup(item,jobId)}</div>`;
}
function refreshEmployerMatchInvitationControls(item, jobId) {
  const candidateId = positiveRecordId(item.candidate_id);
  if (!candidateId || !positiveRecordId(jobId)) return;
  document.querySelectorAll(`#employer-matches [data-match-invitation-candidate="${candidateId}"][data-match-invitation-vacancy="${jobId}"]`)
    .forEach(slot => { slot.innerHTML = employerMatchInvitationMarkup(item,jobId); });
}
function employerCandidateQuestions(item) {
  const questions = [...item.cautions, ...item.score_breakdown.map(factor => factor.caution).filter(Boolean)];
  if (!item.salary_min) questions.push('Зарплатные ожидания не указаны — обсудите сумму и состав оплаты.');
  if (!item.skills.trim()) questions.push('Навыки не указаны в профиле — уточните необходимые для вакансии умения.');
  if (!item.experience_years && !item.work_history.length && !item.achievements.trim()) {
    questions.push('Опыт работы не описан — уточните задачи и результаты, связанные с вакансией.');
  }
  return [...new Set(questions.map(employerMatchText).filter(Boolean))];
}
function employerCandidateComparisonMarkup() {
  const comparison = employerCandidateComparison;
  const selected = [...comparison.selected].map(id => comparison.matches.find(item => item.candidate_id === id)).filter(Boolean);
  const vacancy = comparison.vacancy || {};
  const factorText = (item,key) => {
    const factor = item.score_breakdown.find(entry => entry.key === key);
    return factor?.text ? `<small class="candidate-compare-fact">${esc(employerMatchText(factor.text))}</small>` : '';
  };
  const value = (item,key) => `<p>${esc(item[key] || 'Не указано')}</p>${factorText(item,key === 'city' ? 'location' : key)}`;
  const comparable = {
    profession:item=>[item.profession,item.specializations].join(' | '),
    skills:item=>item.skills,
    salary:item=>String(item.salary_min || 0),
    location:item=>item.city,
    schedule:item=>item.schedule,
    employment:item=>item.employment,
    experience:item=>JSON.stringify([item.experience_years,item.education,item.achievements,item.work_history,item.courses])
  };
  const isDifferent = key => Boolean(comparable[key]) && new Set(selected.map(item => String(comparable[key](item) || '').trim().toLocaleLowerCase('ru-RU'))).size > 1;
  const rows = [
    {key:'score',title:'Совпадение по анкете',requirement:'Профессия, навыки и условия вакансии; опыт не оценивается этим процентом.',
      markup:item=>`<p><strong>${item.score}%</strong></p>`},
    {key:'profession',title:'Профессия и специализация',requirement:vacancy.title || 'Название не указано',
      markup:item=>`<p><strong>${esc(item.profession || 'Не указано')}</strong></p>${item.specializations ? `<p>${esc(item.specializations)}</p>` : ''}${factorText(item,'profession')}`},
    {key:'skills',title:'Навыки',requirement:vacancy.skills || 'Отдельно не указаны',markup:item=>value(item,'skills')},
    {key:'salary',title:'Зарплатные ожидания',requirement:formatPay(vacancy),
      markup:item=>`<p>${esc(candidateSalaryText(item.salary_min))}</p>${factorText(item,'salary')}`},
    {key:'location',title:'Город или формат работы',requirement:vacancy.city || 'Не указано',markup:item=>value(item,'city')},
    {key:'schedule',title:'График',requirement:vacancy.schedule || 'Не указан',markup:item=>value(item,'schedule')},
    {key:'employment',title:'Занятость',requirement:vacancy.employment || 'Не указана',markup:item=>value(item,'employment')},
    {key:'experience',title:'Опыт и образование',requirement:'Сведения из резюме; оцените применимость к задачам вакансии.',
      markup:item=>employerMatchResumeMarkup(item)},
    {key:'questions',title:'Что уточнить',requirement:'Вопросы перед знакомством по этой вакансии',
      markup:item=>{const questions=employerCandidateQuestions(item); return questions.length
        ? `<ul class="candidate-compare-list">${questions.map(text=>`<li class="candidate-compare-question">${esc(text)}</li>`).join('')}</ul>`
        : '<p>Подбор не выделил дополнительных вопросов по указанным условиям. Обсудите задачи и ожидания при знакомстве.</p>'; }},
    {key:'next',title:'Следующий шаг',requirement:'Выберите действие по каждой анкете',
      markup:item=>`<div class="candidate-compare-actions"><button type="button" class="btn btn-outline btn-tiny" data-action="compare-open-profile" data-id="${item.candidate_id}">Открыть резюме</button>${employerMatchInvitationSlot(item,comparison.vacancyId)}</div>`}
  ];
  const differingRows = rows.filter(row=>isDifferent(row.key));
  const differences = differingRows.length;
  const comparisonSummary = differingRows.length
    ? `Различаются: ${differingRows.map(row=>row.title.toLocaleLowerCase('ru-RU')).join(', ')}.`
    : 'По указанным профессиональным критериям различий не обнаружено.';
  const questionsSummary = selected.map(item=>{
    const count = employerCandidateQuestions(item).length;
    return `Анкета №${item.candidate_id}: ${count ? `вопросов для уточнения — ${count}` : 'дополнительных вопросов не выявлено'}`;
  }).join('; ');
  return `<div class="candidate-comparison-heading"><h4>Сравнение выбранных анкет</h4><p>${esc(vacancy.title || 'Выбранная вакансия')}</p>
      <button type="button" class="btn btn-outline candidate-compare-differences-toggle" data-action="compare-differences" aria-pressed="${comparison.differencesOnly}" aria-controls="candidate-compare-table">${comparison.differencesOnly ? 'Показать все критерии' : `Показать только различия (${differences})`}</button>
      <p class="candidate-compare-differences-hint" role="status">${comparison.differencesOnly ? `Показаны ${differences} различающихся критериев, а также оценка, вопросы и действия.` : 'Вы можете скрыть одинаковые сведения, чтобы быстрее увидеть отличия. Оценка, вопросы и действия останутся видны.'}</p></div>
    <div class="candidate-comparison-note" aria-label="Краткое резюме сравнения"><strong>Кратко о различиях</strong><p>${esc(comparisonSummary)}</p><p>${esc(questionsSummary)}. Сверьте условия вакансии и обсудите вопросы перед приглашением.</p></div>
    <p class="candidate-comparison-note">Процент отражает совпадение профессии, навыков и условий. Опыт и достижения показаны со слов кандидата и не входят в расчёт. Возраст не используется. Решение о знакомстве принимаете вы.</p>
    <table class="candidate-compare-table" id="candidate-compare-table"><caption>Анкеты и условия вакансии «${esc(vacancy.title || 'Выбранная вакансия')}»</caption>
      <thead><tr><th scope="col" id="candidate-compare-criterion">Критерий и условия вакансии</th>${selected.map(item=>`<th scope="col" id="candidate-compare-column-${item.candidate_id}">Анкета №${item.candidate_id}<small class="candidate-compare-fact">Совпадение условий: ${item.score}%</small></th>`).join('')}</tr></thead>
      <tbody>${rows.map(row=>`<tr class="candidate-compare-row" data-compare-field="${row.key}" data-compare-different="${isDifferent(row.key)}" ${comparison.differencesOnly && comparable[row.key] && !isDifferent(row.key) ? 'hidden' : ''}><th scope="row" id="candidate-compare-row-${row.key}">${row.title}<small class="candidate-compare-requirement">${esc(row.requirement)}</small></th>${selected.map(item=>`<td data-compare-candidate-id="${item.candidate_id}" headers="candidate-compare-row-${row.key} candidate-compare-column-${item.candidate_id}"><span class="candidate-compare-mobile-label" aria-hidden="true">Анкета №${item.candidate_id}</span><div class="candidate-compare-value">${row.markup(item)}</div></td>`).join('')}</tr>`).join('')}</tbody>
    </table>`;
}
function updateEmployerCandidateComparison() {
  const panel = $('#employer-matches');
  if (!panel || employerCandidateComparison.vacancyId !== state.activeVacancy) return;
  const comparison = employerCandidateComparison;
  const count = comparison.selected.size;
  if (count < 2) comparison.visible = false;
  const status = panel.querySelector('#employer-compare-status');
  if (status) status.textContent = count === 0 ? 'Выберите две или три анкеты. Приглашения отправляются отдельно.'
    : count === 1 ? 'Выбрана 1 анкета из 3. Добавьте ещё одну для сравнения.'
    : count === 3 ? 'Выбраны 3 анкеты из 3. Чтобы добавить другую, снимите выбор с одной из них.'
    : 'Выбраны 2 анкеты из 3. Можно сравнить их или добавить третью.';
  panel.querySelectorAll('[data-action="compare-toggle-candidate"]').forEach(button => {
    const id = Number(button.dataset.id);
    const selected = comparison.selected.has(id);
    button.setAttribute('aria-pressed',String(selected));
    button.setAttribute('aria-label',`${selected ? 'Убрать из сравнения' : 'Добавить в сравнение'} анкету №${id}`);
    button.disabled = !selected && count >= 3;
    button.textContent = selected ? 'Убрать из сравнения' : 'Добавить в сравнение';
    button.classList.toggle('btn-dark',selected);
    button.classList.toggle('btn-outline',!selected);
    button.closest('.candidate-match-card')?.classList.toggle('is-compared',selected);
  });
  const show = panel.querySelector('[data-action="compare-show"]');
  if (show) { show.disabled = count < 2; show.hidden = comparison.visible; show.textContent = `Сравнить${count ? ' (' + count + ')' : ''}`; }
  const clear = panel.querySelector('[data-action="compare-clear"]');
  if (clear) clear.disabled = count === 0;
  const back = panel.querySelector('[data-action="compare-back"]');
  if (back) back.hidden = !comparison.visible;
  const list = panel.querySelector('[data-employer-match-list]');
  if (list) list.hidden = comparison.visible;
  const region = panel.querySelector('#employer-candidate-comparison');
  if (region) {
    region.hidden = !comparison.visible;
    if (comparison.visible) region.innerHTML = employerCandidateComparisonMarkup();
    else region.innerHTML = '';
  }
}
function focusEmployerComparisonCard(id, openResume = false) {
  const card = positiveRecordId(id) && document.querySelector(`#employer-matches .candidate-match-card[data-match-candidate-id="${Number(id)}"]`);
  if (card) {
    if (openResume) { const details = card.querySelector('.candidate-resume-details'); if (details) details.open = true; }
    card.focus({preventScroll:true});
    card.scrollIntoView({block:'nearest'});
  } else $('#employer-matches [data-action="compare-show"]')?.focus({preventScroll:true});
}
function handleEmployerComparisonAction(action, id) {
  const comparison = employerCandidateComparison;
  if (state.user?.role !== 'employer' || state.tab !== 'vacancies' ||
      comparison.ownerId !== state.user.id || comparison.vacancyId !== state.activeVacancy) return;
  if (action === 'compare-toggle-candidate') {
    if (!positiveRecordId(id) || !comparison.matches.some(item => item.candidate_id === id)) return;
    if (comparison.selected.has(id)) comparison.selected.delete(id);
    else if (comparison.selected.size < 3) comparison.selected.add(id);
    comparison.returnFocusId = id;
    updateEmployerCandidateComparison();
  } else if (action === 'compare-differences') {
    if (!comparison.visible || comparison.selected.size < 2) return;
    comparison.differencesOnly = !comparison.differencesOnly;
    updateEmployerCandidateComparison();
    $('#employer-candidate-comparison [data-action="compare-differences"]')?.focus({preventScroll:true});
  } else if (action === 'compare-show') {
    if (comparison.selected.size < 2) return;
    comparison.visible = true;
    updateEmployerCandidateComparison();
    const region = $('#employer-candidate-comparison');
    region?.focus({preventScroll:true});
    region?.scrollIntoView({block:'start'});
  } else if (action === 'compare-back' || action === 'compare-clear' || action === 'compare-open-profile') {
    if (action === 'compare-open-profile' && (!positiveRecordId(id) || !comparison.selected.has(id))) return;
    const focusId = action === 'compare-open-profile' ? id : comparison.returnFocusId;
    comparison.visible = false;
    if (action === 'compare-clear') comparison.selected.clear();
    updateEmployerCandidateComparison();
    focusEmployerComparisonCard(focusId,action === 'compare-open-profile');
  }
}
async function sendEmployerMatchInvitation(button, candidateId) {
  const jobId = positiveRecordId(button.dataset.job);
  const ownerId = positiveRecordId(state.user?.id);
  const comparison = employerCandidateComparison;
  if (!jobId || !positiveRecordId(candidateId) || state.user?.role !== 'employer' ||
      state.tab !== 'vacancies' || comparison.ownerId !== ownerId || comparison.vacancyId !== jobId || state.activeVacancy !== jobId) return;
  const item = comparison.matches.find(candidate => candidate.candidate_id === candidateId);
  if (!item || item.invitation_id || item.invitation_status === 'sent') return;
  const key = employerMatchInvitationKey(ownerId,jobId,candidateId);
  if (pendingEmployerMatchInvitations.has(key) || savedEmployerMatchInvitations.has(key)) return;
  const panel = $('#employer-matches');
  const requestSequence = employerMatchRequestSequence;
  const accountVersion = employerMatchAccountVersion;
  const sameAccount = () => state.user?.role === 'employer' && state.user?.id === ownerId && employerMatchAccountVersion === accountVersion;
  const sameView = () => sameAccount() && panel?.isConnected && state.tab === 'vacancies' &&
    state.activeVacancy === jobId && employerMatchRequestSequence === requestSequence;
  pendingEmployerMatchInvitations.add(key);
  refreshEmployerMatchInvitationControls(item,jobId);
  let saved = false;
  try {
    const result = await api('/api/employer/invitations',{method:'POST',body:JSON.stringify({vacancy_id:jobId,candidate_id:candidateId})});
    saved = true;
    if (!sameAccount()) return;
    const receipt = {invitation_id:positiveRecordId(result.id),invitation_status:'sent',contact_shared:false};
    savedEmployerMatchInvitations.set(key,receipt);
    Object.assign(item,receipt);
    if (comparison.ownerId === ownerId && comparison.vacancyId === jobId) {
      const current = comparison.matches.find(candidate => candidate.candidate_id === candidateId);
      if (current) Object.assign(current,receipt);
      refreshEmployerMatchInvitationControls(current || item,jobId);
    }
    // A late response must not move a person away from the page they chose.
    if (!sameView()) return;
    toast('Приглашение отправлено.');
    employerInvitationVisibleLimit = employerInvitationPageSize;
    state.employerInvitationsTargetId = receipt.invitation_id;
    state.employerInvitationsFilter = 'waiting';
    state.employerInvitationsVacancyFilter = String(jobId);
    state.employerInvitationsQuery = '';
    state.employerInvitationsData = null;
    state.tab = 'invitations';
    state.activeVacancy = null;
    try { await showDashboard(); }
    catch (error) { if (sameAccount()) toast('Приглашение отправлено, но список пока не обновился. Откройте раздел «Знакомства и контакты».',true); }
  } catch (error) {
    if (sameView()) toast(saved ? 'Приглашение отправлено. Откройте раздел «Знакомства и контакты».' : error.message,true);
  } finally {
    pendingEmployerMatchInvitations.delete(key);
    if (sameAccount() && comparison.ownerId === ownerId && comparison.vacancyId === jobId) {
      const current = comparison.matches.find(candidate => candidate.candidate_id === candidateId);
      if (current) refreshEmployerMatchInvitationControls(current,jobId);
    }
  }
}
function employerVacancyHistoryEntries(updates, view) {
  return updates.map(update=>`
    <article class="employer-vacancy-history-entry" data-history-update-id="${Number(update.id)}">
      <div class="employer-vacancy-history-meta">
        <strong>Изменение от ${esc(view.date(update.created_at))}</strong>
        <span class="muted">${Number(update.recipients_total)>0
          ? 'Получателей в личных кабинетах: '+Number(update.recipients_total)
          : 'На момент изменения получателей не было'}</span>
      </div>
      <div class="vacancy-changes-list">${view.markup(update.changes)}</div>
    </article>`).join('');
}
function employerVacancyHistoryPager(result) {
  return result.has_more && result.next_cursor
    ? `<button type="button" class="btn btn-outline" data-action="more-vacancy-history" data-id="${Number(result.vacancy_id)}" data-before-id="${Number(result.next_cursor)}">Показать более ранние изменения</button>`
    : '';
}
async function toggleEmployerVacancyHistory(btn,jobId) {
  const card = btn.closest('.employer-vacancy-card');
  const history = card?.querySelector('#employer-vacancy-history-' + jobId);
  if (!history || !Number.isSafeInteger(jobId) || jobId <= 0) return;
  if (!history.hidden) {
    history.hidden = true;
    btn.setAttribute('aria-expanded','false');
    return;
  }
  const view = window.StazhnoVacancyChanges;
  if (!view || typeof view.markup !== 'function') {
    throw new Error('История изменений временно недоступна. Обновите страницу.');
  }
  btn.disabled = true;
  try {
    const result = await api('/api/employer/vacancies/' + jobId + '/updates');
    // The user may have navigated to another tab while the request was pending.
    if (!history.isConnected) return;
    const updates = result.updates || [];
    history.innerHTML = `<div class="employer-vacancy-history-heading">
        <div><span class="section-kicker">СОХРАНЁННАЯ ИСТОРИЯ</span>
          <h5>Изменения условий</h5>
          <p class="muted">Всего изменений: ${Number(result.total_count||0)}.
            Историю можно просмотреть полностью, по 20 записей.
            Уведомления сохраняются в кабинетах соискателей, которым они предназначены.</p></div>
        </div>
        ${updates.length ? `<div class="employer-vacancy-history-list">${employerVacancyHistoryEntries(updates,view)}</div>`
          : '<p class="muted">Условия этой вакансии ещё не изменялись после публикации.</p>'}
        <div class="employer-vacancy-history-pagination">${employerVacancyHistoryPager(result)}</div>`;
    history.hidden = false;
    btn.setAttribute('aria-expanded','true');
    history.scrollIntoView({block:'nearest'});
  } finally {
    if (btn.isConnected) btn.disabled = false;
  }
}
async function loadMoreEmployerVacancyHistory(btn,jobId) {
  const history = btn.closest('.employer-vacancy-history');
  const list = history?.querySelector('.employer-vacancy-history-list');
  const pager = history?.querySelector('.employer-vacancy-history-pagination');
  const cursor = Number(btn.dataset.beforeId);
  if (!list || !pager || !Number.isSafeInteger(jobId) || jobId <= 0 ||
      !Number.isSafeInteger(cursor) || cursor <= 0) return;
  const view = window.StazhnoVacancyChanges;
  if (!view || typeof view.markup !== 'function') return;
  btn.disabled = true;
  try {
    const result = await api('/api/employer/vacancies/' + jobId +
      '/updates?before_id=' + cursor);
    if (!history.isConnected || history.hidden || !pager.contains(btn)) return;
    const existing = new Set(Array.from(list.querySelectorAll('[data-history-update-id]'))
      .map(item=>item.dataset.historyUpdateId));
    const newUpdates = (result.updates||[]).filter(item=>!existing.has(String(item.id)));
    list.insertAdjacentHTML('beforeend',employerVacancyHistoryEntries(newUpdates,view));
    pager.innerHTML = employerVacancyHistoryPager(result);
  } finally {
    if (btn.isConnected) btn.disabled = false;
  }
}
async function loadMatches(jobId) {
  jobId = positiveRecordId(jobId);
  const target = $('#employer-matches');
  const ownerId = positiveRecordId(state.user?.id);
  syncEmployerMatchAccount();
  if (!target || !jobId || !ownerId || state.user?.role !== 'employer' || state.tab !== 'vacancies') return;
  const vacancy = employerOwnedVacancies.get(jobId);
  if (!vacancy) return;
  const comparison = employerCandidateComparison;
  if (comparison.ownerId !== ownerId || comparison.vacancyId !== jobId) resetEmployerCandidateComparison();
  comparison.ownerId = ownerId;
  comparison.vacancyId = jobId;
  comparison.vacancy = vacancy;
  const requestSequence = ++employerMatchRequestSequence;
  const accountVersion = employerMatchAccountVersion;
  const card = document.querySelector(`#employer-vacancy-results .employer-vacancy-card[data-employer-vacancy-id="${jobId}"]`);
  if (card) card.after(target);
  target.setAttribute('role','region');
  target.setAttribute('aria-label','Подходящие кандидаты по вакансии');
  target.tabIndex = -1;
  target.classList.remove('hidden');
  target.innerHTML = '<div class="panel"><div class="loading">Подбираем кандидатов...</div></div>';
  state.activeVacancy = jobId;
  const isCurrent = () => state.user?.role === 'employer' && state.user?.id === ownerId &&
    employerMatchAccountVersion === accountVersion && requestSequence === employerMatchRequestSequence &&
    state.tab === 'vacancies' && state.activeVacancy === jobId && target.isConnected;
  try {
    const result = await api(`/api/employer/vacancies/${jobId}/matches`);
    if (!isCurrent()) return;
    const seen = new Set();
    const matches = (Array.isArray(result.matches) ? result.matches : []).map(employerMatchSnapshot)
      .filter(item => item.candidate_id && !seen.has(item.candidate_id) && seen.add(item.candidate_id));
    for (const item of matches) {
      const key = employerMatchInvitationKey(ownerId,jobId,item.candidate_id);
      const receipt = savedEmployerMatchInvitations.get(key);
      if (!item.invitation_id && receipt) Object.assign(item,receipt);
      else if (item.invitation_id) savedEmployerMatchInvitations.delete(key);
    }
    comparison.matches = matches;
    comparison.selected = new Set([...comparison.selected].filter(id=>matches.some(item=>item.candidate_id===id)).slice(0,3));
    if (comparison.selected.size < 2) comparison.visible = false;
    target.innerHTML = `<div class="panel matches-panel"><div class="split-header"><div><span class="section-kicker">ПОДБОР ПО ВАКАНСИИ</span><h3>Подходящие кандидаты</h3><p class="employer-match-vacancy-title">${esc(vacancy.title)}</p><p class="muted">Сравните профессию, навыки и условия. Контакты остаются скрытыми до отдельного согласия кандидата.</p></div><div class="employer-matches-head-actions"><span class="mini-badge">${matches.length} совпадений</span><button type="button" class="btn btn-outline btn-tiny" data-action="close-employer-matches">К списку вакансий</button></div></div>
      <div class="matches-guide"><span><b>1</b>Сравните анкеты</span><span><b>2</b>Отправьте приглашение</span><span><b>3</b>Дождитесь согласия</span></div>
      <p class="muted" role="note">После приглашения кандидат сам решает, соглашаться ли на знакомство. До его согласия контактные данные не открываются. Отправленные приглашения и ответы доступны в разделе «Знакомства и контакты».</p>
      ${matches.length ? `<div class="candidate-compare-toolbar"><div><strong>Сравнение по выбранной вакансии</strong><p id="employer-compare-status" role="status" aria-live="polite"></p></div><div class="candidate-compare-toolbar-actions"><button type="button" class="btn btn-primary" data-action="compare-show" disabled>Сравнить</button><button type="button" class="btn btn-outline" data-action="compare-back" hidden>Вернуться к анкетам</button><button type="button" class="btn btn-outline" data-action="compare-clear" disabled>Сбросить выбор</button></div></div>` : ''}
      <section id="employer-candidate-comparison" role="region" aria-label="Сравнение выбранных кандидатов" tabindex="-1" hidden></section>
      <div class="dashboard-list" data-employer-match-list>${matches.length ? matches.map(item => {
        const score = item.score;
        const scoreClass = score >= 90 ? 'excellent' : score >= 80 ? 'high' : score >= 70 ? 'medium' : 'basic';
        const reasons = item.strengths.length ? item.strengths : item.reasons;
        const level = item.match_level || (score>=90?'Очень сильное совпадение':score>=80?'Сильное совпадение':score>=70?'Хорошее совпадение':'Подходит по основным условиям');
        return `<article class="item-card candidate-match-card ${scoreClass}" data-match-candidate-id="${item.candidate_id}" tabindex="-1">
          <header><div><span class="candidate-match-label">Анкета №${item.candidate_id}</span><h4>${esc(item.profession)}</h4><div class="candidate-match-meta"><span>⌖ ${esc(item.city)}</span><span>${esc(candidateSalaryText(item.salary_min))}</span><span>${esc(item.schedule)}</span><span>${esc(item.employment)}</span></div></div><div class="candidate-match-score"><span class="match-score-dot"></span><strong>${score}%</strong><small>${esc(level)}</small></div></header>
          <div class="job-skill-tags">${item.skills.split(',').map(skill=>skill.trim()).filter(Boolean).slice(0,5).map(skill=>`<span>${esc(skill)}</span>`).join('') || '<span>Навыки не указаны</span>'}</div>
          <div class="candidate-match-reasons">${reasons.slice(0,3).map(reason=>`<span>✓ ${esc(reason)}</span>`).join('')}</div>
          <details class="candidate-resume-details"><summary>Профессиональное резюме</summary>${employerMatchResumeMarkup(item)}</details>
          ${item.cautions.length ? `<div class="candidate-match-cautions">${item.cautions.slice(0,2).map(text=>`<span>! ${esc(text)}</span>`).join('')}</div>` : ''}
          <details class="candidate-match-explanation"><summary>Показать расчёт совпадения</summary>${employerMatchBreakdownMarkup(item)}</details>
          <div class="item-actions"><button type="button" class="btn btn-outline btn-tiny" data-action="compare-toggle-candidate" data-id="${item.candidate_id}" aria-pressed="false" aria-describedby="employer-compare-status">Добавить в сравнение</button>${employerMatchInvitationSlot(item,jobId)}</div>
        </article>`;
      }).join('') : '<div class="empty-state"><strong>Точных совпадений пока нет.</strong><p>Попробуйте расширить график, город или зарплатный диапазон вакансии.</p></div>'}</div></div>`;
    updateEmployerCandidateComparison();
    target.focus({preventScroll:true});
    target.scrollIntoView({behavior:'smooth',block:'start'});
  } catch(error) {
    if (!isCurrent()) return;
    comparison.matches = [];
    comparison.selected.clear();
    comparison.visible = false;
    target.innerHTML = `<div class="panel"><p>${esc(error.message)}</p><button type="button" class="btn btn-outline" data-action="close-employer-matches">К списку вакансий</button></div>`;
    target.focus({preventScroll:true});
    toast(error.message,true);
  }
}
const employerInvitationFilterLabels = {
  all:'Все',
  needs_action:'Требуют действия',
  action:'Есть согласие',
  waiting:'Ждём решения',
  introduced:'Ждут итога',
  closed:'Завершённые'
};
function employerInvitationBucket(x) {
  if (['hired','rejected'].includes(x.application_status) || ['hired','rejected'].includes(x.direct_outcome)) return 'closed';
  if (x.contact_shared || x.contact) return 'introduced';
  if (x.status === 'accepted') return 'action';
  if (x.status === 'sent') return 'waiting';
  return 'closed';
}
function employerInvitationNeedsOutcome(x) {
  // A withdrawn application can precede a new direct invitation. Its consent
  // remains actionable, while outcome reminders follow the server exclusion.
  return employerInvitationBucket(x) === 'introduced' && x.application_status !== 'withdrawn';
}
function employerInvitationNeedsAction(x) {
  return employerInvitationBucket(x) === 'action' ||
    (Boolean(x.contact) && employerInvitationNeedsOutcome(x));
}
function employerInvitationStageLabel(x) {
  const bucket = employerInvitationBucket(x);
  const outcome = invitationFinalOutcome(x);
  if (bucket === 'introduced') return 'Знакомство состоялось';
  if (outcome === 'hired') return 'Положительный итог';
  if (outcome === 'rejected') return 'Не договорились';
  if (bucket === 'action') return 'Есть согласие';
  if (bucket === 'waiting') return 'Ждём решения кандидата';
  if (x.status === 'declined') return 'Кандидат отказался';
  return workflowStatus(x,statusTitle[x.status] || x.status);
}
function invitationLastActivity(x) {
  const timeline = Array.isArray(x.timeline) ? x.timeline : [];
  const last = timeline.length ? timeline[timeline.length - 1]?.created_at : x.created_at;
  const timestamp = Date.parse(String(last || '').replace(' ', 'T') + (String(last || '').includes('Z') ? '' : 'Z'));
  return Number.isFinite(timestamp) ? timestamp : Number(x.id || 0);
}
function invitationLastActivityMarkup(x) {
  const timeline = Array.isArray(x.timeline) ? x.timeline : [];
  const last = timeline.length ? timeline[timeline.length - 1] : null;
  if (!last) return '';
  const label = activityLabels[last.event] || last.event || 'Обновление';
  return `<div class="invitation-last-activity"><span>Последнее действие</span><strong>${esc(label)}</strong><small>${esc(formatActivityTimestamp(last.created_at))}</small></div>`;
}
const employerInvitationPageSize = 20;
let employerInvitationVisibleLimit = employerInvitationPageSize;
const pendingEmployerIntroductionActions = new Set();
// A successful mutation is final even when the following read-only refresh
// fails. Replace its action buttons with a receipt before attempting GET,
// so users never retry an already-confirmed operation by mistake.
function employerIntroductionSavedReceipt(button, outcome) {
  const destination = button.closest('.introduction-outcome-actions') || button;
  const receipt = document.createElement('div');
  receipt.className = 'interaction-note is-complete employer-introduction-saved-receipt';
  receipt.setAttribute('role', 'status');
  const label = outcome === 'opened' ? 'Контакт открыт (демо)'
    : outcome === 'hired' ? 'Положительный итог сохранён'
    : 'Итог «Не договорились» сохранён';
  const detail = outcome === 'opened'
    ? 'Знакомство подтверждено сервером. Обновите список, чтобы посмотреть контакт.'
    : 'Итог подтверждён сервером. Повторно отправлять решение не нужно.';
  receipt.innerHTML = '<strong>' + label + '</strong><span>' + detail +
    '</span><button type="button" class="btn btn-outline btn-tiny" ' +
    'data-action="refresh-employer-introductions">Обновить список</button>';
  destination.replaceWith(receipt);
}
async function loadEmployerInvitations(force=false) {
  if (force || !Array.isArray(state.employerInvitationsData)) {
    const result = await api('/api/employer/invitations');
    state.employerInvitationsData = result.invitations || [];
  }
  const invitations = state.employerInvitationsData;
  const selected = Object.hasOwn(employerInvitationFilterLabels,state.employerInvitationsFilter)
    ? state.employerInvitationsFilter
    : 'all';
  state.employerInvitationsFilter = selected;
  const vacancyOptions = [...new Map(invitations.map(item => [String(item.vacancy_id), item.vacancy_title])).entries()];
  const selectedVacancy = state.employerInvitationsVacancyFilter === 'all' ||
    vacancyOptions.some(([id]) => id === String(state.employerInvitationsVacancyFilter))
      ? String(state.employerInvitationsVacancyFilter || 'all')
      : 'all';
  state.employerInvitationsVacancyFilter = selectedVacancy;
  const vacancyScoped = selectedVacancy === 'all'
    ? invitations
    : invitations.filter(item => String(item.vacancy_id) === selectedVacancy);
  const query = String(state.employerInvitationsQuery || '').trim().toLocaleLowerCase('ru-RU');
  const searchScoped = query
    ? vacancyScoped.filter(item => {
        const visibleCandidateName = item.contact?.name || '';
        const haystack = [item.candidate_profession, item.vacancy_title, visibleCandidateName]
          .map(value => String(value || '').toLocaleLowerCase('ru-RU'))
          .join(' ');
        return haystack.includes(query);
      })
    : vacancyScoped;
  const counts = {action:0,waiting:0,introduced:0,closed:0};
  searchScoped.forEach(item => { counts[employerInvitationBucket(item)] += 1; });
  const attentionCount = searchScoped.filter(employerInvitationNeedsAction).length;
  const completedResults = {
    hired: searchScoped.filter(item => invitationFinalOutcome(item) === 'hired').length,
    rejected: searchScoped.filter(item => invitationFinalOutcome(item) === 'rejected').length,
    other: searchScoped.filter(item => employerInvitationBucket(item) === 'closed' &&
      !invitationFinalOutcome(item)).length
  };
  const ordered = [...searchScoped].sort((a,b) => {
    const priority = {introduced:0,action:1,waiting:2,closed:3};
    const bucketDiff = priority[employerInvitationBucket(a)] - priority[employerInvitationBucket(b)];
    if (bucketDiff) return bucketDiff;
    return invitationLastActivity(b) - invitationLastActivity(a);
  });
  const shown = selected === 'all' ? ordered
    : selected === 'needs_action' ? ordered.filter(employerInvitationNeedsAction)
    : ordered.filter(item => employerInvitationBucket(item) === selected);
  // A link from a particular application must open that exact introduction.
  // Put it first within the selected stage without exposing any new data.
  const targetInvitationId = Number(state.employerInvitationsTargetId || 0);
  const targetIndex = targetInvitationId > 0
    ? shown.findIndex(item => Number(item.id) === targetInvitationId) : -1;
  if (targetIndex > 0) shown.unshift(shown.splice(targetIndex, 1)[0]);
  const visible = shown.slice(0, employerInvitationVisibleLimit);
  const filterButtons = [
    ['all',searchScoped.length],
    ['needs_action',attentionCount],
    ['action',counts.action],
    ['waiting',counts.waiting],
    ['introduced',counts.introduced],
    ['closed',counts.closed]
  ].map(([value,count]) => `<button type="button" class="btn btn-tiny ${selected===value?'btn-dark':'btn-outline'}" data-action="filter-employer-invitations" data-filter="${value}" aria-pressed="${selected===value}">${esc(employerInvitationFilterLabels[value])} · ${Number(count)}</button>`).join('');
  const vacancySelector = `<div class="employer-introduction-controls"><label class="employer-introduction-vacancy-filter"><span>Вакансия</span><select data-employer-introduction-vacancy-filter><option value="all">Все вакансии</option>${vacancyOptions.map(([id,title]) => `<option value="${esc(id)}" ${selectedVacancy===id?'selected':''}>${esc(title)}</option>`).join('')}</select></label><label class="employer-introduction-search"><span>Поиск</span><input type="search" value="${esc(state.employerInvitationsQuery)}" placeholder="Кандидат или вакансия" data-employer-introduction-search autocomplete="off"></label></div>`;
  const empty = invitations.length
    ? (query
      ? '<div class="empty-state empty-state-action"><span class="empty-state-icon" aria-hidden="true">⌕</span><strong>По этому запросу знакомств нет</strong><p>Измените поиск или используйте «Сбросить фильтры» выше.</p></div>'
      : '<div class="empty-state empty-state-action"><span class="empty-state-icon" aria-hidden="true">⌕</span><strong>В этом этапе знакомств нет</strong><p>Выберите другой этап или покажите все знакомства.</p><button class="btn btn-outline" data-action="filter-employer-invitations" data-filter="all">Показать все</button></div>')
    : '<div class="empty-state"><strong>Знакомств пока нет.</strong><p>Откройте вакансию, запустите подбор и пригласите подходящего кандидата.</p><button class="btn btn-primary" data-tab="vacancies">К вакансиям →</button></div>';
  $('#dashboard-main').innerHTML = `<div class="panel invitation-center">
    <div class="split-header"><div><span class="section-kicker">ЗНАКОМСТВА</span><h3>Знакомства и контакты</h3><p class="muted">Здесь продолжается работа после отклика: сначала показываем знакомства, где нужен ваш следующий шаг. Контакты открываются только после согласия кандидата.</p></div>${vacancySelector}</div>
    <div class="employer-invitation-stage-filter" role="group" aria-label="Фильтр знакомств по этапу">${filterButtons}</div>
    <p class="muted">«Требуют действия»: кандидат согласился и можно открыть контакт либо после знакомства осталось зафиксировать итог. Ожидающие решения кандидата сюда не входят.</p>
    <div class="employer-invitation-result-line"><span role="status" aria-live="polite">Показываем <strong>${visible.length}</strong> из <strong>${shown.length}</strong> по выбранному этапу (всего по поиску: ${searchScoped.length})${selected==='all'&&searchScoped.length>1?' · сначала знакомства, где нужно ваше действие':''}</span>${selected!=='all'||selectedVacancy!=='all'||query?'<button type="button" class="link-button" data-action="reset-employer-invitation-filters">Сбросить фильтры</button>':''}</div>
    ${counts.closed ? `<div class="completed-introduction-summary" aria-label="Итоги завершённых знакомств"><span><strong>${completedResults.hired}</strong> Выбраны</span><span><strong>${completedResults.rejected}</strong> Не договорились</span>${completedResults.other ? `<span><strong>${completedResults.other}</strong> Другие завершённые</span>` : ''}</div>` : ''}
    ${counts.action ? '<div class="demo-note"><strong>Тестовый режим</strong><span>Открытие контакта имитирует оплату и не списывает деньги.</span></div>' : ''}
    <div class="dashboard-list" id="employer-invitation-results">${visible.length ? visible.map(invitationEmployerMarkup).join('') : empty}</div>
    ${visible.length < shown.length ? `<div class="employer-invitation-pagination"><button type="button" class="btn btn-outline" data-action="more-employer-invitations">Показать следующие ${Math.min(employerInvitationPageSize, shown.length - visible.length)} знакомств</button></div>` : ''}
  </div>`;
  if (targetIndex >= 0) {
    const target = document.querySelector('#employer-invitation-results .employer-invitation-card[data-invitation-id="' + targetInvitationId + '"]');
    if (target) {
      target.tabIndex = -1;
      target.focus({preventScroll:true});
      target.scrollIntoView({block:'nearest'});
    }
  }
  state.employerInvitationsTargetId = null;
}
function invitationEmployerMarkup(x) {
  const bucket = employerInvitationBucket(x);
  const outcome = invitationFinalOutcome(x);
  let next = '';
  if (bucket === 'introduced' && x.contact) {
    const email = String(x.contact.email || '').trim();
    const phone = String(x.contact.phone || '').trim();
    const phoneHref = phone.replace(/[^+\d]/g,'');
    const contactActions = [
      email ? `<a class="btn btn-primary btn-tiny" href="mailto:${encodeURIComponent(email)}">Написать кандидату →</a>` : '',
      phoneHref ? `<a class="btn btn-outline btn-tiny" href="tel:${esc(phoneHref)}">Позвонить</a>` : ''
    ].filter(Boolean).join('');
    next = `<div class="contact-card">
      <span>КОНТАКТ ОТКРЫТ · ДЕМО</span>
      <strong>${esc(x.contact.name)}</strong>
      <div class="contact-card-details">${email ? `<a href="mailto:${encodeURIComponent(email)}">${esc(email)}</a>` : '<span>Email не указан</span>'}<b>·</b><span>${esc(phone || 'Телефон не указан')}</span></div>
      <div class="contact-card-next"><strong>Следующий шаг — свяжитесь с кандидатом</strong><span>Согласие уже получено. После разговора зафиксируйте итог знакомства. Положительный итог на СТАЖНО не означает оформленного трудоустройства.</span></div>
      ${contactActions ? `<div class="contact-card-actions">${contactActions}</div>` : ''}
      ${x.application_id ? `<div class="contact-card-actions introduction-outcome-actions"><button class="btn btn-primary btn-tiny" data-action="introduction-outcome" data-id="${Number(x.application_id)}" data-status="hired">Положительный итог</button><button class="btn btn-outline btn-tiny" data-action="introduction-outcome" data-id="${Number(x.application_id)}" data-status="rejected">Не договорились</button></div>` : `<div class="contact-card-actions introduction-outcome-actions"><button type="button" class="btn btn-primary btn-tiny" data-action="direct-introduction-outcome" data-id="${Number(x.id)}" data-status="hired">Положительный итог</button><button type="button" class="btn btn-outline btn-tiny" data-action="direct-introduction-outcome" data-id="${Number(x.id)}" data-status="rejected">Не договорились</button></div>`}
    </div>`;
  } else if (bucket === 'closed' && x.contact && outcome) {
    const email = String(x.contact.email || '').trim();
    const phone = String(x.contact.phone || '').trim();
    const phoneHref = phone.replace(/[^+\d]/g,'');
    const contactActions = [
      email ? `<a class="btn btn-primary btn-tiny" href="mailto:${encodeURIComponent(email)}">Написать кандидату →</a>` : '',
      phoneHref ? `<a class="btn btn-outline btn-tiny" href="tel:${esc(phoneHref)}">Позвонить</a>` : ''
    ].filter(Boolean).join('');
    const outcomeNote = outcome === 'hired'
      ? '<div class="interaction-note is-complete"><strong>Положительный итог</strong><span>Работодатель отметил интерес к продолжению общения. Это не подтверждение трудоустройства.</span></div>'
      : '<div class="interaction-note is-closed"><strong>Не договорились</strong><span>Знакомство завершено без продолжения.</span></div>';
    next = `${outcomeNote}<div class="contact-card contact-card-completed">
      <span>КОНТАКТ СОХРАНЁН · ДЕМО</span>
      <strong>${esc(x.contact.name)}</strong>
      <div class="contact-card-details">${email ? `<a href="mailto:${encodeURIComponent(email)}">${esc(email)}</a>` : '<span>Email не указан</span>'}<b>·</b><span>${esc(phone || 'Телефон не указан')}</span></div>
      <div class="contact-card-next"><strong>Контакт остаётся доступен в истории</strong><span>Финальный результат уже зафиксирован, менять его повторно не нужно.</span></div>
      ${contactActions ? `<div class="contact-card-actions">${contactActions}</div>` : ''}
    </div>`;
  } else if (bucket === 'action') {
    next = `<div class="application-next-action"><span>Следующее действие</span><strong>Открыть контакт кандидата</strong><small>Согласие уже получено · демо-стоимость: ${money(x.price_rub)}</small></div><button class="btn btn-primary" data-action="demo-pay" data-id="${x.id}">Открыть контакт (демо) →</button>`;
  } else if (bucket === 'waiting') {
    next = '<div class="interaction-note is-waiting"><strong>Ждём решения кандидата</strong><span>Запрос уже отправлен. Повторных действий от работодателя сейчас не требуется.</span></div>';
  } else if (outcome === 'hired') {
    next = '<div class="interaction-note is-complete"><strong>Положительный итог</strong><span>Работодатель отметил интерес к продолжению общения. Это не подтверждение трудоустройства.</span></div>';
  } else if (outcome === 'rejected') {
    next = '<div class="interaction-note is-closed"><strong>Не договорились</strong><span>Знакомство завершено без продолжения.</span></div>';
  } else if (x.status === 'declined') {
    next = '<div class="interaction-note is-closed"><strong>Кандидат отказался от знакомства</strong><span>Знакомство завершено. Повторных действий по этому приглашению нет.</span></div>';
  } else {
    next = '<div class="interaction-note is-closed"><strong>Знакомство завершено</strong><span>Дополнительных действий не требуется.</span></div>';
  }
  return `<article class="item-card invitation-card employer-invitation-card is-${bucket}" data-invitation-id="${Number(x.id)}" data-application-id="${x.application_id ? Number(x.application_id) : ''}"><header><div><span class="card-eyebrow">ЗНАКОМСТВО</span><h4>${esc(x.candidate_profession)}</h4><p class="invitation-vacancy-context">Вакансия: <strong>${esc(x.vacancy_title)}</strong></p></div><span class="mini-badge ${bucket==='closed'?'gray':''}">${esc(employerInvitationStageLabel(x))}</span></header>
  ${interactionStageMarkup(x,'invitation')}
  ${invitationLastActivityMarkup(x)}
  ${activityTimelineMarkup(x)}
  ${next}</article>`;
}
function adminPasskeyMarkup(item) {
  const used = item.last_used_at ? `Последнее использование: ${esc(item.last_used_at)}` : `Добавлен: ${esc(item.created_at || '')}`;
  return `<div class="admin-passkey-row">
    <div class="admin-passkey-icon" aria-hidden="true">⌘</div>
    <div><strong>${esc(item.label || 'Passkey администратора')}</strong><small>${used}</small><small>${item.backed_up ? 'Синхронизируемый passkey' : 'Ключ устройства / аппаратный ключ'}</small></div>
    <button type="button" class="btn btn-outline btn-small" data-action="delete-admin-passkey" data-passkey-id="${esc(item.id)}">Удалить</button>
  </div>`;
}
function adminSecurityCheckMarkup(item) {
  const status = ['ok','warning','danger','info'].includes(item.status) ? item.status : 'info';
  const icon = status === 'ok' ? '✓' : status === 'danger' ? '!' : status === 'warning' ? '!' : 'i';
  return `<div class="admin-security-check ${status}">
    <span class="admin-security-check-icon" aria-hidden="true">${icon}</span>
    <div><strong>${esc(item.label || '')}</strong><small>${esc(item.text || '')}</small></div>
  </div>`;
}
function adminSecurityEventStat(label, value) {
  return `<div class="admin-security-event-stat"><strong>${Number(value || 0).toLocaleString('ru-RU')}</strong><span>${esc(label)}</span></div>`;
}
function adminPrivacyRightsMarkup(requests, available) {
  if (!available) return '<p class="muted">Очередь обращений временно недоступна.</p>';
  const rows = Array.isArray(requests) ? requests.slice(0,50) : [];
  if (!rows.length) return '<p class="muted">Обращений пока нет.</p>';
  return rows.map(item => {
    const key = esc(item.request_key || '');
    const status = String(item.status || '');
    const header = '<div class="privacy-rights-record privacy-rights-admin"><div>' +
      '<strong>' + esc(rightsKindLabels[item.kind] || 'Обращение') + '</strong>' +
      '<small>№ ' + key.slice(0,8) + ' · ' + rightsDate(item.submitted_at) +
      ' · ' + esc(item.email || '') + '</small>' +
      '<span class="status">' + esc(rightsStatusLabels[status] || status) + '</span></div>';
    if (status === 'received') {
      return header + '<button type="button" class="btn btn-outline btn-small" ' +
        'data-action="privacy-rights-review" data-rights-key="' + key +
        '">Взять в работу</button></div>';
    }
    if (status === 'in_review') {
      const disposal = item.kind === 'deletion' || item.kind === 'stop_processing';
      const preflight = disposal ?
        '<button type="button" class="btn btn-outline btn-small" ' +
        'data-action="privacy-disposal-preview" data-rights-key="' + key +
        '">Оценить последствия</button>' +
        '<div class="privacy-disposal-preview" id="privacy-disposal-panel-' + key + '"></div>' : '';
      return header + '<div class="privacy-rights-admin-actions">' + preflight +
        '<label>Результат ручной обработки<select data-rights-closure-reason="' + key + '">' +
        '<option value="fulfilled">Запрос выполнен</option>' +
        '<option value="retention_required">Ограничение по закону</option>' +
        '<option value="identity_unverified">Требуется подтверждение личности</option>' +
        '<option value="other">Иное обоснованное решение</option>' +
        '</select></label>' +
        '<button type="button" class="btn btn-outline btn-small" ' +
        'data-action="privacy-rights-close" data-rights-key="' + key +
        '">Закрыть после ответа пользователю</button></div></div>';
    }
    return header + '</div>';
  }).join('');
}
const disposalCountLabels = Object.freeze({
  active_sessions:'Активные сеансы',auth_tokens:'Сервисные токены',saved_devices:'Устройства',
  legal_acceptances:'Подтверждения договоров',rights_requests:'Обращения',
  security_events:'События безопасности',service_emails:'Сервисные письма',
  delivery_links:'Связи почтовых заданий',
  professional_profile:'Профессиональный профиль',resume:'Резюме',
  qualifications:'Квалификации',applications:'Отклики',
  application_events:'История откликов',favorite_vacancies:'Избранное',
  invitations:'Приглашения',contacts_already_shared:'Ранее открытые контакты',
  vacancy_update_receipts:'Уведомления об изменении вакансий',
  reports_submitted:'Поданные жалобы',company_profile:'Карточка компании',
  public_company_profile:'Открытый профиль компании',
  published_vacancies:'Вакансии',open_vacancies:'Активные вакансии',
  vacancy_drafts:'Черновики',candidate_applications_affected:'Отклики других кандидатов',
  vacancy_updates:'Изменения вакансий',reports_about_employer:'Жалобы на компанию'
});
function disposalPreviewMarkup(impact, review, external) {
  const counts = Object.entries(impact.counts || {});
  const checks = review?.checks || {};
  const labels = review?.labels || {};
  const entries = Object.entries(labels);
  const externalChecks = Array.isArray(external?.checks) ? external.checks : [];
  const externalRows = externalChecks.map(item => {
    const key = esc(item.system_key || '');
    const selected = String(item.status || 'not_reviewed');
    const options = [['not_reviewed','Не проверено'],['reviewed','Проверено вручную'],
      ['followup_required','Требуются действия'],['not_applicable','Не применяется']];
    return '<div class="privacy-external-row"><span>' + esc(item.label || key) +
      '</span><select data-external-system="' + key + '">' +
      options.map(([value,label]) => '<option value="' + value + '"' +
        (selected === value ? ' selected' : '') + (value === 'not_reviewed' ? ' disabled' : '') +
        '>' + label + '</option>').join('') + '</select>' +
      '<button type="button" class="btn btn-outline btn-small" ' +
      'data-action="privacy-external-save" data-rights-key="' + esc(impact.request_key || '') +
      '" data-system-key="' + key + '">Сохранить</button></div>';
  }).join('');
  return '<div class="privacy-disposal-report">' +
    '<h4>Предварительная оценка — только чтение</h4>' +
    '<p class="muted">Запрос на ' +
    (impact.kind === 'deletion' ? 'удаление' : 'прекращение обработки') +
    ': количество связанных записей, а не данные людей.</p>' +
    '<div class="privacy-disposal-counts">' +
    counts.filter(([,n]) => Number(n) > 0).map(([key,value]) =>
      '<div><span>' + esc(disposalCountLabels[key] || key) +
      '</span><strong>' + Number(value) + '</strong></div>'
    ).join('') + '</div>' +
    '<p class="muted">Неизменяемый отчёт: данные могли измениться после просмотра. Фактическое удаление и уведомление получателей не выполняются.</p>' +
    '<ul class="privacy-disposal-risks">' +
    (impact.risk_flags || []).map(r => '<li>' + esc(r) + '</li>').join('') +
    '</ul><h4>Внешние системы и резервные копии</h4>' +
    '<p class="muted">Каждый пункт отмечается только после реальной проверки у соответствующего провайдера. Система не имеет прямого доступа к Timeweb, SMTP или получателям; статусы являются заявлениями оператора.</p>' +
    '<div class="privacy-external-checks">' + externalRows + '</div>' +
    '<h4>Проверки оператора</h4>' +
    '<p class="muted">Отметки — ручные заверения администратора; система не проверяет их истинность. Последний пункт отмечают ТОЛЬКО после действительного исполнения вне этого интерфейса.</p>' +
    '<div class="privacy-disposal-checks">' +
    entries.map(([key,label]) =>
      '<label><input type="checkbox" data-disposal-check="' + esc(key) +
      '"' + (checks[key] ? ' checked' : '') +
      '> <span>' + esc(label) + '</span></label>'
    ).join('') + '</div>' +
    '<button type="button" class="btn btn-outline btn-small" data-action="privacy-disposal-save" ' +
      'data-rights-key="' + esc(impact.request_key || '') +
      '">Сохранить проверки</button>' +
    '<p class="muted">' + (review?.counts_changed_since_review ?
      'После подтверждения изменились связанные записи. Повторно проверьте последствия и сохраните чек-лист.' :
      review?.ready_for_manual_closure ?
      'Все этапы отмечены администратором. Перед закрытием проверьте фактический результат и ответ пользователю.' :
      (review?.external_checks_ready === false && entries.every(([key]) => checks[key]) ?
        'Проверки оператора отмечены, но внешние системы ещё не подтверждены. Завершение запрещено.' :
        'Закрытие со статусом «выполнено» запрещено до заполнения всех этапов.')) +
    '</p></div>';
}
async function renderAdmin() {
  $('#account-content').innerHTML = `<div class="admin-dashboard-stack">
    <section class="panel"><span class="section-kicker">РЕДАКЦИЯ</span><h3>Журнал и публикации</h3><p class="muted">Управляйте статьями: черновики, предпросмотр, публикация и отзыв материала. Все действия фиксируются.</p><a class="btn btn-primary" href="/admin/journal">Открыть редактор Журнала →</a></section>
    <section class="panel"><h3>Профессиональное сообщество</h3><p class="muted">Проверяйте новые профили перед публикацией и рассматривайте жалобы участников.</p><a class="btn btn-primary" href="/community/moderation">Модерация профилей и жалоб →</a></section><section class="panel"><h3>Панель управления</h3><p class="muted">Статистика работы MVP, без раскрытия персональных данных.</p><div class="stat-grid" id="admin-stats"><div class="loading">Загрузка...</div></div></section>
    <section class="panel">
      <span class="section-kicker">ПРИВЛЕЧЕНИЕ АУДИТОРИИ</span>
      <h3>Журнал, маршруты и регистрации — 30 дней</h3>
      <p class="muted">Агрегированные события без идентификаторов посетителей. Регистрации отображаются отдельно, без привязки к статьям.</p>
      <div class="stat-grid" id="admin-growth-stats"><div class="loading">Загрузка…</div></div>
      <div id="admin-growth-articles" class="admin-growth-overflow" tabindex="0" aria-label="Таблица событий, прокрутка по горизонтали" aria-live="polite"></div>
      <p class="muted">Загрузки — не уникальные посетители; переходы не равны регистрациям. Роботы, блокировщики и обновления страницы могут влиять на показатели.</p>
    </section>
    <section class="panel" id="admin-product-growth">
      <span class="section-kicker">ДЕЙСТВИЯ В ПРОДУКТЕ</span>
      <h3>Профили, отклики и знакомства</h3>
      <p class="muted">Независимые агрегаты из рабочих записей сервиса, без привязки к чтению статей. Тестовые и демо-записи также входят в показатели.</p>
      <h4>Текущее состояние профилей</h4>
      <div class="stat-grid" id="admin-product-current"><div class="loading">Загрузка…</div></div>
      <p class="muted">Заполненный профиль: указаны профессия, город, навыки, рассказ о себе и зарплата больше нуля; поиск включён, аккаунт доступен. Дата первого заполнения не фиксируется.</p>
      <h4>Действия за 30 дней, по UTC</h4>
      <div class="stat-grid" id="admin-product-period"><div class="loading">Загрузка…</div></div>
      <div id="admin-product-limitations" class="muted"></div>
    </section>
    <section class="panel admin-retention-policy">
      <span class="section-kicker">ЮРИДИЧЕСКАЯ ГОТОВНОСТЬ</span>
      <h3>Сроки хранения персональных данных</h3>
      <p class="muted">Реестр категорий данных требует согласования с юристом. Программа не назначает универсальный срок и не удаляет записи автоматически.</p>
      <div id="admin-retention-status" aria-live="polite"><p class="loading">Проверяем реестр…</p></div>
    </section>
    <section class="panel admin-privacy-rights">
      <span class="section-kicker">ПРАВА ПОЛЬЗОВАТЕЛЕЙ</span>
      <h3>Обращения по персональным данным</h3>
      <p class="muted">Здесь фиксируются запросы пользователей, а не их автоматическое исполнение. Оператор проверяет личность и основания, выполняет необходимые действия и отдельно отвечает заявителю. Закрытие заявки доступно только после подтверждения ручного ответа.</p>
      <div id="admin-privacy-rights" aria-live="polite"><p class="loading">Загрузка обращений…</p></div>
      <p class="muted">В очереди показываются первые 50 обращений. Если указан тестовый email, реальный ответ через него невозможен.</p>
    </section>
    <section class="panel admin-security-panel admin-security-ops">
      <div class="split-header"><div><span class="section-kicker">КОНТУР БЕЗОПАСНОСТИ</span><h3>Состояние защиты</h3><p class="muted">Сводка ключевых настроек и событий за последние 24 часа. Секреты и токены здесь никогда не отображаются.</p></div><span class="mini-badge" id="admin-security-summary">Проверяем…</span></div>
      <div id="admin-security-checks" class="admin-security-check-grid"><div class="loading">Проверяем настройки...</div></div>
      <div id="admin-security-events-24h" class="admin-security-event-stats"></div>
      <p class="muted admin-security-origin-note" id="admin-security-origin-note"></p>
    </section>
    <section class="panel admin-security-panel">
      <span class="section-kicker">БЕЗОПАСНОСТЬ АДМИНИСТРАТОРА</span>
      <h3>Passkeys / WebAuthn</h3>
      <p class="muted">Passkey подтверждает вход через Windows Hello, Touch ID, телефон или аппаратный FIDO2-ключ. TOTP остаётся резервным фактором.</p>
      <div id="admin-passkeys"><div class="loading">Загрузка...</div></div>
      <div class="admin-passkey-actions"><button type="button" class="btn btn-primary" data-action="register-admin-passkey">Добавить passkey →</button></div>
    </section>
    <section class="panel admin-security-panel">
      <span class="section-kicker">ПОЧТА И ВОССТАНОВЛЕНИЕ</span>
      <h3>Проверка служебных писем</h3>
      <p class="muted">Сначала проверяем TLS и авторизацию, затем отправляем два тестовых примера на <strong>email текущего администратора</strong>. Настоящие отклики, приглашения и письма другим пользователям не создаются.</p>
      <div id="admin-smtp-status" class="empty-state">SMTP ещё не проверялся.</div>
      <div class="admin-passkey-actions">
        <button type="button" class="btn btn-outline" data-action="check-smtp">1. Проверить SMTP →</button>
        <button type="button" class="btn btn-outline" data-action="send-smtp-test-email" data-smtp-scenario="employer_application">2. Тест письма работодателю →</button>
        <button type="button" class="btn btn-outline" data-action="send-smtp-test-email" data-smtp-scenario="candidate_invitation">3. Тест письма соискателю →</button>
      </div>
      <p id="admin-mail-test-result" class="muted" role="status" aria-live="polite">Тестовые письма принимаются SMTP-сервером; получение нужно подтвердить во «Входящих» или «Спаме» вашего почтового ящика.</p>
      <h4>Повторная отправка рабочих уведомлений</h4>
      <div id="admin-mail-queue-summary" class="admin-mail-diagnostics" role="status" aria-live="polite"><p class="muted">Проверяем очередь…</p></div>
      <p class="muted">Автоматические попытки: первоначальная и до трёх повторных. «Принято SMTP» не означает доставку во «Входящие». Исчерпанные попытки требуют проверки SMTP и отдельного решения администратора. Коды MFA и ссылки восстановления автоматически не повторяются. Уведомления старше 72 часов или для недоступного аккаунта не отправляются.</p>
      <h4>События уведомлений</h4>
      <div id="admin-mail-diagnostics" class="admin-mail-diagnostics"><p class="muted">Загружаем события…</p></div>
      <p class="muted">Количество событий — это записи о создании уведомлений, <strong>не доказательство доставки писем</strong>. Пароли, ссылки восстановления и адреса получателей здесь не выводятся.</p>
    </section>
  </div>`;
  try {
    const [stats, security, securityOverview, mailDiagnostics, growth, privacyRights, retention] = await Promise.all([
      api('/api/admin/stats'),
      api('/api/account/security'),
      api('/api/admin/security-overview'),
      api('/api/admin/mail-diagnostics').catch(() => null),
      api('/api/admin/growth?days=30').catch(() => null),
      api('/api/admin/privacy-requests?limit=50').catch(() => null),
      api('/api/admin/privacy-retention-readiness').catch(() => null)
    ]);
    const retentionTarget = $('#admin-retention-status');
    if (retentionTarget) {
      const total = Number(retention?.total || 0);
      const approved = Number(retention?.approved_count || 0);
      retentionTarget.innerHTML = !retention ? '<p class="muted">Реестр временно недоступен.</p>' :
        '<p><strong>' + approved + ' из ' + total + ' категорий согласовано</strong>' +
        (retention.approved ? '' : ' — выпуск заблокирован') + '</p>' +
        '<p class="muted">Автоматическое удаление: отключено. Категории без утверждения:</p>' +
        '<ul class="admin-retention-list">' +
        (retention.categories || []).filter(c => c.approval_status !== 'APPROVED')
          .map(c => '<li>' + esc(c.purpose || c.code) + '</li>').join('') +
        '</ul>';
    }
    const privacyRightsTarget = $('#admin-privacy-rights');
    if (privacyRightsTarget) privacyRightsTarget.innerHTML =
      adminPrivacyRightsMarkup(privacyRights?.requests, Boolean(privacyRights));
    const diagnosticLabels = {
      new_application: 'Новые отклики работодателю',
      invitation: 'Приглашения соискателю',
      invitation_response: 'Ответы на приглашения',
      contact_opened: 'Открытие контакта',
      application_status: 'Изменения статуса отклика',
      application_withdrawn: 'Отозванные отклики',
      introduction_outcome: 'Результаты прямых знакомств'
    };
    const queueContainer = $('#admin-mail-queue-summary');
    if (queueContainer) {
      const queue = mailDiagnostics?.retry_queue;
      const readiness = mailDiagnostics?.mail_readiness;
      const statusLabels = {
        smtp_not_configured: 'Почтовый сервер не настроен',
        worker_disabled: 'Обработчик очереди отключён',
        worker_unconfirmed: 'Нет подтверждения работы обработчика',
        delivery_exhausted: 'Есть письма с исчерпанными попытками',
        queue_overdue: 'Очередь не обработана в срок',
        retrying: 'Идут повторные попытки',
        processing: 'Есть ожидающие отправки письма',
        smtp_acceptance_observed: 'SMTP принимал письма',
        no_workflow_mail_yet: 'Рабочих отправок ещё не было'
      };
      const lastAccepted = readiness?.last_smtp_accept_at;
      const acceptedDate = lastAccepted ? new Date(lastAccepted) : null;
      const acceptedLabel = acceptedDate && Number.isFinite(acceptedDate.getTime())
        ? acceptedDate.toLocaleString('ru-RU') : 'пока нет';
      const oldestMinutes = Number.isFinite(readiness?.oldest_waiting_seconds)
        ? Math.floor(readiness.oldest_waiting_seconds / 60) + ' мин.' : 'нет';
      const overdueMinutes = Number.isFinite(readiness?.overdue_seconds) &&
        readiness.overdue_seconds > 120
        ? ' · Просрочка: ' + Math.floor(readiness.overdue_seconds / 60) + ' мин.' : '';
      const workerAgeLabel = Number.isFinite(readiness?.worker_last_seen_seconds)
        ? Math.floor(readiness.worker_last_seen_seconds / 60) + ' мин. назад'
        : 'нет отметки активности';
      const queueNote = readiness
        ? '<p class="muted"><strong>Состояние:</strong> ' +
          esc(statusLabels[readiness.status] || 'Не проверено') +
          ' · Обработчик: ' + (readiness.worker_recently_seen ? 'активность подтверждена'
            : readiness.worker_configured ? 'включён, но активность не подтверждена' : 'отключён') +
          ' (' + esc(workerAgeLabel) + ')' +
          ' · Ожидание: ' + esc(oldestMinutes) + esc(overdueMinutes) +
          ' · Последний приём SMTP: ' + esc(acceptedLabel) + '</p>' +
          '<p class="muted">Включённый обработчик и ответ SMTP не гарантируют ' +
          'доставку во «Входящие»; для проверки письма используйте свой адрес администратора.</p>'
        : '';
      const states = [
        ['В очереди', queue?.queued],
        ['Повторная попытка', queue?.retrying],
        ['Отправляются', queue?.sending],
        ['Принято SMTP', queue?.accepted],
        ['Исчерпали попытки SMTP', queue?.exhausted],
        ['Остановлены безопасностью', queue?.suppressed],
      ];
      queueContainer.innerHTML = queue
        ? queueNote + '<div class="admin-mail-event-grid">' + states.map(([label, count]) =>
            '<div><span>' + esc(label) + '</span><strong>' +
            Number(count || 0).toLocaleString('ru-RU') + '</strong></div>'
          ).join('') + '</div>'
        : '<p class="muted">Нет данных об очереди. Проверьте состояние приложения.</p>';
    }
    const diagnostics = $('#admin-mail-diagnostics');
    if (diagnostics) {
      diagnostics.innerHTML = mailDiagnostics
        ? '<div class="admin-mail-event-grid">' +
            (mailDiagnostics.events || []).map(item =>
              '<div><span>' + esc(diagnosticLabels[item.event] || 'Уведомление') +
              '</span><strong>' + Number(item.generated || 0).toLocaleString('ru-RU') +
              '</strong></div>'
            ).join('') + '</div>'
        : '<p class="muted">Не удалось загрузить статистику уведомлений. SMTP можно проверить отдельно.</p>';
    }
    const units = [['Соискатели',stats.candidates],['Работодатели',stats.employers],['Открытые вакансии',stats.open_vacancies],['Всего откликов',stats.applications_total],['Активные отклики',stats.applications_active],['Отозванные отклики',stats.applications_withdrawn],['Приглашения',stats.invitations],['Подтверждения',stats.confirmed],['Демо-знакомства',stats.demo_transactions],['Демо-оборот, ₽',stats.demo_turnover_rub]];
    $('#admin-stats').innerHTML = units.map(([title,value]) => `<div class="stat-tile"><strong>${Number(value).toLocaleString('ru-RU')}</strong><span>${esc(title)}</span></div>`).join('');

    const growthSummary = growth?.summary || null;
    const growthArea = $('#admin-growth-stats');
    const growthArticlesArea = $('#admin-growth-articles');
    if (growthArea && growthArticlesArea) {
      if (!growthSummary) {
        growthArea.innerHTML = '<p class="muted">Показатели временно недоступны.</p>';
        growthArticlesArea.innerHTML = '';
      } else {
        const growthUnits = [
          ['Загрузки журнала и маршрутов', growthSummary.journal_requests],
          ['Просмотры публичных вакансий', growthSummary.public_vacancy_views],
          ['Просмотры публичных компаний', growthSummary.public_company_views],
          ['Журнал → вакансии (общий показатель*)', growthSummary.jobs_clicks],
          ['Статья → карточка вакансии', growthSummary.journal_vacancy_clicks],
          ['Вакансия → статья', growthSummary.vacancy_article_clicks],
          ['Компания → статья', growthSummary.company_article_clicks],
          ['Вакансия → компания', growthSummary.company_clicks],
          ['Компания → вакансия', growthSummary.vacancy_clicks],
          ['Вход в сценарий отклика', growthSummary.apply_clicks],
          ['Переходы к профилю', growthSummary.profile_clicks],
          ['Переходы в сообщество', growthSummary.community_clicks],
          ['Новые кандидаты', growthSummary.new_candidates],
          ['Новые работодатели', growthSummary.new_employers]
        ];
        growthArea.innerHTML = growthUnits.map(([title, value]) =>
          '<div class="stat-tile"><strong>' + Number(value || 0).toLocaleString('ru-RU') +
          '</strong><span>' + esc(title) + '</span></div>'
        ).join('');
        const sources = Array.isArray(growth.by_source) ? growth.by_source : [];
        growthArticlesArea.innerHTML =
          '<table class="admin-growth-table"><caption>Анонимные агрегированные события публичной воронки за 30 дней, по UTC</caption>' +
          '<thead><tr><th scope="col">Источник</th><th scope="col">Загрузки</th>' +
          '<th scope="col">К вакансиям</th><th scope="col">К профилю</th><th scope="col">В сообщество</th>' +
          '<th scope="col">К компании</th><th scope="col">К вакансии компании</th><th scope="col">К отклику</th>' +
          '<th scope="col">К карточке из статьи</th><th scope="col">К статье</th>' +
          '<th scope="col">Клики / загрузки*</th></tr></thead><tbody>' +
          sources.map(item =>
            '<tr data-growth-source="' + esc(item.source) + '"><th scope="row">' +
            (item.kind === 'path' ? 'Маршрут: ' : '') + esc(item.title) +
            (item.published ? '' : ' (снят с публикации)') + '</th>' +
            ['view','jobs_click','profile_click','community_click','company_click','vacancy_click','apply_click','recommended_vacancy_click','article_click'].map(action =>
              '<td>' + Number(item[action] || 0).toLocaleString('ru-RU') + '</td>'
            ).join('') + '<td>' + (item.clicks_per_view_percent != null
              ? Number(item.clicks_per_view_percent).toLocaleString('ru-RU', {maximumFractionDigits: 1}) + '%'
              : '—') + '</td></tr>'
          ).join('') + '</tbody></table><p class="muted">* Соотношение событий, не конверсия уникальных людей. Может превышать 100%. Источник конкретной регистрации не определяется. До введения отдельного счётчика карточек переходы из статей к конкретным вакансиям входили в общий показатель. Последовательности действий отдельных посетителей не отслеживаются.</p>';
      }
    }

    const product = growth?.product;
    const productCurrent = $('#admin-product-current');
    const productPeriod = $('#admin-product-period');
    const productLimitations = $('#admin-product-limitations');
    if (productCurrent && productPeriod && productLimitations) {
      if (!product?.current || !product?.period) {
        productCurrent.innerHTML = '<p class="muted">Сводка временно недоступна.</p>';
        productPeriod.innerHTML = '';
      } else {
        const current = product.current;
        const period = product.period;
        const tiles = units => units.map(([title, value]) =>
          '<div class="stat-tile"><strong>' + Number(value || 0).toLocaleString('ru-RU') +
          '</strong><span>' + esc(title) + '</span></div>'
        ).join('');
        productCurrent.innerHTML = tiles([
          ['Доступные аккаунты кандидатов', current.enabled_candidate_accounts],
          ['Заполненные профили с включённым поиском', current.completed_active_candidate_profiles]
        ]);
        productPeriod.innerHTML = tiles([
          ['Созданные вакансии', period.vacancies_created],
          ['Новые отклики', period.new_applications],
          ['Принятые приглашения с согласием', period.consented_introductions],
          ['Демо-открытия контактов', period.demo_contacts_opened],
          ['Зафиксированные итоги знакомств', period.introductions_completed],
          ['Положительные итоги', period.positive_outcomes],
          ['Без договорённости', period.no_agreement_outcomes]
        ]);
        productLimitations.innerHTML = (product.limitations || [])
          .map(note => '<p>' + esc(note) + '</p>').join('');
      }
    }

    const checks = Array.isArray(securityOverview.checks) ? securityOverview.checks : [];
    const dangerCount = checks.filter(item => item.status === 'danger').length;
    const warningCount = checks.filter(item => item.status === 'warning').length;
    $('#admin-security-checks').innerHTML = checks.length
      ? checks.map(adminSecurityCheckMarkup).join('')
      : '<div class="empty-state">Не удалось получить состояние защиты.</div>';
    $('#admin-security-summary').textContent = dangerCount
      ? `Требует действий: ${dangerCount}`
      : warningCount
        ? `Есть рекомендации: ${warningCount}`
        : 'Критичных замечаний нет';
    const e24 = securityOverview.events_24h || {};
    $('#admin-security-events-24h').innerHTML = [
      adminSecurityEventStat('Неудачные входы',e24.failed_auth),
      adminSecurityEventStat('Новые устройства',e24.new_devices),
      adminSecurityEventStat('Изменения пароля',e24.password_changes),
      adminSecurityEventStat('Изменения passkey',e24.passkey_changes),
      adminSecurityEventStat('Активные сессии',securityOverview.active_sessions)
    ].join('');
    $('#admin-security-origin-note').textContent = securityOverview.temporary_origin
      ? 'Passkey на временном домене специально не считается обязательным. Зарегистрируем его после перехода на постоянный домен.'
      : '';

    const passkeys = Array.isArray(security.passkeys) ? security.passkeys : [];
    $('#admin-passkeys').innerHTML = passkeys.length
      ? `<div class="admin-passkey-list">${passkeys.map(adminPasskeyMarkup).join('')}</div>`
      : '<div class="empty-state">Passkey пока не зарегистрирован. До его добавления администратор продолжает входить по TOTP.</div>';
  } catch(e) { toast(e.message,true); }
}
function formValue(form, name) { return form.elements.namedItem(name).value.trim(); }
function parseNumber(form, name) { return Number(formValue(form,name)); }
async function handleDashboardSubmit(event) {
  const form = event.target;
  if (form.id === 'privacy-rights-request-form') {
    event.preventDefault();
    const kind = String(form.elements.namedItem('kind')?.value || '');
    const message = $('#privacy-rights-message');
    if (!Object.hasOwn(rightsKindLabels, kind)) {
      if (message) message.textContent = 'Выберите вид обращения.';
      return;
    }
    const submit = form.querySelector('button[type="submit"]');
    if (submit) submit.disabled = true;
    if (message) message.textContent = 'Сохраняем обращение…';
    try {
      await api('/api/account/privacy-requests', {
        method: 'POST', body: JSON.stringify({kind})
      });
      await renderAccountSecurity($('#dashboard-main'));
      toast('Обращение сохранено в кабинете. Оператор рассмотрит его отдельно.');
    } catch (error) {
      if (message) message.textContent = error.message || 'Не удалось сохранить обращение.';
      toast(error.message || 'Не удалось сохранить обращение.', true);
    } finally {
      if (submit?.isConnected) submit.disabled = false;
    }
    return;
  }
  if (form.id === 'security-password-form') {
    event.preventDefault();
    const message = $('#security-password-message');
    const currentPassword = formValue(form,'current_password');
    const newPassword = formValue(form,'new_password');
    const confirmPassword = formValue(form,'new_password_confirm');
    if (newPassword.length < 15) {
      if (message) message.textContent = 'Новый пароль должен содержать не менее 15 символов.';
      return;
    }
    if (newPassword !== confirmPassword) {
      if (message) message.textContent = 'Новые пароли не совпадают.';
      return;
    }
    const submit = form.querySelector('button[type="submit"]');
    submit.disabled = true;
    if (message) message.textContent = '';
    try {
      await api('/api/account/password/change',{
        method:'POST',
        body:JSON.stringify({current_password:currentPassword,new_password:newPassword})
      });
      form.reset();
      await reloadUser();
      await renderAccountSecurity($('#dashboard-main'));
      toast('Пароль изменён. Все старые сессии завершены.');
    } catch(e) {
      if (message) message.textContent = e.message;
      toast(e.message,true);
    } finally {
      if (submit.isConnected) submit.disabled = false;
    }
    return;
  }
  if (form.id === 'profile-form') {
    event.preventDefault();
    if (editorSubmitting.has(form) || !validateCandidateProfileRows(form)) return;
    const body = candidateProfileFormData(form);
    const savingUserId = state.user?.id;
    const submit = beginEditorSave(form);
    if (!submit) return;
    let persisted = false;
    try {
      const result = await api('/api/candidate/profile',{method:'PUT',body:JSON.stringify(body)});
      persisted = true;
      // The PUT returns the committed profile. A separate /api/me read can fail
      // after a successful write and must not leave the preview or PDF stale.
      if (state.user?.id === savingUserId) {
        state.user = {...state.user, profile:result.profile, phone:body.phone};
      }
      editorSaved(form);
      updateCandidateProfileSavedState(result.profile);
      updateCandidateProfilePreview(form);
      toast('Профиль сохранён.');
      resumePendingApplicationVacancy();
    } catch(e) {
      if (persisted) {
        setEditorStatus(form, 'Профиль сохранён. Не удалось обновить отображение — откройте раздел снова.', true);
        toast('Профиль сохранён. Откройте раздел снова, чтобы обновить отображение.', true);
      } else editorSaveFailure(form, e);
    }
    finally { endEditorSave(form, submit); }
    return;
  }
  if (form.id === 'company-form') {
    event.preventDefault();
    const submit = beginEditorSave(form);
    if (!submit) return;
    const body = {company_name:formValue(form,'company_name'),inn:formValue(form,'inn'),about:formValue(form,'about')};
    let persisted = false;
    try {
      await api('/api/employer/company',{method:'PUT',body:JSON.stringify(body)});
      persisted = true;
      editorSaved(form);
      await reloadUser();
      const result = await api('/api/employer/company');
      $('#dashboard-main').innerHTML = employerCompanyMarkup(result);
      prepareEditorForms();
      toast('Данные компании сохранены.');
    } catch(e) {
      if (persisted) toast('Данные сохранены, но не удалось обновить страницу. Обновите кабинет после восстановления связи.', true);
      else editorSaveFailure(form, e);
    } finally { endEditorSave(form, submit); }
    return;
  }
  if (form.id === 'vacancy-form') {
    event.preventDefault();
    if (draftConflictSessions.has(form)) {
      toast('Сначала выберите и сохраните варианты в блоке сравнения черновика.', true);
      form.querySelector('[data-draft-conflict-panel]')?.scrollIntoView({block:'nearest'});
      return;
    }
    if (publishedVacancyConflictSessions.has(form)) {
      toast('Сначала выберите и примените варианты в блоке сравнения вакансии.', true);
      form.querySelector('[data-published-conflict-panel]')?.scrollIntoView({block:'nearest'});
      return;
    }
    const description = window.OpytnovacancyWizard?.getReviewedDescription(form);
    if (description === null || description === undefined) {
      toast('Сначала проверьте вакансию в предпросмотре.', true);
      return;
    }
    if (draftAutoSaving.has(form)) {
      toast('Автосохранение ещё выполняется. Повторите публикацию после его завершения.', true);
      return;
    }
    cancelDraftAutosave(form);
    const submit = beginEditorSave(form);
    if (!submit) return;
    const editing = Boolean(form.dataset.editId);
    const body = {title:formValue(form,'title'),city:formValue(form,'city'),skills:formValue(form,'skills'),salary_min:parseNumber(form,'salary_min'),salary_max:parseNumber(form,'salary_max'),schedule:formValue(form,'schedule'),employment:formValue(form,'employment'),description};
    if (editing) body.expected_revision = form.dataset.revision;
    let persisted = false;
    let conflict = false;
    try {
      const draftId = !editing ? Number(form.dataset.draftId || 0) : 0;
      if (draftId) {
        const saved = await api(`/api/employer/vacancy-drafts/${draftId}`, {
          method:'PUT', body:JSON.stringify({fields:draftFields(form),expected_version:Number(form.dataset.draftVersion)})
        });
        form.dataset.draftVersion = saved.version;
        await api(`/api/employer/vacancy-drafts/${draftId}/publish`, {method:'POST'});
        state.activeDraft = null;
      } else {
        const endpoint = editing ? `/api/employer/vacancies/${form.dataset.editId}` : '/api/employer/vacancies';
        await api(endpoint,{method:editing ? 'PATCH' : 'POST',body:JSON.stringify(body)});
      }
      persisted = true;
      editorSaved(form);
      state.editVacancy = null;
      state.activeVacancy = null;
      state.tab = 'vacancies';
      await showDashboard();
      await loadPublicJobs();
      toast(editing ? 'Изменения сохранены в прежней вакансии, отклики остались на месте.' : 'Вакансия опубликована. Следующий шаг — подобрать кандидатов в её карточке.');
    } catch(e) {
      if (persisted) {
        toast('Вакансия сохранена, но не удалось обновить список. Проверьте раздел «Мои вакансии».', true);
      } else if (!editing && form.dataset.draftId && e?.httpStatus === 409) {
        conflict = true;
        try {
          await showDraftConflictResolution(form);
          toast('Перед публикацией необходимо согласовать изменения черновика.', true);
        } catch(readError) {
          editorSaveFailure(form, readError, true);
        }
      } else if (editing && e?.httpStatus === 409) {
        conflict = true;
        try {
          await showPublishedVacancyConflict(form);
          toast('Условия уже изменились на другом устройстве. Сравните версии перед сохранением.',true);
        } catch(readError) {
          editorSaveFailure(form,readError);
        }
      } else {
        editorSaveFailure(form, e, !editing);
      }
    } finally {
      endEditorSave(form, submit);
      if (conflict && submit?.isConnected) submit.disabled = true;
    }
    return;
  }
}
let employerInvitationSearchTimer = null;
let candidateInvitationSearchTimer = null;
function handleDashboardInput(event) {
  const workQueueSearch = event.target.closest('[data-employer-workqueue-search]');
  if (workQueueSearch && state.user?.role === 'employer' && state.tab === 'overview') {
    const queue = workQueueSearch.closest('#employer-workqueue');
    if (queue) {
      queue.dataset.visibleLimit = '10';
      applyEmployerWorkQueueFilters(queue);
      rememberEmployerWorkQueueView(queue);
    }
    return;
  }
  const vacancySearch = event.target.closest('[data-employer-vacancy-search]');
  if (vacancySearch && state.user?.role === 'employer' && state.tab === 'vacancies') {
    state.employerVacancySearch = vacancySearch.value;
    applyEmployerVacancySearch();
    return;
  }
  editorChanged(editorForControl(event.target));
  const employerSearch = event.target.closest('[data-employer-introduction-search]');
  if (employerSearch) {
    state.employerInvitationsQuery = String(employerSearch.value || '');
    employerInvitationVisibleLimit = employerInvitationPageSize;
    state.employerInvitationsTargetId = null;
    clearTimeout(employerInvitationSearchTimer);
    employerInvitationSearchTimer = setTimeout(async () => {
      if (state.user?.role !== 'employer' || state.tab !== 'invitations') return;
      try {
        await loadEmployerInvitations();
        const nextSearch = document.querySelector('#dashboard-main [data-employer-introduction-search]');
        if (nextSearch) {
          nextSearch.focus();
          const end = nextSearch.value.length;
          nextSearch.setSelectionRange?.(end,end);
        }
      } catch(e) { toast(e.message,true); }
    }, 180);
    return;
  }
  const candidateSearch = event.target.closest('[data-candidate-introduction-search]');
  if (!candidateSearch) return;
  state.candidateInvitationsQuery = String(candidateSearch.value || '');
  state.candidateInvitationPinnedId = null;
  state.candidateInvitationTargetId = null;
  candidateInvitationVisibleLimit = candidateInvitationPageSize;
  clearTimeout(candidateInvitationSearchTimer);
  candidateInvitationSearchTimer = setTimeout(async () => {
    if (state.user?.role !== 'candidate' || state.tab !== 'invitations') return;
    try {
      await loadCandidateInvitations();
      const nextSearch = document.querySelector('#dashboard-main [data-candidate-introduction-search]');
      if (nextSearch) {
        nextSearch.focus();
        const end = nextSearch.value.length;
        nextSearch.setSelectionRange?.(end,end);
      }
    } catch(e) { toast(e.message,true); }
  }, 180);
}
async function handleDashboardChange(event) {
  const workQueueVacancy = event.target.closest('[data-employer-workqueue-vacancy]');
  if (workQueueVacancy && state.user?.role === 'employer' && state.tab === 'overview') {
    const queue = workQueueVacancy.closest('#employer-workqueue');
    if (queue) {
      queue.dataset.visibleLimit = '10';
      applyEmployerWorkQueueFilters(queue);
      rememberEmployerWorkQueueView(queue);
    }
    return;
  }
  editorChanged(editorForControl(event.target));
  const introductionVacancy = event.target.closest('[data-employer-introduction-vacancy-filter]');
  if (introductionVacancy) {
    state.employerInvitationsVacancyFilter = String(introductionVacancy.value || 'all');
    employerInvitationVisibleLimit = employerInvitationPageSize;
    state.employerInvitationsTargetId = null;
    state.employerInvitationsFilter = 'all';
    await loadEmployerInvitations();
    return;
  }
  const select = event.target.closest('[data-dashboard-tab-select]');
  if (!select) return;
  const nextTab = String(select.value || '');
  if (!nextTab || nextTab === state.tab) return;
  if (!mayLeaveEditor()) {
    select.value = state.tab;
    return;
  }
  if (state.user?.role === 'employer' && nextTab === 'applications') {
    state.employerApplicationsVacancyFilter = 'all';
    state.employerApplicationsStatusFilter = 'all';
    state.employerApplicationsQuery = '';
  }
  if (state.user?.role === 'employer' && nextTab === 'invitations') {
    state.employerInvitationsFilter = 'all';
    state.employerInvitationsVacancyFilter = 'all';
    state.employerInvitationsQuery = '';
    state.employerInvitationsData = null;
  }
  if (state.user?.role === 'candidate' && nextTab === 'invitations') {
    candidateInvitationVisibleLimit = candidateInvitationPageSize;
    state.candidateInvitationTargetId = null;
    state.candidateInvitationPinnedId = null;
    state.candidateInvitationsFilter = 'all';
    state.candidateInvitationsQuery = '';
    state.candidateInvitationsData = null;
  }
  if (state.user?.role === 'employer' && nextTab === 'create') state.activeDraft = null;
  state.tab = nextTab;
  state.activeVacancy = null;
  await showDashboard();
  // The mobile menu is rebuilt on every tab change. Restore keyboard focus
  // to its replacement so keyboard and assistive-technology users do not lose context.
  if (window.matchMedia('(max-width: 700px)').matches) {
    const activeSelect = document.querySelector('#dashboard [data-dashboard-tab-select]');
    if (activeSelect && activeSelect.value === nextTab) activeSelect.focus({preventScroll:true});
  }
}
async function handleDashboardClick(event) {
  const tab = event.target.closest('[data-tab]');
  if (tab) {
    if (!mayLeaveEditor()) return;
    if (state.user?.role === 'employer' && tab.dataset.tab === 'applications') {
      state.employerApplicationsVacancyFilter = 'all';
      state.employerApplicationsStatusFilter = 'all';
      state.employerApplicationsQuery = '';
    }
    if (state.user?.role === 'employer' && tab.dataset.tab === 'invitations') {
      state.employerInvitationsFilter = 'all';
      state.employerInvitationsVacancyFilter = 'all';
      state.employerInvitationsQuery = '';
      state.employerInvitationsData = null;
    }
    if (state.user?.role === 'candidate' && tab.dataset.tab === 'invitations') {
      candidateInvitationVisibleLimit = candidateInvitationPageSize;
      state.candidateInvitationTargetId = null;
      state.candidateInvitationPinnedId = null;
      state.candidateInvitationsFilter = 'all';
      state.candidateInvitationsQuery = '';
      state.candidateInvitationsData = null;
    }
    if (state.user?.role === 'employer' && tab.dataset.tab === 'create') state.activeDraft = null;
    state.tab = tab.dataset.tab;
    state.activeVacancy = null;
    await showDashboard();
    return;
  }
  const btn = event.target.closest('[data-action]'); if (!btn) return;
  const action = btn.dataset.action, id = Number(btn.dataset.id);
  if (btn.disabled) return;
  if (['compare-toggle-candidate','compare-show','compare-differences','compare-clear','compare-back','compare-open-profile'].includes(action)) {
    handleEmployerComparisonAction(action,id);
    return;
  }
  if (action === 'invite') {
    await sendEmployerMatchInvitation(btn,id);
    return;
  }
  if (action === 'open-candidate-profile-preview') {
    openCandidateProfilePreview();
    return;
  }
  if (action === 'open-resume-print') {
    openResumePrintPreview();
    return;
  }
  if (action === 'add-resume-course') {
    const list = document.querySelector('#profile-form #resume-course-list');
    if (!list || list.children.length >= 6) return;
    list.insertAdjacentHTML('beforeend', resumeCourseFields({}, list.children.length));
    list.lastElementChild?.querySelector('[data-course-title]')?.focus();
    btn.disabled = list.children.length >= 6;
    editorChanged(list.closest('form'));
    return;
  }
  if (action === 'remove-resume-course') {
    const form = btn.closest('#profile-form');
    const list = form?.querySelector('#resume-course-list');
    btn.closest('[data-resume-course]')?.remove();
    Array.from(list?.children || []).forEach((entry,index)=>{
      const legend = entry.querySelector('legend');
      if (legend) legend.textContent = 'Обучение ' + (index+1);
    });
    const add = form?.querySelector('#resume-add-course');
    if (add) add.disabled = false;
    add?.focus();
    editorChanged(form);
    return;
  }
  if (action === 'add-resume-role') {
    const list = document.querySelector('#profile-form #resume-work-list');
    if (!list || list.children.length >= 5) return;
    list.insertAdjacentHTML('beforeend', resumeRoleFields({}, list.children.length));
    const entry = list.lastElementChild;
    entry?.querySelector('[data-role-position]')?.focus();
    btn.disabled = list.children.length >= 5;
    editorChanged(list.closest('form'));
    return;
  }
  if (action === 'remove-resume-role') {
    const form = btn.closest('#profile-form');
    const list = form?.querySelector('#resume-work-list');
    btn.closest('[data-resume-role]')?.remove();
    Array.from(list?.children || []).forEach((entry, index) => {
      const legend = entry.querySelector('legend');
      if (legend) legend.textContent = 'Место работы ' + (index + 1);
    });
    const add = form?.querySelector('#resume-add-role');
    if (add) add.disabled = false;
    add?.focus();
    editorChanged(form);
    return;
  }
  if (action === 'save-vacancy-draft') {
    const form = btn.closest('#vacancy-form');
    if (form) await saveVacancyDraft(form);
    return;
  }
  if (action === 'apply-draft-conflict') {
    const form = btn.closest('#vacancy-form');
    if (form) await applyDraftConflictResolution(form);
    return;
  }
  if (action === 'refresh-draft-conflict') {
    const form = btn.closest('#vacancy-form');
    if (form) {
      try { await showDraftConflictResolution(form); }
      catch(error) { setEditorStatus(form, 'Не удалось обновить сравнение: ' + error.message, true); }
    }
    return;
  }
  if (action === 'apply-published-conflict') {
    const form = btn.closest('#vacancy-form');
    if (form) await applyPublishedVacancyConflict(form);
    return;
  }
  if (action === 'refresh-published-conflict') {
    const form = btn.closest('#vacancy-form');
    if (form) {
      try { await showPublishedVacancyConflict(form); }
      catch(error) { setEditorStatus(form,'Не удалось обновить сравнение: ' + error.message,true); }
    }
    return;
  }
  if (action === 'employer-workqueue-filter') {
    if (state.user?.role !== 'employer' || state.tab !== 'overview') return;
    const queue = btn.closest('#employer-workqueue');
    const selected = btn.dataset.filter;
    if (!queue || !['all','outcome','consent','applications'].includes(selected)) return;
    for (const filterButton of queue.querySelectorAll('[data-action="employer-workqueue-filter"]')) {
      const active = filterButton.dataset.filter === selected;
      filterButton.setAttribute('aria-pressed',String(active));
      filterButton.classList.toggle('btn-dark',active);
      filterButton.classList.toggle('btn-outline',!active);
    }
    queue.dataset.visibleLimit = '10';
    applyEmployerWorkQueueFilters(queue);
    rememberEmployerWorkQueueView(queue);
    return;
  }
  if (action === 'employer-workqueue-reset') {
    if (state.user?.role !== 'employer' || state.tab !== 'overview') return;
    const queue = btn.closest('#employer-workqueue');
    if (!queue) return;
    const search = queue.querySelector('[data-employer-workqueue-search]');
    const select = queue.querySelector('[data-employer-workqueue-vacancy]');
    if (search) search.value = '';
    if (select) select.value = 'all';
    for (const filterButton of queue.querySelectorAll('[data-action="employer-workqueue-filter"]')) {
      const active = filterButton.dataset.filter === 'all';
      filterButton.setAttribute('aria-pressed',String(active));
      filterButton.classList.toggle('btn-dark',active);
      filterButton.classList.toggle('btn-outline',!active);
    }
    queue.dataset.visibleLimit = '10';
    applyEmployerWorkQueueFilters(queue);
    rememberEmployerWorkQueueView(queue);
    search?.focus({preventScroll:true});
    return;
  }
  if (action === 'employer-workqueue-more') {
    if (state.user?.role !== 'employer' || state.tab !== 'overview') return;
    const queue = btn.closest('#employer-workqueue');
    if (!queue || btn.hidden) return;
    const previous = new Set(queue.querySelectorAll('[data-employer-workqueue-item]:not([hidden])'));
    queue.dataset.visibleLimit = String((Number(queue.dataset.visibleLimit) || 10) + 10);
    applyEmployerWorkQueueFilters(queue);
    rememberEmployerWorkQueueView(queue);
    const firstNew = Array.from(queue.querySelectorAll('[data-employer-workqueue-item]:not([hidden])'))
      .find(card => !previous.has(card));
    if (firstNew) {
      firstNew.tabIndex = -1;
      firstNew.focus({preventScroll:true});
      firstNew.scrollIntoView({block:'nearest'});
    }
    return;
  }
  const introCard = btn.closest('.employer-invitation-card');
  const introBusyId = ['demo-pay','introduction-outcome','direct-introduction-outcome'].includes(action) && introCard
    ? Number(introCard.dataset.invitationId || 0) : 0;
  if (introBusyId && pendingEmployerIntroductionActions.has(introBusyId)) return;
  if (introBusyId) pendingEmployerIntroductionActions.add(introBusyId);
  const introButtons = introBusyId ? Array.from(introCard.querySelectorAll('[data-action="demo-pay"],[data-action="introduction-outcome"],[data-action="direct-introduction-outcome"]')) : [];
  for (const button of introButtons) {
    button.disabled = true;
    button.setAttribute('aria-busy','true');
  }
  const candidateReplyCard = ['accept','decline'].includes(action) && state.user?.role === 'candidate'
    ? btn.closest('.candidate-introduction-card') : null;
  const candidateReplyId = candidateReplyCard && Number.isSafeInteger(id) && id > 0 ? id : 0;
  if (candidateReplyId && pendingCandidateInvitationActions.has(candidateReplyId)) return;
  if (candidateReplyId) pendingCandidateInvitationActions.add(candidateReplyId);
  const candidateReplyButtons = candidateReplyCard
    ? Array.from(candidateReplyCard.querySelectorAll('.invitation-actions [data-action="accept"], .invitation-actions [data-action="decline"]'))
    : [];
  for (const button of candidateReplyButtons) {
    button.disabled = true;
    button.setAttribute('aria-busy','true');
  }
  btn.disabled = true;
  try {
    if (action === 'open-candidate-profile') {
      if (state.user?.role !== 'candidate' || !mayLeaveEditor()) return;
      const fieldIds = {profession:'profile-profession', city:'profile-city', is_active:'profile-active'};
      const fieldId = fieldIds[btn.dataset.profileField] || 'profile-profession';
      state.tab = 'profile';
      state.activeVacancy = null;
      await showDashboard();
      const field = document.getElementById(fieldId);
      field?.focus({preventScroll:true});
      (field?.closest('.field, .profile-visibility') || field)?.scrollIntoView({block:'center'});
      return;
    }
    if (action === 'resume-vacancy-draft') {
      // Always read the latest server version, not a stale cached list entry.
      const draft = await api(`/api/employer/vacancy-drafts/${id}`);
      if (draft.published_vacancy_id != null) throw new Error('Вакансия уже опубликована');
      state.activeDraft = draft;
      state.tab = 'create';
      await showDashboard();
      return;
    }
    if (action === 'delete-vacancy-draft') {
      if (!confirm('Удалить этот черновик без возможности восстановления?')) return;
      await api(`/api/employer/vacancy-drafts/${id}`, {method:'DELETE'});
      if (Number(state.activeDraft?.id) === id) state.activeDraft = null;
      await loadEmployerVacancies();
      toast('Черновик удалён.');
      return;
    }
    if (action === 'check-smtp') {
      const target = $('#admin-smtp-status');
      if (target) target.innerHTML = '<div class="loading">Проверяем SMTP...</div>';
      const result = await api('/api/admin/smtp/check',{method:'POST'});
      const messages = {
        ok:'SMTP работает: TLS и авторизация успешны.',
        not_configured:'SMTP не настроен в переменных окружения.',
        invalid_port:'В SMTP-порту указано некорректное значение.',
        authentication_failed:'SMTP-сервер доступен, но логин или пароль отклонён.',
        tls_disabled:'SMTP без TLS запрещён для служебных писем.',
        smtp_rejected:'SMTP-сервер отклонил проверочную команду.',
        tls_or_connect_failed:'Не удалось установить защищённое соединение с SMTP.',
        connection_failed:'SMTP недоступен или соединение завершилось ошибкой.'
      };
      if (target) {
        const text = messages[result.status] || 'Неизвестный результат SMTP-проверки.';
        target.innerHTML = `<strong>${result.ok ? '✓ SMTP готов' : 'SMTP требует внимания'}</strong><p>${esc(text)}</p>`;
      }
      toast(result.ok ? 'SMTP-проверка успешно пройдена.' : (messages[result.status] || 'SMTP-проверка не пройдена.'), !result.ok);
      return;
    }
    if (action === 'send-smtp-test-email') {
      const type = btn.dataset.smtpScenario || 'connection';
      const target = $('#admin-mail-test-result');
      const label = type === 'employer_application' ? 'для работодателя'
        : type === 'candidate_invitation' ? 'для соискателя' : 'для проверки SMTP';
      if (target) target.textContent = 'Отправляем тестовое письмо ' + label + '…';
      try {
        const result = await api('/api/admin/smtp/test-email',{
          method:'POST',body:JSON.stringify({scenario:type})
        });
        if (target) target.textContent = result.smtp_accepted
          ? 'SMTP принял тестовое письмо ' + label +
            '. Проверьте «Входящие» и «Спам» почты администратора. Это ещё не подтверждение доставки.'
          : 'SMTP не подтвердил приём тестового письма.';
        toast('SMTP принял тестовое письмо. Проверьте почтовый ящик администратора.');
      } catch (e) {
        if (target) target.textContent = 'Проверка письма ' + label + ' не удалась: ' + String(e.message || e);
        throw e;
      }
      return;
    }
    if (action === 'register-admin-passkey') {
      await registerAdminPasskey();
      await renderAdmin();
      return;
    }
    if (action === 'delete-admin-passkey') {
      const passkeyId = String(btn.dataset.passkeyId || '');
      if (!passkeyId) return;
      await api(`/api/admin/passkeys/${encodeURIComponent(passkeyId)}`,{method:'DELETE'});
      await renderAdmin();
      toast('Passkey удалён.');
      return;
    }
    if (action === 'privacy-disposal-preview') {
      const requestKey = String(btn.dataset.rightsKey || '');
      if (!/^[A-Za-z0-9_-]{16,64}$/.test(requestKey)) return;
      const panel = document.getElementById('privacy-disposal-panel-' + requestKey);
      if (!panel) return;
      btn.disabled = true;
      panel.textContent = 'Считаем связанные записи…';
      try {
        const [impact, checklist, external] = await Promise.all([
          api('/api/admin/privacy-requests/' + encodeURIComponent(requestKey) + '/impact'),
          api('/api/admin/privacy-requests/' + encodeURIComponent(requestKey) + '/disposition-review'),
          api('/api/admin/privacy-requests/' + encodeURIComponent(requestKey) + '/external-review')
        ]);
        panel.innerHTML = disposalPreviewMarkup(impact.preview, checklist.review, external.review);
      } finally {
        btn.disabled = false;
      }
      return;
    }
    if (action === 'privacy-external-save') {
      const requestKey = String(btn.dataset.rightsKey || '');
      const systemKey = String(btn.dataset.systemKey || '');
      if (!/^[A-Za-z0-9_-]{16,64}$/.test(requestKey) ||
          !/^[a-z_]{4,40}$/.test(systemKey)) return;
      const panel = document.getElementById('privacy-disposal-panel-' + requestKey);
      if (!panel) return;
      const selector = Array.from(panel.querySelectorAll('select[data-external-system]'))
        .find(node => node.dataset.externalSystem === systemKey);
      const status = String(selector?.value || '');
      if (!['reviewed','not_applicable','followup_required'].includes(status)) {
        toast('Выберите результат проверки.', true); return;
      }
      if (status !== 'followup_required' && !window.confirm(
        'Вы подтверждаете, что проверили эту внешнюю систему самостоятельно и ' +
        'отметка соответствует действительности? Система не соединяется с провайдером.'
      )) return;
      btn.disabled = true;
      try {
        const url = '/api/admin/privacy-requests/' + encodeURIComponent(requestKey);
        await api(url + '/external-review/' + encodeURIComponent(systemKey), {
          method: 'POST', body: JSON.stringify({status})
        });
        const [impact, checklist, external] = await Promise.all([
          api(url + '/impact'),
          api(url + '/disposition-review'),
          api(url + '/external-review')
        ]);
        panel.innerHTML = disposalPreviewMarkup(impact.preview, checklist.review, external.review);
        toast('Статус внешней проверки записан. Данные у провайдера не изменялись.');
      } finally {
        if (btn.isConnected) btn.disabled = false;
      }
      return;
    }
    if (action === 'privacy-disposal-save') {
      const requestKey = String(btn.dataset.rightsKey || '');
      if (!/^[A-Za-z0-9_-]{16,64}$/.test(requestKey)) return;
      const panel = document.getElementById('privacy-disposal-panel-' + requestKey);
      if (!panel) return;
      const inputs = Array.from(panel.querySelectorAll('input[data-disposal-check]'));
      if (inputs.length !== 7) throw new Error('Чек-лист загружен не полностью.');
      const payload = Object.fromEntries(inputs.map(input => [input.dataset.disposalCheck, input.checked]));
      if (payload.manual_action_verified && !window.confirm(
        'Вы подтверждаете, что разрешённые действия действительно выполнены вручную ' +
        'с проверкой связанных записей, почты и резервных копий? Эта кнопка ничего не удаляет.'
      )) return;
      btn.disabled = true;
      try {
        const saved = await api('/api/admin/privacy-requests/' + encodeURIComponent(requestKey) + '/disposition-review', {
          method:'POST', body:JSON.stringify(payload)
        });
        const [report, external] = await Promise.all([
          api('/api/admin/privacy-requests/' + encodeURIComponent(requestKey) + '/impact'),
          api('/api/admin/privacy-requests/' + encodeURIComponent(requestKey) + '/external-review')
        ]);
        panel.innerHTML = disposalPreviewMarkup(report.preview, saved.review, external.review);
        toast('Ручные проверки сохранены в журнале. Данные не удалены.');
      } finally {
        if (btn.isConnected) btn.disabled = false;
      }
      return;
    }
    if (action === 'privacy-rights-review' || action === 'privacy-rights-close') {
      const requestKey = String(btn.dataset.rightsKey || '');
      if (!/^[A-Za-z0-9_-]{16,64}$/.test(requestKey)) return;
      const isReview = action === 'privacy-rights-review';
      let payload = {status:'in_review'};
      if (!isReview) {
        const selector = document.querySelector('[data-rights-closure-reason="' + requestKey + '"]');
        const reason = String(selector?.value || '');
        const allowedReasons = ['fulfilled','retention_required','identity_unverified','other'];
        if (!allowedReasons.includes(reason)) throw new Error('Укажите основание решения.');
        const approved = window.confirm(
          'Подтверждаете, что оператор вручную проверил основания, предпринял необходимые действия ' +
          'и отдельно сообщил пользователю результат? Изменение статуса НЕ удаляет персональные данные автоматически.'
        );
        if (!approved) return;
        payload = {
          status: reason === 'fulfilled' ? 'completed' : 'declined',
          manual_response_confirmed: true,
          closure_reason: reason
        };
      }
      btn.disabled = true;
      try {
        await api('/api/admin/privacy-requests/' + encodeURIComponent(requestKey) + '/status', {
          method: 'POST', body: JSON.stringify(payload)
        });
        await renderAdmin();
        toast(isReview ? 'Обращение взято в работу.' : 'Решение зарегистрировано. Запись не означает автоматического удаления данных.');
      } finally {
        if (btn.isConnected) btn.disabled = false;
      }
      return;
    }
    if (action === 'revoke-other-sessions') {
      const result = await api('/api/account/sessions/revoke-others',{method:'POST'});
      await renderAccountSecurity($('#dashboard-main'));
      toast(result.revoked ? 'Другие сессии завершены.' : 'Других активных сессий нет.');
      return;
    }
    if (action === 'revoke-session') {
      const sessionId = String(btn.dataset.sessionId || '');
      if (!sessionId) return;
      await api(`/api/account/sessions/${encodeURIComponent(sessionId)}`,{method:'DELETE'});
      await renderAccountSecurity($('#dashboard-main'));
      toast('Сессия завершена.');
      return;
    }
    if (action === 'filter-candidate-invitations') {
      if (!Object.hasOwn(candidateInvitationFilterLabels,btn.dataset.filter)) return;
      candidateInvitationVisibleLimit = candidateInvitationPageSize;
      state.candidateInvitationTargetId = null;
      state.candidateInvitationPinnedId = null;
      state.candidateInvitationsFilter = btn.dataset.filter;
      await loadCandidateInvitations();
      return;
    }
    if (action === 'reset-candidate-invitation-filters') {
      candidateInvitationVisibleLimit = candidateInvitationPageSize;
      state.candidateInvitationTargetId = null;
      state.candidateInvitationPinnedId = null;
      state.candidateInvitationsFilter = 'all';
      state.candidateInvitationsQuery = '';
      await loadCandidateInvitations();
      return;
    }
    if (action === 'more-candidate-invitations') {
      const previous = candidateInvitationVisibleLimit;
      candidateInvitationVisibleLimit += candidateInvitationPageSize;
      await loadCandidateInvitations();
      const next = document.querySelectorAll('#candidate-invitation-results .candidate-introduction-card')[previous];
      if (next) {
        next.tabIndex = -1;
        next.focus({preventScroll:true});
        next.scrollIntoView({block:'nearest'});
      }
      return;
    }
    if (action === 'open-candidate-invitations') {
      candidateInvitationVisibleLimit = candidateInvitationPageSize;
      const linkId = Number(btn.dataset.invitationId || 0);
      state.candidateInvitationTargetId = Number.isSafeInteger(linkId) && linkId > 0 ? linkId : null;
      state.candidateInvitationPinnedId = state.candidateInvitationTargetId;
      const filter = Object.hasOwn(candidateInvitationFilterLabels,btn.dataset.filter) ? btn.dataset.filter : 'all';
      state.candidateInvitationsFilter = filter;
      state.candidateInvitationsQuery = '';
      state.candidateInvitationsData = null;
      state.tab = 'invitations';
      state.activeVacancy = null;
      await showDashboard();
      return;
    }
    if (action === 'vacancy-history') {
      await toggleEmployerVacancyHistory(btn,id);
      return;
    }
    if (action === 'more-vacancy-history') {
      await loadMoreEmployerVacancyHistory(btn,id);
      return;
    }
    if (action === 'employer-analytics-sort') {
      if (state.user?.role !== 'employer' || state.tab !== 'overview') return;
      const root = btn.closest('#employer-vacancy-analytics');
      const selected = btn.dataset.sort;
      if (!root || !['activity','results','attention'].includes(selected)) return;
      for (const control of root.querySelectorAll('[data-action="employer-analytics-sort"]')) {
        const active = control.dataset.sort === selected;
        control.setAttribute('aria-pressed',String(active));
        control.classList.toggle('btn-dark',active);
        control.classList.toggle('btn-outline',!active);
      }
      const list = root.querySelector('.employer-analytics-list');
      if (list) {
        const items = [...list.querySelectorAll('[data-analytics-row]')];
        const number = (el,key) => Number(el.dataset[key]) || 0;
        items.sort((a,b) => {
          if (selected === 'results') return number(b,'analyticsPositive') - number(a,'analyticsPositive') || number(b,'analyticsAttention') - number(a,'analyticsAttention');
          if (selected === 'attention') return number(b,'analyticsAttention') - number(a,'analyticsAttention') || number(b,'analyticsPositive') - number(a,'analyticsPositive');
          return number(b,'analyticsStatus') - number(a,'analyticsStatus') || 0;
        });
        if (selected === 'activity') {
          items.sort((a,b) => (a.dataset.analyticsStatus === 'open' ? -1 : 0) - (b.dataset.analyticsStatus === 'open' ? -1 : 0) || number(a,'analyticsOrder')-number(b,'analyticsOrder'));
        }
        items.forEach(item => list.appendChild(item));
      }
      return;
    }
    if (action === 'employer-analytics-filter') {
      if (state.user?.role !== 'employer' || state.tab !== 'overview') return;
      const root = btn.closest('#employer-vacancy-analytics');
      const selected = btn.dataset.filter;
      if (!root || !['all','open','closed'].includes(selected)) return;
      for (const filter of root.querySelectorAll('[data-action="employer-analytics-filter"]')) {
        const active = filter.dataset.filter === selected;
        filter.setAttribute('aria-pressed',String(active));
        filter.classList.toggle('btn-dark',active);
        filter.classList.toggle('btn-outline',!active);
      }
      let visible = 0;
      for (const row of root.querySelectorAll('[data-analytics-row]')) {
        row.hidden = selected !== 'all' &&
          (selected === 'open' ? row.dataset.analyticsStatus !== 'open' : row.dataset.analyticsStatus === 'open');
        if (!row.hidden) visible += 1;
      }
      const count = root.querySelector('#employer-analytics-visible-count');
      if (count) count.textContent = String(visible);
      const empty = root.querySelector('.employer-analytics-empty');
      if (empty) empty.hidden = visible !== 0;
      return;
    }
    if (action === 'filter-employer-jobs') {
      if (!['all', 'open', 'closed', 'attention'].includes(btn.dataset.filter)) return;
      state.employerVacancyFilter = btn.dataset.filter;
      state.activeVacancy = null;
      await loadEmployerVacancies();
      $('#dashboard-main [data-action="filter-employer-jobs"][data-filter="' + state.employerVacancyFilter + '"]')?.focus({preventScroll:true});
      return;
    }
    if (action === 'clear-employer-job-search') {
      state.employerVacancySearch = '';
      const input = $('#employer-vacancy-search');
      if (input) { input.value = ''; input.focus({preventScroll:true}); }
      applyEmployerVacancySearch();
      return;
    }
    if (action === 'vacancy-applications' || action === 'vacancy-applications-primary') {
      state.employerApplicationsVacancyFilter = String(id);
      state.employerApplicationsStatusFilter = action === 'vacancy-applications-primary' ? 'attention' : 'all';
      state.employerApplicationsQuery = '';
      state.tab = 'applications';
      state.activeVacancy = null;
      await showDashboard();
      return;
    }
    if (action === 'filter-employer-invitations') {
      if (!Object.hasOwn(employerInvitationFilterLabels,btn.dataset.filter)) return;
      state.employerInvitationsTargetId = null;
      employerInvitationVisibleLimit = employerInvitationPageSize;
      state.employerInvitationsFilter = btn.dataset.filter;
      await loadEmployerInvitations();
      return;
    }
    if (action === 'reset-employer-invitation-filters') {
      state.employerInvitationsTargetId = null;
      employerInvitationVisibleLimit = employerInvitationPageSize;
      state.employerInvitationsFilter = 'all';
      state.employerInvitationsVacancyFilter = 'all';
      state.employerInvitationsQuery = '';
      await loadEmployerInvitations();
      return;
    }
    if (action === 'more-employer-invitations') {
      const previous = employerInvitationVisibleLimit;
      employerInvitationVisibleLimit += employerInvitationPageSize;
      await loadEmployerInvitations();
      const next = document.querySelectorAll('#employer-invitation-results .employer-invitation-card')[previous];
      if (next) {
        next.tabIndex = -1;
        next.focus({preventScroll:true});
        next.scrollIntoView({block:'nearest'});
      }
      return;
    }
    if (action === 'refresh-employer-introductions') {
      await loadEmployerInvitations(true);
      return;
    }
    if (action === 'open-employer-invitations') {
      employerInvitationVisibleLimit = employerInvitationPageSize;
      const linkId = Number(btn.dataset.invitationId || 0);
      state.employerInvitationsTargetId = Number.isSafeInteger(linkId) && linkId > 0 ? linkId : null;
      const filter = Object.hasOwn(employerInvitationFilterLabels,btn.dataset.filter) ? btn.dataset.filter : 'all';
      state.employerInvitationsFilter = filter;
      state.employerInvitationsVacancyFilter = btn.dataset.vacancyId ? String(btn.dataset.vacancyId) : 'all';
      state.employerInvitationsQuery = '';
      state.employerInvitationsData = null;
      state.tab = 'invitations';
      state.activeVacancy = null;
      await showDashboard();
      return;
    }
    if (action === 'open-employer-matches') {
      if (!mayLeaveEditor() || !Number.isSafeInteger(id) || id <= 0) return;
      state.employerVacancyFilter = 'all';
      state.employerVacancySearch = '';
      state.tab = 'vacancies';
      state.activeVacancy = id;
      await showDashboard();
      return;
    }
    if (action === 'close-employer-matches') {
      const sourceId = state.activeVacancy;
      state.activeVacancy = null;
      resetEmployerCandidateComparison();
      const target = $('#employer-matches');
      if (target) { target.classList.add('hidden'); target.innerHTML = ''; }
      const card = document.querySelector(`#employer-vacancy-results .employer-vacancy-card[data-employer-vacancy-id="${Number(sourceId)}"]`);
      const focusTarget = card?.querySelector('[data-action="matches-primary"]') || card?.querySelector('h4');
      if (focusTarget) { if (!focusTarget.matches('button,a')) focusTarget.tabIndex = -1; focusTarget.focus({preventScroll:true}); card.scrollIntoView({block:'nearest'}); }
      return;
    }
    if (action === 'new-job') { if (!mayLeaveEditor()) return; state.editVacancy=null; state.activeDraft=null; state.tab='create'; await showDashboard(); }
    if (action === 'edit-job') { if (!mayLeaveEditor()) return; state.editVacancy=id; state.activeVacancy=null; state.tab='edit'; await showDashboard(); }
    if (action === 'cancel-job-edit') { if (!mayLeaveEditor()) return; state.editVacancy=null; state.tab='vacancies'; await showDashboard(); }
    if (action === 'matches' || action === 'matches-primary') { await loadMatches(id); }
    if (action === 'job-status') { await api(`/api/employer/vacancies/${id}/status`,{method:'PATCH',body:JSON.stringify({status:btn.dataset.status})}); await showDashboard(); toast('Статус вакансии обновлён.'); }
    if (action === 'refresh-candidate-introductions') {
      await loadCandidateInvitations($('#dashboard-main'), true);
      refreshActionSummary().catch(() => {});
      return;
    }
    if (action === 'accept' || action === 'decline') {
      const consent = $(`#consent-${id}`);
      if (action === 'accept' && !consent?.checked) {
        throw new Error('Подтвердите согласие на передачу контакта.');
      }
      const accepted = action === 'accept';
      await api(`/api/candidate/invitations/${id}/respond`,{method:'POST',body:JSON.stringify({
        decision: accepted ? 'accepted' : 'declined',
        share_consent: accepted && consent.checked
      })});
      candidateInvitationSavedReceipt(btn, accepted);
      candidateInvitationVisibleLimit = candidateInvitationPageSize;
      state.candidateInvitationsFilter = accepted ? 'waiting' : 'closed';
      state.candidateInvitationsData = null;
      state.candidateInvitationTargetId = id;
      try {
        await loadCandidateInvitations($('#dashboard-main'), true);
      } catch (refreshError) {
        toast('Ответ сохранён, но список пока не обновился. Нажмите «Обновить список».', true);
        return;
      }
      refreshActionSummary().catch(() => {});
      toast(accepted ? 'Согласие сохранено. Ждём работодателя.' : 'Отказ сохранён. Контакты не переданы.');
    }
    if (action === 'direct-introduction-outcome') {
      const outcome = btn.dataset.status;
      if (!['hired','rejected'].includes(outcome)) return;
      const question = outcome === 'hired'
        ? 'Отметить положительный итог прямого знакомства? Это не подтверждение трудоустройства. Изменить результат нельзя.'
        : 'Зафиксировать результат прямого знакомства «Не договорились»? Изменить результат нельзя.';
      if (!confirm(question)) return;
      await api(`/api/employer/invitations/${id}/outcome`, {
        method:'PATCH',body:JSON.stringify({status:outcome})
      });
      employerIntroductionSavedReceipt(btn, outcome);
      state.employerInvitationsData = null;
      state.employerInvitationsFilter = 'closed';
      state.employerInvitationsQuery = '';
      state.employerInvitationsVacancyFilter = 'all';
      employerInvitationVisibleLimit = employerInvitationPageSize;
      state.employerInvitationsTargetId = id;
      try {
        await loadEmployerInvitations(true);
      } catch (refreshError) {
        toast('Итог сохранён, но список пока не обновился. Используйте кнопку «Обновить список».', true);
        return;
      }
      refreshActionSummary().catch(() => {});
      toast(outcome === 'hired' ? 'Положительный итог прямого знакомства сохранён.' : 'Прямое знакомство завершено: не договорились.');
      return;
    }
    if (action === 'introduction-outcome') {
      const outcome = btn.dataset.status;
      if (!['hired','rejected'].includes(outcome)) return;
      const question = outcome === 'hired'
        ? 'Отметить положительный итог знакомства? Это не подтверждение трудоустройства. После сохранения изменить итог нельзя.'
        : 'Зафиксировать результат «Не договорились»? После сохранения изменить итог нельзя.';
      if (!confirm(question)) return;
      await api(`/api/employer/applications/${id}/status`,{method:'PATCH',body:JSON.stringify({status:outcome})});
      const completedInvitationId = Number(btn.closest('.employer-invitation-card')?.dataset.invitationId || 0);
      employerIntroductionSavedReceipt(btn, outcome);
      state.employerInvitationsData = null;
      state.employerInvitationsFilter = 'closed';
      state.employerInvitationsQuery = '';
      state.employerInvitationsVacancyFilter = 'all';
      employerInvitationVisibleLimit = employerInvitationPageSize;
      state.employerInvitationsTargetId = completedInvitationId;
      try {
        await loadEmployerInvitations(true);
      } catch (refreshError) {
        toast('Итог сохранён, но список пока не обновился. Используйте кнопку «Обновить список».', true);
        return;
      }
      refreshActionSummary().catch(() => {});
      const completedCard = document.querySelector(`#dashboard-main .employer-invitation-card[data-application-id="${Number(id)}"]`);
      if (completedCard) {
        completedCard.setAttribute('tabindex','-1');
        completedCard.scrollIntoView({block:'nearest'});
        completedCard.focus({preventScroll:true});
      }
      toast(outcome === 'hired' ? 'Положительный итог знакомства сохранён.' : 'Итог знакомства сохранён: не договорились.');
      return;
    }
    if (action === 'demo-pay') {
      if (!confirm('Это тестовая оплата — реальные средства НЕ списываются. Открыть контакт согласившегося кандидата?')) return;
      const result = await api(`/api/employer/invitations/${id}/demo-pay`,{method:'POST'});
      employerIntroductionSavedReceipt(btn, 'opened');
      state.employerInvitationsFilter = 'introduced';
      state.employerInvitationsQuery = '';
      state.employerInvitationsVacancyFilter = 'all';
      employerInvitationVisibleLimit = employerInvitationPageSize;
      state.employerInvitationsTargetId = id;
      state.employerInvitationsData = null;
      try {
        await loadEmployerInvitations(true);
      } catch (refreshError) {
        toast('Контакт открыт без реального списания. Список пока не обновился — нажмите «Обновить список».', true);
        return;
      }
      refreshActionSummary().catch(() => {});
      toast(`Демо-платёж ${money(result.amount_rub)} проведён без списания средств.`);
    }
  } catch(e) { toast(e.message,true); } finally {
    if (candidateReplyId) pendingCandidateInvitationActions.delete(candidateReplyId);
    for (const button of candidateReplyButtons) {
      if (button.isConnected) {button.disabled = false; button.removeAttribute('aria-busy');}
    }
    if (introBusyId) pendingEmployerIntroductionActions.delete(introBusyId);
    for (const button of introButtons) {
      if (button.isConnected) {button.disabled = false; button.removeAttribute('aria-busy');}
    }
    if (btn.isConnected) btn.disabled = false;
  }
}
async function start() {
  $('#login-open').addEventListener('click',()=>openAuth('login'));
  $('#register-open').addEventListener('click',()=>openAuth('register'));
  if (publicSignupClosed()) {
    const registerButton = $('#register-open');
    registerButton.disabled = true;
    registerButton.textContent = 'Регистрация пока закрыта';
    $$('[data-register]').forEach(button => {
      button.disabled = true;
      button.setAttribute('aria-disabled', 'true');
      button.title = 'Регистрация закрыта до юридического утверждения';
    });
  }
  window.addEventListener('resize', syncResponsiveMemberActions);
  syncResponsiveMemberActions();
  $('#modal-close').addEventListener('click',()=>{
    state.pendingApplicationVacancyId = null;
    $('#auth-dialog').close();
  });
  $('#auth-dialog').addEventListener('click',e=>{
    if(e.target === $('#auth-dialog')) {
      state.pendingApplicationVacancyId = null;
      $('#auth-dialog').close();
    }
  });
  $('#auth-dialog').addEventListener('cancel',()=>{ state.pendingApplicationVacancyId = null; });
  $('#auth-form').addEventListener('submit',submitAuth);
  $('#auth-dialog').addEventListener('click',async e=>{
    const role = e.target.closest('[data-role]'); if(role){ state.role=role.dataset.role; updateAuth(); }
    const mode = e.target.closest('[data-switch]'); if(mode){ resetMfaState(); state.mode=mode.dataset.switch; updateAuth(); }
    const mfaCancel = e.target.closest('[data-mfa-cancel]'); if(mfaCancel){ resetMfaState(); $('#auth-form').reset(); updateAuth(); $('#auth-email').focus(); }
    const fallback = e.target.closest('[data-mfa-totp-fallback]');
    if (fallback) {
      fallback.disabled = true;
      try { await switchAdminMfaToTotp(); } catch(e2) { $('#auth-message').textContent = e2.message; }
      finally { if (fallback.isConnected) fallback.disabled = false; }
    }
  });
  $$('[data-register]').forEach(button=>button.addEventListener('click',()=>openAuth('register',button.dataset.register)));
  $('#account-open').addEventListener('click',()=>{ if (mayLeaveEditor()) showDashboard(true); });
  $('#logout').addEventListener('click',async()=>{ if (!mayLeaveEditor()) return; try { await api('/api/logout',{method:'POST'}); state.user=null; state.employerWorkQueueView=null; syncEmployerMatchAccount(); $('#account-content').innerHTML=''; await reloadUser(); await loadPublicJobs(); window.scrollTo({top:0,behavior:'smooth'}); toast('Вы вышли из аккаунта.'); } catch(e) { toast(e.message,true); }});
  $('#jobs-filter').addEventListener('click',loadPublicJobs);
  $('#city-filter').addEventListener('keydown',e=>{if(e.key==='Enter')loadPublicJobs();});
  $('#account-content').addEventListener('click',captureEmployerWorkQueueNavigation,true);
  $('#account-content').addEventListener('click',handleDashboardClick);
  $('#account-content').addEventListener('input',handleDashboardInput);
  $('#account-content').addEventListener('change',handleDashboardChange);
  $('#account-content').addEventListener('submit',handleDashboardSubmit);
  await reloadUser();
  await loadPublicJobs();
  if (state.user) { state.tab = 'overview'; await showDashboard(); }
  // Feature modules may now open deep-linked public content with correct
  // authenticated state, without creating applications on behalf of users.
  document.dispatchEvent(new Event('stazhno:ready'));
}
// Refresh when a signed-in user returns, never by background polling.
document.addEventListener('visibilitychange', () => {
  if (document.hidden || !state.user || Date.now() - lastActionRefreshAt < 15000) return;
  refreshActionSummary();
});
document.addEventListener('DOMContentLoaded',start);
