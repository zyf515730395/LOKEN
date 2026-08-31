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
from shared.rendering import atomic_write_text
from shared.search_index import SearchDocument, serialize_search_index
from shared.site_shell import render_empty_section_page, render_section_intro, render_site_page


ENTRY_PATTERN = re.compile(
    r"^\|\*\*(?P<date>[^*]+)\*\*\|\*\*(?P<title>.*?)\*\*\|"
    r"(?P<authors>.*?)\|\[(?P<pdf_label>[^]]+)]\((?P<pdf_url>[^)]+)\)\|"
    r"(?P<code>.*?)\|$"
)
SITE_TITLE = "TOGOS"
RECENT_YEAR_COUNT = 3
NOTES_DIRECTORY_NAME = "notes"
SHOW_BOOK_NOTES_NAV = False
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MILESTONE_CATALOG = PROJECT_ROOT / "config" / "milestone_models.yaml"


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


def build_archive(data: dict) -> tuple[list[dict], OrderedDict]:
    categories = []
    themes = OrderedDict()

    for topic, entries in data.items():
        rows = [parse_entry(paper_id, entry) for paper_id, entry in entries.items()]
        rows.sort(key=lambda row: (row["date"], row["id"]), reverse=True)

        grouped_years = {}
        for row in rows:
            week_start, _ = week_bounds(row["date"])
            if week_start.year == row["date"].year:
                year = week_start.year
                month = week_start.month
            else:
                # Keep January papers in their publication year when a natural
                # week starts in the previous December.
                year = row["date"].year
                month = row["date"].month
            grouped_years.setdefault(year, {}).setdefault(month, {}).setdefault(
                week_start, []
            ).append(row)

        years = OrderedDict()
        for year in sorted(grouped_years, reverse=True):
            months = OrderedDict()
            for month in sorted(grouped_years[year], reverse=True):
                weeks = grouped_years[year][month]
                months[month] = OrderedDict(
                    (week_start, weeks[week_start])
                    for week_start in sorted(weeks, reverse=True)
                )
            years[year] = months

        category = {
            "topic": topic,
            "theme": topic,
            "subtype": None,
            "slug": slugify(topic),
            "count": len(rows),
            "years": years,
        }
        categories.append(category)
        themes.setdefault(topic, []).append(category)

    return categories, themes


def month_anchor(category: dict, year: int, month: int) -> str:
    return f'{category["slug"]}-{year}-{month:02d}'


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


def year_paper_count(months: OrderedDict) -> int:
    return sum(month_paper_count(weeks) for weeks in months.values())


def filter_recent_archive(
    categories: list[dict], current_year: int, year_count: int = RECENT_YEAR_COUNT
) -> tuple[list[dict], OrderedDict]:
    earliest_year = current_year - year_count + 1
    recent_categories = []
    recent_themes = OrderedDict()

    for category in categories:
        years = OrderedDict(
            (year, months)
            for year, months in category["years"].items()
            if earliest_year <= year <= current_year
        )
        if not years:
            continue

        recent_category = {
            **category,
            "count": sum(year_paper_count(months) for months in years.values()),
            "years": years,
        }
        recent_categories.append(recent_category)
        recent_themes.setdefault(recent_category["theme"], []).append(recent_category)

    return recent_categories, recent_themes


def _iter_category_rows(category: dict):
    for months in category["years"].values():
        for weeks in months.values():
            for rows in weeks.values():
                yield from rows


def build_paper_search_documents(
    categories: list[dict], summary_catalog: dict[str, dict]
) -> list[SearchDocument]:
    """Create one public result per canonical paper, preferring ready summaries."""
    documents: dict[str, SearchDocument] = {}
    for category in categories:
        topic_summaries = summary_catalog.get(category["topic"], {})
        for row in _iter_category_rows(category):
            paper_id = row["id"]
            summary = topic_summaries.get(paper_id, {})
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
            for year_index, (year, months) in enumerate(category["years"].items()):
                year_count = year_paper_count(months)
                year_open = " open" if theme_index == 0 and category_index == 0 and year_index == 0 else ""
                output.append(f'{indent}<details class="nav-year"{year_open}>')
                output.append(
                    f'{indent}  <summary><span>{year}</span>'
                    f'<span class="nav-count">{year_count}</span></summary>'
                )
                output.append(f'{indent}  <ul>')
                for month, weeks in months.items():
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
) -> str:
    output = [
        '<div class="table-scroll">',
        '  <table class="paper-table">',
        '    <thead><tr><th>Arxiv ID</th><th>Paper</th><th>Authors</th><th>Summary</th></tr></thead>',
        '    <tbody>',
    ]
    topic_summaries = summary_catalog.get(topic, {})
    candidate_statuses = candidate_statuses or {}
    anchored_papers = anchored_papers if anchored_papers is not None else set()
    for row in rows:
        paper_url = html.escape(row["paper_url"], quote=True)
        summary = topic_summaries.get(row["id"], {})
        summary_cell = '<span class="muted">—</span>'
        if summary.get("status") == "pending":
            summary_cell = '<span class="summary-pending">待生成</span>'
        elif summary.get("status") == "ready" and summary.get("url"):
            summary_url = html.escape(summary["url"], quote=True)
            summary_id = html.escape(f"summary-{row['id']}", quote=True)
            summary_cell = (
                f'<a class="summary-link" href="{summary_url}" '
                f'data-summary-url="{summary_url}" data-summary-id="{summary_id}" '
                'aria-haspopup="dialog">查看要点</a>'
            )
        elif candidate_statuses.get(row["id"]) in {"pending", "accepted"}:
            summary_cell = '<span class="summary-pending">待生成</span>'
        anchor = ""
        if row["id"] not in anchored_papers:
            anchor = f' id="paper-{html.escape(row["id"], quote=True)}"'
            anchored_papers.add(row["id"])
        output.append(
            f"      <tr{anchor}>"
            f'<td class="paper-id" data-label="Arxiv ID"><a href="{paper_url}" target="_blank" rel="noopener">'
            f'{html.escape(row["id"])}</a></td>'
            f'<td class="paper-title" data-label="Paper"><a href="{paper_url}" target="_blank" rel="noopener">'
            f'{html.escape(row["title"])}</a></td>'
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
) -> str:
    output = []
    anchored_papers: set[str] = set()
    for category in categories:
        eyebrow = category["theme"]
        heading = category["subtype"] or category["theme"]
        output.extend([
            f'<section class="topic-section" id="{category["slug"]}">',
            '  <header class="topic-header">',
            f'    <p>{html.escape(eyebrow)}</p>',
            f'    <h2>{html.escape(heading)}</h2>',
            f'    <span>{category["count"]} papers</span>',
            '  </header>',
        ])
        for year_index, (year, months) in enumerate(category["years"].items()):
            year_count = year_paper_count(months)
            year_id = f'{category["slug"]}-{year}-content'
            year_expanded = "true" if year_index == 0 else "false"
            selected_month = next(iter(months))
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
                f'aria-label="{year} months">',
            ])
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
                is_selected = month == selected_month
                selected = "true" if is_selected else "false"
                tabindex = "0" if is_selected else "-1"
                output.append(
                    f'        <button id="{anchor}-tab" type="button" role="tab" '
                    f'aria-controls="{anchor}" aria-selected="{selected}" '
                    f'tabindex="{tabindex}" data-month-target="{anchor}">{month_name}</button>'
                )
            output.extend([
                '      </div>',
                f'      <span class="archive-year-count">{year_count} papers</span>',
                '    </div>',
                f'    <div class="archive-year-content" id="{year_id}">',
            ])
            for month, weeks in months.items():
                anchor = month_anchor(category, year, month)
                is_active = month == selected_month
                active = "true" if is_active else "false"
                output.append(
                    f'      <section class="archive-month-panel" id="{anchor}" '
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
                        )
                    )
                    output.append("        </details>")
                output.append("      </section>")
            output.extend(["    </div>", "  </section>"])
        output.append("</section>")
    return "\n".join(output)


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
    writings_source_root: str | Path = PROJECT_ROOT / "content" / "writings",
    writings_report_path: str | Path = PROJECT_ROOT / "build" / "reports" / "writings.json",
) -> None:
    data = json.loads(Path(json_path).read_text(encoding="utf-8"))
    milestone_catalog = load_milestone_catalog(milestone_catalog_path)
    all_categories, _ = build_archive(data)
    today = generated_on or datetime.date.today()
    categories, themes = filter_recent_archive(all_categories, today.year)
    summary_catalog = load_summary_catalog(output_path)
    candidate_statuses = load_candidate_statuses(candidate_path)
    updated = today.isoformat()
    total_papers = sum(category["count"] for category in categories)
    years = {
        year
        for category in categories
        for year in category["years"]
    }

    page_output = Path(output_path)
    site_root = Path(output_root) if output_root is not None else page_output.parent
    main_content = f"""    <header class="hero">
{render_section_intro("learning")}
      <h1>今天学什么</h1>
      <div class="hero-stats" aria-label="Archive statistics">
        <div><strong>{total_papers:,}</strong><span>Papers</span></div>
        <div><strong>{len(themes)}</strong><span>Topics</span></div>
        <div><strong>{len(years)}</strong><span>Years</span></div>
      </div>
      <p class="updated">Updated {updated}</p>
    </header>
{render_content(categories, summary_catalog, candidate_statuses)}
    <footer>Generated from arXiv metadata · Source: <a href="https://github.com/zyf515730395/TOGOS">{SITE_TITLE}</a></footer>
"""
    summary_dialog = """  <dialog class="summary-dialog" id="summary-dialog" aria-labelledby="summary-dialog-title">
    <div class="summary-dialog-shell">
      <header class="summary-dialog-header">
        <h2 id="summary-dialog-title">论文要点</h2>
        <button type="button" class="summary-dialog-close" data-summary-close aria-label="关闭">×</button>
      </header>
      <div class="summary-dialog-content" data-summary-content>
        <p class="muted">正在加载…</p>
      </div>
    </div>
  </dialog>
"""
    document = render_site_page(
        output_file=page_output,
        output_root=site_root,
        active_section="learning",
        page_title=SITE_TITLE,
        meta_description=(
            "A daily index of image, video, and 3D generation, neural rendering, "
            "and depth estimation papers from arXiv."
        ),
        secondary_navigation=render_sidebar(themes),
        main_content=main_content,
        body_class="learning-page",
        trailing_dialogs=summary_dialog,
    )
    atomic_write_text(page_output, document)

    empty_pages = (
        (
            "journeys",
            site_root / "journeys" / "index.html",
            "城市坐标与摄影作品会在这里出现。",
        ),
    )
    for section_key, destination, body_copy in empty_pages:
        atomic_write_text(
            destination,
            render_empty_section_page(
                output_file=destination,
                output_root=site_root,
                section_key=section_key,
                body_copy=body_copy,
            ),
        )

    from milestones.publisher import build_milestone_search_documents
    from writings.publisher import (
        commit_writings_and_search,
        prepare_writings_publication,
    )

    prepared_writings = prepare_writings_publication(
        writings_source_root,
        site_root / "writings",
        writings_report_path,
        today,
    )

    search_documents = [
        *build_paper_search_documents(categories, summary_catalog),
        *build_milestone_search_documents(milestone_catalog),
        *prepared_writings.result.search_documents,
    ]
    search_content = serialize_search_index(search_documents, generated_on=today)
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
