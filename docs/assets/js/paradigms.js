(() => {
  'use strict';
  const payload = document.getElementById('paradigm-catalog');
  if (!payload) return;
  const data = JSON.parse(payload.textContent);
  const $ = s => document.querySelector(s);
  const e = v => String(v).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const routes = new Map(data.routes.map(r => [r.id, r]));
  const choices = new Set(['follow', 'watch', 'skip']);
  const key = 'loken.paradigms.follow.v1';
  let saved = {}, shown = 12, related = '', topic = data.topics[0].id;
  const feedback = text => { $('[data-paradigm-feedback]').textContent = text; };
  const clean = value => {
    if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('format');
    return Object.fromEntries(Object.entries(value).filter(([id, state]) => /^[a-f0-9]{20}$/.test(id) && choices.has(state)));
  };
  try { saved = clean(JSON.parse(localStorage.getItem(key) || '{}')); }
  catch (_) { feedback('已保存的安排暂时无法读取；仍可正常浏览，新的安排可导出备份。'); }
  function persist() {
    try { localStorage.setItem(key, JSON.stringify(saved)); feedback('调研安排已保存在当前浏览器。'); }
    catch (_) { feedback('浏览器未允许保存，当前安排仅在本页有效，请导出备份。'); }
  }
  const follow = id => `<label class="paradigm-follow">调研安排<select data-follow-id="${e(id)}" aria-label="调研安排"><option value="">未筛选</option><option value="follow">准备调研</option><option value="watch">继续观察</option><option value="skip">暂不跟进</option></select></label>`;
  const refs = ids => `<ul class="paradigm-refs">${ids.filter(id => data.papers[id]).map(id => `<li><a href="${e(data.papers[id].url)}">${e(data.papers[id].title)}</a> <small>${e(id)}</small></li>`).join('')}</ul>`;
  function common(item, text) {
    const dimension = $('#paradigm-dimension').value;
    const query = $('#paradigm-query').value.trim().toLocaleLowerCase();
    const arrangement = $('#paradigm-follow-filter').value;
    return item.topic === topic && (!dimension || item.dimension === dimension)
      && (!query || text.toLocaleLowerCase().includes(query))
      && (arrangement === 'all' || (saved[item.id] || '') === arrangement);
  }
  function clueHTML(c) {
    return `<article class="paradigm-clue" id="clue-${e(c.id)}"><small>${e(c.week)} 所在周 · 待研判</small><h3>${e(c.claim)}</h3><details><summary>机制比较与支撑论文</summary><p>${e(c.reasoning)}</p><p>边界：${e(c.limitations)}</p>${refs(c.paper_ids)}</details>${follow(c.id)}</article>`;
  }
  function syncSelects() {
    document.querySelectorAll('[data-follow-id]').forEach(s => { s.value = saved[s.dataset.followId] || ''; });
  }
  function update() {
    const status = $('#paradigm-status').value;
    document.querySelectorAll('[data-topic-panel]').forEach(p => { p.hidden = p.dataset.topicPanel !== topic; });
    document.querySelectorAll('[data-topic-link]').forEach(a => {
      if (a.dataset.topicLink === topic) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
    });
    document.querySelectorAll('[data-section-jump]').forEach(a => { a.href = `#${a.dataset.sectionJump}-${topic}`; });
    let count = 0;
    document.querySelectorAll('[data-route-id]').forEach(row => {
      const r = routes.get(row.dataset.routeId);
      const text = [r.name, r.mechanism, r.previous, r.limitations, ...r.sources.map(s => s.title), ...r.events.flatMap(ev => ev.paper_ids.map(id => data.papers[id]?.title || ''))].join(' ');
      const visible = common(r, text) && (!status || r.status === status || r.activity === status);
      row.hidden = !visible;
      count += Number(visible);
    });
    document.querySelectorAll('[data-topic-route-count]').forEach(el => { if (el.dataset.topicRouteCount === topic) el.textContent = `${count} 条`; });
    document.querySelectorAll('[data-topic-empty]').forEach(el => { el.hidden = el.dataset.topicEmpty !== topic || count > 0; });
    const filtered = data.clues.filter(c => (!related || c.matches.includes(related)) && (!status || status === 'clue')
      && common(c, [c.claim, c.reasoning, c.limitations, ...c.paper_ids.map(id => data.papers[id]?.title || '')].join(' ')));
    $('[data-clue-count]').textContent = `${filtered.length} 条`;
    $('[data-clues]').innerHTML = filtered.slice(0, shown).map(clueHTML).join('') || '<p class="periodical-note">当前主题没有符合筛选条件的历史线索。</p>';
    $('[data-more-clues]').hidden = shown >= filtered.length;
    $('[data-related-label]').hidden = !related;
    $('[data-related-label]').textContent = related ? `当前关联：${routes.get(related)?.name || ''}。重置筛选可恢复本主题全部线索。` : '';
    if (status === 'clue' || related) $('#paradigm-clues').open = true;
    syncSelects();
  }
  function readHash(scroll) {
    let id;
    try { id = decodeURIComponent(location.hash.slice(1)); } catch (_) { return; }
    let chosen = id ? data.topics.find(t => ['topic-', 'roadmap-', 'directions-', 'clues-'].some(prefix => id === prefix + t.id))?.id : data.topics[0].id;
    if (id === 'paradigm-clues') chosen = data.topics[0].id;
    const route = id.startsWith('route-') ? routes.get(id.slice(6)) : null;
    const clue = id.startsWith('clue-') ? data.clues.find(c => c.id === id.slice(5)) : null;
    chosen = chosen || route?.topic || clue?.topic;
    if (chosen) {
      topic = chosen; related = ''; shown = 12;
      if (route || clue) $('.paradigm-filters').reset();
      if (clue) { shown = data.clues.length; $('#paradigm-clues').open = true; }
    }
    if (id === 'paradigm-clues' || id.startsWith('clues-')) $('#paradigm-clues').open = true;
    update();
    const targetId = id.startsWith('clues-') ? 'paradigm-clues'
      : id === 'paradigm-latest' ? `directions-${topic}`
      : id === 'paradigm-atlas' ? `roadmap-${topic}` : id;
    if (scroll && targetId) {
      const target = document.getElementById(targetId);
      target?.scrollIntoView({block:'start'});
      const heading = target?.querySelector('h2, h3') || target;
      if (heading) { heading.tabIndex = -1; heading.focus({preventScroll:true}); }
    }
  }
  $('.paradigm-filters').addEventListener('input', () => { shown = 12; related = ''; update(); });
  $('.paradigm-filters').addEventListener('reset', () => { related = ''; shown = 12; setTimeout(update, 0); });
  $('[data-more-clues]').addEventListener('click', () => { shown += 12; update(); });
  window.addEventListener('hashchange', () => readHash(true));
  document.addEventListener('change', event => {
    const select = event.target.closest('[data-follow-id]');
    if (!select) return;
    if (choices.has(select.value)) saved[select.dataset.followId] = select.value; else delete saved[select.dataset.followId];
    persist(); syncSelects(); if ($('#paradigm-follow-filter').value !== 'all') update();
  });
  document.querySelectorAll('[data-related-route]').forEach(b => b.addEventListener('click', () => {
    $('.paradigm-filters').reset(); related = b.dataset.relatedRoute; topic = routes.get(related).topic; shown = 12;
    update(); $('#paradigm-clues').scrollIntoView({behavior:'smooth', block:'start'});
  }));
  $('[data-export-follow]').addEventListener('click', () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify({schema_version:1, choices:saved}, null, 2)], {type:'application/json'}));
    const a = document.createElement('a'); a.href = url; a.download = 'loken-paradigm-follow-up.json'; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000); feedback('已导出调研安排。');
  });
  $('[data-import-follow]').addEventListener('change', async event => {
    const file = event.target.files[0]; if (!file) return;
    try {
      if (file.size > 1024 * 1024) throw new Error('size');
      const value = JSON.parse(await file.text()); if (value.schema_version !== 1) throw new Error('version');
      saved = {...saved, ...clean(value.choices)}; persist(); update();
    } catch (_) { feedback('无法导入，请选择本页导出的调研安排 JSON 文件（不超过 1 MB）。'); }
    event.target.value = '';
  });
  readHash(true);
})();
