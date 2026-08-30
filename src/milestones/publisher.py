"""Render Milestone Models pages from the tracked catalog and local Markdown."""

from __future__ import annotations

import datetime as dt
import html
from pathlib import Path
import re
from typing import Any

import bleach
import markdown
import yaml

from .catalog import (
    find_family,
    iter_families,
    load_milestone_catalog,
    render_milestone_navigation,
)
from shared.rendering import atomic_write_text, render_note_content
from shared.site_shell import render_site_page


DEEP_READING_FIELDS = (
    ("版本", "版本"),
    ("训练数据", "训练数据"),
    ("VAE 结构", "VAE 结构"),
    ("Text Encoder", "Text Encoder"),
    ("生成主体网络", "生成主体网络"),
    ("训练 Trick", "训练 Trick"),
    ("新提出的创新点", "新提出的创新点"),
    ("局限性", "局限性"),
)
FRONT_MATTER_PATTERN = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
H2_PATTERN = re.compile(r"^##\s+(.+?)\s*$")
H3_PATTERN = re.compile(r"^###\s+(.+?)\s*$")
CELL_TAGS = {"a", "br", "code", "em", "li", "ol", "p", "strong", "ul"}
CELL_ATTRIBUTES = {"a": ["href", "title", "target", "rel"]}
STATUS_LABELS = {
    "released": "已发布",
    "early-access": "Early Access",
    "announced": "已宣布",
}


class MilestoneNoteError(ValueError):
    """Raised when a local milestone Markdown document is ambiguous or invalid."""


def split_markdown_document(content: str) -> tuple[dict[str, Any], str]:
    match = FRONT_MATTER_PATTERN.match(content)
    if match is None:
        return {}, content
    try:
        metadata = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as error:
        raise MilestoneNoteError(f"Invalid Markdown front matter: {error}") from error
    if not isinstance(metadata, dict):
        raise MilestoneNoteError("Markdown front matter must be a mapping")
    return metadata, content[match.end() :]


def extract_deep_reading(body: str) -> dict[str, str] | None:
    """Extract fixed third-level sections from the 文章精读 block."""
    lines = body.splitlines()
    in_deep_reading = False
    current_heading: str | None = None
    sections: dict[str, list[str]] = {}
    for line in lines:
        h2_match = H2_PATTERN.match(line)
        if h2_match:
            heading = h2_match.group(1).strip()
            if heading == "文章精读":
                in_deep_reading = True
                current_heading = None
                continue
            if in_deep_reading:
                break
        if not in_deep_reading:
            continue
        h3_match = H3_PATTERN.match(line)
        if h3_match:
            heading = h3_match.group(1).strip()
            current_heading = heading if heading in dict(DEEP_READING_FIELDS) else None
            if current_heading:
                sections.setdefault(current_heading, [])
            continue
        if current_heading:
            sections[current_heading].append(line)
    if not in_deep_reading:
        return None
    return {
        heading: "\n".join(sections.get(heading, [])).strip()
        for heading, _ in DEEP_READING_FIELDS
    }


def render_cell(markdown_content: str) -> str:
    if not markdown_content.strip():
        return '<span class="milestone-value is-undisclosed">未披露</span>'
    rendered = markdown.markdown(markdown_content, extensions=["extra", "sane_lists"])
    cleaned = bleach.clean(
        rendered,
        tags=CELL_TAGS,
        attributes=CELL_ATTRIBUTES,
        protocols={"http", "https", "mailto"},
        strip=True,
    )
    return bleach.linkify(cleaned)


def _release_note_candidates(
    notes_root: Path, topic_name: str, note_id: str
) -> list[Path]:
    topic_directory = notes_root / topic_name
    if not topic_directory.is_dir():
        return []
    prefix = f"[{note_id}] "
    return sorted(
        path for path in topic_directory.glob("*.md") if path.name.startswith(prefix)
    )


def load_release_note(
    notes_root: Path,
    topic_name: str,
    family_slug: str,
    release: dict[str, Any],
) -> dict[str, Any] | None:
    """Load a release note, preferring explicit family/release front matter."""
    candidates = _release_note_candidates(notes_root, topic_name, release["note_id"])
    explicit: list[tuple[Path, str, dict[str, Any], str]] = []
    fallback: list[tuple[Path, str, dict[str, Any], str]] = []
    for path in candidates:
        content = path.read_text(encoding="utf-8")
        metadata, body = split_markdown_document(content)
        item = (path, content, metadata, body)
        if (
            metadata.get("milestone_family") == family_slug
            and metadata.get("milestone_release") == release["slug"]
        ):
            explicit.append(item)
        else:
            fallback.append(item)
    selected = explicit or fallback
    if len(selected) > 1:
        names = ", ".join(item[0].name for item in selected)
        raise MilestoneNoteError(
            f"Multiple notes match {family_slug}/{release['slug']}: {names}"
        )
    if not selected:
        return None
    path, content, metadata, body = selected[0]
    deep_reading = extract_deep_reading(body)
    return {
        "path": path,
        "content": content,
        "metadata": metadata,
        "body": body,
        "deep_reading": deep_reading,
        "ready": deep_reading is not None,
    }


def release_notes(
    notes_root: Path, topic: dict[str, Any], family: dict[str, Any]
) -> dict[str, dict[str, Any] | None]:
    return {
        release["slug"]: load_release_note(
            notes_root,
            topic["name"],
            family["slug"],
            release,
        )
        for release in family["releases"]
    }


def _theme_bootstrap() -> str:
    return """  <script>
    (() => {
      document.documentElement.classList.add("js");
      const storageKey = "arxiv-theme";
      let theme = null;
      try { theme = window.localStorage.getItem(storageKey); } catch (error) { /* unavailable */ }
      if (theme !== "light" && theme !== "dark") {
        theme = window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
      }
      document.documentElement.dataset.theme = theme;
    })();
  </script>"""


def _status_badge(status: str) -> str:
    return (
        f'<span class="release-status status-{html.escape(status, quote=True)}">'
        f'{html.escape(STATUS_LABELS[status])}</span>'
    )


def render_timeline(family: dict[str, Any]) -> str:
    output = [
        '<section class="milestone-panel timeline-panel" aria-labelledby="timeline-heading">',
        '  <div class="milestone-panel-heading">',
        '    <div><p>ROADMAP</p><h2 id="timeline-heading">官方版本时间线</h2></div>',
        '    <span>可横向拖动</span>',
        '  </div>',
        '  <div class="milestone-timeline-viewport" data-drag-scroll tabindex="0" '
        'aria-label="FLUX 官方版本时间线，使用左右方向键或拖动浏览">',
        '    <ol class="milestone-timeline">',
    ]
    for release in family["releases"]:
        variants = "".join(
            f'<li>{html.escape(variant)}</li>' for variant in release["variants"]
        )
        output.extend([
            f'      <li class="timeline-release status-{html.escape(release["status"], quote=True)}">',
            '        <span class="timeline-dot" aria-hidden="true"></span>',
            f'        <time datetime="{release["release_date"]}">{release["release_date"]}</time>',
            f'        <h3>{html.escape(release["name"])}</h3>',
            f'        {_status_badge(release["status"])}',
            f'        <ul>{variants}</ul>',
            '      </li>',
        ])
    output.extend(["    </ol>", "  </div>", "</section>"])
    return "\n".join(output)


def render_comparison_table(
    family: dict[str, Any], notes: dict[str, dict[str, Any] | None]
) -> str:
    releases_by_slug = {release["slug"]: release for release in family["releases"]}
    grouped_releases = {
        group["slug"]: [
            release
            for release in family["releases"]
            if release["comparison_group"] == group["slug"]
        ]
        for group in family["comparison_groups"]
    }
    output = [
        '<section class="milestone-panel comparison-panel" aria-labelledby="comparison-heading">',
        '  <div class="milestone-panel-heading">',
        '    <div><p>COMPARISON</p><h2 id="comparison-heading">大版本技术对比</h2></div>',
        '    <span>内容来自本地 Markdown 精读</span>',
        '  </div>',
        '  <div class="milestone-table-scroll">',
        '    <table class="milestone-comparison-table">',
        '      <thead><tr><th scope="col">对比项</th>',
    ]
    for group in family["comparison_groups"]:
        releases = grouped_releases[group["slug"]]
        baseline = releases_by_slug[group["baseline_release"]]
        baseline_note = notes[baseline["slug"]]
        start_date = releases[0]["release_date"]
        end_date = releases[-1]["release_date"]
        date_label = start_date if start_date == end_date else f"{start_date} — {end_date}"
        source_links = " · ".join(
            f'<a href="{html.escape(source["url"], quote=True)}" target="_blank" '
            f'rel="noopener">官方资料 {index}</a>'
            for index, source in enumerate(baseline["sources"], start=1)
        )
        note_link = (
            f'<a class="milestone-note-link" href="{family["slug"]}-notes.html#milestone-{baseline["slug"]}">查看代际精读</a>'
            if baseline_note and baseline_note["ready"]
            else '<span class="milestone-note-pending">待精读</span>'
        )
        output.extend([
            '        <th scope="col" class="milestone-version-heading">',
            f'          <time datetime="{start_date}">{date_label}</time>',
            f'          <strong>{html.escape(group["name"])}</strong>',
            f'          {_status_badge(baseline["status"])}',
            f'          <span class="milestone-release-count">{len(releases)} 个官方发布节点</span>',
            f'          <div class="milestone-source-links">{source_links}</div>',
            f'          {note_link}',
            '        </th>',
        ])
    output.append("      </tr></thead>")
    output.append("      <tbody>")
    for heading, label in DEEP_READING_FIELDS:
        output.append(f'        <tr><th scope="row">{html.escape(label)}</th>')
        for group in family["comparison_groups"]:
            releases = grouped_releases[group["slug"]]
            if heading == "版本":
                version_entries = []
                for release in releases:
                    note = notes[release["slug"]]
                    if not note or not note["ready"]:
                        content = '<span class="milestone-value is-pending">待精读</span>'
                    else:
                        content = render_cell(note["deep_reading"].get(heading, ""))
                    note_link = (
                        f'<a href="{family["slug"]}-notes.html#milestone-{release["slug"]}">精读</a>'
                        if note and note["ready"]
                        else ""
                    )
                    version_entries.append(
                        '<section class="milestone-minor-release">'
                        f'<header><strong>{html.escape(release["name"])}</strong>{note_link}</header>'
                        f'{content}</section>'
                    )
                cell = "".join(version_entries)
            else:
                baseline_slug = group["baseline_release"]
                baseline_note = notes[baseline_slug]
                if not baseline_note or not baseline_note["ready"]:
                    cell = '<span class="milestone-value is-pending">待精读</span>'
                else:
                    cell = render_cell(baseline_note["deep_reading"].get(heading, ""))
            output.append(f"          <td>{cell}</td>")
        output.append("        </tr>")
    output.extend(["      </tbody>", "    </table>", "  </div>", "</section>"])
    return "\n".join(output)


def render_family_page(
    catalog: dict[str, Any],
    topic: dict[str, Any],
    family: dict[str, Any],
    notes: dict,
    *,
    output_file: Path,
    output_root: Path,
) -> str:
    updated = dt.date.today().isoformat()
    statuses = "".join(
        f'<li>{_status_badge(status)}<span>{label}</span></li>'
        for status, label in STATUS_LABELS.items()
    )
    main_content = f"""    <header class="milestone-hero">
      <div>
        <p>{html.escape(topic['name'])} · {html.escape(family['organization'])}</p>
        <h1>{html.escape(family['name'])}</h1>
        <span>官方模型版本演进与核心技术对比</span>
      </div>
      <div class="milestone-hero-meta">
        <ul class="status-legend" aria-label="发布状态图例">{statuses}</ul>
        <p>Updated {updated}</p>
      </div>
    </header>
    <div class="milestone-workspace">
{render_timeline(family)}
{render_comparison_table(family, notes)}
    </div>
    <footer>仅收录官方发布 · 未公开的信息明确标记为“未披露”</footer>
"""
    return render_site_page(
        output_file=output_file,
        output_root=output_root,
        active_section="milestones",
        page_title=f"{family['name']} · 身经百战",
        meta_description=f"{family['name']} 官方模型版本时间线与技术对比。",
        secondary_navigation=render_milestone_navigation(catalog, family["slug"]),
        main_content=main_content,
        body_class="milestone-page",
    )


def render_notes_page(family: dict[str, Any], notes: dict) -> str:
    articles = []
    for release in family["releases"]:
        note = notes[release["slug"]]
        if not note or not note["ready"]:
            continue
        articles.append(
            f'    <article class="summary-article summary-topic-entry" '
            f'id="milestone-{html.escape(release["slug"], quote=True)}">\n'
            f'{render_note_content(note["content"])}\n'
            "    </article>"
        )
    article_markup = "\n".join(articles) or '    <p class="muted">暂无已完成的文章精读。</p>'
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(family['name'])} · 文章精读</title>
  <link rel="stylesheet" href="../assets/css/site.css">
</head>
<body class="summary-page">
  <main class="summary-page-shell">
    <header class="summary-topic-header">
      <a class="summary-back" href="{html.escape(family['slug'], quote=True)}.html">← 返回版本对比</a>
      <h1>{html.escape(family['name'])} · 文章精读</h1>
    </header>
    <div class="summary-topic-list">
{article_markup}
    </div>
  </main>
</body>
</html>
"""


def publish_milestone_models(
    catalog_path: str | Path,
    notes_root: str | Path,
    output_root: str | Path,
    only_family: str | None = None,
) -> dict[str, int]:
    """Render every ready family, using placeholders for missing local notes."""
    catalog = load_milestone_catalog(catalog_path)
    notes_path = Path(notes_root)
    destination = Path(output_root)
    destination.mkdir(parents=True, exist_ok=True)
    published = 0
    ready_notes = 0
    families = (
        [find_family(catalog, only_family)]
        if only_family
        else list(iter_families(catalog))
    )
    for topic, family in families:
        if family["page_status"] != "ready":
            continue
        notes = release_notes(notes_path, topic, family)
        ready_notes += sum(bool(note and note["ready"]) for note in notes.values())
        atomic_write_text(
            destination / f"{family['slug']}.html",
            render_family_page(
                catalog,
                topic,
                family,
                notes,
                output_file=destination / f"{family['slug']}.html",
                output_root=destination.parent,
            ),
        )
        atomic_write_text(
            destination / f"{family['slug']}-notes.html",
            render_notes_page(family, notes),
        )
        published += 1
    return {"published_families": published, "ready_release_notes": ready_notes}
