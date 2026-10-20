"""Publish bounded paper digests from public records and published summaries.

The candidate ledger is consulted only for visibility and its immutable first
collected_at timestamp, never as a content source. First collection is not first
publication on this website. Legacy/overlay records without this timestamp use
their explicitly labeled publication date; partial dates are never invented.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import html
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo

import bleach
import yaml

from papers.annotations.catalog import load_annotation_catalog, load_annotation_definitions, load_label_definitions
from papers.conference_library import library_rows, load_library, retain_library_matches
from papers.paths import CONFIG
from papers.site import build_archive, filter_recent_archive, load_candidate_statuses, parse_entry, _iter_category_rows
from shared.periodicals import render_periodical_page
from shared.rendering import atomic_write_text
from papers.digest_analysis import load_analysis, render_topic

DATE_NOTE = ('按北京时间首次采集日期归档（仅已公开论文）；无首次采集记录的历史论文按发表日期归档，逐篇标明。'
             '仅月份或年份已知的记录不分配到某一天。周报覆盖周一至周日；逐篇问题与贡献依据公开摘要生成，再综合分析主题趋势。未更新的历史条目保留原摘要结论并明确标记。')
WEEKLY_NOTE = ('周一至周日的技术趋势回顾，基于本期全部公开论文综合分析，保留支撑引用，不逐篇罗列。'
               '按北京时间首次采集日期归档；缺少采集记录的历史论文使用已核验发表日期。结论仅适用于本期样本。')


def _first_collected(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return stamp.astimezone(ZoneInfo('Asia/Shanghai')).date()
    except ValueError:
        return None


def load_public_papers(config_path: str | Path = CONFIG, *, today: date | None = None,
                       archive_path: str | Path | None = None, candidate_path: str | Path | None = None,
                       annotation_path: str | Path | None = None) -> tuple[list[dict], list[tuple[str, str]]]:
    """Apply the same curation, taxonomy, overlay and visibility gates as site.py."""
    path = Path(config_path).resolve()
    config = yaml.safe_load(path.read_text(encoding='utf-8'))
    project = path.parent.parent

    def source(key: str, fallback: str) -> Path:
        target = Path(config.get(key, fallback))
        return target if target.is_absolute() else project / target

    archive_source = Path(archive_path) if archive_path is not None else source('json_gitpage_path', 'content/papers/archive.json')
    archive = json.loads(archive_source.read_text(encoding='utf-8'))
    ledger_path = Path(candidate_path) if candidate_path is not None else source('candidate_ledger_path', 'content/papers/arxiv-candidates.json')
    ledger = json.loads(ledger_path.read_text(encoding='utf-8'))
    cutoff = config.get('collection', {}).get('review_required_since')
    statuses = load_candidate_statuses(ledger_path, review_required_since=str(cutoff)) if cutoff is not None else {}
    labels = load_label_definitions(path)
    annotation_source = Path(annotation_path) if annotation_path is not None else source('annotation_path', 'content/papers/paper-annotations.json')
    annotations = load_annotation_catalog(annotation_source, load_annotation_definitions(path))
    library = load_library(source('conference_library_path', 'content/papers/conference-library.json'))
    # Dedupe against the complete archive before applying presentation filters.
    extra = library_rows(library, archive, ledger)
    excluded = {int(year) for year in config.get('publication', {}).get('excluded_years', [])}
    public_archive = {topic: {key: value for key, value in entries.items() if parse_entry(key, value)['date'].year not in excluded}
                      for topic, entries in archive.items()}
    extra = [row for row in extra if row['date'].year not in excluded]
    categories, _ = build_archive(public_archive, labels, annotations, statuses, extra)
    all_rows = [row for category in categories for row in _iter_category_rows(category)]
    retain_library_matches(all_rows, library, ledger)
    visible, _ = filter_recent_archive(categories, (today or date.today()).year)
    unique = {row['id']: row for category in visible for row in _iter_category_rows(category)}
    output = []
    for key, row in unique.items():
        first = _first_collected(ledger.get('papers', {}).get(key, {}).get('collected_at'))
        # Conference records can carry durable first-seen metadata in future.
        if first is None and row.get('conference_library'):
            first = _first_collected(library['papers'].get(key, {}).get('first_seen_at'))
        if first is None and row.get('date_precision', 3) < 3:
            continue
        output.append({**row, 'digest_date': first or row['date'],
                       'date_basis': 'first_collected' if first else 'publication'})
    return output, [(label.name, label.slug) for label in labels]


def load_published_summaries(output_root: str | Path) -> dict[str, str]:
    """Read only ready manifest-bound articles; strip scripts and unsafe links."""
    summaries: dict[str, str] = {}
    manifest_pattern = re.compile(r'<script type="application/json" id="summary-catalog">(.*?)</script>', re.S)
    article_pattern = re.compile(r'<article\b[^>]*\bid=["\']summary-([^"\']+)["\'][^>]*>(.*?)</article>', re.S)
    for path in sorted((Path(output_root) / 'notes').glob('*.html')):
        document = path.read_text(encoding='utf-8')
        match = manifest_pattern.search(document)
        if not match:
            continue
        manifest = json.loads(match.group(1))
        ready = {key for key, item in manifest.get('papers', {}).items()
                 if isinstance(item, dict) and item.get('status') == 'ready'
                 and item.get('url') == f'notes/{path.name}#summary-{key}'}
        for article in article_pattern.finditer(document):
            key, body = article.groups()
            if key not in ready or key in summaries:
                continue
            body = re.sub(r'<h[12]\b[^>]*>.*?</h[12]>', '', body, count=1, flags=re.S)
            body = re.sub(r'<(script|style)\b[^>]*>.*?</\1>', '', body, flags=re.S | re.I)
            body = re.sub(r'<(/?)h[23]\b[^>]*>', r'<\1h4>', body)
            summaries[key] = bleach.clean(body, tags={'p','h4','ul','ol','li','strong','em','code','pre','blockquote','a','br'},
                attributes={'a': lambda tag, name, value: name == 'href' and value.startswith(('https://','http://'))},
                protocols={'https','http'}, strip=True)
    return summaries


def _paper_html(row: dict, summaries: dict[str, str]) -> str:
    url = str(row.get('paper_url', ''))
    title = html.escape(str(row['title']))
    if url.startswith(('https://', 'http://')):
        title = f'<a href="{html.escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">{title}</a>'
    basis = '首次采集' if row['date_basis'] == 'first_collected' else '论文发表日期（缺少首次采集记录）'
    public_date = row.get('published_at', row['date'].isoformat())
    summary = summaries.get(row['id'])
    content = f'<div class="digest-summary">{summary}</div>' if summary else '<p class="digest-summary-missing">摘要尚未发布。可通过标题查看论文原文。</p>'
    return (f'<article class="digest-paper"><h3>{title}</h3>'
            f'<p class="digest-paper-meta">{html.escape(str(row.get("display_id", row["id"])))} · '
            f'{basis} {row["digest_date"].isoformat()} · 发表 {html.escape(str(public_date))}</p>{content}</article>')


def load_digest_evidence(output_root: Path, analysis_root: Path) -> dict[str, str]:
    from papers.digest_analysis import evidence_hash
    summaries = load_published_summaries(output_root)
    path = analysis_root / 'official-abstracts.json'
    if path.exists():
        payload = json.loads(path.read_text(encoding='utf-8'))
        for key, value in payload['papers'].items():
            text = value['text']
            if (not re.fullmatch(r'\d{4}\.\d{4,5}', key) or value['url'] != f'https://arxiv.org/abs/{key}'
                    or value['sha256'] != evidence_hash(text) or not 40 <= len(text) <= 16000):
                raise ValueError(f'Invalid official digest evidence: {key}')
            summaries.setdefault(key, text)
    return summaries


def build_digest_periods(rows: list[dict], topics: list[tuple[str, str]], summaries: dict[str, str], *, kind: str, today: date, limit: int, analysis_root: Path | None = None) -> list[dict]:
    """Build calendar days or Monday–Sunday weeks with exact, deduplicated counts."""
    if kind not in {'daily','weekly'} or limit < 1:
        raise ValueError('Expected daily/weekly and a positive period limit')
    step = 1 if kind == 'daily' else 7
    anchor = today if kind == 'daily' else today - timedelta(days=today.weekday())
    periods = []
    for offset in range(limit):
        start = anchor - timedelta(days=offset * step)
        end = start + timedelta(days=step - 1)
        selected = {row['id']: row for row in rows if start <= row['digest_date'] <= min(end, today)}
        sections = []
        analyses = load_analysis(analysis_root, kind, start.isoformat()) if analysis_root else {}
        for topic, slug in topics:
            members = sorted((row for row in selected.values() if topic in row['topics']), key=lambda row: (row['digest_date'], row['id']), reverse=True)
            if members:
                sections.append({'id': slug, 'label': f'{topic} · {len(members)}',
                                 'html': render_topic(members, summaries, analyses.get(slug), include_papers=kind == 'daily')})
        label = start.isoformat() if kind == 'daily' else f'{start.isoformat()} — {end.isoformat()}'
        summary_count = sum(key in summaries for key in selected)
        periods.append({'id': start.isoformat(), 'date': start.isoformat(),
                        'title': f'{label} · {"日报" if kind == "daily" else "周报"}',
                        'subtitle': f'{len(selected)} 篇公开论文 · {summary_count} 篇已有摘要' + (' · 本周更新中' if kind == 'weekly' and today < end else ''),
                        'sections': sections, 'metadata': {'note': DATE_NOTE if kind == 'daily' else WEEKLY_NOTE,
                            'empty_message': '本日没有符合公开条件的新论文。' if kind == 'daily' else '本周没有符合公开条件的新论文。'}})
    return periods


def publish_paper_digests(config_path: str | Path = CONFIG, *, output_root: str | Path | None = None,
                         generated_on: date | None = None, daily_limit: int = 30, weekly_limit: int = 12,
                         archive_path: str | Path | None = None, candidate_path: str | Path | None = None,
                         annotation_path: str | Path | None = None) -> list[Path]:
    """Publish 30 days/12 weeks with lazy JSON, rebuilding every retained period.

    No dated HTML copies are created. Only managed digest JSON outside the bounded
    windows is removed, so excluded/rejected records cannot survive in old assets.
    Published source records and note pages are never modified.
    """
    config_file = Path(config_path).resolve()
    config = yaml.safe_load(config_file.read_text(encoding='utf-8'))
    root = Path(output_root) if output_root is not None else Path(config.get('output_root', 'docs'))
    if not root.is_absolute():
        root = config_file.parent.parent / root
    today = generated_on or datetime.now(ZoneInfo('Asia/Shanghai')).date()
    rows, topics = load_public_papers(config_file, today=today, archive_path=archive_path,
                                     candidate_path=candidate_path, annotation_path=annotation_path)
    summaries = load_digest_evidence(root, config_file.parent.parent / 'content/papers/digests')
    reports = root / 'reports'
    results: list[Path] = []
    retained: set[Path] = set()
    documents = {}
    for kind, limit in [('daily', daily_limit), ('weekly', weekly_limit)]:
        periods = build_digest_periods(rows, topics, summaries, kind=kind, today=today, limit=limit,
                                      analysis_root=config_file.parent.parent / 'content/papers/digests')
        catalog = []
        for index, period in enumerate(periods):
            data_path = reports / 'periods' / f'{kind}-{period["id"]}.json'
            documents[data_path] = json.dumps(period, ensure_ascii=False, separators=(',', ':')) + '\n'
            retained.add(data_path)
            # The newest article is server-rendered; historical articles load on demand.
            catalog.append({**period, 'sections': period['sections'] if index == 0 else [],
                            'metadata': {**period['metadata'], **({'data_url': f'periods/{data_path.name}'} if index else {})}})
        destination = reports / f'{kind}.html'
        documents[destination] = render_periodical_page(output_file=destination, output_root=root, active_section='learning',
            title='论文日报' if kind == 'daily' else '论文周报', kind=kind, periods=catalog, active_subtopic=kind)
    # Build all documents before replacing anything; malformed input preserves output.
    for destination, document in documents.items():
        atomic_write_text(destination, document)
        results.append(destination)
    for path in (reports / 'periods').glob('*.json'):
        if re.fullmatch(r'(daily|weekly)-\d{4}-\d{2}-\d{2}\.json', path.name) and path not in retained:
            path.unlink()
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=CONFIG)
    parser.add_argument('--output-root', type=Path)
    args = parser.parse_args(argv)
    paths = publish_paper_digests(args.config, output_root=args.output_root)
    print(json.dumps({'published_files': len(paths), 'daily_periods': 30, 'weekly_periods': 12}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
