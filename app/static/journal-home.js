/* Show live, administrator-published Journal content on the homepage. */
document.addEventListener('DOMContentLoaded', async () => {
  const grid = document.getElementById('journal-home-highlights');
  if (!grid) return;
  try {
    const response = await fetch('/api/public/journal/highlights', {credentials:'same-origin',cache:'no-store'});
    if (!response.ok) return;
    const payload = await response.json();
    if (!payload || !Array.isArray(payload.articles) || !payload.articles.length) return;
    const cards = [];
    for (const article of payload.articles.slice(0,4)) {
      if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(article.slug)) continue;
      const card = document.createElement('a');
      card.className = 'jr-preview-card';
      card.href = '/journal/' + article.slug;
      const category = document.createElement('span');category.textContent = article.category;
      const title = document.createElement('strong');title.textContent = article.title;
      const cue = document.createElement('small');cue.textContent = 'Читать материал →';
      card.append(category,title,cue);
      cards.push(card);
    }
    if (cards.length) grid.replaceChildren(...cards);
  } catch {
    // Preserve static navigation to existing Journal guides if offline.
  }
});