"""Shared information architecture and outer page shell for TOGOS."""

from __future__ import annotations

from dataclasses import dataclass
import html
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Section:
    key: str
    label: str
    description: str
    route: str


SECTIONS = (
    Section(
        "learning",
        "学习一个",
        "毕竟还too young，感觉还要学习一个",
        "index.html",
    ),
    Section(
        "milestones",
        "身经百战",
        "这些模型是身经百战了",
        "milestone-models/flux.html",
    ),
    Section(
        "writings",
        "谈笑风生",
        "还是要提高自己的知识水平",
        "writings/index.html",
    ),
    Section(
        "journeys",
        "跑得还快",
        "记录走过的城市与拍下的瞬间",
        "journeys/index.html",
    ),
)
SECTIONS_BY_KEY = {section.key: section for section in SECTIONS}


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


def render_primary_navigation(active_section: str, site_root: str) -> str:
    get_section(active_section)
    items = []
    for section in SECTIONS:
        active_class = " is-active" if section.key == active_section else ""
        current = ' aria-current="page"' if section.key == active_section else ""
        items.append(
            f'      <a class="primary-nav-item{active_class}" '
            f'href="{html.escape(site_root + section.route, quote=True)}"{current}>'
            f'<span>{html.escape(section.label)}</span></a>'
        )
    return "\n".join(
        [
            '  <aside class="primary-sidebar" aria-label="知识主题">',
            f'    <a class="primary-brand" href="{html.escape(site_root + SECTIONS[0].route, quote=True)}" '
            'aria-label="TOGOS 首页">TOGOS</a>',
            '    <nav class="primary-navigation" aria-label="知识主题">',
            *items,
            "    </nav>",
            "  </aside>",
        ]
    )


def render_section_intro(section_key: str) -> str:
    """Render the section identity at the top of the page body."""
    section = get_section(section_key)
    return (
        '      <div class="section-intro">\n'
        f'        <p class="section-intro-label">{html.escape(section.label)}</p>\n'
        f'        <p class="section-intro-description">{html.escape(section.description)}</p>\n'
        "      </div>"
    )


def render_context_sidebar(active_section: str, secondary_navigation: str) -> str:
    section = get_section(active_section)
    return f"""  <aside class="paper-sidebar context-sidebar" id="paper-sidebar" aria-label="{html.escape(section.label, quote=True)}导航">
    <div class="context-toolbar">
      <p class="context-toolbar-label"><span>CONTENTS</span><span>目录</span></p>
      <button class="context-collapse" type="button" aria-controls="context-navigation" aria-expanded="true" data-context-collapse>
        <span aria-hidden="true" data-context-collapse-icon>‹</span>
        <span class="visually-hidden" data-context-collapse-label>折叠二级导航</span>
      </button>
    </div>
    <nav class="archive-nav context-navigation" id="context-navigation" aria-label="{html.escape(section.label, quote=True)}目录">
{secondary_navigation}
    </nav>
  </aside>"""


def _state_bootstrap() -> str:
    return """  <script>
    (() => {
      document.documentElement.classList.add("js");
      let theme = null;
      let collapsed = null;
      try {
        theme = window.localStorage.getItem("arxiv-theme");
        collapsed = window.localStorage.getItem("togos-secondary-sidebar-collapsed");
      } catch (error) { /* Storage can be unavailable. */ }
      if (theme !== "light" && theme !== "dark") {
        theme = window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
      }
      document.documentElement.dataset.theme = theme;
      if (collapsed === "true") document.documentElement.dataset.secondaryCollapsed = "true";
    })();
  </script>"""


def _render_search_dialog() -> str:
    return """  <dialog class="search-dialog" id="search-dialog" aria-labelledby="search-dialog-title">
    <div class="search-dialog-shell">
      <header class="search-dialog-header">
        <div>
          <p>全站公开内容</p>
          <h2 id="search-dialog-title">搜索文章标题</h2>
        </div>
        <button type="button" class="search-dialog-close" data-search-close aria-label="关闭搜索">×</button>
      </header>
      <label class="visually-hidden" for="search-input">搜索公开文章标题</label>
      <input id="search-input" class="search-input" type="search" placeholder="搜索公开文章标题"
             autocomplete="off" role="combobox" aria-autocomplete="list" aria-controls="search-results"
             aria-haspopup="listbox" aria-expanded="false">
      <p class="search-status" data-search-status aria-live="polite">输入标题关键词开始搜索</p>
      <div class="search-results" id="search-results" data-search-results role="listbox" aria-label="搜索结果"></div>
    </div>
  </dialog>"""


def render_site_page(
    *,
    output_file: Path,
    output_root: Path,
    active_section: str,
    page_title: str,
    meta_description: str,
    secondary_navigation: str,
    main_content: str,
    body_class: str = "",
    trailing_dialogs: str = "",
) -> str:
    site_root = site_root_for(output_file, output_root)
    body_attributes = (
        f' data-site-root="{html.escape(site_root, quote=True)}"'
        f' data-active-section="{html.escape(active_section, quote=True)}"'
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
  <link rel="stylesheet" href="{html.escape(site_root, quote=True)}assets/css/site.css?v=3">
  <script src="{html.escape(site_root, quote=True)}assets/js/site-shell.js?v=3" defer></script>
  <script src="{html.escape(site_root, quote=True)}assets/js/search-core.js?v=3" defer></script>
  <script src="{html.escape(site_root, quote=True)}assets/js/search.js?v=3" defer></script>
  <script src="{html.escape(site_root, quote=True)}assets/js/sidebar.js?v=3" defer></script>
</head>
<body{body_attributes}>
  <button class="sidebar-toggle" type="button" aria-controls="navigation-shell" aria-expanded="false">
    <span aria-hidden="true" data-sidebar-toggle-icon>☰</span><span data-sidebar-toggle-label>打开导航</span>
  </button>
  <button class="theme-toggle" type="button" aria-label="切换颜色主题" aria-pressed="false">
    <span data-theme-icon aria-hidden="true"></span>
  </button>
  <button class="search-trigger" type="button" data-search-trigger>
    <span>搜索公开文章标题</span><kbd>Ctrl K</kbd>
  </button>
  <div class="sidebar-scrim" data-sidebar-close></div>
<div class="navigation-shell" id="navigation-shell">
{render_primary_navigation(active_section, site_root)}
{render_context_sidebar(active_section, secondary_navigation)}
</div>
  <main class="page-content" id="top">
{main_content}
  </main>
{trailing_dialogs}
{_render_search_dialog()}
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
    secondary_navigation = (
        '      <a class="context-overview is-active" href="#top" '
        'aria-current="page">页面概览</a>'
    )
    main_content = f"""    <section class="empty-section" aria-labelledby="empty-section-title">
{render_section_intro(section_key)}
      <h1 id="empty-section-title">{html.escape(section.label)}</h1>
      <p class="empty-section-copy">{html.escape(body_copy)}</p>
    </section>
"""
    return render_site_page(
        output_file=output_file,
        output_root=output_root,
        active_section=section_key,
        page_title=f"{section.label} · TOGOS",
        meta_description=section.description,
        secondary_navigation=secondary_navigation,
        main_content=main_content,
        body_class="empty-section-page",
    )
