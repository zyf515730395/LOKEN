"""Render only verified public data; preserve the existing timeline visual language."""

from __future__ import annotations

from datetime import datetime
import html
import os
from pathlib import Path
import tempfile

from shared.site_shell import render_section_intro, render_site_page

from .data import NEW_YORK, SHANGHAI, aware_datetime, load_public_content


def escaped(value: object) -> str:
    return html.escape(str(value), quote=True)


def render_sources(sources: list[dict]) -> str:
    return '<ul class="stocks-sources">' + "".join(
        f'<li><a href="{escaped(source["url"])}" target="_blank" rel="noopener noreferrer">{escaped(source["title"])}</a>'
        f'<span> · 核验于 {escaped(aware_datetime(source["verified_at"], "source").astimezone(SHANGHAI).strftime("%Y.%m.%d %H:%M"))} 北京时间</span></li>'
        for source in sources
    ) + "</ul>"


def render_evidence(value: dict | None, unknown: str = "待核验") -> str:
    if value is None:
        return f'<span class="stocks-unknown">{escaped(unknown)}</span>'
    return f'<span>{escaped(value["value"])} {escaped(value["unit"])}</span>{render_sources(value["sources"])}'


def _style() -> str:
    # Scoped layout only. All colors inherit the established site palette.
    return """<style>
.stocks-page .stocks-intro{margin:0 0 2rem;max-width:72ch;color:var(--muted)}
.stocks-page .stocks-calendar{border-bottom:1px solid var(--line);padding:clamp(2rem,3.5vw,3.25rem) clamp(1.25rem,2.6vw,2.5rem)}
.stocks-page .stocks-sources{font-size:.72rem;line-height:1.65;padding-left:1rem;color:var(--muted);overflow-wrap:anywhere}
.stocks-page .stocks-monitors{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:2rem;border-top:1px solid var(--line);padding-top:1.5rem;margin-top:2rem}
.stocks-page .stocks-monitor{min-width:0}
.stocks-page .stocks-observations{font-size:.8rem}.stocks-page .stocks-note{font-size:.8rem;color:var(--muted);line-height:1.7}
.stocks-page .stocks-observations h4{font-size:.78rem;font-weight:600;margin:1rem 0 .5rem}
.stocks-page .stocks-observations dl{margin:0}.stocks-page .stocks-observation-row{display:grid;grid-template-columns:5.5em minmax(0,1fr);gap:.5rem;padding:.18rem 0;align-items:baseline}
.stocks-page .stocks-observation-row dt{color:var(--muted)}.stocks-page .stocks-observation-row dd{margin:0;min-width:0}
.stocks-page .stocks-observation-row dd>.stocks-sources{margin:.3rem 0 .5rem;padding-left:1rem;font-size:.66rem}
.stocks-page .stocks-time-secondary{font-size:.72rem;margin:.4rem 0;color:var(--muted)}
.stocks-page .stocks-timeline .timeline-release{min-width:270px;max-width:320px}
.stocks-page .stocks-timeline footer{margin-top:auto}.stocks-page .stocks-timeline footer .stocks-sources{margin:0}
.stocks-page .stocks-timeline .stocks-observations:last-of-type{padding-bottom:1rem}
.stocks-page .stocks-unknown{color:var(--muted)}
.stocks-page .stocks-empty{color:var(--muted);line-height:1.9}
.stocks-page .stocks-yields{margin-top:2rem}
</style>"""


def _section_header() -> str:
    return '<div class="section-sticky-header"><header class="section-header">' + render_section_intro("stocks") + '</header></div>'


def _observations(event: dict, config: dict) -> str:
    rows = []
    for observation in event.get("observations", []):
        label = config["indicators"][observation["indicator"]]["label"]
        values = "".join(f'<div class="stocks-observation-row"><dt>{name}</dt><dd>{render_evidence(observation.get(key))}</dd></div>'
                         for key, name in (("actual", "公布值"), ("consensus", "一致预期"), ("previous", "前值")))
        rows.append(f'<div class="stocks-observations"><h4>{escaped(label)}</h4><dl>{values}</dl></div>')
    return "".join(rows)


def render_calendar(config: dict, document: dict, *, output_file: Path, output_root: Path) -> str:
    now = datetime.now(SHANGHAI)
    releases = sorted((event for event in document["events"] if event["kind"] != "monitor"),
                      key=lambda event: event.get("scheduled_at") or "9999")
    future = [event for event in releases if event.get("scheduled_at") and aware_datetime(event["scheduled_at"], "event") >= now]
    current = future[0]["id"] if future else (releases[-1]["id"] if releases else "")
    cards = []
    for event in releases:
        scheduled = event.get("scheduled_at")
        if scheduled:
            instant = aware_datetime(scheduled, "event")
            beijing = instant.astimezone(SHANGHAI)
            eastern = instant.astimezone(NEW_YORK)
            clock = f'<time datetime="{escaped(beijing.isoformat())}">{beijing.strftime("%Y.%m.%d · %H:%M")}</time><p class="stocks-time-secondary">北京时间 · {eastern.strftime("%m.%d %H:%M %Z")} 美东</p>'
        else:
            clock = '<p class="stocks-time-secondary">官方日期待核验</p>'
        selected = ' data-stocks-current="true"' if event["id"] == current else ""
        period = f'<p class="conference-location">{escaped(event["period"])}</p>' if event.get("period") else ""
        note = f'<p class="stocks-note">{escaped(event["note"])}</p>' if event.get("note") else ""
        cards.append(f'<li class="timeline-release conference-release status-released" id="{escaped(event["id"])}"{selected}>'
                     f'<span class="timeline-dot" aria-hidden="true"></span>{clock}<h3>{escaped(event["title"])}</h3>{period}{note}'
                     f'{_observations(event, config)}<footer>{render_sources(event["sources"])}</footer></li>')
    if cards:
        timeline = '<div class="milestone-timeline-viewport conference-timeline stocks-timeline" tabindex="0" aria-label="美股关键节点时间线，可水平滚动" data-drag-scroll><ol class="milestone-timeline">' + "".join(cards) + '</ol></div>'
    else:
        timeline = '<p class="stocks-empty">暂无已核验的发布日程。官方来源确认后更新。</p>'
    monitors = []
    for event in document["events"]:
        if event["kind"] == "monitor":
            monitors.append(f'<article class="stocks-monitor"><h3>{escaped(event["title"])}</h3><p class="stocks-note">连续观察 · 不设固定发布日期</p>'
                            f'{_observations(event, config)}{render_sources(event["sources"])}<p class="stocks-note">{escaped(event.get("note", ""))}</p></article>')
    updated = aware_datetime(document["updated_at"], "events.updated_at").astimezone(SHANGHAI).strftime("%Y.%m.%d %H:%M")
    body = _section_header() + f'<section class="stocks-calendar conference-section"><header class="topic-header"><p>Key Events</p><h2>关键节点</h2><span>更新于 {updated} · 北京时间</span></header>'
    body += '<p class="stocks-intro">CPI、PCE、就业与 FOMC 的官方日程。日期随夏令时自动换算；未知数值留待核验。</p>'
    body += timeline + '<section class="stocks-yields" aria-labelledby="stocks-yields"><header class="topic-header"><p>Treasury Yields</p><h2 id="stocks-yields">美债收益率</h2></header><div class="stocks-monitors">' + "".join(monitors) + '</div></section></section>'
    script = """<script>document.addEventListener('DOMContentLoaded',()=>{const el=document.querySelector('[data-stocks-current]');const rail=document.querySelector('.stocks-timeline');if(el&&rail)rail.scrollLeft=el.offsetLeft-rail.offsetLeft-24;});</script>"""
    return render_site_page(output_file=output_file, output_root=output_root, active_section="stocks", active_subtopic="events",
                            page_title="关键节点 · LOKEN", meta_description="已核验的美国宏观事件与美债收益率观察。",
                            main_content=body, body_class="stocks-page", head_content=_style(), trailing_dialogs=script)


def outlook_period(document: dict, config: dict) -> dict:
    sections = []
    names = {"upside": "上行情境", "base": "基准情境", "downside": "下行情境"}
    for section in document["sections"]:
        key = section["indicator"]
        label = section.get("title") or " / ".join(config["indicators"][item]["label"] for item in section.get("indicators", [key]))
        content = '<p class="periodical-note">条件假设 · 以下为情境推演，市场反应取决于数据、预期差及当时环境。</p>'
        content += '<p>已核验预期：' + render_evidence(section.get("expectation"), "暂无可核验一致预期") + '</p>'
        if section.get("note"):
            content += f'<p>{escaped(section["note"])}</p>'
        content += f'<div class="outlook-table-wrap" tabindex="0" role="region" aria-label="{escaped(label)}情境对照表"><table class="outlook-scenarios"><caption class="visually-hidden">{escaped(label)}：条件假设与可能影响</caption><thead><tr><th scope="col">情境</th><th scope="col">条件</th><th scope="col">对美股的可能影响</th></tr></thead><tbody>'
        for scenario, title in names.items():
            item = section["scenarios"][scenario]
            content += f'<tr><th scope="row">{title}</th><td>若 {escaped(item["condition"])}</td><td>{escaped(item["implication"])}</td></tr>'
        content += '</tbody></table></div>' + render_sources(section["sources"])
        sections.append({"id": key, "label": label, "html": content})
    return {"id": document["period"], "date": document["period"], "title": document["title"],
            "subtitle": f'{document["week_start"]} — {document["week_end"]} · 周一至周日',
            "metadata": {"note": "每周日 08:00 更新 · 事实附来源，未知项留空，推演为条件假设。"}, "sections": sections}


def render_quant(*, output_file: Path, output_root: Path) -> str:
    return render_site_page(output_file=output_file, output_root=output_root, active_section="stocks", active_subtopic="quant",
                            page_title="量化投资 · LOKEN", meta_description="量化投资研究档案。",
                            main_content=_section_header() + '<section class="stocks-calendar"><header class="topic-header"><p>Quantitative Investing</p><h2>量化投资</h2></header><p class="stocks-empty">研究整理中。首份经过验证的策略研究将在这里归档。</p></section>',
                            body_class="stocks-page", head_content=_style())


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".stocks-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def publish_stocks(*, config_path: str | Path = "config/stocks.yaml", content_root: str | Path = "content/stocks",
                   output_root: str | Path = "docs") -> list[Path]:
    from shared.periodicals import render_periodical_page

    config, events, outlooks = load_public_content(Path(config_path), Path(content_root))
    root = Path(output_root)
    paths = [root / "stocks/index.html", root / "stocks/outlook.html", root / "stocks/quant.html"]
    # Complete validation and rendering before touching any published page.
    pages = [render_calendar(config, events, output_file=paths[0], output_root=root),
             render_periodical_page(output_file=paths[1], output_root=root, active_section="stocks", active_subtopic="outlook",
                                    title="预期推演", kind="outlook", periods=[outlook_period(item, config) for item in reversed(outlooks)]),
             render_quant(output_file=paths[2], output_root=root)]
    for path, page in zip(paths, pages):
        _atomic_write(path, page)
    return paths
