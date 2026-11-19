/* Journal reading preference — same key as the main STAZHNO homepage. */
'use strict';
document.addEventListener('DOMContentLoaded', () => {
  const button = document.getElementById('reading-mode-toggle');
  if (!button) return;
  const key = 'stazhno-large-text';
  const read = () => { try { return localStorage.getItem(key) === 'yes'; } catch { return false; } };
  const apply = enabled => {
    document.body.classList.toggle('comfortable-view', enabled);
    button.setAttribute('aria-pressed', String(enabled));
    button.setAttribute('aria-label', enabled ? 'Выключить крупный текст' : 'Включить крупный текст');
    button.title = enabled ? 'Обычный текст' : 'Крупный текст';
    try { localStorage.setItem(key, enabled ? 'yes' : 'no'); } catch { /* restricted storage */ }
  };
  apply(read());
  button.addEventListener('click', () => apply(!document.body.classList.contains('comfortable-view')));
});
