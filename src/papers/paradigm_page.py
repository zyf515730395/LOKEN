"""Static route atlas with progressive evidence and local follow-up controls."""
from __future__ import annotations
import html
import json
from pathlib import Path
from shared.site_shell import render_site_page, site_root_for


def esc(value):
    return html.escape(str(value), quote=True)


def follow(key):
    return f'''<label class="paradigm-follow">调研安排<select data-follow-id="{esc(key)}" aria-label="调研安排">
      <option value="">未筛选</option><option value="follow">准备调研</option>
      <option value="watch">继续观察</option><option value="skip">暂不跟进</option></select></label>'''


def references(ids, papers):
    return '<ul class="paradigm-refs">' + ''.join(
        f'<li><a href="{esc(papers[key]["url"])}">{esc(papers[key]["title"])}</a> <small>{esc(key)}</small></li>'
        for key in ids if key in papers) + '</ul>'


def render_route(route, catalog):
    names = {t['id']: t['name'] for t in catalog['topics']}
    labels = {'mainstream': '主流路线 · 基线', 'developing': '持续发展 · 本站样本', 'watch': '新出现 · 待观察'}
    events = sorted(route['events'], key=lambda event: event['week'], reverse=True)
    timeline = ''.join(f'<section class="paradigm-event"><h4>{esc(event["week"])} 所在周 · {"历史周报复核" if event.get("origin") == "historical_review" else "每周机制观察"}</h4>'
                       f'<p>{esc(event["previous"])} → {esc(event["mechanism"])}</p>'
                       f'<p class="paradigm-muted">边界：{esc(event["limitations"])}</p>'
                       + references(event['paper_ids'], catalog['papers']) + '</section>' for event in events)
    sources = ' · '.join(f'<a href="{esc(source["url"])}" target="_blank" rel="noopener noreferrer">{esc(source["title"])}</a>' for source in route['sources'])
    recent = (f'窗口内首次观察 {route["first_seen"]} · 最近 {route["last_seen"]} · {route["paper_count"]} 篇支撑论文'
              if events else '尚无结构化周报观察；不据此判断路线已停止发展')
    associated = len(route['associations'])
    return f'''<article class="paradigm-route" id="route-{esc(route['id'])}" data-route-id="{esc(route['id'])}"
      data-topic="{esc(route['topic'])}" data-dimension="{esc(route['dimension'])}" data-status="{esc(route['status'])}" data-activity="{esc(route['activity'])}">
      <div class="paradigm-meta"><span>{esc(names[route['topic']])}</span><span>{esc(route['dimension'])}</span><span>{labels[route['status']]}</span></div>
      <h3>{esc(route['name'])}</h3><p>{esc(route['mechanism'])}</p>
      <p class="paradigm-muted">{esc(recent)}</p>
      <details><summary>变化、边界与证据</summary>
        <dl><dt>对照路线</dt><dd>{esc(route['previous'])}</dd><dt>适用边界</dt><dd>{esc(route['limitations'])}</dd>
        <dt>调研切入点</dt><dd>{esc(route.get('investigate', '检查该机制能否迁移到你的任务，以及收益和代价是否可复现。'))}</dd></dl>
        {('<p>基础代表来源（可能早于观察窗口）：' + sources + '</p>') if sources else ''}
        {timeline or '<p class="paradigm-muted">历史周报线索尚未做结构化新颖性判定，见下方关联线索。</p>'}
        <button type="button" data-related-route="{esc(route['id'])}">查看 {associated} 条历史关联线索</button>
        <p class="paradigm-muted">基线路线使用机制词检索关联；已复核路线关联原分析。关联本身不代表采纳、复现或范式变化。</p>
      </details>{follow(route['id'])}
    </article>'''


def render_clue(clue, catalog):
    name = next(t['name'] for t in catalog['topics'] if t['id'] == clue['topic'])
    return f'''<article class="paradigm-clue" id="clue-{esc(clue['id'])}">
      <div class="paradigm-meta">{esc(name)} · {esc(clue['week'])} 所在周 · 历史线索 / 待研判</div>
      <h3>{esc(clue['claim'])}</h3><details><summary>阅读机制比较与支撑论文</summary>
      <p>{esc(clue['reasoning'])}</p><p class="paradigm-muted">边界：{esc(clue['limitations'])}</p>
      {references(clue['paper_ids'], catalog['papers'])}</details>{follow(clue['id'])}</article>'''


def render_page(catalog, output_root: Path):
    output = output_root / 'reports/paradigms.html'
    root = site_root_for(output, output_root)
    options = ''.join(f'<option value="{esc(t["id"])}">{esc(t["name"])}</option>' for t in catalog['topics'])
    dims = sorted({route['dimension'] for route in catalog['routes']})
    dim_options = ''.join(f'<option>{esc(d)}</option>' for d in dims)
    valid = sum(row['valid'] for row in catalog['coverage'])
    total = len(catalog['coverage'])
    weeks = len({row['week'] for row in catalog['coverage'] if row['valid']})
    gaps = ''.join(f'<li>{esc(row["week"])} · {esc(next(t["name"] for t in catalog["topics"] if t["id"] == row["topic"]))}：{esc(row["reason"])}</li>'
                   for row in catalog['coverage'] if not row['valid'])
    skipped = sum(row['skipped_papers'] for row in catalog['coverage'] if row['valid'])
    routes = ''.join(render_route(route, catalog) for route in catalog['routes'])
    clues = ''.join(render_clue(clue, catalog) for clue in catalog['clues'][:12])
    payload = json.dumps(catalog, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    main = f'''<section class="paradigm-reader">
      <header class="paradigm-heading"><p class="paradigm-kicker">RESEARCH RADAR / LOKEN</p><h1>最新范式</h1>
        <p>看清技术路线如何变化，决定下一步研究什么。</p>
        <p class="paradigm-muted">观察窗口 {esc(catalog['start'])} — {esc(catalog['end'])} · 每周随论文分析更新</p>
      </header>
      <div class="paradigm-stats"><span><strong>{len(catalog['topics'])}</strong> 研究主题</span><span><strong>{len(catalog['routes'])}</strong> 路线条目</span>
        <span><strong>{weeks}</strong> 周有效分析</span><span><strong>{len(catalog['clues'])}</strong> 历史线索</span></div>
      <details class="paradigm-coverage"><summary>证据覆盖 {valid}/{total} 个有论文的主题周 · 阅读口径</summary>
        <p>主流路线是有代表来源支撑的常用技术基线，不是市场份额排名。基础来源核验于 {esc(catalog['baseline_verified_at'])}。
        持续发展表示本站样本中至少两周、两篇不同论文出现同名机制，不代表独立团队复现。新出现指窗口内首次观察，不是技术首次提出。</p>
        <p>历史线索复用已核验周报，仍可能包含训练改进或评测观察，不能直接视为新范式。缺分析、引用变化或跨窗口的混合证据不参与判断。
        按现有期刊的首次采集日期归档，无记录时使用发表日期；基础论文可早于窗口。有效主题周另有 {skipped} 个逐篇跳过项。</p>
        <ul>{gaps or '<li>有公开样本的主题周均有可用分析。</li>'}</ul>
      </details>
      <form class="paradigm-filters" role="search" aria-label="筛选范式" onsubmit="return false">
        <label>研究主题<select id="paradigm-topic"><option value="">全部主题</option>{options}</select></label>
        <label>变化维度<select id="paradigm-dimension"><option value="">全部维度</option>{dim_options}<option>待研判</option></select></label>
        <label>发展阶段<select id="paradigm-status"><option value="">全部阶段</option><option value="mainstream">主流路线</option><option value="developing">持续发展</option><option value="watch">新出现 / 待观察</option><option value="clue">历史线索</option></select></label>
        <label>调研安排<select id="paradigm-follow-filter"><option value="all">全部安排</option><option value="">未筛选</option><option value="follow">准备调研</option><option value="watch">继续观察</option><option value="skip">暂不跟进</option></select></label>
        <label class="paradigm-search">搜索机制或论文<input id="paradigm-query" type="search" placeholder="例如：记忆、物理、单流…"></label>
        <button type="reset">重置</button>
      </form>
      <nav class="paradigm-tabs" aria-label="范式视图"><a href="#paradigm-latest">近期变化</a><a href="#paradigm-atlas">路线地图</a><a href="#paradigm-clues">历史线索</a></nav>
      <section id="paradigm-latest"><h2>近期变化</h2><div data-latest-events><p class="paradigm-muted">新一期周报的结构化观察将在这里汇总。过去一年的已核验材料见历史线索。</p></div></section>
      <section id="paradigm-atlas"><h2>路线地图 <small data-route-count>{len(catalog['routes'])} 条</small></h2>
        <p class="paradigm-muted">按主题筛选后，从机制变化与适用边界选择调研方向。</p><div class="paradigm-grid">{routes}</div>
        <p data-route-empty hidden>没有符合条件的路线。可重置筛选，或查看尚未归类的历史线索。</p>
      </section>
      <section id="paradigm-clues"><h2>过去一年的历史线索 <small data-clue-count>{len(catalog['clues'])} 条</small></h2>
        <p class="paradigm-muted">最新在前。先读机制比较，再决定是否值得跟进；这些线索尚未逐条认定为范式变化。</p>
        <p data-related-label hidden></p><div data-clues>{clues}</div><button type="button" data-more-clues>加载更多线索</button>
      </section>
      <footer class="paradigm-footer"><p>调研安排仅保存在当前浏览器，可导出备份后在其他设备导入。</p>
        <button type="button" data-export-follow>导出安排</button><label class="paradigm-import">导入安排<input type="file" data-import-follow accept="application/json,.json"></label>
        <p role="status" aria-live="polite" data-paradigm-feedback></p></footer>
      <noscript><p>启用 JavaScript 可筛选、加载更多历史线索和保存调研安排；路线及首批证据可直接阅读。</p></noscript>
    </section><script type="application/json" id="paradigm-catalog">{payload}</script>
    <script src="{root}assets/js/paradigms.js?v=1" defer></script>'''
    document = render_site_page(output_file=output, output_root=output_root, active_section='learning',
                            active_subtopic='paradigms', page_title='最新范式 · LOKEN', meta_description='研究主题的模型路线与每周新机制追踪',
                            main_content=main, body_class='paradigm-page',
                            head_content=f'<link rel="stylesheet" href="{root}assets/css/paradigms.css?v=1">\n')
    return '\n'.join(line.rstrip() for line in document.splitlines()) + '\n'
