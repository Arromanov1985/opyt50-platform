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
 
// First-party aggregate counters only. No visitor ID, IP, cookies, local
// storage, query strings, UTM parameters or referrers are included in events.
// A blocked request must never stop reading or following an ordinary link.
document.addEventListener('DOMContentLoaded', () => {
  const path = window.location.pathname.endsWith('/')
    ? window.location.pathname.slice(0, -1) : window.location.pathname;
  const source = path === '/journal'
    ? 'journal'
    : path.startsWith('/journal/') ? path.slice('/journal/'.length) : '';
  if (!source || !/^[a-z0-9-]{1,80}$/.test(source)) return;
  function sendGrowthEvent(action) {
    try {
      fetch('/api/growth/event', {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'X-Requested-With': 'OPYT50'},
        credentials: 'omit',
        referrerPolicy: 'no-referrer',
        cache: 'no-store',
        keepalive: true,
        body: JSON.stringify({source, action})
      }).catch(() => {});
    } catch { /* always leave navigation usable */ }
  }
  sendGrowthEvent('view');
  document.querySelectorAll('a[data-growth-action]').forEach(link => {
    link.addEventListener('click', () => {
      const action = link.getAttribute('data-growth-action');
      if (action === 'jobs_click' || action === 'profile_click') {
        sendGrowthEvent(action);
      }
    });
  });
});
