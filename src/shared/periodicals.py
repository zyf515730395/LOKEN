"""Shared, independently scrolling reader for dated public periodicals.

Callers own the provenance and sanitization of each section's HTML. This module
escapes navigation labels and safely embeds the period catalog, never model data.
"""
from __future__ import annotations

import html
import json
from pathlib import Path
import re

from shared.site_shell import render_site_page, site_root_for


def render_periodical_page(
    *, output_file: Path, output_root: Path, active_section: str, title: str,
    kind: str, periods: list[dict], active_subtopic: str = '',
) -> str:
    """Render newest first; optional metadata.data_url lazily loads old sections."""
    identifiers: set[str] = set()
    for period in periods:
        key = period['id']
        if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', key) or key in identifiers:
            raise ValueError('Period IDs must be unique URL-safe strings')
        identifiers.add(key)
        section_ids: set[str] = set()
        for section in period.get('sections', []):
            section_id = section['id']
            if not re.fullmatch(r'[A-Za-z0-9_-]+', section_id) or section_id in section_ids:
                raise ValueError('Section IDs must be unique URL-safe strings')
            section_ids.add(section_id)
        data_url = period.get('metadata', {}).get('data_url')
        if data_url and (not isinstance(data_url, str) or not re.fullmatch(r'periods/[a-z0-9_-]+\.json', data_url)):
            raise ValueError('Period data URL must remain in the local periods directory')
    root = site_root_for(output_file, output_root)
    selected = periods[0] if periods else {}
    selected_id = str(selected.get('id', ''))
    options = ''.join(
        f'<option value="{html.escape(period["id"], quote=True)}">{html.escape(str(period.get("title", period["id"])))}</option>'
        for period in periods
    )
    sections = selected.get('sections', [])
    body = ''.join(
        f'<section class="periodical-section" id="periodical-{html.escape(section["id"], quote=True)}">'
        f'<h2>{html.escape(str(section["label"]))}</h2>{section["html"]}</section>'
        for section in sections
    ) or '<p class="periodical-empty">' + html.escape(selected.get('metadata', {}).get('empty_message', '暂无已发布内容。请稍后查看。')) + '</p>'
    toc = ''.join(
        f'<a href="#periodical-{html.escape(section["id"], quote=True)}">{html.escape(str(section["label"]))}</a>'
        for section in sections
    )
    payload = json.dumps(periods, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    note = selected.get('metadata', {}).get('note', '')
    main = f'''<section class="periodical-reader" data-periodical-reader data-kind="{html.escape(kind, quote=True)}">
  <header class="periodical-heading">
    <p class="periodical-kicker">{html.escape(kind.upper())} / LOKEN</p>
    <h1>{html.escape(title)}</h1>
    <h2 data-periodical-title>{html.escape(str(selected.get('title', title)))}</h2>
    <p data-periodical-subtitle>{html.escape(str(selected.get('subtitle', ''))) }</p>
    <p class="periodical-note" data-periodical-note>{html.escape(str(note))}</p>
  </header>
  <aside class="periodical-tools" aria-label="期刊工具">
    <section class="periodical-date-panel" aria-label="选择期刊日期">
      <p class="periodical-tool-label">{'本周回顾' if kind == 'weekly' else '本期归档'} / 选择日期</p>
      <div class="periodical-date-caption"><strong data-period-day>—</strong><span data-period-stamp></span></div>
      <button type="button" class="calendar-toggle" data-calendar-toggle aria-expanded="false" aria-controls="periodical-calendar">展开月历</button>
      <div class="periodical-calendar" id="periodical-calendar">
        <div class="periodical-month-nav"><button type="button" data-month-prev aria-label="上个月">‹</button><strong data-calendar-month aria-live="polite"></strong><button type="button" data-month-next aria-label="下个月">›</button></div>
        <div class="periodical-weekdays" aria-hidden="true"><span>一</span><span>二</span><span>三</span><span>四</span><span>五</span><span>六</span><span>日</span></div>
        <div class="periodical-calendar-grid" data-calendar-grid aria-label="选择有期刊的日期"></div>
        <p class="periodical-calendar-hint">{'点击日期查看所在周，高亮为周一至周日。' if kind == 'weekly' else '点击带标记日期切换已发布期刊。'}</p>
      </div>
      <div class="periodical-switch"><button type="button" data-period-prev>← 上一期</button><button type="button" data-period-next>下一期 →</button></div>
      <label class="periodical-date-jump">跳转<input type="date" data-period-date aria-label="跳转到期刊日期" {'disabled' if not periods else ''}></label>
      <details class="periodical-archive"><summary>{len(periods)} 期归档</summary><label for="periodical-date" class="visually-hidden">选择期刊</label><select id="periodical-date" data-periodical-select {'disabled' if not periods else ''}>{options}</select></details>
    </section>
    <p class="periodical-tool-label periodical-toc-heading">本期目录</p>
    <nav class="periodical-toc" aria-label="本期目录" data-periodical-toc>{toc}</nav>
  </aside>
  <article class="periodical-article" data-periodical-article tabindex="0" aria-label="{html.escape(title, quote=True)}正文" data-period-id="{html.escape(selected_id, quote=True)}">{body}</article>
  <p class="periodical-status" role="status" aria-live="polite" data-periodical-status></p>
</section>
<script type="application/json" id="periodical-catalog">{payload}</script>
<script src="{root}assets/js/periodicals.js?v=4" defer></script>'''
    return render_site_page(
        output_file=output_file, output_root=output_root, active_section=active_section,
        page_title=f'{title} · LOKEN', meta_description=title, main_content=main,
        active_subtopic=active_subtopic, body_class='periodical-page',
        head_content=f'<link rel="stylesheet" href="{root}assets/css/periodicals.css?v=4">\n',
    )
