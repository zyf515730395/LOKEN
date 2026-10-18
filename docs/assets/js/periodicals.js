(() => {
  'use strict';
  const reader = document.querySelector('[data-periodical-reader]');
  if (!reader) return;
  const catalog = JSON.parse(document.getElementById('periodical-catalog').textContent);
  const select = reader.querySelector('[data-periodical-select]');
  const article = reader.querySelector('[data-periodical-article]');
  const toc = reader.querySelector('[data-periodical-toc]');
  const status = reader.querySelector('[data-periodical-status]');
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
        const response = await fetch(period.metadata.data_url, {credentials: 'same-origin'});
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
        empty.textContent = '暂无已发布内容。请稍后查看。';
        content.append(empty);
      }
      article.replaceChildren(content);
      toc.replaceChildren(links);
      reader.querySelector('[data-periodical-title]').textContent = period.title;
      reader.querySelector('[data-periodical-subtitle]').textContent = period.subtitle || '';
      reader.querySelector('[data-periodical-note]').textContent = (period.metadata || {}).note || '';
      article.dataset.periodId = period.id;
      article.scrollTop = 0;
      select.value = period.id;
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
      status.textContent = '本期加载失败，请重新选择日期重试。';
    }
  };
  toc.addEventListener('click', event => {
    const link = event.target.closest('a');
    if (!link) return;
    const target = document.getElementById(link.hash.slice(1));
    if (!target || !article.contains(target)) return;
    event.preventDefault();
    article.scrollTo({top: target.offsetTop - article.offsetTop, behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'});
    target.setAttribute('tabindex', '-1');
    target.focus({preventScroll: true});
  });
  select.addEventListener('change', () => choose(select.value, true));
  watchSections();
  const requested = new URL(location.href).searchParams.get('period');
  if (requested && requested !== article.dataset.periodId) choose(requested, false);
})();
