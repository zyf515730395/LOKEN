"""Title candidate retrieval with independent identity evidence."""
from __future__ import annotations

from difflib import SequenceMatcher
from functools import lru_cache
from collections import defaultdict, Counter
import math
import html
import re
import unicodedata

STOP = {'a', 'an', 'the', 'and', 'of', 'for', 'with', 'via', 'in', 'to', 'from'}


@lru_cache(maxsize=16384)
def title_variants(title: str) -> tuple[str, ...]:
    title = unicodedata.normalize('NFKC', html.unescape(title)).casefold()
    title = re.sub(r'\\(?:text|mathrm|mathbf|mathit|textrm)\s*\{([^{}]*)\}', r'\1', title)
    title = re.sub(r'[$^{}]', '', title)
    parts = [title]
    if ':' in title:
        parts.append(title.split(':', 1)[1])
    return tuple(' '.join(re.findall(r'[a-z0-9]+', p)) for p in parts)


def _authors(values) -> set[str]:
    if not isinstance(values, (list,tuple)):
        return set()
    return {' '.join(sorted(re.findall(r'[^\W\d_]+', unicodedata.normalize('NFKD', name).casefold())))
            for name in values if isinstance(name,str) and len(name.split()) >= 2}


def title_score(left: str, right: str) -> float:
    best = 0.0
    for a in title_variants(left):
        wa = set(a.split()) - STOP
        for b in title_variants(right):
            wb = set(b.split()) - STOP
            jac = len(wa & wb) / max(1,len(wa | wb))
            if jac < .35:
                continue
            best = max(best,.55 * jac + .45 * SequenceMatcher(None,a,b).ratio())
    return best


class CandidateIndex:
    """Recall-preserving token prefilter for large arXiv response caches."""
    def __init__(self, candidates):
        self.items=list(candidates)
        self.words=defaultdict(set)
        for i,candidate in enumerate(self.items):
            for word in set(title_variants(candidate['title'])[0].split())-STOP:
                self.words[word].add(i)

    def for_record(self, record):
        selected=set()
        for variant in title_variants(record['title']):
            words=set(variant.split())-STOP
            overlaps=Counter(i for word in words for i in self.words.get(word,()))
            threshold=max(1,math.ceil(.35*len(words)))
            selected.update(i for i,n in overlaps.items() if n>=threshold)
        return [self.items[i] for i in sorted(selected)]


def rank_candidates(record: dict, candidates: list[dict]) -> list[dict]:
    if isinstance(candidates,CandidateIndex): candidates=candidates.for_record(record)
    ranked = []
    for candidate in candidates:
        score = title_score(record['title'],candidate['title'])
        if score >= .60:
            ranked.append({'score':score,'candidate':candidate})
    return sorted(ranked,key=lambda item:-item['score'])


def verified_match(record: dict, candidates: list[dict]) -> dict:
    ranked = rank_candidates(record,candidates)
    accepted = {}
    authors = _authors(record.get('authors'))
    for item in ranked:
        candidate, score = item['candidate'],item['score']
        a,b = title_variants(record['title'])[0],title_variants(candidate['title'])[0]
        if set(re.findall(r'\d+',a)) != set(re.findall(r'\d+',b)):
            continue
        if (set(a.split()) & {'not','without','non'}) != (set(b.split()) & {'not','without','non'}):
            continue
        other = _authors(candidate.get('authors'))
        shared = authors & other
        corroborated = (len(shared) >= 2 and len(shared) / max(1,min(len(authors),len(other))) >= .5
                        or len(authors) == len(other) == len(shared) == 1)
        doi_match = bool(record.get('doi') and record['doi'].casefold() == candidate.get('doi','').casefold())
        if score >= .80 and (corroborated or doi_match):
            accepted[candidate['arxiv_id']] = candidate
    if len(accepted) != 1:
        return {}
    candidate = next(iter(accepted.values()))
    # A close rival cannot be dismissed solely because its author metadata is absent.
    winner_score = title_score(record['title'],candidate['title'])
    if any(x['candidate']['arxiv_id'] != candidate['arxiv_id'] and x['score'] >= winner_score - .04 for x in ranked):
        return {}
    return {**{k:v for k,v in candidate.items() if k != 'title'},
            'match_evidence':{'method':'fuzzy_title_with_identity','title':candidate['title'],
                              'score':round(winner_score,4),
                              'reference_url':record.get('author_evidence_url') or record.get('date_source',{}).get('url') or record.get('url'),
                              'matched_authors':sorted(authors & _authors(candidate.get('authors')))}}


def search_query(title: str) -> str:
    """Search abbreviated and subtitle variants without requiring every title word."""
    parts = title_variants(title)
    words = sorted(set(parts[-1].split())-STOP,key=lambda w:(-len(w),w))
    terms = [word for word in words if len(word)>3][:3]
    queries = ['(' + ' AND '.join('ti:'+word for word in terms) + ')'] if terms else []
    prefix = title.split(':',1)[0]
    if ':' in title and len(prefix.split()) <= 3:
        acronym = ''.join(title_variants(prefix)[0].split())
        if len(acronym) >= 4:
            queries.append('ti:'+acronym)
    return '('+' OR '.join(queries)+')'
