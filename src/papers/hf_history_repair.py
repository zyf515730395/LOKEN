"""Hash-bound repair scope and strict output contract for the existing HF CLI."""
from __future__ import annotations

import json
from pathlib import Path

from papers import curation, paths


def original_root():
    return paths.ROOT / 'build/reports/hf-2024-2025/reviews'


def load(path):
    from papers.hf_backfill import digest, REPORT
    path = Path(path).resolve()
    path.relative_to((paths.ROOT / 'build/reports').resolve())
    manifest = json.loads(path.read_text(encoding='utf-8'))
    ids = manifest.get('paper_ids')
    if (manifest.get('routine_first') is not True or manifest.get('priority_override') is not False
            or not isinstance(ids, list) or not ids or any(not isinstance(k, str) for k in ids)
            or len(set(ids)) != len(ids) or set(manifest.get('original_receipts', {})) != set(ids)):
        raise ValueError('Invalid explicit HF repair manifest')
    targets, uncertain = {}, []
    for key in ids:
        refs = manifest['original_receipts'][key]
        if not isinstance(refs, list) or not refs:
            raise ValueError('Missing original HF failure evidence: ' + key)
        originals = []
        for ref in refs:
            source = (paths.ROOT / ref['path']).resolve()
            source.relative_to(original_root().resolve())
            value = json.loads(source.read_text(encoding='utf-8'))
            if (value.get('status') not in ('invalid_review', 'uncertain')
                    or value.get('status') != ref.get('status')
                    or value.get('input', {}).get('material', {}).get('id') != key
                    or value.get('input_sha256') != digest(value.get('input'))
                    or value.get('input_sha256') != ref.get('input_sha256')
                    or value.get('raw_sha256') != digest(value.get('raw'))
                    or value.get('raw_sha256') != ref.get('raw_sha256')):
                raise ValueError('Original HF repair evidence changed: ' + key)
            originals.append(value)
        if any(v['status'] == 'uncertain' for v in originals):
            uncertain.append(key)
        else:
            targets[key] = originals
    checksum = digest(manifest)
    return {'path': path, 'sha256': checksum, 'targets': targets, 'uncertain': uncertain,
            'root': REPORT / 'repairs' / checksum}


def schema(key, topics):
    return {'type': 'object', 'additionalProperties': False, 'required': ['decisions'],
            'properties': {'decisions': {'type': 'array', 'minItems': 1, 'maxItems': 1,
                'items': {'type': 'object', 'additionalProperties': False,
                    'required': ['id', 'action', 'topic', 'reason'], 'properties': {
                        'id': {'type': 'string', 'enum': [key]},
                        'action': {'type': 'string', 'enum': ['accept', 'reject', 'uncertain']},
                        'topic': {'anyOf': [{'type': 'string', 'enum': topics}, {'type': 'null'}]},
                        'reason': {'type': 'string', 'minLength': 1, 'maxLength': 1000}}}}}}


def parse(raw, key, topics):
    def unique(pairs):
        value = {}
        for k, v in pairs:
            if k in value:
                raise ValueError('duplicate JSON key')
            value[k] = v
        return value
    value = json.loads(raw, object_pairs_hook=unique)
    if (not isinstance(value, dict) or set(value) != {'decisions'}
            or not isinstance(value['decisions'], list) or len(value['decisions']) != 1):
        raise ValueError('Expected exactly one wrapped repair decision')
    decisions = curation.parse_decisions(json.dumps(value['decisions'], ensure_ascii=False), {key})
    item = value['decisions'][0]
    if ((item['action'] == 'accept' and item['topic'] not in topics)
            or (item['action'] != 'accept' and item['topic'] is not None)):
        raise ValueError('Repair decision topic mismatch')
    return decisions


def bind(value, context, topics):
    key = value['material']['id']
    originals = context['targets'][key]
    if any(old['input']['hf_evidence_sha256'] != value['hf_evidence_sha256'] for old in originals):
        raise ValueError('HF material changed; inspect before repairing: ' + key)
    return {**value, 'repair': {'version': 1, 'manifest_sha256': context['sha256'],
            'originals': [{'input_sha256': old['input_sha256'], 'raw_sha256': old['raw_sha256']}
                          for old in originals]}, 'json_schema': schema(key, topics)}
