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
