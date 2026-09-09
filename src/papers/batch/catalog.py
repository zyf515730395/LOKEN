"""Full-archive selection for local batches; no candidate-ledger mutation."""

from dataclasses import dataclass
import json

from papers.candidate_ledger import load_candidate_ledger
from papers.paths import DOCS
from papers.site import parse_entry
from papers.summaries.catalog import PaperCandidate, TOPIC_SLUGS
from papers.summaries.models import PaperSummaryError
from papers.summaries.paths import normalize_arxiv_id
from papers.summaries.publisher import load_ready_keys
from papers.annotations.catalog import load_label_definitions
from papers.paths import CONFIG

TOPIC_NAMES = {name: label.name for label in load_label_definitions(CONFIG)
               for name in (label.name, *label.aliases)}


def archive_review_state(entry, topic):
    canonical = TOPIC_NAMES[topic]
    decisions = entry.get('recheck_decisions', {})
    if canonical in decisions:
        accept = decisions[canonical]['accept']
        if accept is None:
            return 'recheck_uncertain'
        if type(accept) is not bool:
            raise ValueError('invalid persisted recheck decision')
        return 'accepted' if accept else 'rejected'
    state = entry.get('status', 'unreviewed')
    if state == 'accepted' and TOPIC_NAMES.get(entry.get('selected_topic')) != canonical:
        return 'accepted_elsewhere'
    return state


@dataclass(frozen=True, slots=True)
class ArchiveCandidate(PaperCandidate):
    historical: bool
    review_state: str
    abstract: str


def archive_candidates(archive_path, ledger_path, paper_ids=(), *, docs_root=DOCS,
                       include_ready=False):
    try:
        archive = json.loads(archive_path.read_text(encoding='utf-8'))
        ledger = load_candidate_ledger(ledger_path)['papers']
        if not isinstance(archive, dict) or not set(archive).issubset(TOPIC_SLUGS):
            raise ValueError('invalid archive topics')
        ready = load_ready_keys(docs_root)
        all_items = {}
        for topic, entries in archive.items():
            if not isinstance(entries, dict):
                raise ValueError('invalid archive category')
            for raw_id, row in entries.items():
                paper_id = normalize_arxiv_id(raw_id)
                parsed = parse_entry(paper_id, row)
                entry = ledger.get(paper_id, {})
                historical = not bool(entry)
                state = archive_review_state(entry, topic)
                title = entry.get('title') or parsed['title']
                abstract = entry.get('abstract') or ''
                if not isinstance(title, str) or not isinstance(abstract, str):
                    raise ValueError('invalid paper metadata')
                item = ArchiveCandidate(paper_id, ' '.join(title.split()), topic,
                                        parsed['date'], historical, state, abstract)
                old = all_items.get((topic, paper_id))
                if old is None or item.updated > old.updated:
                    all_items[topic, paper_id] = item
        requested = {normalize_arxiv_id(value) for value in paper_ids}
        if requested - {item.arxiv_id for item in all_items.values()}:
            raise PaperSummaryError('paper_not_archived', 'requested paper is not in the full archive')
        return sorted((item for key, item in all_items.items()
                       if (include_ready or key not in ready or item.arxiv_id in requested)
                       and (not requested or item.arxiv_id in requested)),
                      key=lambda item: (-item.updated.toordinal(), item.arxiv_id,
                                        list(TOPIC_SLUGS).index(item.topic)))
    except PaperSummaryError:
        raise
    except (OSError, ValueError, TypeError, AttributeError, KeyError):
        raise PaperSummaryError('invalid_archive', 'archive or ledger cannot be read safely') from None
