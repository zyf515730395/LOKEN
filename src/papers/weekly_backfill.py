"""Resumable, newest-first local-model weekly digest backfill (canonical WSL only)."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
import hashlib
import json
from pathlib import Path
import sys
import threading
import time

from papers import paths
from papers.digest_analysis import load_analysis, validate_analysis
from papers.digest_writer import generate_periods, now, write_json
from papers.digests import load_digest_evidence, load_public_papers, publish_paper_digests, build_digest_periods

ROOT = paths.ROOT
ANALYSES = ROOT / 'content/papers/digests'
REPORTS = ROOT / 'build/reports/digests'


def model_admission(boundary, deadline):
    """Serialize probes: flock probes from our own workers must not race."""
    from papers.runtime import daily_waiting
    probe_lock = threading.Lock()
    def admitted():
        with probe_lock:
            return not daily_waiting() and datetime.fromisoformat(now()) < boundary and time.monotonic() < deadline
    return admitted


def weeks_for_year(year: int, today: date) -> list[date]:
    """Completed Monday–Sunday weeks intersecting the requested calendar year."""
    first = date(year, 1, 1)
    first -= timedelta(days=first.weekday())
    last = min(date(year, 12, 31), today - timedelta(days=today.weekday() + 1))
    if last < first:
        return []
    last -= timedelta(days=last.weekday())
    return [last - timedelta(days=7 * i) for i in range((last-first).days // 7 + 1)]


def analysis_processed(analyses, members, topics, summaries):
    expected = {slug: sorted(row['id'] for row in members if topic in row['topics'])
                for topic, slug in topics if any(topic in row['topics'] for row in members)}
    if set(analyses) != set(expected):
        return False
    try:
        for slug, ids in expected.items():
            item=analyses[slug]
            if any(key not in summaries and key not in item.get('skipped_papers',{}) for key in ids):
                return False
            validate_analysis(item, ids, summaries,titles={r['id']:r['title'] for r in members})
        if len({key for item in analyses.values() for key in item.get('skipped_papers',{})}) > 5:
            return False
    except (ValueError, TypeError, KeyError):
        return False
    return True


def analysis_complete(analyses, members, topics, summaries):
    return analysis_processed(analyses,members,topics,summaries) and not any(item.get('skipped_papers') for item in analyses.values())


def fingerprint(relative):
    target = ROOT / relative
    return hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else None


def managed_files(start):
    return [f'content/papers/digests/weekly-{start}.json',
            'content/papers/digests/official-abstracts.json', 'docs/reports/weekly.html',
            *[str(p.relative_to(ROOT)) for p in (ROOT/'docs/reports/periods').glob('weekly-*.json')]]


def changed_files():
    from papers.runtime import git
    # -z preserves spaces/non-ASCII and never relies on quoted porcelain paths.
    tracked = git('diff', '--name-only', '-z', capture=True).split('\0')
    untracked = git('ls-files', '--others', '--exclude-standard', '-z', capture=True).split('\0')
    return set(filter(None, tracked + untracked))


def allowed(relative, start):
    import re
    return relative in {f'content/papers/digests/weekly-{start}.json',
                        'content/papers/digests/official-abstracts.json','docs/reports/weekly.html'} or bool(re.fullmatch(
        r'docs/reports/periods/weekly-\d{4}-\d{2}-\d{2}\.json', relative))


def assert_owned_changes(start, state):
    for relative in changed_files():
        if relative.startswith('content/papers/digests/weekly-') and not allowed(relative,start):
            raise RuntimeError(f'Another weekly source edit must finish first: {relative}')
        if allowed(relative, start) and (relative not in state.get('owned', {})
                                       or fingerprint(relative) != state['owned'][relative]):
            raise RuntimeError(f'Foreign or changed digest edit preserved: {relative}')


def recover_commit(state, state_path):
    """Recover only a predeclared, content-bound commit transaction."""
    from papers.runtime import git
    intent = state.get('commit_intent')
    if not intent:
        return
    head = git('rev-parse','HEAD',capture=True)
    if any(fingerprint(p) != digest for p,digest in intent['hashes'].items()):
        raise RuntimeError('Commit intent files changed; preserve the index and worktree')
    staged = set(filter(None,git('diff','--cached','--name-only','-z',capture=True).split('\0')))
    if head == intent['base']:
        if staged != set(intent['files']):
            raise RuntimeError('Interrupted commit index changed; preserve it')
        git('diff','--cached','--check')
        git('commit','-m',f'Backfill weekly paper trends for {intent["week"]}')
        head = git('rev-parse','HEAD',capture=True)
    else:
        if staged or git('rev-parse',f'{head}^',capture=True) != intent['base']:
            raise RuntimeError('Interrupted commit history changed; preserve it')
        actual = set(filter(None,git('diff-tree','--no-commit-id','--name-only','-r','-z',head,capture=True).split('\0')))
        if actual != set(intent['files']):
            raise RuntimeError('Interrupted commit includes foreign files')
        for relative,digest in intent['hashes'].items():
            # Blob hashes avoid newline transformations and bind HEAD to the intent.
            if git('rev-parse',f'{head}:{relative}',capture=True) != intent['blobs'][relative]:
                raise RuntimeError('Interrupted commit content differs from intent')
    state['pending'] = {'week':intent['week'],'commit':head,'papers':intent['papers'],'topics':intent['topics'],'complete':intent.get('complete',True),'resume_status':intent.get('resume_status'),'advance':intent.get('advance',False),'skipped_papers':intent.get('skipped_papers',{})}
    state.pop('commit_intent')
    write_json(state_path,state)


def recover_push(state, state_path):
    from papers.runtime import git, _push_main_once
    pending = state.get('pending')
    if not pending:
        return
    git('fetch', 'origin', 'main')
    commit = pending['commit']
    from papers.runtime import command
    published = command('git', 'merge-base', '--is-ancestor', commit, 'origin/main', check=False).returncode == 0
    if not published:
        if git('rev-parse', 'HEAD', capture=True) != commit:
            raise RuntimeError('Pending backfill commit is not HEAD; preserve concurrent history')
        _push_main_once(commit, timeout=120)
        git('fetch', 'origin', 'main')
        if command('git', 'merge-base', '--is-ancestor', commit, 'origin/main', check=False).returncode:
            raise RuntimeError('Backfill remote inclusion unconfirmed')
    category = 'completed' if pending.get('complete',True) else ('partial' if pending.get('advance') else 'checkpoints')
    for old_category in ('completed','partial','checkpoints'):
        if old_category != category:
            previous=state.get(old_category,{}).pop(pending['week'],None)
            if previous: state.setdefault('publication_history',[]).append({'category':old_category,**previous})
    state.setdefault(category, {})[pending['week']] = {**pending, 'verified_at': now()}
    state.pop('pending')
    state['owned'] = {}
    if pending.get('complete',True) or pending.get('advance'):
        state['remaining_weeks'] = [w for w in state.get('remaining_weeks',[]) if w != pending['week']]
        state['verified_weeks']=[w for w in state.get('verified_weeks',[]) if w != pending['week']]
        state['partial_weeks']=[w for w in state.get('partial_weeks',[]) if w != pending['week']]
        if not pending.get('complete',True): state['partial_weeks'].append(pending['week'])
        if pending.get('complete',True):
            state['verified_weeks'] = sorted(set(state.get('verified_weeks',[])) | {pending['week']},reverse=True)
        state['processed_weeks'] = sorted(set(state.get('processed_weeks',[])) | set(state.get('verified_weeks',[])) | {pending['week']},reverse=True)
        state['status'] = ('partial_published' if pending.get('advance') and not pending.get('complete',True) else 'checkpoint_published') if state['remaining_weeks'] else ('completed_with_gaps' if state.get('partial_weeks') else 'completed')
    else:
        state['status'] = pending.get('resume_status') or 'deferred_generation'
    state.pop('error',None)
    write_json(state_path, state)


def publish_week(start, base, state, state_path, *, complete=True, advance=False, skipped=None):
    from papers.runtime import git
    if git('rev-parse', 'HEAD', capture=True) != base:
        raise RuntimeError('HEAD changed during generation; preserve all changes')
    if git('diff', '--cached', '--name-only', capture=True):
        raise RuntimeError('Index belongs to another task; preserve it')
    candidates = sorted(p for p in changed_files() if allowed(p, start))
    for relative in candidates:
        if relative not in state.get('owned', {}) or fingerprint(relative) != state['owned'][relative]:
            raise RuntimeError(f'Unowned publication edit: {relative}')
    if candidates:
        git('add', '--', *candidates)
        git('diff', '--cached', '--check')
        staged = set(git('diff', '--cached', '--name-only', '-z', capture=True).split('\0')) - {''}
        if staged != set(candidates):
            raise RuntimeError('Concurrent index change; do not commit')
        state['commit_intent'] = {'base':base,'week':str(start),'files':candidates,
                                  'hashes':{p:fingerprint(p) for p in candidates},
                                  'blobs':{p:git('rev-parse',f':{p}',capture=True) for p in candidates},
                                  'papers':state['papers'],'topics':state['topics'],'complete':complete,'resume_status':state.get('resume_status'),'advance':advance,'skipped_papers':skipped or {}}
        write_json(state_path,state)
        recover_commit(state,state_path)
        recover_push(state,state_path)
        return
    commit = git('rev-parse', 'HEAD', capture=True)
    state['pending'] = {'week': str(start), 'commit': commit, 'papers': state['papers'], 'topics': state['topics'],'complete':complete,'resume_status':state.get('resume_status'),'advance':advance,'skipped_papers':skipped or {}}
    write_json(state_path, state)
    recover_push(state, state_path)


def run(year, max_weeks=1, max_minutes=60):
    from papers.runtime import lock, daily_waiting, model_service, git, PRIVATE
    state_path = REPORTS / f'backfill-{year}.json'
    state = json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {'version': 1, 'year': year, 'completed': {}, 'owned': {}}
    if state.get('version') != 1 or state.get('year') != year:
        raise ValueError('Invalid backfill checkpoint; preserve it')
    began = datetime.fromisoformat(now())
    boundary = began.replace(hour=18, minute=0, second=0, microsecond=0)
    if boundary <= began:
        boundary += timedelta(days=1)
    deadline = time.monotonic() + max_minutes * 60
    finished = 0
    try:
        while max_weeks == 0 or finished < max_weeks:
            with lock('runtime.lock', blocking=False) as acquired:
                if not acquired or daily_waiting() or datetime.fromisoformat(now()) >= boundary:
                    state['status'] = 'deferred_daily_or_runtime'
                    break
                if (PRIVATE/'recheck/local-only.json').exists() or (PRIVATE/'pending-runtime-push.json').exists():
                    raise RuntimeError('Another publication/review checkpoint requires recovery first')
                if git('branch', '--show-current', capture=True) != 'main':
                    raise RuntimeError('Backfill publication requires main')
                recover_commit(state,state_path)
                if git('diff', '--cached', '--name-only', capture=True):
                    raise RuntimeError('Preserve another task staged changes')
                recover_push(state, state_path)
                git('pull', '--ff-only', 'origin', 'main')
                base = git('rev-parse', 'HEAD', capture=True)
                if base != git('rev-parse', 'origin/main', capture=True):
                    raise RuntimeError('Unknown unpublished commits; preserve them')
                today = datetime.fromisoformat(now()).date()
                weeks = weeks_for_year(year, today)
                print('Loading public weekly coverage and evidence', flush=True)
                rows, topics = load_public_papers(today=today,include_historical=True)
                summaries = load_digest_evidence(ROOT/'docs', ANALYSES)
                pending = []
                valid = []
                partial = []
                for start in weeks:
                    members = [r for r in rows if start <= r['digest_date'] <= start+timedelta(days=6)]
                    saved=load_analysis(ANALYSES,'weekly',str(start))
                    exists=(ANALYSES/f'weekly-{start}.json').exists()
                    processed=exists and analysis_processed(saved,members,topics,summaries)
                    complete=processed and analysis_complete(saved,members,topics,summaries)
                    # A valid committed source still needs a published calendar asset.
                    asset = ROOT/f'docs/reports/periods/weekly-{start}.json'
                    published = git('ls-files', '--', str((ANALYSES/f'weekly-{start}.json').relative_to(ROOT)), capture=True) if processed else ''
                    expected_asset = build_digest_periods(members,topics,summaries,kind='weekly',today=start+timedelta(days=6),limit=1,analysis_root=ANALYSES)[0] if processed else None
                    asset_current = asset.exists() and json.loads(asset.read_text(encoding='utf-8')) == expected_asset
                    if processed and asset_current and published and not any(allowed(p,start) for p in changed_files()):
                        (valid if complete else partial).append(str(start))
                    else:
                        pending.append((start, members, processed))
                state.update(total_weeks=len(weeks), verified_weeks=valid, partial_weeks=partial, processed_weeks=sorted(valid+partial,reverse=True), remaining_weeks=[str(p[0]) for p in pending], updated_at=now())
                write_json(state_path, state)
                if not pending:
                    state['status'] = 'completed_with_gaps' if partial else 'completed'
                    break
                # Finish our unpublished transaction before admitting a newer week.
                active = state.get('active_week') if state.get('owned') else None
                start, members, processed = next((item for item in pending if str(item[0]) == active), pending[0])
                assert_owned_changes(start, state)
                state.update(active_week=str(start), status='generating', papers=len(members), topics=sum(any(t in r['topics'] for r in members) for t,_ in topics))
                write_json(state_path, state)
                print(f'Backfill {start}: {len(members)} papers; {len(pending)} weeks remaining', flush=True)

                def record_write(path):
                    relative = str(path.relative_to(ROOT))
                    state.setdefault('owned', {})[relative] = fingerprint(relative)
                    state['updated_at'] = now()
                    write_json(state_path, state)

                admission = model_admission(boundary,deadline)

                if not admission():
                    state['status']='deferred_slice'
                    break
                incomplete = False
                if not processed:
                    with model_service('vllm-paper.service') as model:
                        result = generate_periods([('weekly',start,start+timedelta(days=6))],today=today,model=model,
                                                  sentence_evidence_only=True, context=(rows,topics,summaries),on_write=record_write,should_continue=admission,skip_failed_papers=True)
                    state['generation'] = result
                    write_json(state_path, state)
                    blocking=[f for f in result['failures'] if f.get('paper') not in result.get('skipped_papers',{})]
                    if blocking or result.get('interrupted'):
                        incomplete = True
                        state['resume_status'] = 'deferred_generation' if result.get('interrupted') else 'failed_generation'
                analyses = load_analysis(ANALYSES,'weekly',str(start))
                if not incomplete and not analysis_processed(analyses,members,topics,summaries):
                    raise RuntimeError('Full-week evidence coverage validation failed')
                assert_owned_changes(start, state)
                before = {p: fingerprint(p) for p in managed_files(start)}
                print(f'Building weekly archive through {start}', flush=True)
                outputs = publish_paper_digests(generated_on=today,kinds=('weekly',))
                for path in outputs:
                    relative = str(path.relative_to(ROOT))
                    if fingerprint(relative) != before.get(relative):
                        record_write(path)
                state['status'] = 'publishing'
                write_json(state_path, state)
                skips={key:value for item in analyses.values() for key,value in item.get('skipped_papers',{}).items()}
                advance=not incomplete and bool(skips)
                publish_week(start,base,state,state_path,complete=not incomplete and not skips,advance=advance,skipped=skips)
                category = 'checkpoints' if incomplete else ('partial' if advance else 'completed')
                print(f'Published {category} checkpoint {start}: {state[category][str(start)]["commit"]}',flush=True)
                if incomplete:
                    break
                finished += 1
            if time.monotonic() >= deadline:
                state['status'] = 'deferred_slice'
                break
        state['weeks_published_this_run'] = finished
        state['updated_at'] = now()
        write_json(state_path, state)
        return state
    except Exception as error:
        state.update(status='failed',error=f'{type(error).__name__}: {error}',updated_at=now())
        write_json(state_path, state)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('status','run'))
    parser.add_argument('--year',type=int,default=2026)
    parser.add_argument('--max-weeks',type=int,default=1,help='0 processes until the slice boundary')
    parser.add_argument('--max-minutes',type=int,default=60,help='stop admitting model requests at the slice boundary')
    args = parser.parse_args(argv)
    if not 1 <= args.year <= 9998 or args.max_weeks < 0 or args.max_minutes < 1:
        parser.error('Expected a valid year, nonnegative weeks and positive minutes')
    if sys.platform != 'linux' or ROOT.resolve() != Path('/mnt/g/share/projects/arxiv-papers-daily').resolve():
        parser.error('Use the canonical shared WSL workspace')
    target = REPORTS / f'backfill-{args.year}.json'
    if args.command == 'status':
        value = json.loads(target.read_text(encoding='utf-8')) if target.exists() else {'status':'not_started','year':args.year,'total_weeks':len(weeks_for_year(args.year,datetime.fromisoformat(now()).date()))}
    else:
        from papers.runtime import lock
        with lock('weekly-backfill-owner.lock',blocking=False) as acquired:
            if not acquired:
                print('Another weekly backfill owns the queue; deferred.',file=sys.stderr)
                return 4
            value = run(args.year,args.max_weeks,args.max_minutes)
    print(json.dumps(value,ensure_ascii=False,indent=2))
    return 3 if str(value.get('status','')).startswith('failed') else 0


if __name__ == '__main__':
    raise SystemExit(main())
