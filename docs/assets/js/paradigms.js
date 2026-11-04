(() => {
  'use strict';
  const payload = document.getElementById('paradigm-catalog');
  if (!payload) return;
  const data = JSON.parse(payload.textContent);
  const $ = selector => document.querySelector(selector);
  const e = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const topics = Object.fromEntries(data.topics.map(t => [t.id, t.name]));
  const routes = new Map(data.routes.map(r => [r.id, r]));
  const key = 'loken.paradigms.follow.v1';
  const choices = new Set(['follow', 'watch', 'skip']);
  let saved = {}, shown = 12, related = '';
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
  function followMatches(id) {
    const filter = $('#paradigm-follow-filter').value;
    return filter === 'all' || (saved[id] || '') === filter;
  }
  function common(item, text) {
    const topic = $('#paradigm-topic').value;
    const dimension = $('#paradigm-dimension').value;
    const query = $('#paradigm-query').value.trim().toLocaleLowerCase();
    return (!topic || item.topic === topic) && (!dimension || item.dimension === dimension)
      && (!query || text.toLocaleLowerCase().includes(query)) && followMatches(item.id);
  }
  function clueHTML(c) {
    return `<article class="paradigm-clue" id="clue-${e(c.id)}"><div class="paradigm-meta">${e(topics[c.topic])} · ${e(c.week)} 所在周 · 历史线索 / 待研判</div><h3>${e(c.claim)}</h3><details><summary>阅读机制比较与支撑论文</summary><p>${e(c.reasoning)}</p><p class="paradigm-muted">边界：${e(c.limitations)}</p>${refs(c.paper_ids)}</details>${follow(c.id)}</article>`;
  }
  function syncSelects() {
    document.querySelectorAll('[data-follow-id]').forEach(select => { select.value = saved[select.dataset.followId] || ''; });
  }
  function update() {
    const status = $('#paradigm-status').value;
    let count = 0;
    document.querySelectorAll('[data-route-id]').forEach(card => {
      const route = routes.get(card.dataset.routeId);
      const text = [route.name, route.mechanism, route.previous, route.limitations, ...route.events.flatMap(ev => ev.paper_ids.map(id => data.papers[id]?.title || ''))].join(' ');
      const visible = common(route, text) && (!status || route.status === status || route.activity === status);
      card.hidden = !visible;
      count += Number(visible);
    });
    $('[data-route-count]').textContent = `${count} 条`;
    $('[data-route-empty]').hidden = count > 0;
    const filtered = data.clues.filter(c => (!related || c.matches.includes(related)) && (!status || status === 'clue')
      && common(c, [c.claim, c.reasoning, c.limitations, ...c.paper_ids.map(id => data.papers[id]?.title || '')].join(' ')));
    $('[data-clue-count]').textContent = `${filtered.length} 条`;
    $('[data-clues]').innerHTML = filtered.slice(0, shown).map(clueHTML).join('') || '<p class="paradigm-muted">没有符合条件的历史线索。可重置筛选查看全部。</p>';
    $('[data-more-clues]').hidden = shown >= filtered.length;
    $('[data-related-label]').hidden = !related;
    $('[data-related-label]').textContent = related ? `当前关联：${routes.get(related)?.name || ''}。点击“重置”恢复全部线索。` : '';
    const events = data.routes.flatMap(r => r.events.map(ev => ({route:r,event:ev})))
      .filter(({route:r,event:ev}) => common({...r, dimension:ev.dimension}, [r.name, ev.previous, ev.mechanism, ev.limitations, ...ev.paper_ids.map(id => data.papers[id]?.title || '')].join(' ')) && (!status || r.status === status || r.activity === status))
      .sort((a,b) => b.event.week.localeCompare(a.event.week));
    $('[data-latest-events]').innerHTML = events.slice(0, 8).map(({route:r,event:ev}) => `<article class="paradigm-clue"><div class="paradigm-meta">${e(topics[r.topic])} · ${e(ev.week)} 所在周 · ${e(r.dimension)} · ${ev.origin === 'historical_review' ? '历史周报复核' : '每周机制观察'}</div><h3><a href="#route-${e(r.id)}">${e(r.name)}</a></h3><p>${e(ev.previous)} → ${e(ev.mechanism)}</p><details><summary>支撑论文与边界</summary><p>${e(ev.limitations)}</p>${refs(ev.paper_ids)}</details></article>`).join('')
      || '<p class="paradigm-muted">当前筛选下尚无结构化变化记录。历史分析不会自动冒充新范式；可在下方历史线索中筛选调研方向，新一期周报识别的机制会自动进入这里。</p>';
    syncSelects();
  }
  $('.paradigm-filters').addEventListener('input', () => { shown = 12; related = ''; update(); });
  $('.paradigm-filters').addEventListener('reset', () => { related = ''; shown = 12; setTimeout(update, 0); });
  $('[data-more-clues]').addEventListener('click', () => { shown += 12; update(); });
  document.addEventListener('change', event => {
    const select = event.target.closest('[data-follow-id]');
    if (!select) return;
    const id = select.dataset.followId;
    if (choices.has(select.value)) saved[id] = select.value; else delete saved[id];
    persist(); syncSelects();
    if ($('#paradigm-follow-filter').value !== 'all') update();
  });
  document.querySelectorAll('[data-related-route]').forEach(button => button.addEventListener('click', () => {
    $('.paradigm-filters').reset();
    // The form reset schedules update; set association after the reset handler.
    related = button.dataset.relatedRoute; shown = 12;
    $('#paradigm-topic').value = routes.get(related).topic;
    update(); $('#paradigm-clues').scrollIntoView({behavior:'smooth', block:'start'});
  }));
  $('[data-export-follow]').addEventListener('click', () => {
    const blob = new Blob([JSON.stringify({schema_version:1, choices:saved}, null, 2)], {type:'application/json'});
    const url = URL.createObjectURL(blob), a = document.createElement('a');
    a.href = url; a.download = 'loken-paradigm-follow-up.json'; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000); feedback('已导出调研安排。');
  });
  $('[data-import-follow]').addEventListener('change', async event => {
    const file = event.target.files[0]; if (!file) return;
    try {
      if (file.size > 1024 * 1024) throw new Error('size');
      const value = JSON.parse(await file.text());
      if (value.schema_version !== 1) throw new Error('version');
      saved = {...saved, ...clean(value.choices)}; persist(); update();
    } catch (_) { feedback('无法导入，请选择本页导出的调研安排 JSON 文件（不超过 1 MB）。'); }
    event.target.value = '';
  });
  update();
})();
