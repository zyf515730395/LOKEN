"""Validate source-bound editorial analyses and render compact contribution tables."""
from __future__ import annotations
import hashlib
import html
import json
from pathlib import Path
import re


def evidence_hash(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def plain(value: str) -> str:
    return re.sub(r'\s+', ' ', html.unescape(re.sub('<[^>]+>', ' ', value))).strip()


def validate_analysis(item: dict, ids: list[str], summaries: dict[str, str]) -> None:
    if not isinstance(item, dict) or not isinstance(item.get('paper_ids'), list) or not all(isinstance(key, str) for key in item['paper_ids']):
        raise ValueError('Analysis must contain a paper ID list')
    if set(item.get('paper_ids', [])) != set(ids) or len(item.get('paper_ids', [])) != len(ids):
        raise ValueError('Analysis must cover exactly the visible topic papers')
    contributions = item.get('contributions', {})
    if not isinstance(contributions, dict):
        raise ValueError('Contributions must be an object')
    if set(contributions) != {key for key in ids if key in summaries}:
        raise ValueError('Contributions must cover every available summary')
    for key, contribution in contributions.items():
        if not isinstance(contribution, dict):
            raise ValueError('Contribution must be an object')
        if not isinstance(contribution.get('text'), str) or not 1 <= len(contribution['text']) <= 350:
            raise ValueError('Expected a concise contribution sentence')
        if contribution.get('evidence_hash') != evidence_hash(summaries[key]):
            raise ValueError('Analysis evidence changed')
    trends = item.get('trends')
    if not isinstance(trends, list) or (contributions and not trends):
        raise ValueError('Evidence-backed topic analysis required')
    for trend in trends:
        if not isinstance(trend, dict):
            raise ValueError('Trend must be an object')
        if not all(isinstance(trend.get(k), str) and trend[k].strip() for k in ('claim', 'reasoning', 'limitations')):
            raise ValueError('Trend needs claim, technical reasoning and limitations')
        refs = trend.get('paper_ids', [])
        if not isinstance(refs, list) or not refs or not all(isinstance(key, str) for key in refs) or not set(refs) <= set(contributions):
            raise ValueError('Trend references must have published evidence in this topic and period')


def render_topic(members: list[dict], summaries: dict[str, str], analysis: dict | None) -> str:
    ids = [row['id'] for row in members]
    valid = False
    if analysis:
        try:
            validate_analysis(analysis, ids, summaries)
            valid = True
        except (ValueError, TypeError, KeyError):
            pass
    contributions = analysis['contributions'] if valid else {}
    rows = []
    urls = {}
    for row in members:
        key = row['id']
        url = str(row.get('paper_url', ''))
        title = html.escape(row['title'])
        if url.startswith(('https://', 'http://')):
            urls[key] = url
            title = f'<a href="{html.escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">{title}</a>'
        sentence = contributions.get(key, {}).get('text')
        if sentence is None:
            from papers.digest_writer import contribution
            try:
                sentence = contribution(summaries[key])
            except (KeyError, ValueError):
                sentence = '贡献提炼待更新。' if key in summaries else '摘要尚未发布，暂不推断贡献。'
        basis = '首次采集' if row['date_basis'] == 'first_collected' else '发表日期'
        rows.append(f'<tr><td>{title}<small>{html.escape(str(row.get("display_id", key)))}</small></td><td>{html.escape(sentence)}</td><td>{row["digest_date"].isoformat()}<small>{basis}</small></td></tr>')
    result = '<div class="digest-table-wrap" role="region" aria-label="论文贡献表" tabindex="0"><table class="digest-table"><thead><tr><th scope="col">论文</th><th scope="col">一句话贡献</th><th scope="col">归档日期</th></tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div><h3>技术趋势与分析</h3>'
    if not valid:
        return result + '<p class="periodical-note">本期分析待生成或证据已更新；不以论文标题推断技术趋势。</p>'
    result += '<p class="periodical-note">以下为本期公开样本的综合分析，不代表全领域统计；论文事实与趋势判断分开呈现。</p>'
    for trend in analysis['trends']:
        refs = '、'.join(f'<a href="{html.escape(urls[key], quote=True)}" target="_blank" rel="noopener noreferrer">{html.escape(key)}</a>' if key in urls else html.escape(key) for key in trend['paper_ids'])
        result += f'<div class="digest-trend"><h4>{html.escape(trend["claim"])}</h4><p>{html.escape(trend["reasoning"])}</p><p class="periodical-note">适用边界：{html.escape(trend["limitations"])}</p><p class="periodical-note">依据：{refs}</p></div>'
    return result


def load_analysis(root: Path, kind: str, period: str) -> dict:
    path = root / f'{kind}-{period}.json'
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict) or value.get('schema_version') != 1 or value.get('kind') != kind or value.get('period') != period or not isinstance(value.get('topics'), dict):
        raise ValueError(f'Invalid digest analysis identity: {path.name}')
    return value.get('topics', {})
