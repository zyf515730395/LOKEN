"""Fair, persistent attempts: unseen work first, then least-attempted retries."""
import json

from papers.candidate_ledger import atomic_write_json
from papers.summaries.paths import private_path


def select_attempts(items, *, key, namespace, limit=None, state_path=None):
    """Called under the shared run lock. Input order resolves equal attempts."""
    if namespace not in {'summary', 'annotation'}:
        raise ValueError('unknown retry queue')
    path = state_path or private_path(f'{namespace}-attempts.json')
    attempts = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    if not isinstance(attempts, dict) or any(not isinstance(k, str) or type(v) is not int or v < 0 for k, v in attempts.items()):
        raise ValueError('invalid retry history; preserve and inspect it')
    if limit is not None and limit < 1:
        raise ValueError('limit must be positive')
    selected = sorted(items, key=lambda item: attempts.get(key(item), 0))
    if limit is not None:
        selected = selected[:limit]
    if selected:
        for item in selected:
            identifier = key(item)
            attempts[identifier] = attempts.get(identifier, 0) + 1
        atomic_write_json(path, attempts)
    return selected
