"""WSL job owner: model lifecycle, daily priority, batch checkpoints and Git publishing."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime
import json
import os
import re
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import time
import urllib.request
from zoneinfo import ZoneInfo

from papers import paths
from papers.model_runtime import DEFAULT_MODEL, DEFAULT_MODEL_TIMEOUT_SECONDS, DEFAULT_MODEL_WORKERS, MAX_MODEL_WORKERS

PUBLIC = ('content/papers/archive.json', 'content/papers/arxiv-candidates.json',
          'content/papers/conference-library.json',
          'content/papers/paper-annotations.json', 'docs/notes/', 'docs/index.html',
          'docs/search-index.json', 'docs/togos-papers.json', 'docs/reports/', 'content/papers/digests/')
PRIVATE = paths.ROOT / 'build/paper-summaries'
ZONE = ZoneInfo('Asia/Shanghai')
BACKFILL_BATCH_SIZE = 100
GIT_PUSH_TIMEOUT_SECONDS = 5 * 60
GIT_SYNC_TIMEOUT_SECONDS = 120
GIT_PUSH_RETRY_SECONDS = 60
GIT_SSH_COMMAND = 'ssh -o BatchMode=yes -o ConnectTimeout=20 -o ServerAliveInterval=15 -o ServerAliveCountMax=4'
PENDING_PUSH = PRIVATE / 'pending-runtime-push.json'
DAILY_STATE = PRIVATE / 'daily-all-state.json'
CONFERENCE_STATE = PRIVATE / 'conference-backlog-state.json'


class RetryableGitPush(RuntimeError):
    """A transient push failure that must not discard completed publication work."""


def command(*args, capture=False, check=True, timeout=None, env=None):
    if timeout is None:
        return subprocess.run(args, cwd=paths.ROOT, check=check, text=True,
                              stdout=subprocess.PIPE if capture else None, env=env)
    process = subprocess.Popen(args, cwd=paths.ROOT, text=True, env=env,
                               stdout=subprocess.PIPE if capture else None,
                               start_new_session=True)
    try:
        stdout, _ = process.communicate(timeout=timeout)
    except (subprocess.TimeoutExpired, KeyboardInterrupt):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate()
        raise
    result = subprocess.CompletedProcess(args, process.returncode, stdout)
    if check:
        result.check_returncode()
    return result


def git(*args, capture=False):
    network = args[0] in ('pull', 'fetch', 'push', 'ls-remote')
    environment = os.environ.copy()
    environment.setdefault('GIT_SSH_COMMAND', GIT_SSH_COMMAND)
    environment['GIT_TERMINAL_PROMPT'] = '0'
    result = command('git', *args, capture=capture, env=environment,
                     timeout=GIT_SYNC_TIMEOUT_SECONDS if network else None)
    return result.stdout.strip() if capture else ''


def _origin_is_ancestor():
    return command('git', 'merge-base', '--is-ancestor', 'origin/main', 'HEAD',
                   check=False).returncode == 0


def _push_main_once(commit, *, timeout=GIT_PUSH_TIMEOUT_SECONDS):
    environment = os.environ.copy()
    environment['GIT_SSH_COMMAND'] = GIT_SSH_COMMAND
    process = subprocess.Popen(
        ('git', 'push', 'origin', f'{commit}:refs/heads/main'), cwd=paths.ROOT, env=environment,
        start_new_session=True,
    )
    try:
        return_code = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
        raise RetryableGitPush(
            f'git push timed out after {timeout:g}s; completed commit retained for retry'
        ) from None
    if return_code:
        raise RetryableGitPush(
            f'git push failed: exit={return_code}; completed commit retained for retry'
        )


def _push_main():
    if (PRIVATE / 'recheck/local-only.json').exists():
        raise RuntimeError('local recheck review is active; remote publication is disabled')
    receipt = json.loads(PENDING_PUSH.read_text(encoding='utf-8'))
    commit = receipt.get('commit')
    base = receipt.get('base')
    if (not commit or not base or git('rev-parse', 'HEAD', capture=True) != commit
            or git('rev-parse', f'{commit}^', capture=True) != base):
        raise RuntimeError('Publication history changed; preserve concurrent task commits for review')
    _push_main_once(commit)
    git('fetch', 'origin', 'main')
    if commit != git('rev-parse', 'origin/main', capture=True):
        raise RetryableGitPush('git push was not confirmed by origin/main; completed commit retained for retry')
    PENDING_PUSH.unlink(missing_ok=True)


def clean_pull():
    if (PRIVATE / 'recheck/local-only.json').exists():
        return False
    if git('branch', '--show-current', capture=True) != 'main':
        raise RuntimeError('runtime requires main; integrate the reviewed migration first')
    if git('status', '--porcelain', capture=True):
        raise RuntimeError('worktree is not clean; preserve changes and resolve before retry')
    git('pull', '--ff-only', 'origin', 'main')
    recovered = False
    if git('rev-parse', 'HEAD', capture=True) != git('rev-parse', 'origin/main', capture=True):
        if not _origin_is_ancestor():
            raise RuntimeError('local main and origin/main diverged; preserve both histories for review')
        receipt = json.loads(PENDING_PUSH.read_text(encoding='utf-8')) if PENDING_PUSH.exists() else {}
        if receipt.get('commit') != git('rev-parse', 'HEAD', capture=True):
            raise RuntimeError('Local commits await explicit publication; another maintenance job must not push them')
        print('Recovering this runtime publication from its pending push receipt', flush=True)
        _push_main()
        recovered = True
    git('var', 'GIT_AUTHOR_IDENT', capture=True)
    return recovered


def allowed_path(path):
    if path.startswith('content/papers/digests/'):
        if path == 'content/papers/digests/official-abstracts.json':
            return True
        return bool(re.fullmatch(r'content/papers/digests/(daily|weekly)-\d{4}-\d{2}-\d{2}\.json', path))
    if path.startswith('docs/reports/'):
        return path in {'docs/reports/daily.html', 'docs/reports/weekly.html'} or bool(
            re.fullmatch(r'docs/reports/periods/(daily|weekly)-\d{4}-\d{2}-\d{2}\.json', path))
    return any((path.startswith(item) and path.endswith('.html') and '/' not in path[len(item):])
               if item.endswith('/') else path == item for item in PUBLIC)


def publish(mode, *, expected_head, model=None):
    digest_failed = False
    if (PRIVATE / 'recheck/local-only.json').exists():
        command(sys.executable, '-m', 'papers', 'build')
        print('Local review: built results; Git publication remains disabled', flush=True)
        return
    if git('branch', '--show-current', capture=True) != 'main' or git('rev-parse', 'HEAD', capture=True) != expected_head:
        raise RuntimeError('Another task changed the branch or committed during inference; preserve both results for review')
    # No untracked or unrelated file can hitchhike in an automatic commit.
    names = git('diff', '--name-only', capture=True).splitlines()
    staged = git('diff', '--cached', '--name-only', capture=True).splitlines()
    untracked = git('ls-files', '--others', '--exclude-standard', capture=True).splitlines()
    if any(not allowed_path(name) for name in names + staged + untracked):
        raise RuntimeError('unexpected public changes; preserve worktree for review')
    command(sys.executable, '-m', 'papers', 'build')
    if mode == 'daily arxiv':
        from papers.digest_writer import generate_recent
        report = generate_recent(model=model)
        digest_failed = bool(report['failures'])
        print('Digest analysis: ' + json.dumps(report, ensure_ascii=False), flush=True)
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
        return digest_failed
    if git('branch', '--show-current', capture=True) != 'main' or git('rev-parse', 'HEAD', capture=True) != expected_head:
        raise RuntimeError('Publication base changed during build; preserve the staged results for review')
    git('commit', '-m', f'Publish {mode} paper results for {datetime.now(ZONE):%Y-%m-%d}')
    from papers.candidate_ledger import atomic_write_json
    commit = git('rev-parse', 'HEAD', capture=True)
    if git('rev-parse', f'{commit}^', capture=True) != expected_head:
        raise RuntimeError('Concurrent commit detected; local results retained without pushing')
    atomic_write_json(PENDING_PUSH, {'commit': commit, 'base': expected_head})
    _push_main()
    return digest_failed


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
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def registered_model():
        try:
            with opener.open('http://127.0.0.1:8000/v1/models', timeout=5) as response:
                model = json.load(response)['data'][0]['id']
            return model if isinstance(model, str) and model else None
        except (OSError, ValueError, KeyError, IndexError):
            return None

    try:
        model = registered_model()
        if model is None and command('systemctl', 'is-active', '--quiet', service, check=False).returncode:
            command('sudo', '-n', '/usr/bin/systemctl', 'start', service)
            started = True
        deadline = time.monotonic() + DEFAULT_MODEL_TIMEOUT_SECONDS
        while True:
            model = registered_model()
            if model is None:
                if command('systemctl', 'is-failed', '--quiet', service, check=False).returncode == 0:
                    raise RuntimeError('model service failed during startup; inspect its systemd journal')
                if time.monotonic() >= deadline:
                    raise RuntimeError('model readiness timed out') from None
                time.sleep(5)
                continue
            break
        if model != os.environ.get('TOGOS_WSL_LLM_MODEL', DEFAULT_MODEL):
            raise RuntimeError('active model differs from the configured paper model; preserve the existing service and inspect its configuration')
        yield model
    finally:
        if started:
            command('sudo', '-n', '/usr/bin/systemctl', 'stop', service)


def in_weekend_window(now=None):
    now = now or datetime.now(ZONE)
    return ((now.weekday() == 5 and (now.hour, now.minute) >= (9, 30))
            or (now.weekday() == 6 and (now.hour, now.minute) < (23, 30)))


def execute_daily(args, model, common, expected_head):
    """Recover publication, then catch up the newest arXiv period before backlog."""
    from papers.scheduler import periods
    while True:
        result = _execute_daily_pass(args, model, common, expected_head)
        state = json.loads(DAILY_STATE.read_text())
        saved_period = state.get('arxiv_period', state['started_at'][:10])
        if saved_period >= periods(datetime.now(ZONE))['daily']:
            return result
        expected_head = git('rev-parse', 'HEAD', capture=True)


def _execute_daily_pass(args, model, common, expected_head):
    """Publish arXiv before conferences; retain stage progress across interruption."""
    from papers.candidate_ledger import atomic_write_json
    from papers.conference_intake import PRIVATE as CONFERENCE_PRIVATE, summarize
    if (PRIVATE / 'recheck/local-only.json').exists():
        raise RuntimeError('daily stage handoff requires remote publication; local review is active')
    state = json.loads(DAILY_STATE.read_text()) if DAILY_STATE.exists() else {}
    if state and state.get('phase') not in {'arxiv', 'arxiv_publish', 'conference', 'conference_publish', 'complete'}:
        raise RuntimeError('invalid daily stage checkpoint; preserve it for inspection')
    from papers.scheduler import periods
    period = periods(datetime.now(ZONE))['daily']
    if (state.get('phase') == 'conference'
            and state.get('arxiv_period', state['started_at'][:10]) < period):
        # Old conference work must not suppress a newer daily arXiv pass.
        atomic_write_json(CONFERENCE_STATE, state)
        history = PRIVATE / 'daily-runs' / (state['started_at'].replace(':', '-') + '-deferred.json')
        atomic_write_json(history, {**state, 'status': 'deferred'})
        state = {}
    if not state or state.get('phase') == 'complete':
        state = {'started_at': datetime.now(ZONE).isoformat(), 'phase': 'arxiv',
                 'limit': args.limit, 'arxiv_exit': 0, 'arxiv_period': period}
        atomic_write_json(DAILY_STATE, state)
    if state['limit'] != args.limit:
        raise RuntimeError('resume daily with its original limit; preserve the active checkpoint')
    if state['phase'] == 'arxiv':
        scope = ['--all'] if args.limit is None else ['--limit', str(args.limit)]
        result = command(sys.executable, '-m', 'papers', 'daily', *common, *scope, check=False)
        if result.returncode not in (0, 3):
            raise RuntimeError(f'daily arxiv failed: exit={result.returncode}; preserve checkpoint')
        state.update(phase='arxiv_publish', arxiv_exit=result.returncode)
        atomic_write_json(DAILY_STATE, state)
    if state['phase'] == 'arxiv_publish':
        digest_failed = publish('daily arxiv', expected_head=expected_head, model=model)
        if digest_failed:
            state.update(arxiv_exit=3, digest_failed=True, digest_report='build/reports/digests/latest.json')
        expected_head = git('rev-parse', 'HEAD', capture=True)
        baseline_path = CONFERENCE_PRIVATE / 'summary-state.json'
        baseline = json.loads(baseline_path.read_text()) if baseline_path.exists() else {}
        backlog = json.loads(CONFERENCE_STATE.read_text()) if CONFERENCE_STATE.exists() else {}
        state.update(phase='conference', arxiv_sha=expected_head,
                     conference_baseline=backlog.get('conference_baseline',
                         {k: v.get('attempts', 0) for k, v in baseline.items()}))
        atomic_write_json(DAILY_STATE, state)
        print(f'arXiv stage published: {expected_head}; starting conference queue', flush=True)
    if state['phase'] == 'conference':
        if state.get('arxiv_period', state['started_at'][:10]) < periods(datetime.now(ZONE))['daily']:
            # The arXiv stage or its recovered publication crossed a daily boundary.
            # Hand back to execute_daily before admitting any old conference work.
            return 4
        if datetime.now(ZONE).weekday() >= 5:
            atomic_write_json(CONFERENCE_STATE, state)
            state.update(phase='complete', conference_deferred='weekend',
                         completed_at=datetime.now(ZONE).isoformat())
            atomic_write_json(DAILY_STATE, state)
            archive = PRIVATE / 'daily-runs' / (state['started_at'].replace(':', '-') + '.json')
            atomic_write_json(archive, state)
            return 3 if state['arxiv_exit'] else 0
        baseline = state['conference_baseline']
        receipts_path = CONFERENCE_PRIVATE / 'summary-state.json'
        receipts = json.loads(receipts_path.read_text()) if receipts_path.exists() else {}
        from papers.conference_retry import current_attempt
        from papers.conference_library import load_library
        records = load_library()['papers']
        excluded = {k for k, v in receipts.items() if v.get('attempts', 0) > baseline.get(k, 0)
                    and current_attempt(records.get(k, {}), v)}
        remaining_limit = None if args.limit is None else max(0, args.limit - len(excluded))
        from datetime import timedelta
        now = datetime.now(ZONE)
        saved_period = state.get('arxiv_period', state['started_at'][:10])
        next_daily = datetime.fromisoformat(saved_period).replace(
            hour=18, tzinfo=ZONE) + timedelta(days=1)
        seconds = min(120 * 60, (next_daily - now).total_seconds())
        if seconds <= 0:
            return 4
        report = summarize(limit=remaining_limit, timeout=args.timeout, model=model,
                           runtime_owned=True, excluded_ids=excluded,
                           deadline=time.monotonic() + seconds)
        receipts = json.loads(receipts_path.read_text()) if receipts_path.exists() else {}
        attempted = {k: v for k, v in receipts.items() if v.get('attempts', 0) > baseline.get(k, 0)}
        # Include failures from an interrupted portion, not just the latest process.
        failed = sum(v.get('status') == 'failed' for v in attempted.values())
        state.update(phase='conference_publish', conference_report=report,
                     conference_attempts=list(attempted), conference_failed=failed)
        atomic_write_json(DAILY_STATE, state)
    publish('daily conferences', expected_head=expected_head)
    counts = state.get('conference_report', {}).get('counts', {})
    if counts.get('yielded_to_calendar') or counts.get('yielded_to_deadline'):
        state.update(phase='conference',
                     conference_deferred='weekend' if counts.get('yielded_to_calendar') else 'time_slice',
                     conference_sha=git('rev-parse', 'HEAD', capture=True))
        atomic_write_json(DAILY_STATE, state)
        atomic_write_json(CONFERENCE_STATE, state)
        return 4
    state.update(phase='complete', conference_sha=git('rev-parse', 'HEAD', capture=True),
                 completed_at=datetime.now(ZONE).isoformat())
    atomic_write_json(DAILY_STATE, state)
    CONFERENCE_STATE.unlink(missing_ok=True)
    archive_path = PRIVATE / 'daily-runs' / (state['started_at'].replace(':','-') + '.json')
    atomic_write_json(archive_path, state)
    partial = (state['arxiv_exit'] or state.get('conference_failed')
               or state.get('conference_report', {}).get('counts', {}).get('failed')
               or state.get('conference_report', {}).get('remaining'))
    return 3 if partial else 0


def execute(mode, args):
    recovered_push = clean_pull()
    expected_head = git('rev-parse', 'origin/main', capture=True)
    if mode == 'backfill' and recovered_push:
        print('Recovered prior publication push', flush=True)
        return 0
    with model_service(args.service) as model:
        common = ['--model', model, '--workers', str(args.workers), '--timeout', str(args.timeout)]
        if mode == 'daily':
            return execute_daily(args, model, common, expected_head)
        else:
            from datetime import timedelta
            now = datetime.now(ZONE)
            # Release runtime.lock after each checkpoint batch. Publication
            # batching never imposes a paper-count-based inference rest.
            batch_count = 1
            command_args = [sys.executable, '-m', 'papers', 'batch',
                            '--batch-size', str(BACKFILL_BATCH_SIZE),
                            '--max-batches', str(batch_count), '--batch-pause', '0', *common]
            if mode == 'weekend':
                end = (now + timedelta(days=6 - now.weekday())).replace(
                    hour=23, minute=30, second=0, microsecond=0)
                result = command(*command_args, check=False,
                                 timeout=max(1, (end - now).total_seconds()))
            else:
                result = command(*command_args, check=False)
            if result.returncode in (0, 3):
                command(sys.executable, '-m', 'papers', 'publish-offline')
        if result.returncode not in (0, 3):
            raise RuntimeError(f'{mode} failed: exit={result.returncode}; preserve checkpoint and worktree')
        publish(mode, expected_head=expected_head)
        return result.returncode


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['daily', 'weekend', 'backfill'])
    parser.add_argument('--service', default='vllm-paper.service')
    parser.add_argument('--workers', type=int, default=DEFAULT_MODEL_WORKERS)
    parser.add_argument('--timeout', type=float, default=DEFAULT_MODEL_TIMEOUT_SECONDS)
    parser.add_argument('--limit', type=int, default=None, help='optional bounded daily attempt limit; default all')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    effective_mode = 'backfill' if args.mode == 'weekend' else args.mode
    if (not 1 <= args.workers <= MAX_MODEL_WORKERS or (args.limit is not None and args.limit < 1) or args.timeout <= 0
            or args.service != 'vllm-paper.service'):
        parser.error(f'workers 1-{MAX_MODEL_WORKERS}, positive limit/timeout and configured model service required')
    if args.dry_run:
        print(json.dumps({'mode': effective_mode, 'workers': args.workers, 'timeout': args.timeout,
                          'limit': args.limit, 'weekend_window': in_weekend_window(),
                          'checkpoint_batch_size': BACKFILL_BATCH_SIZE,
                          'inference_run_seconds': 7200, 'inference_rest_seconds': 600,
                          'public_paths': PUBLIC}))
        return 0
    if sys.platform != 'linux':
        parser.error('run this command inside WSL')
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        if effective_mode == 'daily':
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
            while True:
                if daily_waiting():
                    time.sleep(5)
                    continue
                try:
                    with lock('runtime.lock'):
                        if daily_waiting():
                            continue
                        result = execute('backfill', args)
                except RetryableGitPush as error:
                    print(f'{error}; retrying in {GIT_PUSH_RETRY_SECONDS}s', file=sys.stderr, flush=True)
                    time.sleep(GIT_PUSH_RETRY_SECONDS)
                    continue
                from papers.batch.cycle import load_state, recovery_cycle_pending
                state = load_state()
                if state is None:
                    if recovery_cycle_pending():
                        continue
                    return result
                if state.get('network_paused') or state['phase'] == 'summarize':
                    return 3
        return 0
    except KeyboardInterrupt:
        print('Stopped; completed caches and batch checkpoint retained', flush=True)
        return 130
    except subprocess.TimeoutExpired as error:
        print(f'Command timed out after {error.timeout}s: {error.cmd}; '
              'completed results and checkpoints retained for retry', flush=True)
        return 130
    except (RuntimeError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr, flush=True)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
