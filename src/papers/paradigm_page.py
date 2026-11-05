"""Topic-based model history and current directions in the shared periodical shell."""
from __future__ import annotations
import html
import json
from pathlib import Path
from shared.site_shell import render_site_page, site_root_for


def esc(value):
    return html.escape(str(value), quote=True)


def follow(key):
    return f'<label class="paradigm-follow">调研安排<select data-follow-id="{esc(key)}" aria-label="调研安排"><option value="">未筛选</option><option value="follow">准备调研</option><option value="watch">继续观察</option><option value="skip">暂不跟进</option></select></label>'


def references(ids, papers):
    return '<ul class="paradigm-refs">' + ''.join(f'<li><a href="{esc(papers[k]["url"])}">{esc(papers[k]["title"])}</a> <small>{esc(k)}</small></li>' for k in ids if k in papers) + '</ul>'


def render_route(route, catalog):
    labels = {'mainstream': '主流基线', 'developing': '持续发展', 'watch': '新出现 · 待观察'}
    events = sorted(route['events'], key=lambda e: e['week'], reverse=True)
    timeline = ''.join(f'<section class="paradigm-event"><h4>{esc(e["week"])} 所在周 · {"历史周报复核" if e.get("origin") == "historical_review" else "每周机制观察"}</h4><p>{esc(e["previous"])} → {esc(e["mechanism"])}</p><p>边界：{esc(e["limitations"])}</p>' + references(e['paper_ids'], catalog['papers']) + '</section>' for e in events)
    sources = ' · '.join(f'<a href="{esc(s["url"])}" target="_blank" rel="noopener noreferrer">{esc(s["title"])}</a>' for s in route['sources'])
    recent = f'最近观察 {route["last_seen"]} · {route["paper_count"]} 篇支撑论文' if events else '尚无窗口内结构化观察'
    return f'''<tr id="route-{esc(route['id'])}" data-route-id="{esc(route['id'])}">
      <th scope="row"><strong>{esc(route['name'])}</strong><small>{esc(route['dimension'])}</small></th>
      <td><p>{esc(route['mechanism'])}</p><details><summary>变化与边界</summary><p><strong>对照路线：</strong>{esc(route['previous'])}</p><p><strong>适用边界：</strong>{esc(route['limitations'])}</p><p><strong>调研切入点：</strong>{esc(route.get('investigate', '检查机制迁移、收益及代价是否可复现。'))}</p></details></td>
      <td><span class="paradigm-stage">{labels[route['status']]}</span><small>{esc(recent)}</small><details><summary>论文与观察记录</summary>{('<p>基础代表来源：' + sources + '</p>') if sources else ''}{timeline or '<p>暂无结构化周报观察；基础路线不因此视为停止发展。</p>'}<button type="button" data-related-route="{esc(route['id'])}">查看 {len(route['associations'])} 条历史线索</button></details></td>
      <td>{follow(route['id'])}</td></tr>'''


def render_clue(c, catalog):
    return f'<article class="paradigm-clue" id="clue-{esc(c["id"])}"><small>{esc(c["week"])} 所在周 · 待研判</small><h3>{esc(c["claim"])}</h3><details><summary>机制比较与支撑论文</summary><p>{esc(c["reasoning"])}</p><p>边界：{esc(c["limitations"])}</p>{references(c["paper_ids"], catalog["papers"])}</details>{follow(c["id"])}</article>'


def render_topic(topic, catalog):
    slug = topic['id']
    roadmap = ''.join(f'<li class="roadmap-node"><div class="roadmap-stamp"><time>{n["year"]}</time><span>{esc(n["branch"])}</span></div><div><h4><a href="{esc(n["url"])}" target="_blank" rel="noopener noreferrer">{esc(n["title"])}</a></h4><p>{esc(n["contribution"])}</p><small>演进意义：{esc(n["transition"])}</small></div></li>' for n in catalog['roadmaps']['topics'][slug])
    routes = sorted((r for r in catalog['routes'] if r['topic'] == slug), key=lambda r: (r['last_seen'], r['name']), reverse=True)
    return f'''<section class="paradigm-topic-panel periodical-section" id="topic-{esc(slug)}" data-topic-panel="{esc(slug)}">
      <h2>{esc(topic['name'])}</h2><section id="roadmap-{esc(slug)}"><h3>发展路线图 <span class="paradigm-section-en">ROADMAP</span></h3><p class="periodical-note">按论文首次公开年份串联关键节点，明确标注会议或期刊版本时采用该版本年份；分支并行发展，不代表全面替代。“演进意义”为基于论文机制的归纳。</p><ol class="paradigm-roadmap">{roadmap}</ol></section>
      <section id="directions-{esc(slug)}"><h3>最新方向 <small data-topic-route-count="{esc(slug)}">{len(routes)} 条</small></h3><p class="periodical-note">对照主流基线与过去一年的机制观察；“新出现”指本站窗口内首次观察。</p>
      <div class="paradigm-table-wrap" role="region" aria-label="{esc(topic['name'])}最新方向" tabindex="0"><table class="digest-table paradigm-table"><thead><tr><th scope="col">方向 / 维度</th><th scope="col">机制变化</th><th scope="col">进展与证据</th><th scope="col">后续调研</th></tr></thead><tbody>{''.join(render_route(r, catalog) for r in routes)}</tbody></table></div><p data-topic-empty="{esc(slug)}" hidden>没有符合条件的方向，可重置筛选或查看历史线索。</p></section></section>'''


def render_page(catalog, output_root: Path):
    output = output_root / 'reports/paradigms.html'
    root = site_root_for(output, output_root)
    nav = ''.join(f'<a href="#topic-{esc(t["id"])}" data-topic-link="{esc(t["id"])}">{esc(t["name"])}</a>' for t in catalog['topics'])
    dims = ''.join(f'<option>{esc(d)}</option>' for d in sorted({r['dimension'] for r in catalog['routes']}))
    names = {t['id']: t['name'] for t in catalog['topics']}
    gaps = ''.join(f'<li>{esc(r["week"])} · {esc(names[r["topic"]])}：{esc(r["reason"])}</li>' for r in catalog['coverage'] if not r['valid'])
    valid = sum(r['valid'] for r in catalog['coverage'])
    payload = json.dumps(catalog, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    first = esc(catalog['topics'][0]['id'])
    main = f'''<section class="periodical-reader paradigm-reader">
      <header class="periodical-heading"><p class="periodical-kicker">MODEL PARADIGMS / LOKEN</p><h1>模型范式</h1><p>从经典论文看清路线演进，从每周观察选择下一步研究方向。</p><p>近期观察 {esc(catalog['start'])} — {esc(catalog['end'])} · 历史来源核验于 {esc(catalog['roadmaps']['verified_at'])}</p></header>
      <aside class="periodical-tools paradigm-tools"><p class="periodical-tool-label">研究主题</p><nav class="periodical-toc paradigm-topic-nav" aria-label="模型范式研究主题">{nav}</nav><nav class="paradigm-section-nav" aria-label="当前主题目录"><a data-section-jump="roadmap" href="#roadmap-{first}">发展路线图</a><a data-section-jump="directions" href="#directions-{first}">最新方向</a><a data-section-jump="clues" href="#paradigm-clues">历史线索</a></nav></aside>
      <article class="periodical-article" tabindex="0" aria-label="模型范式正文"><details class="paradigm-filter-panel"><summary>筛选最新方向与历史线索</summary><form class="paradigm-filters" role="search" aria-label="筛选范式" onsubmit="return false">
        <label>变化维度<select id="paradigm-dimension"><option value="">全部维度</option>{dims}<option>待研判</option></select></label><label>发展阶段<select id="paradigm-status"><option value="">全部阶段</option><option value="mainstream">主流基线</option><option value="developing">持续发展</option><option value="watch">新出现 / 待观察</option><option value="clue">历史线索</option></select></label>
        <label>调研安排<select id="paradigm-follow-filter"><option value="all">全部安排</option><option value="">未筛选</option><option value="follow">准备调研</option><option value="watch">继续观察</option><option value="skip">暂不跟进</option></select></label><label class="paradigm-search">搜索机制或论文<input id="paradigm-query" type="search" placeholder="记忆、物理、单流…"></label><button type="reset">重置筛选</button></form></details>
      {''.join(render_topic(t, catalog) for t in catalog['topics'])}
      <details id="paradigm-clues" class="paradigm-clues-panel"><summary>过去一年的历史线索 <small data-clue-count></small></summary><p class="periodical-note">当前主题尚待研判的线索，关联不代表新范式或独立复现。</p><p data-related-label hidden></p><div data-clues>{''.join(render_clue(c, catalog) for c in catalog['clues'][:12])}</div><button type="button" data-more-clues>加载更多线索</button></details>
      <details class="paradigm-coverage"><summary>证据覆盖与阅读口径 · 全站 {valid}/{len(catalog['coverage'])} 个主题周</summary><p>主流基线由代表来源支持，不是市场份额排名；持续发展表示本站至少两周、两篇不同论文出现同名机制，不代表独立复现。</p><p>路线图不限于近期窗口；历史线索不能直接视为新范式，缺分析、引用变化或跨窗口证据不参与判断。</p><ul>{gaps or '<li>有公开样本的主题周均有可用分析。</li>'}</ul></details>
      <footer class="paradigm-footer"><p class="periodical-note">调研安排仅保存在当前浏览器，可导出备份后在其他设备导入。</p><button type="button" data-export-follow>导出安排</button><label class="paradigm-import">导入安排<input type="file" data-import-follow accept="application/json,.json"></label><p role="status" aria-live="polite" data-paradigm-feedback></p></footer><noscript><p>启用 JavaScript 可切换主题和保存安排；各主题路线图和表格仍可直接阅读。</p></noscript></article></section>
      <script type="application/json" id="paradigm-catalog">{payload}</script><script src="{root}assets/js/paradigms.js?v=2" defer></script>'''
    document = render_site_page(output_file=output, output_root=output_root, active_section='learning', active_subtopic='paradigms', page_title='模型范式 · LOKEN', meta_description='研究主题的经典论文路线图与最新模型方向', main_content=main, body_class='periodical-page paradigm-page', head_content=f'<link rel="stylesheet" href="{root}assets/css/periodicals.css?v=4">\n<link rel="stylesheet" href="{root}assets/css/paradigms.css?v=2">\n')
    return '\n'.join(line.rstrip() for line in document.splitlines()) + '\n'
