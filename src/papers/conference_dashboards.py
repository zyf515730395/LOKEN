"""Source-linked edition dashboards for the configured conference series."""

from __future__ import annotations

from collections.abc import Set
from datetime import date
from functools import cache
import html
from pathlib import Path

import yaml

from papers.conferences import (
    Conference,
    ConferenceMeeting,
    _https_url,
    _mapping,
    _meeting_date_label,
    _meeting_year,
    _reject_unknown_fields,
    _text,
    dashboard_route,
    load_conferences,
)
from shared.rendering import atomic_write_text
from shared.site_shell import SITE_NAME, render_site_page, site_root_for


ROOT = Path(__file__).resolve().parents[2]
CONFERENCE_CONFIG = ROOT / "config/conferences.yaml"
DASHBOARD_CATALOG = ROOT / "content/papers/conference-dashboards.yaml"
THEME_KINDS = ("技术趋势", "新模型范式", "新概念")


def navigation_links(conferences: tuple[Conference, ...]) -> tuple[tuple[str, str, str], ...]:
    return tuple((f"conference-{c.id}", c.name, dashboard_route(c.id))
                 for c in conferences if c.meetings)


@cache
def configured_navigation(as_of: date) -> tuple[tuple[str, str, str], ...]:
    return navigation_links(load_conferences(CONFERENCE_CONFIG, as_of=as_of))


def _records(data: dict, key: str, required: set[str], optional: Set[str] = frozenset()) -> list[dict]:
    rows = data.get(key, [])
    if not isinstance(rows, list):
        raise ValueError(f"{key} must be a list")
    for raw in rows:
        row = _mapping(raw, key)
        _reject_unknown_fields(row, required | optional, key)
        if required - row.keys():
            raise ValueError(f"Missing {key} fields: {required - row.keys()}")
        for field, value in row.items():
            if field == "references":
                continue
            validator = _https_url if field in {"url", "source_url", "paper_url", "award_url"} else _text
            validator(value, f"{key}.{field}")
    return rows


def load_dashboard_catalog(path: Path, conferences: tuple[Conference, ...]) -> dict:
    if not path.is_file():
        return {}
    root = _mapping(yaml.safe_load(path.read_text(encoding="utf-8")), "dashboard catalog")
    _reject_unknown_fields(root, {"version", "editions"}, "dashboard catalog")
    if root.get("version") != 1:
        raise ValueError("Unsupported conference dashboard version")
    editions = _mapping(root.get("editions"), "dashboard editions")
    known = {meeting.edition for c in conferences for meeting in c.meetings}
    for edition, raw in editions.items():
        if edition not in known:
            raise ValueError(f"Dashboard has no configured edition: {edition}")
        data = _mapping(raw, edition)
        _reject_unknown_fields(data, {"statistics", "awards", "themes"}, edition)
        _records(data, "statistics", {"label", "value", "scope", "source_url"})
        _records(data, "awards", {"name", "title", "award_url", "paper_url"}, {"reading"})
        for theme in _records(data, "themes", {"kind", "title", "analysis", "references"}):
            if theme["kind"] not in THEME_KINDS or not _records(theme, "references", {"title", "url"}):
                raise ValueError(f"Theme requires a supported kind and references: {edition}")
    return editions


def _escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def _link(url: str, label: str) -> str:
    return f'<a href="{_escape(url)}">{_escape(label)}</a>'


def _stats(rows: list[dict], proceedings: dict) -> str:
    cards = [
        f'<li><span>{_escape(row["label"])}</span><strong>{_escape(row["value"])}</strong>'
        f'<p>{_escape(row["scope"])} · {_link(row["source_url"], "官方来源")}</p></li>'
        for row in rows
    ]
    entries = proceedings.get("papers", [])
    if entries and proceedings.get("status") in {"collected", "refresh_failed"}:
        stale = "（最新刷新失败，上次留存）" if proceedings["status"] == "refresh_failed" else ""
        source = proceedings.get("source_url")
        link = " · " + _link(_https_url(source, "proceedings.source_url"), "论文库来源") if source else ""
        cards.append(f'<li><span>本站已索引的论文库条目{stale}</span><strong>{len(entries):,}</strong>'
                     f'<p>论文库覆盖量，不等同于官方录用量{link}</p></li>')
    missing = "" if rows else '<p class="dashboard-muted">未找到可核验的官方数据，暂不填投稿量、录用量或录用率。</p>'
    return missing + (f'<ul class="conference-metrics">{"".join(cards)}</ul>' if cards else "")


def _awards(rows: list[dict]) -> str:
    if not rows:
        return '<p class="dashboard-muted">奖项与获奖论文精读待核验。</p>'
    items = []
    for row in rows:
        reading = _escape(row["reading"]) if row.get("reading") else "精读待补。"
        items.append(f'<li><h4>{_escape(row["name"])} · {_link(row["paper_url"], row["title"])}</h4>'
                     f'<p>{reading}</p><small>{_link(row["award_url"], "官方获奖名单")}</small></li>')
    return '<ul class="conference-evidence-list">' + "".join(items) + "</ul>"


def _themes(rows: list[dict]) -> str:
    sections = []
    for kind in THEME_KINDS:
        items = []
        for row in rows:
            if row["kind"] != kind:
                continue
            refs = " · ".join(_link(ref["url"], ref["title"]) for ref in row["references"])
            items.append(f'<li><h5>{_escape(row["title"])}</h5><p>{_escape(row["analysis"])}</p>'
                         f'<small>支撑论文：{refs}</small></li>')
        content = ('<ul class="conference-evidence-list">' + "".join(items) + "</ul>"
                   if items else '<p class="dashboard-muted">待补可核验的论文证据。</p>')
        sections.append(f'<section><h4>{kind}</h4>{content}</section>')
    return "".join(sections)


def _board(meeting: ConferenceMeeting, rows: dict, proceedings: dict, as_of: date, default: bool) -> str:
    year = _meeting_year(meeting)
    state = ("日期未公布" if meeting.end_date is None else
             "已举办" if meeting.end_date < as_of else "举办中" if meeting.start_date <= as_of else "已确认")
    sources = _link(meeting.website or meeting.source_url, "会议官网")
    if meeting.proceedings_url:
        sources += " · " + _link(meeting.proceedings_url, "官方论文库")
    cls = "conference-year-board" + (" is-default" if default else "")
    return f"""<article class="{cls}" id="year-{year}" aria-labelledby="title-{year}">
  <header class="conference-board-heading">
    <div><p>{state} · {_escape(_meeting_date_label(meeting))}</p><h2 id="title-{year}">{_escape(meeting.edition)}</h2></div>
    <p>{_escape(meeting.location)}<br>{sources}</p>
  </header>
  <section class="conference-board-section"><h3>会议数据</h3>{_stats(rows.get("statistics", []), proceedings)}</section>
  <section class="conference-board-section"><h3>关键奖项与论文精读</h3>{_awards(rows.get("awards", []))}</section>
  <section class="conference-board-section"><h3>研究方向</h3>
  <p class="dashboard-muted">基于所列论文的观察，不代表全会趋势、占比或首创结论。</p>{_themes(rows.get("themes", []))}</section>
</article>"""


def publish_conference_dashboards(
    conferences: tuple[Conference, ...], proceedings: dict, *, output_root: Path,
    as_of: date, dashboard_catalog: Path = DASHBOARD_CATALOG,
) -> list[Path]:
    content = load_dashboard_catalog(dashboard_catalog, conferences)
    catalog = {(row["conference"], row["edition"]): row for row in proceedings["editions"]}
    links = navigation_links(conferences)
    outputs = []
    for conference in conferences:
        meetings = sorted(conference.meetings, key=_meeting_year, reverse=True)
        if not meetings:
            continue
        years = [_meeting_year(m) for m in meetings]
        if len(set(years)) != len(years):
            raise ValueError(f"Multiple editions share one dashboard year: {conference.id}")
        default = next((m for m in meetings if m.end_date and m.end_date < as_of), meetings[0])
        chips = "".join(f'<a href="#year-{year}">{year}</a>' for year in years)
        boards = "\n".join(_board(m, content.get(m.edition, {}), catalog.get((conference.id, m.edition), {}),
                                    as_of, m == default) for m in meetings)
        path = output_root / dashboard_route(conference.id)
        root = site_root_for(path, output_root)
        name = conference.name
        body = f"""<div class="conference-dashboard">
<header class="conference-dashboard-heading">
  <p>学习一个 / 会议</p><h1>{_escape(name)}</h1>
  <p>逐届查看会议数据、获奖论文与研究方向。没有官方依据的字段不会以零代替。</p>
</header>
<nav class="conference-year-picker" aria-label="切换会议年份">{chips}</nav>
<div class="conference-year-boards">{boards}</div>
</div>"""
        atomic_write_text(path, render_site_page(
            output_file=path, output_root=output_root, active_section="learning",
            page_title=f"{name} 逐届看板 · {SITE_NAME}",
            meta_description=f"{name} 的历届会议数据、关键奖项、论文精读与研究方向。",
            main_content=body, body_class="conference-dashboard-page",
            sidebar_status="CONFERENCE / EDITIONS", active_subtopic=f"conference-{conference.id}",
            conference_links=links,
            head_content=f'  <link rel="stylesheet" href="{_escape(root)}assets/css/conference-dashboards.css?v=1">\n',
        ))
        outputs.append(path)
    return outputs
