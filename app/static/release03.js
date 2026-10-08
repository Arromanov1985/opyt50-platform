/* Release 0.3. Accessible presentation preference: no account data stored. */
'use strict';
document.addEventListener('DOMContentLoaded', () => {
  const button=document.getElementById('reading-mode-toggle');
  if(!button) return;
  const key='opytno-large-text';
  function readPreference() {
    try { return localStorage.getItem(key)==='yes'; } catch { return false; }
  }
  function setMode(enabled) {
    document.body.classList.toggle('comfortable-view', enabled);
    button.setAttribute('aria-pressed', String(enabled));
    button.setAttribute('aria-label', enabled ? 'Выключить крупный текст' : 'Включить крупный текст');
    button.title=enabled ? 'Обычный текст' : 'Крупный текст';
    try { localStorage.setItem(key, enabled ? 'yes' : 'no'); } catch { /* private mode */ }
  }
  setMode(readPreference());
  button.addEventListener('click', () => setMode(!document.body.classList.contains('comfortable-view')));
});


/*
 * Candidate work-experience guide.
 * Entirely local: no API requests, no model calls and no automatic saving.
 * The only persisted value is the standard profile "about" field, if the
 * candidate explicitly chooses "Добавить в профиль" and then "Сохранить профиль".
 */
(function () {
  const parts = ['experience-work', 'experience-tasks', 'experience-strengths'];
  function compact(raw) {
    return String(raw || '').replace(/\s+/g, ' ').trim().replace(/[.!?。]+$/g, '');
  }
  function contactInfoFound(value) {
    return /[^\s@]+@[^\s@]+\.[^\s@]+/.test(value) ||
      /(?:\+?\d[\s()\-]*){10,}/.test(value);
  }
  function describeExperience(work, tasks, strengths) {
    const lines = [];
    if (work) lines.push('Направление работы: ' + work + '.');
    if (tasks) lines.push('Основные задачи: ' + tasks + '.');
    if (strengths) lines.push('Сильные стороны и навыки: ' + strengths + '.');
    return lines.join(' ');
  }
  function say(message, error) {
    const line = document.getElementById('experience-helper-message');
    if (!line) return;
    line.textContent = message;
    line.classList.toggle('is-error', Boolean(error));
  }
  function invalidatePreview() {
    const insert = document.getElementById('experience-insert');
    const preview = document.getElementById('experience-preview-block');
    if (insert) insert.disabled = true;
    if (preview) preview.hidden = true;
  }
  function compose() {
    const fields = parts.map(id => compact(document.getElementById(id)?.value));
    const preview = document.getElementById('experience-preview');
    const block = document.getElementById('experience-preview-block');
    const insert = document.getElementById('experience-insert');
    if (!preview || !block || !insert) return;
    invalidatePreview();
    if (fields.every(value => !value)) {
      say('Заполните хотя бы один ответ, затем нажмите «Составить текст».', true);
      return;
    }
    if (fields.some(contactInfoFound)) {
      say('Уберите из ответов телефон или email. Эти сведения нельзя включать в описание опыта.', true);
      return;
    }
    const composed = describeExperience(...fields);
    if (composed.length > 700) {
      say('Описание получилось слишком длинным. Сократите ответы и попробуйте снова.', true);
      return;
    }
    preview.textContent = composed;
    block.hidden = false;
    insert.disabled = false;
    say('Проверьте текст. Он пока не добавлен в профиль и никуда не отправлен.', false);
  }
  function insertText() {
    const input = document.getElementById('profile-about');
    const preview = document.getElementById('experience-preview');
    const button = document.getElementById('experience-insert');
    if (!input || !preview || !button || button.disabled) return;
    const text = preview.textContent.trim();
    if (!text) return;
    const existing = input.value.trim();
    if (existing.includes(text)) {
      button.disabled = true;
      say('Такой текст уже есть в поле «Немного о вашем опыте».', false);
      return;
    }
    const combined = existing ? existing + '\n\n' + text : text;
    if (combined.length > input.maxLength) {
      say('В поле «Немного о вашем опыте» недостаточно места. Сократите прежний текст или ответы.', true);
      return;
    }
    input.value = combined;
    input.dispatchEvent(new Event('input', {bubbles:true}));
    button.disabled = true;
    say('Описание добавлено. Его можно исправить вручную. Для сохранения профиля нажмите «Сохранить профиль».', false);
    input.focus();
  }
  document.addEventListener('click', event => {
    if (event.target.closest('#experience-build')) compose();
    if (event.target.closest('#experience-insert')) insertText();
  });
  document.addEventListener('input', event => {
    if (parts.some(id => event.target.id === id)) {
      invalidatePreview();
      say('', false);
    }
  });
})();
