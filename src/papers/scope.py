"""Configured research-scope exclusions shared by intake and publication."""
import re


def excluded(config, paper_id='', title='', tags=()):
    rules = config.get('publication', {})
    return (paper_id in set(rules.get('excluded_paper_ids', []))
            or bool(set(tags) & set(rules.get('excluded_tags', [])))
            or any(re.search(pattern, title.replace('-', ' ').replace('_', ' '), re.I) for pattern in rules.get('excluded_title_patterns', [])))


def filter_archive(archive, ledger, config, annotations=None):
    from papers.site import parse_entry
    return {topic: {key: value for key, value in entries.items()
                    if not excluded(config, key, parse_entry(key, value)['title'],
                                    [*ledger.get('papers', {}).get(key, {}).get('subtopics', []),
                                     *getattr((annotations or {}).get(key), 'tags', ())])}
            for topic, entries in archive.items()}


def excluded_row(config, row):
    identity = re.search(r'arxiv\.org/abs/(\d{4}\.\d{4,5})(?:v\d+)?$', row.get('paper_url', ''))
    return excluded(config, row['id'], row['title'], row.get('tags', ())) or bool(identity and excluded(config, identity[1]))
