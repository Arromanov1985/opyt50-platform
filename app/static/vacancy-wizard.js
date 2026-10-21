/* Release 0.3: employer vacancy guide. Local preview; existing API format unchanged.
 * Submitting remains in app.js. This script never sends data to the server.
 */
'use strict';
(() => {
  const approved = new WeakMap();
  const maxDescription = 1200;
  const formatMoney = value => new Intl.NumberFormat('ru-RU').format(Number(value)) + ' ₽';
  function getField(form, name) {
    const element = form.elements.namedItem(name);
    return element ? element.value.trim() : '';
  }
  function splitDescription(description) {
    // Only parse the precise format created by our guided composer.
    // Legacy free-text vacancies are shown in their original field instead
    // of splitting or truncating any existing text.
    const match = /^Обязанности:\n([\s\S]*?)\n\nТребования:\n([\s\S]*?)\n\nУсловия работы:\n([\s\S]*)$/.exec(String(description || ''));
    if (!match) return null;
    const fields = {
      responsibilities: match[1],
      requirements: match[2],
      conditions: match[3],
    };
    if (fields.responsibilities.length > 400 ||
        fields.requirements.length > 300 ||
        fields.conditions.length > 350) return null;
    return fields;
  }
  function describe(form) {
    if (form.dataset.editMode === 'legacy') {
      return getField(form, 'legacy_description');
    }
    return [
      'Обязанности:',
      getField(form, 'responsibilities'),
      '',
      'Требования:',
      getField(form, 'requirements'),
      '',
      'Условия работы:',
      getField(form, 'conditions'),
    ].join('\n');
  }
  function signature(form) {
    return JSON.stringify([...form.querySelectorAll('[name]')].map(field => [field.name, field.value]));
  }
  function message(form, text, error = false) {
    const el = form.querySelector('#vacancy-form-message');
    if (!el) return;
    el.textContent = text;
    el.classList.toggle('is-error', error);
  }
  function invalidate(form, notify = false) {
    const reviewed = approved.has(form);
    approved.delete(form);
    const publish = form.querySelector('#vacancy-publish');
    const preview = form.querySelector('#vacancy-preview');
    if (publish) publish.disabled = true;
    if (preview) preview.hidden = true;
    if (notify && reviewed) message(form, 'Данные изменены. Повторно откройте предпросмотр перед публикацией.');
  }
  function setText(form, id, text) {
    const element = form.querySelector('#' + id);
    if (element) element.textContent = text;
  }
  function showPreview(form) {
    invalidate(form);
    if (!form.reportValidity()) {
      message(form, 'Заполните обязательные поля, чтобы посмотреть вакансию.', true);
      return;
    }
    for (const field of (form.dataset.editMode === 'legacy' ? [] : ['responsibilities', 'requirements', 'conditions'])) {
      if (!getField(form, field)) {
        const control = form.elements.namedItem(field);
        message(form, 'Заполните обязанности, требования и условия работы — эти разделы необходимы.', true);
        control.focus();
        return;
      }
    }
    const salaryMin = Number(getField(form,'salary_min'));
    const salaryMax = Number(getField(form,'salary_max'));
    if (!Number.isFinite(salaryMin) || !Number.isFinite(salaryMax) || salaryMax < salaryMin) {
      message(form, 'Проверьте зарплату: верхняя граница не может быть меньше нижней.', true);
      form.elements.namedItem('salary_max').focus();
      return;
    }
    const description = describe(form);
    if (description.length > maxDescription) {
      message(form, 'Описание превышает допустимую длину 1200 символов. Сократите текст.', true);
      return;
    }
    // Plain text only. The employer cannot inject markup into the preview.
    const name = document.querySelector('.tab-heading')?.textContent?.trim() || 'Компания';
    setText(form,'vacancy-preview-company', name);
    setText(form,'vacancy-preview-title',getField(form,'title'));
    setText(form,'vacancy-preview-city',getField(form,'city'));
    setText(form,'vacancy-preview-salary',formatMoney(salaryMin)+' — '+formatMoney(salaryMax));
    setText(form,'vacancy-preview-schedule','График: '+getField(form,'schedule')+' · Занятость: '+getField(form,'employment'));
    setText(form,'vacancy-preview-skills','Ключевые навыки: '+(getField(form,'skills') || 'По договорённости'));
    setText(form,'vacancy-preview-description',description);
    const preview = form.querySelector('#vacancy-preview');
    preview.hidden = false;
    const publish = form.querySelector('#vacancy-publish');
    publish.disabled = false;
    approved.set(form, {signature:signature(form),description});
    message(form, form.dataset.editId
      ? 'Изменения готовы к сохранению. Проверьте объявление и нажмите «Сохранить изменения».'
      : 'Вакансия готова к публикации. Проверьте предпросмотр и нажмите «Опубликовать вакансию».');
    preview.scrollIntoView({behavior:'smooth',block:'nearest'});
  }
  function getReviewedDescription(form) {
    if (form?.id !== 'vacancy-form') return null;
    const review = approved.get(form);
    if (!review || review.signature !== signature(form) || form.querySelector('#vacancy-preview').hidden) {
      invalidate(form);
      message(form, 'Сначала проверьте актуальную версию вакансии.', true);
      return null;
    }
    return review.description;
  }
  document.addEventListener('click', event => {
    const button = event.target.closest('#vacancy-show-preview');
    if (!button) return;
    const form = button.closest('#vacancy-form');
    if (form) showPreview(form);
  });
  for (const name of ['input','change']) {
    document.addEventListener(name, event => {
      const target = event.target;
      const form = target.closest?.('#vacancy-form');
      if (form && target.matches('[name]')) invalidate(form, true);
    });
  }
  window.OpytnovacancyWizard = {getReviewedDescription, splitDescription};
})();
