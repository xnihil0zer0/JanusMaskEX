import json
from pathlib import Path

def compute_brief_status(repo_root: Path, state_dir: Path) -> list[dict]:
    accepted_map = {}
    ledger_path = state_dir / 'impl_progress.jsonl'
    if ledger_path.exists():
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        row = json.loads(line)
                        if isinstance(row, dict) and row.get('phase') == 'accepted' and (row.get('event') == 'auto_commit'):
                            tid = row.get('task_id')
                            if tid:
                                accepted_map[tid] = {'task_id': tid, 'commit_sha': row.get('commit_sha'), 'ts': row.get('ts')}
                    except json.JSONDecodeError:
                        pass
        except OSError:
            pass
    records = []
    archive_root = (repo_root / '_archive').resolve()
    for p in repo_root.glob('brief_hooks_*.md'):
        try:
            if archive_root in p.resolve().parents:
                continue
        except OSError:
            pass
        slug = p.stem.removeprefix('brief_hooks_')
        plan_filename = f'plan_hooks_{slug}.json'
        plan_file = repo_root / plan_filename
        has_plan = plan_file.exists() and (not plan_filename.endswith('_critique.json'))
        task_ids = []
        if has_plan:
            try:
                with open(plan_file, 'r', encoding='utf-8') as f:
                    plan_data = json.load(f)
                    if isinstance(plan_data, dict) and isinstance(plan_data.get('tasks'), list):
                        for t in plan_data['tasks']:
                            if isinstance(t, dict) and 'task_id' in t:
                                task_ids.append(t['task_id'])
            except Exception:
                has_plan = False
        if not has_plan:
            plan_filename = None
        accepted_for_brief = []
        remaining = []
        for tid in task_ids:
            if tid in accepted_map:
                accepted_for_brief.append(accepted_map[tid])
            else:
                remaining.append(tid)
        queued = [tid for tid in task_ids if (state_dir / 'tasks' / f'{tid}.json').exists()]
        processing = [tid for tid in task_ids if (state_dir / 'tasks' / 'processing' / f'{tid}.json').exists() or (state_dir / 'tasks' / f'{tid}.json.processing').exists()]
        processed_unaccepted = [tid for tid in task_ids if (state_dir / 'tasks' / 'processed' / f'{tid}.json').exists() and tid not in accepted_map]
        blocked = [tid for tid in task_ids if (state_dir / 'tasks' / 'blocked' / f'{tid}.json').exists()]
        if not has_plan:
            state = 'unplanned'
        elif not task_ids:
            state = 'planned'
        elif blocked:
            state = 'blocked'
        elif queued or processing:
            state = 'in_flight'
        elif not remaining:
            state = 'complete'
        else:
            state = 'queued'
        staged_or_done = set(queued) | set(processing) | set(processed_unaccepted) | set(blocked) | {a['task_id'] for a in accepted_for_brief}
        unstaged_task_ids = [tid for tid in task_ids if tid not in staged_or_done]
        records.append({'slug': slug, 'brief_filename': p.name, 'brief_mtime': p.stat().st_mtime, 'has_plan': has_plan, 'plan_filename': plan_filename, 'task_ids': task_ids, 'queued': queued, 'processing': processing, 'processed_unaccepted': processed_unaccepted, 'accepted': accepted_for_brief, 'blocked': blocked, 'remaining': remaining, 'state': state, 'unstaged_task_ids': unstaged_task_ids})
    records.sort(key=lambda x: x['brief_mtime'], reverse=True)
    return records

def compute_autowork_eligibility(repo_root: Path, state_dir: Path, now=None, max_age_sec: int=604800) -> dict:
    import time
    if now is None:
        now = time.time()
    records = compute_brief_status(repo_root, state_dir)
    allowlist_path = state_dir / 'control' / 'autowork' / 'auto_promote.allowlist'
    if not allowlist_path.exists():
        allow = None
    else:
        try:
            lines = allowlist_path.read_text(encoding='utf-8').splitlines()
            allow = {s for line in lines if (s := line.strip()) and (not s.startswith('#'))}
        except OSError:
            allow = None
    eligible: list[str] = []
    blocked: list[dict] = []
    dispatchable: list[str] = []
    parked: dict[str, list] = {}
    for record in records:
        slug = record['slug']
        zombies = list(record.get('processed_unaccepted') or [])
        if zombies:
            parked[slug] = zombies
        try:
            mtime = float(record['brief_mtime'] or 0)
        except (TypeError, ValueError):
            mtime = 0.0
        if mtime <= 0 or now - mtime > float(max_age_sec):
            blocked.append({'slug': slug, 'reason': 'stale'})
        elif slug not in (allow or set()):
            blocked.append({'slug': slug, 'reason': 'allowlist_missing' if allow is None else 'not_in_allowlist'})
        else:
            eligible.append(slug)
            if record.get('unstaged_task_ids'):
                dispatchable.append(slug)
    return {'eligible': eligible, 'blocked': blocked, 'eligible_count': len(eligible), 'blocked_count': len(blocked), 'allowlist_present': allow is not None, 'allowlist_slugs': sorted(allow) if allow else [], 'max_age_sec': int(max_age_sec), 'dispatchable': dispatchable, 'parked': parked}

def compute_autowork_backlog(repo_root: Path, state_dir: Path, now=None, max_age_sec: int=604800) -> dict:
    eligibility = compute_autowork_eligibility(repo_root, state_dir, now, max_age_sec)
    records = compute_brief_status(repo_root, state_dir)
    record_index = {r['slug']: r for r in records}
    eligible_with_work: list[str] = []
    eligible_without_work: list[str] = []
    detail: list[dict] = []
    for slug in eligibility['eligible']:
        record = record_index.get(slug)
        if record is None:
            state = 'unplanned'
            has_unfinished_work = True
        else:
            state = record['state']
            has_unfinished_work = state == 'unplanned' or bool(record['unstaged_task_ids']) or bool(record['remaining'])
        if has_unfinished_work:
            eligible_with_work.append(slug)
        else:
            eligible_without_work.append(slug)
        detail.append({'slug': slug, 'has_unfinished_work': has_unfinished_work, 'state': state})
    return {'eligible_with_work': eligible_with_work, 'eligible_without_work': eligible_without_work, 'detail': detail}