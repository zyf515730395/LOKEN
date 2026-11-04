"""Evidence-bounded, inference-free index of model routes and weekly signals."""
from __future__ import annotations

from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import re
import unicodedata

import yaml

OBSERVATION_VERSION = 'paradigms-v1'
FIELDS = ('name', 'dimension', 'previous', 'mechanism', 'limitations')


def year_start(today: date) -> date:
    try:
        return today.replace(year=today.year - 1)
    except ValueError:
        return today.replace(year=today.year - 1, day=28)


def route_key(topic: str, name: str) -> str:
    normalized = ' '.join(unicodedata.normalize('NFKC', name).casefold().split())
    return hashlib.sha256(f'{topic}:{normalized}'.encode()).hexdigest()[:20]


def clue_hash(clue):
    source = {k: clue[k] for k in ('claim', 'reasoning', 'limitations', 'paper_ids')}
    return hashlib.sha256(json.dumps(source, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def validate_observations(items, allowed_ids):
    if not isinstance(items, list) or len(items) > 5:
        raise ValueError('Expected at most five paradigm observations')
    for item in items:
        if not isinstance(item, dict) or set(item) != {*FIELDS, 'paper_ids'}:
            raise ValueError('Invalid paradigm observation fields')
        for key in FIELDS:
            limit = 80 if key in ('name', 'dimension') else 500
            if not isinstance(item[key], str) or not 1 <= len(item[key].strip()) <= limit:
                raise ValueError(f'Invalid paradigm {key}')
        refs = item['paper_ids']
        if (not isinstance(refs, list) or not 1 <= len(refs) <= 8
                or not all(isinstance(ref, str) for ref in refs)
                or len(set(refs)) != len(refs) or not set(refs) <= set(allowed_ids)):
            raise ValueError('Paradigm citations must be unique evidence-backed topic IDs')


def observation_status(events):
    weeks = {event['week'] for event in events}
    papers = {key for event in events for key in event['paper_ids']}
    return 'developing' if len(weeks) >= 2 and len(papers) >= 2 else 'watch'


def weekly_schema(ids):
    return {'type': 'array', 'maxItems': 5, 'items': {
        'type': 'object', 'properties': {
            **{key: {'type': 'string', 'minLength': 1, 'maxLength': 80 if key in ('name', 'dimension') else 500} for key in FIELDS},
            'paper_ids': {'type': 'array', 'minItems': 1, 'maxItems': min(8, len(ids)),
                          'items': {'type': 'string', 'enum': list(ids)}}},
        'required': [*FIELDS, 'paper_ids'], 'additionalProperties': False}}


def synthesis_instruction():
    return ('\n另输出paradigms数组0至5项，只有材料支持机制级变化时记录，允许空数组。'
            '不把参数量、数据量、指标提升、换应用场景或单纯评测当新范式。'
            '维度不限于骨干结构、模态融合、表示与压缩、生成目标、训练与对齐、推理与加速、'
            '控制与交互、任务迁移、几何与物理、记忆与规划，可新增维度。'
            '每项name为可跨周复用的简短机制名称，不用论文名或营销名；dimension为维度；'
            'previous为对照路线；mechanism解释机制如何变化及解决的问题；limitations说明待验证边界；'
            'paper_ids只选直接支撑的本主题论文。不要声称技术首次提出、主导地位或独立复现。'
            'known_routes仅是本主题命名词表，不是本周证据：若机制相同，name必须原样复用词表的name，'
            '不要换同义名或论文品牌；机制确实不同才新增名称。绝不因词表存在就生成观察。')


def route_vocabulary(topic, config_path: Path, analysis_root: Path, today: date):
    """Naming context only; this never supplies evidence for a weekly claim."""
    if not config_path.exists():
        return []
    from papers.digest_analysis import load_analysis
    entries = [r for r in yaml.safe_load(config_path.read_text(encoding='utf-8'))['routes'] if topic in r['topics']]
    reviews = analysis_root.parent / 'paradigm-observations.json'
    if reviews.exists():
        entries.extend(r['observation'] for r in json.loads(reviews.read_text(encoding='utf-8'))['observations'] if r['topic'] == topic)
    for path in sorted(analysis_root.glob('weekly-*.json'), reverse=True):
        week = path.stem.removeprefix('weekly-')
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', week):
            continue
        if not year_start(today) - timedelta(days=6) <= date.fromisoformat(week) <= today:
            continue
        try:
            item = load_analysis(analysis_root, 'weekly', week).get(topic, {})
            if item.get('paradigm_version') == OBSERVATION_VERSION:
                validate_observations(item.get('paradigms'), item.get('contributions', {}))
                entries.extend(item['paradigms'])
        except (ValueError, TypeError, KeyError):
            continue
    unique = {}
    for entry in entries:
        key = route_key(topic, entry['name'])
        unique.setdefault(key, {'name': entry['name'], 'aliases': entry.get('aliases', []),
                                'mechanism': entry['mechanism'][:200]})
    return list(unique.values())[:128]


def build_catalog(rows, topics, summaries, analysis_root: Path, config_path: Path, today: date):
    """Reject stale topic analysis, never splice citations out of an old claim."""
    from papers.digest_analysis import load_analysis, validate_analysis
    start = year_start(today)
    definitions = yaml.safe_load(config_path.read_text(encoding='utf-8'))
    review_path = analysis_root.parent / 'paradigm-observations.json'
    reviews = json.loads(review_path.read_text(encoding='utf-8'))['observations'] if review_path.exists() else []
    topic_names = {slug: name for name, slug in topics}
    routes = {}
    for seed in definitions['routes']:
        for topic in seed['topics']:
            if topic not in topic_names:
                raise ValueError(f'Unknown paradigm topic: {topic}')
            key = route_key(topic, seed['name'])
            if key in routes:
                raise ValueError('Duplicate baseline route')
            routes[key] = {**seed, 'id': key, 'topic': topic, 'baseline': True, 'status': 'mainstream',
                           'events': [], 'associations': []}
    public = {row['id']: row for row in rows}
    by_week = {}
    for row in rows:
        day = row['digest_date']
        monday = day - timedelta(days=day.weekday())
        if monday <= today and monday + timedelta(days=6) >= start:
            by_week.setdefault(monday, []).append(row)
    coverage, clues = [], []
    monday = start - timedelta(days=start.weekday())
    while monday <= today:
        source = analysis_root / f'weekly-{monday}.json'
        try:
            analyses = load_analysis(analysis_root, 'weekly', str(monday))
        except (ValueError, TypeError):
            analyses = {}
        for name, slug in topics:
            members = [row for row in by_week.get(monday, []) if name in row['topics']]
            ids = [row['id'] for row in members]
            if not ids:
                continue
            item = analyses.get(slug)
            reason = ''
            try:
                if not item:
                    raise ValueError('missing')
                validate_analysis(item, ids, summaries, titles={r['id']: r['title'] for r in members})
                if item.get('skipped_trend') or not item.get('trends'):
                    raise ValueError('skipped')
            except (ValueError, TypeError, KeyError):
                reason = '待生成或证据已变化' if item else '尚无周报分析'
            coverage.append({'week': str(monday), 'topic': slug, 'papers': len(ids),
                             'valid': not reason, 'reason': reason,
                             'skipped_papers': len(item.get('skipped_papers', {})) if item else 0,
                             'structured': bool(item and item.get('paradigm_version') == OBSERVATION_VERSION)})
            if reason:
                continue
            def in_window(refs):
                return all(key in public and start <= public[key]['digest_date'] <= today for key in refs)
            for index, trend in enumerate(item['trends']):
                if not in_window(trend['paper_ids']):
                    continue
                clue = {**trend, 'id': route_key(slug, f'{monday}:{index}:{trend["claim"]}'),
                        'topic': slug, 'week': str(monday), 'dimension': '待研判', 'matches': []}
                # Association only. A keyword hit cannot establish novelty or adoption.
                text = trend['claim'] + '\n' + trend['reasoning']
                for route in routes.values():
                    if route['topic'] == slug and route.get('baseline') and any(re.search(pattern, text, re.I) for pattern in route.get('patterns', [])):
                        route['associations'].append(clue['id'])
                        clue['matches'].append(route['id'])
                clues.append(clue)
            events = [(event, 'weekly', None) for event in item.get('paradigms', [])] if item.get('paradigm_version') == OBSERVATION_VERSION else []
            current_clues = {clue['id']: clue for clue in clues if clue['topic'] == slug and clue['week'] == str(monday)}
            for review in reviews:
                clue = current_clues.get(review['source_id'])
                if not clue or review['source_hash'] != clue_hash(clue):
                    continue
                validate_observations([review['observation']], clue['paper_ids'])
                events.append((review['observation'], 'historical_review', clue))
            for event, origin, source_clue in events:
                if not in_window(event['paper_ids']):
                    continue
                key = route_key(slug, event['name'])
                # Exact normalized names/curated aliases only; no semantic merge by keywords.
                for candidate in routes.values():
                    aliases = [candidate['name'], *candidate.get('aliases', [])]
                    if candidate['topic'] == slug and key in {route_key(slug, alias) for alias in aliases}:
                        key = candidate['id']
                        break
                if key not in routes:
                    routes[key] = {**{k: event[k] for k in FIELDS}, 'id': key, 'topic': slug,
                                   'baseline': False, 'sources': [], 'events': [], 'associations': []}
                bound = {**event, 'week': str(monday), 'origin': origin}
                if not any(e['week'] == bound['week'] and set(e['paper_ids']) == set(bound['paper_ids']) for e in routes[key]['events']):
                    routes[key]['events'].append(bound)
                if source_clue and source_clue['id'] not in routes[key]['associations']:
                    routes[key]['associations'].append(source_clue['id'])
                    source_clue['matches'].append(key)
        monday += timedelta(days=7)
    for route in routes.values():
        events = route['events']
        route['activity'] = observation_status(events) if events else 'unclassified'
        if not route['baseline']:
            route['status'] = route['activity']
            latest = max(events, key=lambda event: event['week'])
            route.update({k: latest[k] for k in FIELDS})
        route['first_seen'] = min((e['week'] for e in events), default='')
        route['last_seen'] = max((e['week'] for e in events), default='')
        route['paper_count'] = len({key for e in events for key in e['paper_ids']})
        route.pop('patterns', None)
    cited = {key for c in clues for key in c['paper_ids']} | {key for r in routes.values() for e in r['events'] for key in e['paper_ids']}
    return {'schema_version': 1, 'start': str(start), 'end': str(today),
            'topics': [{'name': name, 'id': slug} for name, slug in topics],
            'routes': list(routes.values()), 'clues': sorted(clues, key=lambda c: c['week'], reverse=True),
            'coverage': coverage, 'baseline_verified_at': str(definitions['verified_at']),
            'papers': {key: {'title': public[key]['title'], 'date': str(public[key]['digest_date']),
                             'url': f'../index.html#paper-{key}'} for key in sorted(cited)}}
