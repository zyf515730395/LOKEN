(() => {
  'use strict';
  const reader = document.querySelector('[data-periodical-reader]');
  if (!reader) return;
  const catalog = JSON.parse(document.getElementById('periodical-catalog').textContent);
  const select = reader.querySelector('[data-periodical-select]');
  const article = reader.querySelector('[data-periodical-article]');
  const toc = reader.querySelector('[data-periodical-toc]');
  const status = reader.querySelector('[data-periodical-status]');
  const calendar = reader.querySelector('[data-calendar-grid]');
  const dateInput = reader.querySelector('[data-period-date]');
  const datePanel = reader.querySelector('.periodical-date-panel');
  const calendarToggle = reader.querySelector('[data-calendar-toggle]');
  // Calendar arithmetic uses UTC date-only values so browser timezones cannot
  // move a publication into the previous day or change Monday-Sunday ranges.
  const dateValue = value => new Date(`${value}T00:00:00Z`);
  const dateKey = value => value.toISOString().slice(0, 10);
  const shiftDate = (value, days) => { const result = dateValue(value); result.setUTCDate(result.getUTCDate() + days); return dateKey(result); };
  const range = period => [period.date, reader.dataset.kind === 'weekly' ? shiftDate(period.date, 6) : period.date];
  const periodForDate = value => catalog.find(period => { const [start, end] = range(period); return value >= start && value <= end; });
  const chronological = [...catalog].sort((a, b) => a.date.localeCompare(b.date));
  let calendarMonth = (catalog[0]?.date || new Date().toISOString().slice(0, 10)).slice(0, 7);
  const setCalendarOpen = open => {
    datePanel.classList.toggle('calendar-open', open);
    calendarToggle.setAttribute('aria-expanded', String(open));
    calendarToggle.textContent = open ? '收起月历' : '展开月历';
  };
  const drawCalendar = (selected, resetMonth = false) => {
    const [start, end] = selected ? range(selected) : ['', ''];
    if (selected && resetMonth) calendarMonth = end.slice(0, 7);
    const first = dateValue(`${calendarMonth}-01`);
    const year = first.getUTCFullYear(), month = first.getUTCMonth();
    reader.querySelector('[data-calendar-month]').textContent = `${year} 年 ${month + 1} 月`;
    const monthStart = `${calendarMonth}-01`;
    const earliest = chronological[0]?.date || monthStart;
    const latest = chronological.length ? range(chronological.at(-1))[1] : monthStart;
    reader.querySelector('[data-month-prev]').disabled = calendarMonth <= earliest.slice(0, 7);
    reader.querySelector('[data-month-next]').disabled = calendarMonth >= latest.slice(0, 7);
    const fragment = document.createDocumentFragment();
    for (let i = 0; i < (first.getUTCDay() + 6) % 7; i++) {
      const gap = document.createElement('span'); gap.className = 'periodical-calendar-gap'; gap.setAttribute('aria-hidden', 'true'); fragment.append(gap);
    }
    const days = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
    for (let day = 1; day <= days; day++) {
      const key = `${calendarMonth}-${String(day).padStart(2, '0')}`;
      const period = periodForDate(key);
      const button = document.createElement('button');
      button.type = 'button'; button.textContent = day; button.dataset.calendarDay = key;
      button.disabled = !period; button.setAttribute('aria-label', `${key}${period ? ' · 查看期刊' : ' · 暂无期刊'}`);
      button.setAttribute('aria-pressed', String(key === end));
      button.classList.toggle('is-in-range', !!selected && key >= start && key <= end);
      fragment.append(button);
    }
    calendar.replaceChildren(fragment);
    const index = selected ? chronological.findIndex(period => period.id === selected.id) : -1;
    reader.querySelector('[data-period-prev]').disabled = index <= 0;
    reader.querySelector('[data-period-next]').disabled = index < 0 || index >= chronological.length - 1;
    dateInput.min = earliest; dateInput.max = latest; dateInput.value = end;
    reader.querySelector('[data-period-day]').textContent = end ? end.slice(-2) : '—';
    reader.querySelector('[data-period-stamp]').textContent = end ? `${end.slice(0, 4)} / ${end.slice(5, 7)}\n${reader.dataset.kind === 'weekly' ? '周一至周日' : '发布日'}` : '暂无期刊';
  };
  let request = 0;
  let observer;
  const watchSections = () => {
    if (observer) observer.disconnect();
    if (!('IntersectionObserver' in window)) return;
    observer = new IntersectionObserver(entries => {
      const visible = entries.filter(entry => entry.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
      if (!visible) return;
      toc.querySelectorAll('a').forEach(link => {
        if (link.hash === `#${visible.target.id}`) link.setAttribute('aria-current', 'location');
        else link.removeAttribute('aria-current');
      });
    }, {root: article, rootMargin: '0px 0px -65% 0px'});
    article.querySelectorAll('.periodical-section').forEach(section => observer.observe(section));
  };
  const choose = async (id, updateURL) => {
    const period = catalog.find(item => item.id === id);
    if (!period) return;
    const revision = ++request;
    status.textContent = '正在加载本期内容…';
    try {
      let sections = period.sections || [];
      if (period.metadata && period.metadata.data_url && !period.loaded) {
        const response = await fetch(period.metadata.data_url, {credentials: 'same-origin', cache: 'no-cache'});
        if (!response.ok) throw new Error('period unavailable');
        const data = await response.json();
        if (data.id !== period.id || !Array.isArray(data.sections)) throw new Error('period mismatch');
        period.sections = sections = data.sections;
        period.loaded = true;
      }
      if (revision !== request) return;
      const content = document.createDocumentFragment();
      const links = document.createDocumentFragment();
      sections.forEach(section => {
        const block = document.createElement('section');
        block.className = 'periodical-section';
        block.id = `periodical-${section.id}`;
        const heading = document.createElement('h2');
        heading.textContent = section.label;
        block.append(heading);
        // Only generator-sanitized public HTML is included in the catalog.
        block.insertAdjacentHTML('beforeend', section.html);
        content.append(block);
        const link = document.createElement('a');
        link.href = `#${block.id}`;
        link.textContent = section.label;
        links.append(link);
      });
      if (!sections.length) {
        const empty = document.createElement('p');
        empty.className = 'periodical-empty';
        empty.textContent = (period.metadata || {}).empty_message || '暂无已发布内容。请稍后查看。';
        content.append(empty);
      }
      article.replaceChildren(content);
      toc.replaceChildren(links);
      reader.querySelector('[data-periodical-title]').textContent = period.title;
      reader.querySelector('[data-periodical-subtitle]').textContent = period.subtitle || '';
      reader.querySelector('[data-periodical-note]').textContent = (period.metadata || {}).note || '';
      article.dataset.periodId = period.id;
      article.scrollTo({top: 0, behavior: 'instant'});
      select.value = period.id;
      drawCalendar(period, true);
      setCalendarOpen(false);
      if (updateURL) {
        const url = new URL(location.href);
        url.searchParams.set('period', period.id);
        history.replaceState(null, '', url);
      }
      status.textContent = '';
      watchSections();
    } catch (_) {
      if (revision !== request) return;
      select.value = article.dataset.periodId;
      drawCalendar(catalog.find(item => item.id === article.dataset.periodId));
      status.textContent = '本期加载失败，请重新选择日期重试。';
    }
  };
  toc.addEventListener('click', event => {
    const link = event.target.closest('a');
    if (!link) return;
    const target = document.getElementById(link.hash.slice(1));
    if (!target || !article.contains(target)) return;
    event.preventDefault();
    const distance = target.getBoundingClientRect().top - article.getBoundingClientRect().top;
    const immediate = matchMedia('(prefers-reduced-motion: reduce)').matches || Math.abs(distance) > article.clientHeight * 2;
    article.scrollTo({top: article.scrollTop + distance, behavior: immediate ? 'instant' : 'smooth'});
    target.setAttribute('tabindex', '-1');
    target.focus({preventScroll: true});
  });
  select.addEventListener('change', () => choose(select.value, true));
  calendar.addEventListener('click', event => {
    const button = event.target.closest('[data-calendar-day]');
    const period = button && !button.disabled && periodForDate(button.dataset.calendarDay);
    if (period) choose(period.id, true);
  });
  dateInput.addEventListener('change', () => {
    const period = periodForDate(dateInput.value);
    if (period) choose(period.id, true);
    else {
      status.textContent = '该日期暂无期刊，请选择月历中带标记的日期。';
      const current = catalog.find(item => item.id === article.dataset.periodId);
      dateInput.value = current ? range(current)[1] : '';
    }
  });
  for (const [name, step] of [['prev', -1], ['next', 1]]) {
    reader.querySelector(`[data-month-${name}]`).addEventListener('click', () => {
      const date = dateValue(`${calendarMonth}-01`); date.setUTCMonth(date.getUTCMonth() + step);
      calendarMonth = dateKey(date).slice(0, 7);
      drawCalendar(catalog.find(item => item.id === article.dataset.periodId));
    });
    reader.querySelector(`[data-period-${name}]`).addEventListener('click', () => {
      const index = chronological.findIndex(item => item.id === article.dataset.periodId);
      const period = chronological[index + step];
      if (period) choose(period.id, true);
    });
  }
  calendarToggle.addEventListener('click', () => setCalendarOpen(calendarToggle.getAttribute('aria-expanded') !== 'true'));
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && datePanel.classList.contains('calendar-open')) { setCalendarOpen(false); calendarToggle.focus(); }
  });
  document.addEventListener('click', event => { if (!datePanel.contains(event.target)) setCalendarOpen(false); });
  drawCalendar(catalog.find(item => item.id === article.dataset.periodId), true);
  watchSections();
  const requested = new URL(location.href).searchParams.get('period');
  if (requested && requested !== article.dataset.periodId) choose(requested, false);
})();
