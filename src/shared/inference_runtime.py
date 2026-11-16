"""Explicit connection to an existing shared WSL inference runtime."""
from pathlib import Path
from contextlib import contextmanager
import json
import os
import sys

PROJECT_ROOT=Path(__file__).resolve().parents[2]
EXTERNAL_CLIENT=False

def runtime_paths():
    path=PROJECT_ROOT/'ops/inference-runtime.json'
    if not path.is_file():
        raise ValueError('Configure ops/inference-runtime.json with the existing shared WSL runtime before inference')
    value=json.loads(path.read_text(encoding='utf-8'))
    if set(value)!={'budget_directory','runtime_lock','daily_request_lock'}: raise ValueError('Invalid shared inference configuration')
    paths={key:Path(item) for key,item in value.items()}
    if any(not item.is_absolute() for item in paths.values()): raise ValueError('Shared runtime paths must be absolute WSL paths')
    if not (paths['budget_directory']/'state.json').is_file() or not all(paths[key].is_file() for key in ('runtime_lock','daily_request_lock')):
        raise ValueError('Existing shared runtime or budget state is unavailable; do not initialize a new budget')
    return {key:item.resolve() for key,item in paths.items()}

def lock_is_held(path: Path) -> bool:
    """Read kernel lock ownership without momentarily impersonating a daily owner."""
    info=path.stat()
    for line in Path('/proc/locks').read_text().splitlines():
        parts=line.split()
        if '->' in parts: continue  # waiting requests do not own the lock
        if len(parts)<6: raise ValueError('Unable to inspect shared runtime locks')
        major,minor,inode=parts[5].split(':')
        if (int(major,16),int(minor,16),int(inode))==(os.major(info.st_dev),os.minor(info.st_dev),info.st_ino): return True
    return False

@contextmanager
def external_model_access():
    if not EXTERNAL_CLIENT:
        yield
        return
    if sys.platform!='linux': raise ValueError('Run inference inside the shared WSL environment')
    import fcntl
    paths=runtime_paths()
    with paths['runtime_lock'].open('r+b') as runtime:
        try: fcntl.flock(runtime,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Shared model is occupied; retry after routine work releases the runtime') from None
        try:
            if lock_is_held(paths['daily_request_lock']):
                raise ValueError('Daily work is queued; retry after it finishes')
            # A later daily can now set its own intent and queue behind this bounded request.
            yield
        finally: fcntl.flock(runtime,fcntl.LOCK_UN)
