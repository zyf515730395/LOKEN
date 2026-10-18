"""Shared information architecture and outer page shell for LOKEN."""

from __future__ import annotations

from dataclasses import dataclass
import html
from pathlib import Path
import re
import unicodedata

import yaml


@dataclass(frozen=True, slots=True)
class Section:
    key: str
    label: str
    content_label: str
    description: str
    route: str


SECTIONS = (
    Section(
        "learning",
        "学习一个",
        "PAPERS",
        "毕竟还too young，感觉还要学习一个",
        "index.html",
    ),
    Section(
        "milestones",
        "身经百战",
        "MODELS",
        "这些模型是身经百战了",
        "milestone-models/flux.html",
    ),
    Section(
        "writings",
        "谈笑风生",
        "ARTICLES",
        "还是要提高自己的知识水平",
        "writings/index.html",
    ),
    Section(
        "journeys",
        "跑得还快",
        "TRAVELS",
        "比其他的西方记者啊，跑得还快",
        "journeys/index.html",
    ),
    Section("stocks", "闷声发大财", "STOCKS", "投资研究、策略与量化方法", "stocks/index.html"),
)
SECTIONS_BY_KEY = {section.key: section for section in SECTIONS}
SITE_NAME = "LOKEN"
ASSET_VERSION = "15"
SECTION_METADATA = {
    "learning": "01 / PAPERS",
    "milestones": "02 / MODELS",
    "writings": "03 / ARTICLES",
    "journeys": "04 / TRAVELS",
    "stocks": "05 / STOCKS",
}
CONTINENTS = (
    ("asia", "亚洲", "ASIA"),
    ("europe", "欧洲", "EUROPE"),
    ("africa", "非洲", "AFRICA"),
    ("north-america", "北美洲", "NORTH AMERICA"),
    ("south-america", "南美洲", "SOUTH AMERICA"),
    ("oceania", "大洋洲", "OCEANIA"),
    ("antarctica", "南极洲", "ANTARCTICA"),
)


def get_section(key: str) -> Section:
    try:
        return SECTIONS_BY_KEY[key]
    except KeyError as error:
        raise ValueError(f"Unknown knowledge section: {key}") from error


def site_root_for(output_file: str | Path, output_root: str | Path) -> str:
    output = Path(output_file).resolve()
    root = Path(output_root).resolve()
    try:
        relative_parent = output.relative_to(root).parent
    except ValueError as error:
        raise ValueError(f"Output page must be inside site root: {output}") from error
    return "../" * len(relative_parent.parts)


def render_primary_navigation(
    active_section: str,
    site_root: str,
    sidebar_status: str = "AUTOMATED / WEEKDAYS",
) -> str:
    get_section(active_section)
    items = []
    for section in SECTIONS:
        active_class = " is-active" if section.key == active_section else ""
        current = ' aria-current="page"' if section.key == active_section else ""
        items.append(
            f'      <a class="primary-nav-item{active_class}" '
            f'href="{html.escape(site_root + section.route, quote=True)}"{current}>'
            '<span class="primary-nav-copy">'
            f'<span class="primary-nav-label">{html.escape(section.label)}</span>'
            f'<span class="primary-nav-meta">{SECTION_METADATA[section.key]}</span>'
            "</span></a>"
        )
    brand_href = html.escape(site_root + SECTIONS[0].route, quote=True)
    brand_label = html.escape(f"{SITE_NAME} 首页", quote=True)
    logo_src = html.escape(site_root + "assets/images/loken-logo.png", quote=True)
    brand = (
        f'<a class="primary-brand" href="{brand_href}" aria-label="{brand_label}">'
        f'<img class="brand-logo" src="{logo_src}" width="1990" height="329" alt=""></a>'
    )
    return "\n".join(
        [
            '  <aside class="primary-sidebar" aria-label="知识主题">',
            f"    {brand}",
            '    <button class="primary-menu" type="button" data-context-toggle '
            'aria-controls="context-drawer" aria-expanded="true" aria-label="收起二级导航">'
            '<span>MENU</span><span aria-hidden="true">☰</span></button>',
            '    <nav class="primary-navigation" aria-label="知识主题">',
            *items,
            "    </nav>",
            '    <div class="primary-sidebar-status">'
            f'<span>LAST SYNC</span><strong>{html.escape(sidebar_status)}</strong></div>',
            "  </aside>",
        ]
    )


def render_section_intro(section_key: str) -> str:
    """Render the section identity at the top of the page body."""
    section = get_section(section_key)
    return (
        '      <div class="section-intro">\n'
        f'        <h1 class="section-intro-title" id="section-{html.escape(section.key, quote=True)}-title">'
        f'{html.escape(section.content_label)}</h1>\n'
        f'        <p class="section-intro-description">{html.escape(section.description)}</p>\n'
        "      </div>"
    )


def _state_bootstrap() -> str:
    return """  <script>
    (() => {
      document.documentElement.classList.add("js");
      let theme = null;
      let contextOpen = null;
      try {
        theme = window.localStorage.getItem("arxiv-theme");
        contextOpen = window.localStorage.getItem("togos-secondary-sidebar-collapsed");
      } catch (error) { /* Storage can be unavailable. */ }
      if (theme !== "light" && theme !== "dark") {
        theme = window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
      }
      document.documentElement.dataset.theme = theme;
      if (contextOpen !== "true") document.documentElement.dataset.contextOpen = "true";
    })();
  </script>"""


def render_inline_search() -> str:
    return """    <div class="site-search" data-search-root>
      <label class="site-search-field" for="search-input">
        <span aria-hidden="true">⌕</span>
        <input id="search-input" type="search" placeholder="搜索文章标题"
               aria-label="搜索文章标题" role="combobox"
               autocomplete="off" aria-autocomplete="list" aria-controls="search-results" aria-expanded="false">
        <kbd aria-hidden="true">Ctrl K</kbd>
      </label>
      <div class="search-popover" data-search-popover hidden>
        <p class="search-status" data-search-status aria-live="polite">输入标题关键词开始搜索</p>
        <div id="search-results" class="search-results" data-search-results role="listbox"></div>
      </div>
    </div>"""


def render_context_strip(
    links: tuple[tuple[str, str], ...],
    *,
    active_index: int = 0,
    filter_keys: tuple[str, ...] | None = None,
) -> str:
    """Render one compact in-content navigation strip."""
    if filter_keys is not None and len(filter_keys) != len(links):
        raise ValueError("filter_keys must align with links")
    rendered_links = []
    for index, (label, href) in enumerate(links):
        active_class = " is-active" if index == active_index else ""
        current = ' aria-current="location"' if index == active_index else ""
        filter_attribute = ""
        if filter_keys is not None:
            filter_attribute = (
                f' data-topic-filter="{html.escape(filter_keys[index], quote=True)}"'
            )
        rendered_links.append(
            f'    <a class="context-strip-link{active_class}" '
            f'href="{html.escape(href, quote=True)}"{current}{filter_attribute}>'
            f'{html.escape(label)}</a>'
        )
    navigation_attribute = " data-topic-navigation" if filter_keys is not None else ""
    return (
        f'<nav class="context-strip" aria-label="本页快捷目录"{navigation_attribute}>\n'
        + "\n".join(rendered_links)
        + "\n  </nav>"
    )


def _take_context_navigation(main_content: str) -> tuple[str, str]:
    """Move only generator-owned navigation; keep all original content byte for byte."""
    blocks: list[str] = []

    def take(match: re.Match[str]) -> str:
        blocks.append(match.group(0))
        return ""

    # Paper navigation has a sibling Conference link outside its nav element.
    content = re.sub(
        r'<div class="paper-context-navigation">.*?</div>', take, main_content, flags=re.S
    )
    content = re.sub(
        r'<nav class="context-strip"[^>]*>.*?</nav>', take, content, flags=re.S
    )
    return content, "\n".join(blocks)


def _nav_group(label: str, content: str) -> str:
    return (f'<details class="secondary-nav-group" open><summary>{html.escape(label)}</summary>'
            f'<div class="secondary-nav-links">{content}</div></details>')


def _nav_link(label: str, route: str, site_root: str, *, active: bool = False) -> str:
    current = ' aria-current="page"' if active else ""
    active_class = " is-active" if active else ""
    return (f'<a class="secondary-nav-link{active_class}" '
            f'href="{html.escape(site_root + route, quote=True)}"{current}>{html.escape(label)}</a>')


def _paper_archive_navigation(site_root: str) -> str:
    config = yaml.safe_load((Path(__file__).resolve().parents[2] / "config/site.yaml").read_text(encoding="utf-8"))
    links = []
    for label in config.get("paper_labels", []):
        name = label["name"]
        normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
        slug = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
        links.append(_nav_link(name, f"index.html?tag={slug}#{slug}", site_root))
    return "\n".join(links)


def render_secondary_navigation(
    active_section: str, site_root: str, original_navigation: str = "", active_subtopic: str = ""
) -> str:
    """Render the current theme's vertical navigation and preserve original controls."""
    section = get_section(active_section)
    groups = []
    if active_section == "learning":
        groups.append(_nav_group("论文报刊", "".join(
            _nav_link(label, route, site_root, active=active_subtopic == key)
            for key, label, route in (("daily", "论文日报", "reports/daily.html"),
                                      ("weekly", "论文周报", "reports/weekly.html"))
        )))
        if original_navigation:
            conference = re.search(r'<a\b[^>]*class="[^"]*conference-navigation-link[^"]*"[^>]*>.*?</a>', original_navigation, re.S)
            topics = original_navigation
            if conference:
                topics = topics.replace(conference.group(0), "")
            groups.append(_nav_group("研究主题", topics))
            if conference:
                groups.append(_nav_group("会议", conference.group(0)))
        else:
            groups.append(_nav_group("研究主题", _paper_archive_navigation(site_root)))
            groups.append(_nav_group("会议", _nav_link("Conference", "index.html?tag=conferences#conferences", site_root)))
    elif active_section == "milestones":
        groups.append(_nav_group("模型系列", original_navigation))
    elif active_section == "writings":
        groups.append(_nav_group("文章栏目", original_navigation or _nav_link("LATEST", "writings/index.html", site_root, active=True)))
    elif active_section == "journeys":
        groups.append(_nav_group("旅行档案", _nav_link("环游世界", "journeys/index.html", site_root, active=active_subtopic in ("", "world"))))
        groups.append(_nav_group("七大洲", "".join(
            _nav_link(label, f"journeys/{slug}.html", site_root, active=active_subtopic == slug)
            for slug, label, _ in CONTINENTS
        )))
    elif active_section == "stocks":
        groups.append(_nav_group("投资信息", "".join(
            _nav_link(label, route, site_root, active=active_subtopic == key)
            for key, label, route in (("events", "关键节点", "stocks/index.html"),
                                      ("outlook", "预期推演", "stocks/outlook.html"),
                                      ("quant", "量化投资", "stocks/quant.html"))
        )))
    return f'''  <aside class="context-drawer" id="context-drawer" aria-label="{html.escape(section.label)}二级导航">
    <header class="secondary-nav-header"><div><span>{section.content_label}</span><h2>{html.escape(section.label)}</h2></div>
      <button type="button" data-context-close aria-label="收起二级导航">‹</button></header>
    <div class="secondary-nav-scroll">{"".join(groups)}</div>
  </aside>'''


def render_site_page(
    *,
    output_file: Path,
    output_root: Path,
    active_section: str,
    page_title: str,
    meta_description: str,
    main_content: str,
    body_class: str = "",
    sidebar_status: str = "AUTOMATED / WEEKDAYS",
    trailing_dialogs: str = "",
    head_content: str = "",
    active_subtopic: str = "",
) -> str:
    site_root = site_root_for(output_file, output_root)
    main_content, original_navigation = _take_context_navigation(main_content)
    body_attributes = (
        f' data-site-root="{html.escape(site_root, quote=True)}"'
        f' data-active-section="{html.escape(active_section, quote=True)}"'
        f' data-active-subtopic="{html.escape(active_subtopic, quote=True)}"'
    )
    if body_class:
        body_attributes += f' class="{html.escape(body_class, quote=True)}"'
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="{html.escape(meta_description, quote=True)}">
  <title>{html.escape(page_title)}</title>
{_state_bootstrap()}
{head_content}  <link rel="stylesheet" href="{html.escape(site_root, quote=True)}assets/css/site.css?v={ASSET_VERSION}">
  <script src="{html.escape(site_root, quote=True)}assets/js/site-shell.js?v={ASSET_VERSION}" defer></script>
  <script src="{html.escape(site_root, quote=True)}assets/js/search-core.js?v={ASSET_VERSION}" defer></script>
  <script src="{html.escape(site_root, quote=True)}assets/js/search.js?v={ASSET_VERSION}" defer></script>
  <script src="{html.escape(site_root, quote=True)}assets/js/sidebar.js?v={ASSET_VERSION}" defer></script>
</head>
<body{body_attributes}>
  <header class="site-utility" aria-label="页面工具">
    <button class="sidebar-toggle" type="button" aria-controls="navigation-shell" aria-expanded="false">
      <span aria-hidden="true" data-sidebar-toggle-icon>☰</span><span data-sidebar-toggle-label>导航</span>
    </button>
{render_inline_search()}
    <button class="theme-toggle" type="button" aria-label="切换颜色主题" aria-pressed="false">
      <span data-theme-icon aria-hidden="true"></span>
    </button>
  </header>
  <div class="sidebar-scrim" data-sidebar-close></div>
<div class="navigation-shell" id="navigation-shell">
  <button class="navigation-close" type="button" data-navigation-close
          aria-label="关闭导航" hidden>×</button>
{render_primary_navigation(active_section, site_root, sidebar_status)}
{render_secondary_navigation(active_section, site_root, original_navigation, active_subtopic)}
</div>
  <main class="page-content" id="top">
{main_content}
  </main>
{trailing_dialogs}
</body>
</html>
"""


def render_empty_section_page(
    *,
    output_file: Path,
    output_root: Path,
    section_key: str,
    body_copy: str,
) -> str:
    section = get_section(section_key)
    main_content = f"""    <section class="empty-section" aria-labelledby="empty-section-title">
{render_section_intro(section_key)}
      <h1 id="empty-section-title">{html.escape(section.label)}</h1>
      <p class="empty-section-copy">{html.escape(body_copy)}</p>
    </section>
{render_context_strip((("OVERVIEW", "#top"),))}
"""
    return render_site_page(
        output_file=output_file,
        output_root=output_root,
        active_section=section_key,
        page_title=f"{section.label} · {SITE_NAME}",
        meta_description=section.description,
        main_content=main_content,
        body_class="empty-section-page",
    )


def render_journey_placeholder_page(*, output_file: Path, output_root: Path) -> str:
    """Render the City Memory shell without manufacturing travel data."""
    section = get_section("journeys")
    main_content = f"""    <section class="journey-archive" aria-labelledby="section-journeys-title">
      <div class="section-sticky-header">
      <header class="journey-header section-header">
{render_section_intro("journeys")}
      </header>
      </div>
      <div class="journey-map-placeholder" id="world-map" aria-label="尚未开放的城市地图档案">
        <div class="journey-map-grid" aria-hidden="true"><span class="journey-world-silhouette"></span></div>
        <aside class="journey-photo-contact" id="photography">
          <div class="journey-photo-contact-surface" aria-hidden="true"></div>
          <p>摄影接触表将随首批城市档案一同出现。</p>
        </aside>
      </div>
    </section>
"""
    return render_site_page(
        output_file=output_file,
        output_root=output_root,
        active_section="journeys",
        page_title=f"{section.label} · {SITE_NAME}",
        meta_description=section.description,
        main_content=main_content,
        body_class="journey-page",
    )


def render_journey_continent_page(
    *, output_file: Path, output_root: Path, continent: str
) -> str:
    """Render an honest empty country/photo archive for one continent."""
    try:
        _, label, english = next(item for item in CONTINENTS if item[0] == continent)
    except StopIteration as error:
        raise ValueError(f"Unknown continent: {continent}") from error
    content = f'''<section class="journey-continent" aria-labelledby="continent-title">
      <header class="section-header"><p class="journey-continent-meta">{english} / TRAVEL ARCHIVE</p>
        <h1 id="continent-title">{label}</h1><p>按国家收纳旅途中的照片与记忆。</p></header>
      <div class="journey-continent-empty"><span aria-hidden="true">◎</span><h2>{label}</h2>
        <h3>暂无照片</h3><p>{label}的国家与照片档案将在这里呈现。</p></div>
    </section>'''
    return render_site_page(output_file=output_file, output_root=output_root,
        active_section="journeys", active_subtopic=continent,
        page_title=f"{label} · {SITE_NAME}", meta_description=f"{label}旅行照片与记忆",
        main_content=content, body_class="journey-page")


def publish_journey_pages(output_root: Path) -> list[Path]:
    """Publish the original world map and seven continent archive routes."""
    from shared.rendering import atomic_write_text

    output_root = Path(output_root)
    directory = output_root / "journeys"
    directory.mkdir(parents=True, exist_ok=True)
    world = directory / "index.html"
    atomic_write_text(world, render_journey_placeholder_page(output_file=world, output_root=output_root))
    paths = [world]
    for slug, _, _ in CONTINENTS:
        destination = directory / f"{slug}.html"
        atomic_write_text(destination, render_journey_continent_page(output_file=destination, output_root=output_root, continent=slug))
        paths.append(destination)
    return paths
