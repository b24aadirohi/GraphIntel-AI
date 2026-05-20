'use strict';
const $ = (id) => document.getElementById(id);
const node = (tag, text, className) => {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
};
async function api(path, options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 45000);
  try {
    const headers = {...options.headers};
    const csrf = document.querySelector('meta[name="csrf-token"]')?.content;
    if (csrf) headers["X-CSRF-Token"] = csrf;
    const response = await fetch(`/api/${path}`, {...options, headers, signal: controller.signal});
    if (response.status === 401) { window.location.assign("/login"); throw new Error("Sign in to continue."); }
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'The platform could not complete this request. Try again.');
    return data;
  } catch (error) {
    if (error.name === 'AbortError') throw new Error('The platform took too long to respond. Try again.');
    if (error instanceof TypeError) throw new Error('Could not reach the dataset. Check your connection and try again.');
    throw error;
  } finally { clearTimeout(timer); }
}
function state(target, message, error = false) {
  target.replaceChildren(node('p', message, `state${error ? ' error' : ''}`));
}
function card(movie) {
  const article = node('article', undefined, 'movie-card');
  const poster = node('div', undefined, 'poster');
  poster.append(node('span', `FILM / ${movie.released || 'UNDATED'}`, 'poster-index'), node('h3', movie.title));
  const body = node('div', undefined, 'card-body');
  body.append(node('div', (movie.genres || []).join(' · '), 'metadata'), node('p', movie.summary || 'Open this film to explore its connections.', 'card-summary'));
  if (movie.explanation) body.append(node('p', movie.explanation, 'card-summary'));
  const button = node('button', 'Explore film ', 'card-open');
  button.type = 'button';
  button.append(node('span', '↗'));
  button.addEventListener('click', () => openMovie(movie.id));
  article.append(poster, body, button);
  return article;
}
let searchVersion = 0;
let nextCursor = null;
let activeQuery = "";
let shownMovies = 0;
async function search(append = false) {
  const version = ++searchVersion;
  if (!append) {
    state($('movies'), 'Searching the dataset…');
    activeQuery = $('search-input').value.trim();
    nextCursor = null; shownMovies = 0;
    $('movie-count').textContent = '';
    $('load-more').hidden = true;
  }
  $('load-more').disabled = true;
  try {
    const params = new URLSearchParams({q: activeQuery, limit: '24'});
    if (append && nextCursor) params.set('cursor', nextCursor);
    const data = await api(`movies?${params}`);
    if (version !== searchVersion) return;
    if (append) $('movies').append(...data.items.map(card));
    else $('movies').replaceChildren(...data.items.map(card));
    shownMovies += data.items.length;
    nextCursor = data.next_cursor || null;
    $('load-more').hidden = !nextCursor;
    $('movie-count').textContent = `${shownMovies} films shown`;
    if (!shownMovies) state($('movies'), 'No films matched. Try another title, person, or genre.');
  } catch (error) { if (version === searchVersion) {
    if (append) $('movie-count').textContent = error.message;
    else state($('movies'), error.message, true);
  } } finally { if (version === searchVersion) $('load-more').disabled = false; }
}
$('load-more').addEventListener('click', () => search(true));
$('search-form').addEventListener('submit', (event) => { event.preventDefault(); search(); });
let detailVersion = 0;
async function openMovie(id) {
  const version = ++detailVersion;
  const dialog = $('movie-dialog');
  if (!dialog.open) dialog.showModal();
  state($('movie-detail'), 'Opening film…');
  try {
    const movie = await api(`movies/${encodeURIComponent(id)}`);
    if (version !== detailVersion) return;
    const title = node('h2', movie.title, 'detail-title');
    title.id = 'detail-title';
    const credits = node('div', undefined, 'detail-credits');
    for (const [label, value] of [['Director', movie.directors], ['Cast', movie.cast]]) {
      const line = node('p');
      line.append(node('strong', `${label} / `), document.createTextNode((value || []).join(', ') || 'Not listed'));
      credits.append(line);
    }
    const recommendations = node('div', undefined, 'movie-grid');
    $('movie-detail').replaceChildren(title, node('p', `${movie.released || 'Undated'} · ${(movie.genres || []).join(' · ')}`, 'metadata'), node('p', movie.summary, 'detail-summary'), credits, node('h3', 'Follow this film to…'), recommendations);
    state(recommendations, 'Finding connected films…');
    try {
      const data = await api(`recommendations/${encodeURIComponent(id)}?limit=4`);
      if (version !== detailVersion) return;
      recommendations.replaceChildren(...data.items.map(card));
      if (!data.items.length) state(recommendations, 'No recommendations yet. Explore another film.');
    } catch (error) { state(recommendations, error.message, true); }
  } catch (error) { if (version === detailVersion) state($('movie-detail'), error.message, true); }
}
$('close-dialog').addEventListener('click', () => $('movie-dialog').close());
$('movie-dialog').addEventListener('click', (event) => { if (event.target === $('movie-dialog')) { const r = event.target.getBoundingClientRect(); if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) event.target.close(); } });
const svgNode = (tag, attrs = {}) => {
  const element = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [key, value] of Object.entries(attrs)) element.setAttribute(key, String(value));
  return element;
};
async function graph() {
  state($('graph'), 'Tracing the connections…');
  try {
    const data = await api('graph?limit=18');
    if (!data.nodes.length) { state($('graph'), 'The map is empty. Add films to the catalog to see their connections.'); return; }
    const positions = new Map();
    const groups = {movie: [], person: [], genre: []};
    for (const item of data.nodes) (groups[String(item.type).toLowerCase()] || groups.person).push(item);
    const height = Math.max(510, Math.max(...Object.values(groups).map((items) => items.length)) * 25 + 70);
    const svg = svgNode('svg', {viewBox: `0 0 900 ${height}`, role: 'group', 'aria-label': 'Film connection map; select film nodes for details'});
    for (const [type, items] of Object.entries(groups)) {
      items.forEach((item, index) => {
        const x = {movie: 450, person: 150, genre: 750}[type];
        const y = 35 + (index + 0.5) * (height - 70) / items.length;
        positions.set(String(item.id), {x, y, item, type});
      });
    }
    for (const link of data.links) {
      const a = positions.get(String(link.source)), b = positions.get(String(link.target));
      if (a && b) {
        const line = svgNode('line', {x1: a.x, y1: a.y, x2: b.x, y2: b.y});
        const title = svgNode('title'); title.textContent = link.type; line.append(title); svg.append(line);
      }
    }
    for (const {x, y, item, type} of positions.values()) {
      const group = svgNode(type === 'movie' ? 'a' : 'g', {class: type});
      if (type === 'movie') {
        group.setAttribute('href', '#catalog');
        group.setAttribute('aria-label', `Open ${item.label}`);
        group.addEventListener('click', (event) => { event.preventDefault(); openMovie(item.movie_id || String(item.id).replace(/^movie:/, '')); });
      }
      const title = svgNode('title'); title.textContent = `${item.label} (${type})`;
      const label = svgNode('text', {x: x + 12, y: y + 4});
      label.textContent = item.label.length > 23 ? `${item.label.slice(0, 22)}…` : item.label;
      group.append(title, svgNode('circle', {cx: x, cy: y, r: type === 'movie' ? 7 : 5}), label);
      svg.append(group);
    }
    $('graph').replaceChildren(svg);
    $('graph-selection').textContent = `${data.nodes.length} nodes · ${data.links.length} connections. Hover a label to read its full name.`;
  } catch (error) { state($('graph'), error.message, true); }
}
$('refresh-graph').addEventListener('click', graph);
$('chat-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const question = $('question').value.trim();
  if (!question || $('ask-button').disabled) return;
  const entry = node('article', undefined, 'chat-entry');
  entry.append(node('h3', question));
  const answer = node('p', 'Searching the dataset for evidence…');
  entry.append(answer); $('chat-log').append(entry);
  $('ask-button').disabled = true;
  try {
    const data = await api('chat', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({question})});
    const evidenceMode = /evidence|extractive/i.test(data.mode);
    entry.insertBefore(node('span', evidenceMode ? 'Evidence-only · retrieved excerpts, no LLM generation' : `Answer mode: ${data.mode}`, 'tag'), answer);
    answer.textContent = data.answer;
    const sources = node('div', undefined, 'sources');
    for (const source of (data.sources || [])) {
      const button = node('button', `[${source.id}] ${source.title}`, 'secondary');
      button.title = source.summary || source.title;
      button.addEventListener('click', () => openMovie(source.id));
      sources.append(button);
    }
    entry.append(sources);
    $('question').value = '';
  } catch (error) { answer.textContent = error.message; answer.classList.add('error'); }
  finally { $('ask-button').disabled = false; entry.scrollIntoView({block: 'nearest'}); }
});
let analyticsVersion = 0;
async function analytics() {
  const version = ++analyticsVersion;
  const params = new URLSearchParams();
  for (const key of ['start', 'end']) if ($(key).value) params.set(key, $(key).value);
  if ($('start').value && $('end').value && $('start').value > $('end').value) { $('analytics-state').textContent = 'Start date must be on or before end date.'; return; }
  $('analytics-state').textContent = 'Loading activity…';
  $('export').href = `/api/analytics.csv?${params}`;
  try {
    const data = await api(`analytics?${params}`);
    if (version !== analyticsVersion) return;
    const labels = {search: 'Searches', recommendation: 'Recommendations', chat: 'Questions'};
    $('analytics-totals').replaceChildren(...Object.entries(labels).map(([key, label]) => { const item = node('span', label); item.prepend(node('strong', data.totals[key] || 0)); return item; }));
    if (!data.daily.length) { state($('chart'), 'No activity in this period. Search for films or ask the dataset to get started.'); }
    else {
      const maximum = Math.max(1, ...data.daily.flatMap((row) => Object.keys(labels).map((key) => row[key] || 0)));
      const table = node('table', undefined, 'chart-table');
      const caption = node('caption', 'Daily activity counts. Bars share the same scale.');
      const head = node('thead'); const headings = node('tr');
      for (const text of ['Date', ...Object.values(labels)]) { const th = node('th', text); th.scope = 'col'; headings.append(th); }
      head.append(headings); const body = node('tbody');
      for (const row of data.daily) {
        const tr = node('tr'); const day = node('th', row.date); day.scope = 'row'; tr.append(day);
        for (const key of Object.keys(labels)) {
          const td = node('td'); const bar = svgNode('svg', {viewBox: '0 0 70 8', class: 'bar', 'aria-hidden': 'true'});
          bar.append(svgNode('rect', {width: 70, height: 8, class: 'spark-background'}), svgNode('rect', {width: Math.max(0, (Number(row[key]) || 0) / maximum * 70), height: 8, class: 'spark-bar'}));
          td.append(bar, document.createTextNode(String(row[key] || 0))); tr.append(td);
        }
        body.append(tr);
      }
      table.append(caption, head, body); $('chart').replaceChildren(table);
    }
    $('analytics-state').textContent = 'Daily events in UTC. Both filter dates are included.';
  } catch (error) { if (version !== analyticsVersion) return; $('analytics-state').textContent = error.message; $('analytics-totals').replaceChildren(); state($('chart'), 'Activity could not be loaded. Apply dates to try again.', true); }
}
$('analytics-form')?.addEventListener('submit', (event) => { event.preventDefault(); analytics(); });
$('analytics-form')?.addEventListener('reset', () => setTimeout(analytics, 0));
async function stats() {
  try {
    const data = await api('stats');
    for (const key of ['movies', 'people', 'genres']) $(`stat-${key}`).textContent = Number(data[key] || 0).toLocaleString();
    $('service-status').textContent = 'Platform connected';
  } catch (error) { $('service-status').textContent = 'Platform unavailable · refresh to retry'; }
}
search(); stats(); graph(); if ($('activity')) analytics();
