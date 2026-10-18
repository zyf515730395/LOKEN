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
    ) or '<p class="periodical-empty">暂无已发布内容。请稍后查看。</p>'
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
    <label for="periodical-date">选择{'周次' if kind == 'weekly' else '日期'}</label>
    <select id="periodical-date" data-periodical-select {'disabled' if not periods else ''}>{options}</select>
    <p class="periodical-archive-count">{len(periods)} 期归档</p>
    <nav class="periodical-toc" aria-label="本期目录" data-periodical-toc>{toc}</nav>
  </aside>
  <article class="periodical-article" data-periodical-article tabindex="0" aria-label="{html.escape(title, quote=True)}正文" data-period-id="{html.escape(selected_id, quote=True)}">{body}</article>
  <p class="periodical-status" role="status" aria-live="polite" data-periodical-status></p>
</section>
<script type="application/json" id="periodical-catalog">{payload}</script>
<script src="{root}assets/js/periodicals.js?v=1" defer></script>'''
    return render_site_page(
        output_file=output_file, output_root=output_root, active_section=active_section,
        page_title=f'{title} · LOKEN', meta_description=title, main_content=main,
        active_subtopic=active_subtopic, body_class='periodical-page',
        head_content=f'<link rel="stylesheet" href="{root}assets/css/periodicals.css?v=1">\n',
    )
