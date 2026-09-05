"""Generate the standalone GitHub Pages paper archive."""

import calendar
from collections import OrderedDict
import datetime
import html
import json
from pathlib import Path
import re
import unicodedata

from milestones.catalog import load_milestone_catalog
from papers.annotations.catalog import load_annotation_catalog, load_label_definitions
from papers.annotations.models import LabelDefinition, PaperAnnotation
from shared.rendering import atomic_write_text
from shared.search_index import SearchDocument, serialize_search_index
from shared.site_shell import (
    SITE_NAME,
    render_context_strip,
    render_journey_placeholder_page,
    render_section_intro,
    render_site_page,
)


ENTRY_PATTERN = re.compile(
    r"^\|\*\*(?P<date>[^*]+)\*\*\|\*\*(?P<title>.*?)\*\*\|"
    r"(?P<authors>.*?)\|\[(?P<pdf_label>[^]]+)]\((?P<pdf_url>[^)]+)\)\|"
    r"(?P<code>.*?)\|$"
)
RECENT_YEAR_COUNT = 3
NOTES_DIRECTORY_NAME = "notes"
SHOW_BOOK_NOTES_NAV = False
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MILESTONE_CATALOG = PROJECT_ROOT / "config" / "milestone_models.yaml"
DEFAULT_SITE_CONFIG = PROJECT_ROOT / "config" / "site.yaml"
DEFAULT_ANNOTATION_CATALOG = PROJECT_ROOT / "data" / "paper-annotations.json"


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")


def parse_entry(paper_id: str, entry: str) -> dict:
    match = ENTRY_PATTERN.match(entry.strip())
    if match is None:
        raise ValueError(f"Unexpected paper entry for {paper_id}: {entry[:100]}")

    values = match.groupdict()
    published = datetime.date.fromisoformat(values["date"])
    code_match = re.search(r"\[[^]]*]\(([^)]+)\)", values["code"])
    paper_url = values["pdf_url"].replace("http://arxiv.org/", "https://arxiv.org/")
    return {
        "id": paper_id,
        "date": published,
        "title": values["title"],
        "authors": values["authors"],
        "paper_url": paper_url,
        "code_url": code_match.group(1) if code_match else None,
    }


def _annotation_values(value: PaperAnnotation | dict) -> tuple[tuple[str, ...], str]:
    if isinstance(value, PaperAnnotation):
        return value.tags, value.paper_type
    return tuple(value["tags"]), value["paper_type"]


def build_archive(
    data: dict,
    labels: tuple[LabelDefinition, ...] | None = None,
    annotations: dict[str, PaperAnnotation | dict] | None = None,
) -> tuple[list[dict], OrderedDict]:
    categories = []
    themes = OrderedDict()

    if labels is None:
        labels = tuple(
            LabelDefinition(topic, topic, slugify(topic)) for topic in data
        )
    annotations = annotations or {}
    paper_rows: dict[str, dict] = {}
    legacy_topics: dict[str, list[str]] = {}
    for topic, entries in data.items():
        for paper_id, entry in entries.items():
            row = parse_entry(paper_id, entry)
            paper_rows.setdefault(paper_id, row)
            legacy_topics.setdefault(paper_id, [])
            if topic not in legacy_topics[paper_id]:
                legacy_topics[paper_id].append(topic)

    configured_names = {label.name for label in labels}
    for paper_id, row in paper_rows.items():
        annotation = annotations.get(paper_id)
        if annotation is None:
            tags = tuple(topic for topic in legacy_topics[paper_id] if topic in configured_names)
            paper_type = "paper"
            annotation_status = "pending"
        else:
            tags, paper_type = _annotation_values(annotation)
            annotation_status = "ready"
        row.update(tags=tags, paper_type=paper_type, annotation_status=annotation_status)

    for label in labels:
        topic = label.name
        rows = [row.copy() for row in paper_rows.values() if topic in row["tags"]]
        rows.sort(key=lambda row: (row["date"], row["id"]), reverse=True)

        grouped_years = {}
        for row in rows:
            if row["paper_type"] == "survey":
                grouped_years.setdefault(
                    row["date"].year, {"surveys": [], "months": {}}
                )["surveys"].append(row)
                continue
            week_start, _ = week_bounds(row["date"])
            if week_start.year == row["date"].year:
                year = week_start.year
                month = week_start.month
            else:
                # Keep January papers in their publication year when a natural
                # week starts in the previous December.
                year = row["date"].year
                month = row["date"].month
            grouped_years.setdefault(year, {"surveys": [], "months": {}})[
                "months"
            ].setdefault(month, {}).setdefault(week_start, []).append(row)

        years = OrderedDict()
        for year in sorted(grouped_years, reverse=True):
            months = OrderedDict()
            for month in sorted(grouped_years[year]["months"], reverse=True):
                weeks = grouped_years[year]["months"][month]
                months[month] = OrderedDict(
                    (week_start, weeks[week_start])
                    for week_start in sorted(weeks, reverse=True)
                )
            years[year] = {
                "surveys": sorted(
                    grouped_years[year]["surveys"],
                    key=lambda row: (row["date"], row["id"]),
                    reverse=True,
                ),
                "months": months,
            }

        category = {
            "topic": topic,
            "theme": topic,
            "subtype": None,
            "slug": label.slug,
            "count": len(rows),
            "years": years,
        }
        categories.append(category)
        themes.setdefault(topic, []).append(category)

    return categories, themes


def month_anchor(category: dict, year: int, month: int) -> str:
    return f'{category["slug"]}-{year}-{month:02d}'


def survey_anchor(category: dict, year: int) -> str:
    return f'{category["slug"]}-{year}-surveys'


def week_anchor(category: dict, year: int, month: int, week_start: datetime.date) -> str:
    return f'{month_anchor(category, year, month)}-week-{week_start.isoformat()}'


def week_bounds(published: datetime.date) -> tuple[datetime.date, datetime.date]:
    week_start = published - datetime.timedelta(days=published.weekday())
    return week_start, week_start + datetime.timedelta(days=6)


def week_label(week_start: datetime.date) -> str:
    week_end = week_start + datetime.timedelta(days=6)
    start_month = calendar.month_abbr[week_start.month]
    end_month = calendar.month_abbr[week_end.month]
    if week_start.year != week_end.year:
        return (
            f"{start_month} {week_start.day}, {week_start.year}"
            f"–{end_month} {week_end.day}, {week_end.year}"
        )
    if week_start.month != week_end.month:
        return f"{start_month} {week_start.day}–{end_month} {week_end.day}"
    return f"{start_month} {week_start.day}–{week_end.day}"


def month_paper_count(weeks: OrderedDict) -> int:
    return sum(len(rows) for rows in weeks.values())


def year_paper_count(year_data: dict) -> int:
    return len(year_data["surveys"]) + sum(
        month_paper_count(weeks) for weeks in year_data["months"].values()
    )


def filter_recent_archive(
    categories: list[dict], current_year: int, year_count: int = RECENT_YEAR_COUNT
) -> tuple[list[dict], OrderedDict]:
    earliest_year = current_year - year_count + 1
    recent_categories = []
    recent_themes = OrderedDict()

    for category in categories:
        years = OrderedDict(
            (year, year_data)
            for year, year_data in category["years"].items()
            if earliest_year <= year <= current_year
        )

        recent_category = {
            **category,
            "count": sum(year_paper_count(year_data) for year_data in years.values()),
            "years": years,
        }
        recent_categories.append(recent_category)
        recent_themes.setdefault(recent_category["theme"], []).append(recent_category)

    return recent_categories, recent_themes


def _iter_category_rows(category: dict):
    for year_data in category["years"].values():
        yield from year_data["surveys"]
        for weeks in year_data["months"].values():
            for rows in weeks.values():
                yield from rows


def _summary_for_paper(summary_catalog: dict[str, dict], paper_id: str) -> dict:
    for topic_summaries in summary_catalog.values():
        summary = topic_summaries.get(paper_id)
        if summary:
            return summary
    return {}


def build_paper_search_documents(
    categories: list[dict], summary_catalog: dict[str, dict]
) -> list[SearchDocument]:
    """Create one public result per canonical paper, preferring ready summaries."""
    documents: dict[str, SearchDocument] = {}
    for category in categories:
        for row in _iter_category_rows(category):
            paper_id = row["id"]
            summary = _summary_for_paper(summary_catalog, paper_id)
            ready_summary = summary.get("status") == "ready" and summary.get("url")
            url = (
                summary["url"]
                if ready_summary
                else f"index.html#paper-{paper_id}"
            )
            document = SearchDocument(
                id=f"paper:{paper_id}",
                title=row["title"],
                url=url,
                section="learning",
                kind="paper",
                published_at=row["date"].isoformat(),
            )
            existing = documents.get(paper_id)
            if existing is None or (
                existing.url.startswith("index.html#") and ready_summary
            ):
                documents[paper_id] = document
    return list(documents.values())


def render_sidebar(
    themes: OrderedDict,
    show_book_notes: bool = SHOW_BOOK_NOTES_NAV,
) -> str:
    output = [
        '      <div class="sidebar-actions">',
        '        <button type="button" data-sidebar-action="expand">Expand all</button>',
        '        <button type="button" data-sidebar-action="collapse">Collapse all</button>',
        '      </div>',
    ]

    for theme_index, (theme, categories) in enumerate(themes.items()):
        theme_count = sum(category["count"] for category in categories)
        open_attribute = " open" if theme_index == 0 else ""
        output.append(f'    <details class="nav-theme"{open_attribute}>')
        output.append(
            f'      <summary><span>{html.escape(theme)}</span>'
            f'<span class="nav-count">{theme_count}</span></summary>'
        )

        for category_index, category in enumerate(categories):
            has_subtype = category["subtype"] is not None
            if has_subtype:
                category_open = " open" if theme_index == 0 and category_index == 0 else ""
                output.append(f'      <details class="nav-subtopic"{category_open}>')
                output.append(
                    f'        <summary><span>{html.escape(category["subtype"])}</span>'
                    f'<span class="nav-count">{category["count"]}</span></summary>'
                )

            indent = "        " if has_subtype else "      "
            for year_index, (year, year_data) in enumerate(category["years"].items()):
                year_count = year_paper_count(year_data)
                year_open = " open" if theme_index == 0 and category_index == 0 and year_index == 0 else ""
                output.append(f'{indent}<details class="nav-year"{year_open}>')
                output.append(
                    f'{indent}  <summary><span>{year}</span>'
                    f'<span class="nav-count">{year_count}</span></summary>'
                )
                output.append(f'{indent}  <ul>')
                if year_data["surveys"]:
                    anchor = survey_anchor(category, year)
                    output.append(
                        f'{indent}    <li><a href="#{anchor}">'
                        f'<span>Surveys</span><span class="nav-count">'
                        f'{len(year_data["surveys"])}</span></a></li>'
                    )
                for month, weeks in year_data["months"].items():
                    anchor = month_anchor(category, year, month)
                    output.append(
                        f'{indent}    <li><a href="#{anchor}">'
                        f'<span>{calendar.month_name[month]}</span>'
                        f'<span class="nav-count">{month_paper_count(weeks)}</span></a></li>'
                    )
                output.append(f'{indent}  </ul>')
                output.append(f'{indent}</details>')

            if has_subtype:
                output.append("      </details>")

        output.append("    </details>")

    return "\n".join(output)


def load_summary_catalog(output_path: str | Path) -> dict[str, dict]:
    notes_directory = Path(output_path).parent / NOTES_DIRECTORY_NAME
    if not notes_directory.is_dir():
        return {}

    catalog = {}
    manifest_pattern = re.compile(
        r'<script type="application/json" id="summary-catalog">(.*?)</script>',
        re.DOTALL,
    )
    for summary_path in sorted(notes_directory.glob("*.html")):
        document = summary_path.read_text(encoding="utf-8")
        match = manifest_pattern.search(document)
        if match is None:
            continue
        try:
            manifest = json.loads(match.group(1))
        except json.JSONDecodeError as error:
            raise ValueError(f"Invalid summary manifest: {summary_path}") from error
        topic = manifest.get("topic")
        papers = manifest.get("papers")
        if not isinstance(topic, str) or not isinstance(papers, dict):
            raise ValueError(f"Invalid summary manifest schema: {summary_path}")
        catalog[topic] = papers
    return catalog


def render_table(
    rows: list[dict],
    topic: str,
    summary_catalog: dict[str, dict],
    candidate_statuses: dict[str, str] | None = None,
    anchored_papers: set[str] | None = None,
    label_slugs: dict[str, str] | None = None,
) -> str:
    output = [
        '<div class="table-scroll">',
        '  <table class="paper-table">',
        '    <thead><tr><th>Arxiv ID</th><th>Paper</th><th>Authors</th><th>Summary</th></tr></thead>',
        '    <tbody>',
    ]
    candidate_statuses = candidate_statuses or {}
    anchored_papers = anchored_papers if anchored_papers is not None else set()
    label_slugs = label_slugs or {}
    for row in rows:
        paper_url = html.escape(row["paper_url"], quote=True)
        summary = _summary_for_paper(summary_catalog, row["id"])
        summary_cell = '<span class="muted">—</span>'
        if summary.get("status") == "pending":
            summary_cell = '<span class="summary-pending">待生成</span>'
        elif summary.get("status") == "ready" and summary.get("url"):
            summary_url = html.escape(summary["url"], quote=True)
            summary_id = html.escape(f"summary-{row['id']}", quote=True)
            summary_cell = (
                f'<a class="summary-link" href="{summary_url}" '
                f'data-summary-url="{summary_url}" data-summary-id="{summary_id}" '
                'aria-controls="paper-summary-panel" aria-expanded="false">要点</a>'
            )
        elif candidate_statuses.get(row["id"]) in {"pending", "accepted"}:
            summary_cell = '<span class="summary-pending">待生成</span>'
        anchor = ""
        if row["id"] not in anchored_papers:
            anchor = f' id="paper-{html.escape(row["id"], quote=True)}"'
            anchored_papers.add(row["id"])
        tags = "".join(
            f'<a class="paper-tag" href="?tag={html.escape(label_slugs.get(tag, slugify(tag)), quote=True)}'
            f'#{html.escape(label_slugs.get(tag, slugify(tag)), quote=True)}" '
            f'data-paper-tag="{html.escape(label_slugs.get(tag, slugify(tag)), quote=True)}">'
            f'{html.escape(tag)}</a>'
            for tag in row.get("tags", ())
        )
        tag_markup = f'<span class="paper-tags">{tags}</span>' if tags else ""
        output.append(
            f"      <tr{anchor}>"
            f'<td class="paper-id" data-label="Arxiv ID"><a href="{paper_url}" target="_blank" rel="noopener">'
            f'{html.escape(row["id"])}</a></td>'
            f'<td class="paper-title" data-label="Paper"><a class="paper-title-link" href="{paper_url}" target="_blank" rel="noopener">'
            f'{html.escape(row["title"])}</a>{tag_markup}</td>'
            f'<td data-label="Authors">{html.escape(row["authors"])}</td>'
            f'<td class="paper-summary" data-label="Summary">{summary_cell}</td>'
            "</tr>"
        )
    output.extend(["    </tbody>", "  </table>", "</div>"])
    return "\n".join(output)


def render_content(
    categories: list[dict],
    summary_catalog: dict[str, dict],
    candidate_statuses: dict[str, str] | None = None,
    label_slugs: dict[str, str] | None = None,
) -> str:
    output = []
    anchored_papers: set[str] = set()
    for category_index, category in enumerate(categories):
        eyebrow = category["theme"]
        heading = category["subtype"] or category["theme"]
        active_class = " is-topic-active" if category_index == 0 else ""
        output.extend([
            f'<section class="topic-section{active_class}" id="{category["slug"]}" '
            f'data-topic-section="{category["slug"]}">',
            '  <header class="topic-header">',
            f'    <p>{html.escape(eyebrow)}</p>',
            f'    <h2>{html.escape(heading)}</h2>',
            f'    <span>{category["count"]} papers</span>',
            '  </header>',
        ])
        if not category["years"]:
            output.append('  <p class="archive-empty">No papers in the current archive window.</p>')
        for year_index, (year, year_data) in enumerate(category["years"].items()):
            surveys = year_data["surveys"]
            months = year_data["months"]
            year_count = year_paper_count(year_data)
            year_id = f'{category["slug"]}-{year}-content'
            year_expanded = "true" if year_index == 0 else "false"
            selected_period = "surveys" if surveys else next(iter(months))
            output.append(
                f'  <section class="archive-year" data-archive-year '
                f'data-expanded="{year_expanded}">'
            )
            output.extend([
                '    <div class="archive-year-header">',
                f'      <button class="archive-year-toggle" type="button" '
                f'aria-expanded="{year_expanded}" aria-controls="{year_id}">',
                f'        <span>{year}</span>',
                '      </button>',
                f'      <div class="archive-month-tabs" role="tablist" '
                f'aria-label="{year} paper periods">',
            ])
            surveys_anchor = survey_anchor(category, year)
            survey_selected = selected_period == "surveys"
            if surveys:
                output.append(
                    f'        <button id="{surveys_anchor}-tab" type="button" role="tab" '
                    f'aria-controls="{surveys_anchor}" aria-selected="{str(survey_selected).lower()}" '
                    f'tabindex="{0 if survey_selected else -1}" data-period-target="{surveys_anchor}">'
                    f'Surveys <span>{len(surveys)}</span></button>'
                )
            else:
                output.append(
                    '        <button type="button" role="tab" disabled aria-disabled="true" '
                    'aria-selected="false">Surveys <span>0</span></button>'
                )
            for month in range(1, 13):
                weeks = months.get(month)
                month_name = calendar.month_abbr[month]
                if weeks is None:
                    output.append(
                        f'        <button type="button" role="tab" disabled '
                        f'aria-disabled="true" aria-selected="false">{month_name}</button>'
                    )
                    continue
                anchor = month_anchor(category, year, month)
                is_selected = month == selected_period
                selected = "true" if is_selected else "false"
                tabindex = "0" if is_selected else "-1"
                output.append(
                    f'        <button id="{anchor}-tab" type="button" role="tab" '
                    f'aria-controls="{anchor}" aria-selected="{selected}" '
                    f'tabindex="{tabindex}" data-period-target="{anchor}">{month_name}</button>'
                )
            output.extend([
                '      </div>',
                f'      <span class="archive-year-count">{year_count} papers</span>',
                '    </div>',
                f'    <div class="archive-year-content" id="{year_id}">',
            ])
            if surveys:
                output.append(
                    f'      <section class="archive-period-panel archive-survey-panel" '
                    f'id="{surveys_anchor}" role="tabpanel" aria-labelledby="{surveys_anchor}-tab" '
                    f'aria-hidden="{"false" if survey_selected else "true"}" '
                    f'data-active="{str(survey_selected).lower()}" data-period="surveys">'
                )
                output.append(
                    render_table(
                        surveys,
                        category["topic"],
                        summary_catalog,
                        candidate_statuses,
                        anchored_papers,
                        label_slugs,
                    )
                )
                output.append("      </section>")
            for month, weeks in months.items():
                anchor = month_anchor(category, year, month)
                is_active = month == selected_period
                active = "true" if is_active else "false"
                output.append(
                    f'      <section class="archive-period-panel archive-month-panel" id="{anchor}" '
                    f'role="tabpanel" aria-labelledby="{anchor}-tab" '
                    f'aria-hidden="{"false" if is_active else "true"}" data-active="{active}">'
                )
                for week_index, (week_start, rows) in enumerate(weeks.items()):
                    anchor_id = week_anchor(category, year, month, week_start)
                    week_open = " open" if week_index == 0 else ""
                    output.append(
                        f'        <details class="archive-week" id="{anchor_id}"{week_open}>'
                    )
                    output.append(
                        f'          <summary><span>{week_label(week_start)}</span>'
                        f'<span>{len(rows)} papers</span></summary>'
                    )
                    output.append(
                        render_table(
                            rows,
                            category["topic"],
                            summary_catalog,
                            candidate_statuses,
                            anchored_papers,
                            label_slugs,
                        )
                    )
                    output.append("        </details>")
                output.append("      </section>")
            output.extend(["    </div>", "  </section>"])
        output.append("</section>")
    archive = "\n".join(output)
    return f"""<div class="learning-workspace">
  <div class="learning-archive">
{archive}
  </div>
  <div data-summary-panel-home></div>
  <aside class="paper-summary-panel" id="paper-summary-panel" aria-live="polite">
    <header class="paper-summary-header"><h2 data-summary-title>论文要点</h2></header>
    <div data-summary-content><p>选择一篇已有摘要的论文查看要点。</p></div>
    <a data-summary-direct hidden>打开完整总结 →</a>
  </aside>
</div>"""


def render_paper_navigation(categories: list[dict]) -> str:
    """Render full paper-topic names as the learning archive switcher."""
    links = tuple(
        (category["topic"], f'?tag={category["slug"]}#{category["slug"]}')
        for category in categories
    )
    filter_keys = tuple(category["slug"] for category in categories)
    return render_context_strip(links, filter_keys=filter_keys)


def load_candidate_statuses(candidate_path: str | Path | None) -> dict[str, str]:
    if candidate_path is None or not Path(candidate_path).is_file():
        return {}
    payload = json.loads(Path(candidate_path).read_text(encoding="utf-8"))
    if payload.get("version") != 1 or not isinstance(payload.get("papers"), dict):
        raise ValueError(f"Invalid candidate ledger schema: {candidate_path}")
    return {
        paper_id: entry.get("status")
        for paper_id, entry in payload["papers"].items()
        if isinstance(entry, dict) and entry.get("status") in {"pending", "accepted"}
    }


def generate_site(
    json_path: str | Path,
    output_path: str | Path,
    candidate_path: str | Path | None = None,
    milestone_catalog_path: str | Path = DEFAULT_MILESTONE_CATALOG,
    *,
    output_root: str | Path | None = None,
    search_index_path: str | Path | None = None,
    generated_on: datetime.date | None = None,
    config_path: str | Path = DEFAULT_SITE_CONFIG,
    annotation_path: str | Path = DEFAULT_ANNOTATION_CATALOG,
    writings_source_root: str | Path = PROJECT_ROOT / "content" / "writings",
    writings_report_path: str | Path = PROJECT_ROOT / "build" / "reports" / "writings.json",
) -> None:
    data = json.loads(Path(json_path).read_text(encoding="utf-8"))
    labels = load_label_definitions(config_path)
    annotations = load_annotation_catalog(annotation_path, labels)
    milestone_catalog = load_milestone_catalog(milestone_catalog_path)
    all_categories, _ = build_archive(data, labels, annotations)
    today = generated_on or datetime.date.today()
    categories, themes = filter_recent_archive(all_categories, today.year)
    summary_catalog = load_summary_catalog(output_path)
    candidate_statuses = load_candidate_statuses(candidate_path)
    label_slugs = {label.name: label.slug for label in labels}
    updated = today.isoformat()

    page_output = Path(output_path)
    site_root = Path(output_root) if output_root is not None else page_output.parent
    archive_rows = [
        row for category in categories for row in _iter_category_rows(category)
    ]
    latest_date = max((row["date"] for row in archive_rows), default=today)
    latest_count = sum(row["date"] == latest_date for row in archive_rows)
    archive_count = len(archive_rows)
    main_content = f"""    <div class="section-sticky-header">
    <header class="hero section-header">
{render_section_intro("learning")}
      <div class="hero-stats" aria-label="主题统计">
        <div><strong>{latest_count:,}</strong><span>LATEST BATCH</span></div>
        <div><strong>{archive_count:,}</strong><span>ARCHIVED</span></div>
      </div>
    </header>
{render_paper_navigation(categories)}
    </div>
{render_content(categories, summary_catalog, candidate_statuses, label_slugs)}
    <footer>Generated from arXiv metadata · Source: <a href="https://github.com/zyf515730395/TOGOS">{SITE_NAME}</a></footer>
"""
    document = render_site_page(
        output_file=page_output,
        output_root=site_root,
        active_section="learning",
        page_title=SITE_NAME,
        meta_description=(
            "A daily index of image, video, and 3D generation, neural rendering, "
            "and depth estimation papers from arXiv."
        ),
        main_content=main_content,
        body_class="learning-page",
        sidebar_status=f"{updated.replace('-', '.')} / DAILY",
    )
    atomic_write_text(page_output, document)

    journey_destination = site_root / "journeys" / "index.html"
    atomic_write_text(
        journey_destination,
        render_journey_placeholder_page(
            output_file=journey_destination,
            output_root=site_root,
        ),
    )

    from milestones.publisher import build_milestone_search_documents
    from writings.publisher import (
        abort_writings_publication,
        commit_writings_and_search,
        prepare_writings_publication,
    )

    prepared_writings = prepare_writings_publication(
        writings_source_root,
        site_root / "writings",
        writings_report_path,
        today,
    )

    try:
        search_documents = [
            *build_paper_search_documents(categories, summary_catalog),
            *build_milestone_search_documents(milestone_catalog),
            *prepared_writings.result.search_documents,
        ]
        search_content = serialize_search_index(search_documents, generated_on=today)
    except Exception:
        abort_writings_publication(prepared_writings)
        raise
    commit_writings_and_search(
        prepared_writings,
        search_index_path or site_root / "search-index.json",
        search_content,
    )
    for issue in prepared_writings.result.issues:
        source = issue.source.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        message = issue.message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print(f"::warning file={source},title=Writings {issue.code}::{message}")
    result = prepared_writings.result
    print(
        "Writings publication: "
        f"published={len(result.published)} retained={len(result.retained)} "
        f"skipped={len(result.skipped)} removed={len(result.removed)}"
    )
