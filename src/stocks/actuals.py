"""Official release-value overlays, independent from immutable weekly outlooks."""
from __future__ import annotations
import argparse
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path

from .data import SHANGHAI, aware_datetime, load_config, read_json, require, sources, validate_events
from .site import _atomic_write


def pending_events(events: dict, *, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(SHANGHAI)
    result = []
    for event in events['events']:
        stamp = event.get('scheduled_at')
        if event['kind'] == 'monitor' or not stamp or aware_datetime(stamp, 'scheduled_at') > now:
            continue
        actual = {item['indicator']: item.get('actual') for item in event.get('observations', [])}
        missing = [key for key in event['indicators'] if actual.get(key) is None]
        if missing:
            result.append({'id': event['id'], 'period': event.get('period'), 'scheduled_at': stamp, 'missing': missing, 'sources': event['sources']})
    return result


def merge_actuals(events: dict, overlay: dict, config: dict, *, now: datetime | None = None) -> dict:
    now = now or datetime.now(SHANGHAI)
    require(overlay.get('schema_version') == 1 and isinstance(overlay.get('releases'), list), 'actuals: schema_version/release list required')
    merged = deepcopy(events)
    by_id = {item['id']: item for item in merged['events']}
    seen = set()
    for release in overlay['releases']:
        key = release.get('event_id')
        require(key in by_id and key not in seen, 'actuals: unknown or duplicate event')
        seen.add(key)
        event = by_id[key]
        require(event['kind'] != 'monitor' and event.get('scheduled_at') is not None, 'actuals: scheduled releases only')
        published = aware_datetime(event['scheduled_at'], 'scheduled_at')
        require(published <= now, 'actuals: cannot publish future values')
        require(release.get('period') == event.get('period'), 'actuals: reporting period mismatch')
        updates = release.get('observations')
        require(isinstance(updates, list) and bool(updates), 'actuals: observations required')
        observations = {item['indicator']: item for item in event.get('observations', [])}
        updated = set()
        for item in updates:
            indicator = item.get('indicator')
            require(indicator in event['indicators'] and indicator not in updated, 'actuals: invalid/duplicate indicator')
            updated.add(indicator)
            require(set(item) <= {'indicator', 'actual', 'previous'}, 'actuals: cannot rewrite consensus')
            require(item.get('actual') is not None, 'actuals: actual value required; unavailable remains pending')
            for field in ('actual', 'previous'):
                value = item.get(field)
                if value is None:
                    continue
                sources(value.get('sources'), 'actuals.sources', config['indicators'][indicator]['official_domains'])
                for source in value['sources']:
                    verified = aware_datetime(source['verified_at'], 'verified_at')
                    require(published <= verified <= now, 'actuals: evidence must be verified after release and not in future')
            observations.setdefault(indicator, {'indicator': indicator}).update(deepcopy(item))
        event['observations'] = list(observations.values())
    validate_events(merged, config)
    return merged


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['status', 'apply'])
    parser.add_argument('--input', type=Path)
    args = parser.parse_args(argv)
    root = Path('content/stocks')
    config = load_config(Path('config/stocks.yaml'))
    events = read_json(root / 'events.json')
    target = root / 'actuals.json'
    overlay = read_json(target) if target.exists() else {'schema_version': 1, 'releases': [], 'revisions': []}
    if args.command == 'apply':
        require(args.input is not None, '--input required')
        incoming = read_json(args.input)
        merge_actuals(events, incoming, config)
        previous = {r['event_id']: r for r in overlay['releases']}
        changed = []
        for release in incoming['releases']:
            key = release['event_id']
            prior = previous.get(key)
            # Partial new evidence must not erase already published indicators.
            values = {v['indicator']: v for v in (prior or {}).get('observations', [])}
            for value in release['observations']:
                indicator = value['indicator']
                values[indicator] = {**values.get(indicator, {}), **value}
            replacement = {**release, 'observations': list(values.values())}
            if prior == replacement:
                continue
            if prior:
                overlay.setdefault('revisions', []).append({'replaced_at': datetime.now(SHANGHAI).isoformat(), 'release': prior})
            previous[key] = replacement
            changed.append(key)
        overlay['releases'] = list(previous.values())
        merge_actuals(events, overlay, config)
        if changed:
            overlay['updated_at'] = datetime.now(SHANGHAI).isoformat()
            _atomic_write(target, json.dumps(overlay, ensure_ascii=False, indent=2) + '\n')
    merged = merge_actuals(events, overlay, config)
    print(json.dumps({'pending': pending_events(merged), 'filled_releases': len(overlay['releases'])}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
