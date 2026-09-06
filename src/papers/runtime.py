"""WSL job owner: model lifecycle, daily priority, batch checkpoints and Git publishing."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime
import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import time
import urllib.request
from zoneinfo import ZoneInfo

from papers import paths

PUBLIC = ('content/papers/archive.json', 'content/papers/arxiv-candidates.json',
          'content/papers/paper-annotations.json', 'docs/notes/', 'docs/index.html',
          'docs/search-index.json', 'docs/togos-papers.json')
PRIVATE = paths.ROOT / 'build/paper-summaries'
ZONE = ZoneInfo('Asia/Shanghai')


def command(*args, capture=False, check=True, timeout=None):
    return subprocess.run(args, cwd=paths.ROOT, check=check, text=True,
                          stdout=subprocess.PIPE if capture else None, timeout=timeout)


def git(*args, capture=False):
    result = command('git', *args, capture=capture)
    return result.stdout.strip() if capture else ''


def clean_pull():
    if git('branch', '--show-current', capture=True) != 'main':
        raise RuntimeError('runtime requires main; integrate the reviewed migration first')
    if git('status', '--porcelain', capture=True):
        raise RuntimeError('worktree is not clean; preserve changes and resolve before retry')
    git('pull', '--ff-only', 'origin', 'main')
    if git('rev-parse', 'HEAD', capture=True) != git('rev-parse', 'origin/main', capture=True):
        raise RuntimeError('local main has unpublished commits; publish the reviewed code before automatic jobs')
    git('var', 'GIT_AUTHOR_IDENT', capture=True)


def allowed_path(path):
    return any((path.startswith(item) and path.endswith('.html') and '/' not in path[len(item):])
               if item.endswith('/') else path == item for item in PUBLIC)


def publish(mode):
    # No untracked or unrelated file can hitchhike in an automatic commit.
    names = git('diff', '--name-only', capture=True).splitlines()
    staged = git('diff', '--cached', '--name-only', capture=True).splitlines()
    untracked = git('ls-files', '--others', '--exclude-standard', capture=True).splitlines()
    if any(not allowed_path(name) for name in names + staged + untracked):
        raise RuntimeError('unexpected public changes; preserve worktree for review')
    command(sys.executable, '-m', 'papers', 'build')
    git('diff', '--check')
    for path in (paths.DOCS / 'assets/js').glob('*.js'):
        node = shutil.which('node') or shutil.which('node.exe')
        if node is None:
            raise RuntimeError('Node.js is required for public JavaScript validation')
        subprocess.run([node, '--check'], input=path.read_text(encoding='utf-8'), text=True, check=True)
    names = git('diff', '--name-only', capture=True).splitlines()
    untracked = git('ls-files', '--others', '--exclude-standard', capture=True).splitlines()
    for name in names + untracked:
        if not allowed_path(name):
            raise RuntimeError('build touched unrelated output')
        path = paths.ROOT / name
        if path.is_file() and any(value in path.read_text(encoding='utf-8') for value in
                                  ('/mnt/g/share', '/home/zyf', 'G:\\share', 'build/paper-summaries', 'vllm-paper.service')):
            raise RuntimeError('public output contains private runtime information')
    git('add', '--', *PUBLIC)
    git('diff', '--cached', '--check')
    if not git('diff', '--cached', '--name-only', capture=True):
        print('No public changes', flush=True)
        return
    git('commit', '-m', f'Publish {mode} paper results for {datetime.now(ZONE):%Y-%m-%d}')
    git('push', 'origin', 'main')


@contextmanager
def lock(name, *, blocking=True):
    import fcntl
    PRIVATE.mkdir(parents=True, exist_ok=True)
    with (PRIVATE / name).open('a+b') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def daily_waiting():
    with lock('daily-request.lock', blocking=False) as available:
        return not available


@contextmanager
def model_service(service):
    started = False
    try:
        if command('systemctl', 'is-active', '--quiet', service, check=False).returncode:
            command('sudo', '-n', '/usr/bin/systemctl', 'start', service)
            started = True
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for attempt in range(60):
            try:
                with opener.open('http://127.0.0.1:8000/v1/models', timeout=5) as response:
                    model = json.load(response)['data'][0]['id']
                if not isinstance(model, str) or not model:
                    raise ValueError('invalid model registry')
            except (OSError, ValueError, KeyError, IndexError):
                if attempt == 59:
                    raise RuntimeError('model readiness timed out') from None
                time.sleep(5)
                continue
            break
        yield model
    finally:
        if started:
            command('sudo', '-n', '/usr/bin/systemctl', 'stop', service)


def in_weekend_window(now=None):
    now = now or datetime.now(ZONE)
    return ((now.weekday() == 5 and (now.hour, now.minute) >= (9, 30))
            or (now.weekday() == 6 and (now.hour, now.minute) < (23, 30)))


def execute(mode, args):
    clean_pull()
    with model_service(args.service) as model:
        common = ['--model', model, '--workers', str(args.workers)]
        if mode == 'daily':
            result = command(sys.executable, '-m', 'papers', 'daily', *common, '--limit', str(args.limit), check=False)
        else:
            from datetime import timedelta
            now = datetime.now(ZONE)
            end = (now + timedelta(days=6 - now.weekday())).replace(hour=23, minute=30, second=0, microsecond=0)
            result = command(sys.executable, '-m', 'papers', 'batch', '--max-batches', '1', *common,
                             check=False, timeout=max(1, (end - now).total_seconds()))
            if result.returncode in (0, 3):
                command(sys.executable, '-m', 'papers', 'publish-offline')
        if result.returncode not in (0, 3):
            raise RuntimeError(f'{mode} failed: exit={result.returncode}; preserve checkpoint and worktree')
        publish(mode)
        return result.returncode


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['daily', 'weekend'])
    parser.add_argument('--service', default='vllm-paper.service')
    parser.add_argument('--workers', type=int, default=2)
    parser.add_argument('--limit', type=int, default=100)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    if not 1 <= args.workers <= 8 or args.limit < 1 or args.service != 'vllm-paper.service':
        parser.error('workers 1-8, positive limit and configured model service required')
    if args.dry_run:
        print(json.dumps({'mode': args.mode, 'workers': args.workers, 'limit': args.limit,
                          'weekend_window': in_weekend_window(), 'public_paths': PUBLIC}))
        return 0
    if sys.platform != 'linux':
        parser.error('run this command inside WSL')
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        if args.mode == 'daily':
            with lock('daily-request.lock', blocking=False) as acquired:
                if not acquired:
                    print('Daily job already queued or running')
                    return 0
                with lock('runtime.lock'):
                    return execute('daily', args)
        # A single durable weekend owner; daily can take runtime.lock between batches.
        with lock('weekend-owner.lock', blocking=False) as acquired:
            if not acquired:
                print('Weekend job already running')
                return 0
            while in_weekend_window():
                if daily_waiting():
                    time.sleep(5)
                    continue
                with lock('runtime.lock'):
                    if daily_waiting():
                        continue
                    result = execute('weekend', args)
                from papers.batch.cycle import load_state
                state = load_state()
                if state is None:
                    return result
                if state.get('network_paused') or state['phase'] == 'summarize':
                    return 3
                time.sleep(5)
        return 0
    except KeyboardInterrupt:
        print('Stopped; completed caches and batch checkpoint retained', flush=True)
        return 130
    except subprocess.TimeoutExpired:
        print('Weekend window ended; cached results and checkpoint retained', flush=True)
        return 130
    except (RuntimeError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr, flush=True)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
