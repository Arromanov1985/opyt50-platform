(() => {
  'use strict';

  let taxonomyPromise = null;
  let sequence = 0;
  const mounted = new WeakSet();

  function norm(value) {
    return String(value || '')
      .toLocaleLowerCase('ru-RU')
      .replace(/ё/g, 'е')
      .replace(/[^\p{L}\p{N}+#-]+/gu, ' ')
      .replace(/\s+/g, ' ')
      .trim();
  }

  async function loadTaxonomy() {
    if (!taxonomyPromise) {
      taxonomyPromise = fetch('/api/taxonomy', {
        credentials: 'same-origin',
        headers: {'Accept': 'application/json'}
      }).then(response => {
        if (!response.ok) throw new Error('Не удалось загрузить справочник');
        return response.json();
      }).catch(error => {
        taxonomyPromise = null;
        throw error;
      });
    }
    return taxonomyPromise;
  }

  function searchScore(query, values) {
    if (!query) return 20;
    let best = 999;
    for (const raw of values) {
      const value = norm(raw);
      if (value === query) best = Math.min(best, 0);
      else if (value.startsWith(query)) best = Math.min(best, 1);
      else if (value.split(' ').some(word => word.startsWith(query))) best = Math.min(best, 2);
      else if (value.includes(query)) best = Math.min(best, 3);
    }
    return best;
  }

  function rankProfession(items, query) {
    return items
      .map(item => ({item, score: searchScore(query, [item.value, item.family])}))
      .filter(row => row.score < 999)
      .sort((a, b) => a.score - b.score || a.item.value.localeCompare(b.item.value, 'ru'))
      .slice(0, 8)
      .map(row => row.item);
  }

  function rankSkills(items, query) {
    return items
      .map(item => ({item, score: searchScore(query, [item.value, ...(item.aliases || [])])}))
      .filter(row => row.score < 999)
      .sort((a, b) => a.score - b.score || a.item.value.localeCompare(b.item.value, 'ru'))
      .slice(0, 8)
      .map(row => row.item);
  }

  function currentSkillQuery(input) {
    const value = input.value || '';
    const cursor = typeof input.selectionStart === 'number' ? input.selectionStart : value.length;
    const before = value.slice(0, cursor);
    const separator = Math.max(before.lastIndexOf(','), before.lastIndexOf(';'));
    return norm(before.slice(separator + 1));
  }

  function replaceCurrentSkill(input, value) {
    const source = input.value || '';
    const cursor = typeof input.selectionStart === 'number' ? input.selectionStart : source.length;
    const before = source.slice(0, cursor);
    const after = source.slice(cursor);
    const separator = Math.max(before.lastIndexOf(','), before.lastIndexOf(';'));
    const head = separator >= 0 ? before.slice(0, separator + 1) + ' ' : '';
    const next = head + value + after;
    input.value = next.replace(/\s+,/g, ',');
    const caret = (head + value).length;
    input.setSelectionRange(caret, caret);
    input.dispatchEvent(new Event('input', {bubbles: true}));
    input.dispatchEvent(new Event('change', {bubbles: true}));
  }

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, char => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    })[char]);
  }

  function setContext(input, kind, data) {
    const context = input.parentElement?.querySelector('.taxonomy-context');
    if (!context) return;

    if (kind === 'profession') {
      const current = norm(input.value);
      const found = data.professions.find(item => norm(item.value) === current);
      if (found?.family) {
        context.innerHTML = '<span>✓</span> Подбор понимает эту профессию как: <strong>' +
          escapeHtml(found.family) + '</strong>';
        context.classList.add('is-visible');
      } else {
        context.textContent = '';
        context.classList.remove('is-visible');
      }
      return;
    }

    const tokens = String(input.value || '')
      .split(/[,;]+/)
      .map(part => norm(part))
      .filter(Boolean);
    const recognized = [];
    for (const token of tokens) {
      const item = data.skills.find(skill =>
        norm(skill.value) === token ||
        (skill.aliases || []).some(alias => norm(alias) === token)
      );
      if (item && !recognized.includes(item.value)) recognized.push(item.value);
    }
    if (recognized.length) {
      context.innerHTML = '<span>✓</span> Справочник распознал: <strong>' +
        recognized.map(escapeHtml).join(' · ') + '</strong>';
      context.classList.add('is-visible');
    } else {
      context.textContent = '';
      context.classList.remove('is-visible');
    }
  }

  function mount(input, kind, data) {
    if (!input || mounted.has(input)) return;
    mounted.add(input);
    input.dataset.taxonomyReady = '1';

    const field = input.closest('.field') || input.parentElement;
    if (!field) return;
    field.classList.add('taxonomy-field');

    const id = 'taxonomy-list-' + (++sequence);
    const list = document.createElement('div');
    list.className = 'taxonomy-suggestions hidden';
    list.id = id;
    list.setAttribute('role', 'listbox');

    const context = document.createElement('div');
    context.className = 'taxonomy-context';
    context.setAttribute('aria-live', 'polite');

    input.setAttribute('role', 'combobox');
    input.setAttribute('aria-autocomplete', 'list');
    input.setAttribute('aria-controls', id);
    input.setAttribute('aria-expanded', 'false');

    field.append(list, context);

    let results = [];
    let active = -1;

    function close() {
      list.classList.add('hidden');
      list.innerHTML = '';
      results = [];
      active = -1;
      input.setAttribute('aria-expanded', 'false');
      input.removeAttribute('aria-activedescendant');
    }

    function paintActive() {
      list.querySelectorAll('[role="option"]').forEach((node, index) => {
        const selected = index === active;
        node.classList.toggle('is-active', selected);
        node.setAttribute('aria-selected', selected ? 'true' : 'false');
        if (selected) input.setAttribute('aria-activedescendant', node.id);
      });
    }

    function select(item) {
      if (kind === 'profession') {
        input.value = item.value;
        input.setSelectionRange(input.value.length, input.value.length);
        input.dispatchEvent(new Event('input', {bubbles: true}));
        input.dispatchEvent(new Event('change', {bubbles: true}));
      } else {
        replaceCurrentSkill(input, item.value);
      }
      setContext(input, kind, data);
      close();
      input.focus();
    }

    function render() {
      const query = kind === 'profession' ? norm(input.value) : currentSkillQuery(input);
      if (kind === 'profession' && query.length === 1) return close();

      results = kind === 'profession'
        ? rankProfession(data.professions || [], query)
        : rankSkills(data.skills || [], query);

      if (!results.length) return close();
      active = -1;
      list.innerHTML = results.map((item, index) => {
        const meta = kind === 'profession'
          ? (item.family ? '<small>' + escapeHtml(item.family) + '</small>' : '<small>Профессия</small>')
          : '<small>' + escapeHtml((item.aliases || []).filter(alias => norm(alias) !== norm(item.value)).slice(0, 3).join(' · ') || 'Навык') + '</small>';
        return '<button type="button" class="taxonomy-option" role="option" aria-selected="false" id="' +
          id + '-option-' + index + '" data-index="' + index + '"><strong>' +
          escapeHtml(item.value) + '</strong>' + meta + '</button>';
      }).join('');
      list.classList.remove('hidden');
      input.setAttribute('aria-expanded', 'true');
    }

    input.addEventListener('input', () => {
      setContext(input, kind, data);
      render();
    });
    input.addEventListener('focus', render);
    input.addEventListener('blur', () => window.setTimeout(close, 120));
    input.addEventListener('keydown', event => {
      if (list.classList.contains('hidden')) {
        if (event.key === 'ArrowDown') {
          render();
          if (results.length) {
            active = 0;
            paintActive();
            event.preventDefault();
          }
        }
        return;
      }
      if (event.key === 'ArrowDown') {
        active = Math.min(results.length - 1, active + 1);
        paintActive();
        event.preventDefault();
      } else if (event.key === 'ArrowUp') {
        active = Math.max(0, active - 1);
        paintActive();
        event.preventDefault();
      } else if (event.key === 'Enter' && active >= 0) {
        select(results[active]);
        event.preventDefault();
      } else if (event.key === 'Escape') {
        close();
        event.preventDefault();
      }
    });
    list.addEventListener('pointerdown', event => {
      const option = event.target.closest('[data-index]');
      if (!option) return;
      event.preventDefault();
      const item = results[Number(option.dataset.index)];
      if (item) select(item);
    });

    setContext(input, kind, data);
  }

  function scan(data) {
    mount(document.querySelector('#profile-profession'), 'profession', data);
    mount(document.querySelector('#vacancy-title'), 'profession', data);
    mount(document.querySelector('#profile-skills'), 'skills', data);
    mount(document.querySelector('#vacancy-skills'), 'skills', data);
  }

  async function boot() {
    try {
      const data = await loadTaxonomy();
      scan(data);
      const observer = new MutationObserver(() => scan(data));
      observer.observe(document.body, {childList: true, subtree: true});
    } catch (error) {
      console.warn('Taxonomy suggestions unavailable:', error);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot, {once: true});
  } else {
    boot();
  }
})();