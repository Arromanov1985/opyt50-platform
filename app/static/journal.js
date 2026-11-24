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
    : path.startsWith('/journal/paths/') ? 'path:' + path.slice('/journal/paths/'.length)
    : path === '/journal/paths' ? ''
    : path.startsWith('/journal/') ? path.slice('/journal/'.length)
    : /^\/vacancies\/[1-9][0-9]*$/.test(path) ? 'vacancy:' + path.slice('/vacancies/'.length)
    : /^\/(?:companies|employers)\/[1-9][0-9]*$/.test(path)
      ? 'company:' + path.split('/').pop()
      : '';
  if (!source || source.length > 90 ||
      !/^(?:(?:path|vacancy|company):)?[a-z0-9]+(?:-[a-z0-9]+)*$/.test(source)) return;
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
      if (['jobs_click','profile_click','community_click','company_click','vacancy_click','apply_click'].includes(action)) {
        sendGrowthEvent(action);
      }
    });
  });
});


// Local-only discovery for the public Journal: no searches, filters, or
// visitor identities are sent to the server or written to browser storage.
document.addEventListener('DOMContentLoaded', () => {
  const search = document.getElementById('jr-article-search');
  const grid = document.getElementById('jr-article-grid');
  if (!search || !grid) return;
  const cards = Array.from(grid.querySelectorAll('.jr-card'));
  const filters = Array.from(document.querySelectorAll('[data-jr-category-filter]'));
  const count = document.getElementById('jr-results-count');
  const empty = document.getElementById('jr-no-results');
  let activeCategory = 'all';
  const normalize = text => String(text || '').trim().toLocaleLowerCase('ru-RU');
  function update() {
    const query = normalize(search.value);
    let found = 0;
    for (const card of cards) {
      const categoryMatch = activeCategory === 'all'
        || card.dataset.jrCategory === activeCategory;
      const textMatch = !query || normalize(card.textContent).includes(query);
      card.hidden = !(categoryMatch && textMatch);
      if (!card.hidden) found++;
    }
    if (count) count.textContent = `Показано: ${found} из ${cards.length}`;
    if (empty) empty.hidden = found > 0;
    for (const button of filters) {
      button.setAttribute('aria-pressed', String(button.dataset.jrCategoryFilter === activeCategory));
    }
  }
  search.addEventListener('input', update);
  for (const button of filters) {
    button.addEventListener('click', () => {
      activeCategory = button.dataset.jrCategoryFilter;
      update();
    });
  }
  document.getElementById('jr-reset-search')?.addEventListener('click', () => {
    search.value = '';
    activeCategory = 'all';
    update();
    search.focus();
  });
  update();
});
