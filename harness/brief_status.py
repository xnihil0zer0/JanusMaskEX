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
                        if not isinstance(row, dict):
                            continue
                        tid = row.get('task_id')
                        if not tid:
                            continue
                        if row.get('phase') == 'accepted' and row.get('event') == 'auto_commit':
                            accepted_map[tid] = {'task_id': tid, 'commit_sha': row.get('commit_sha'), 'ts': row.get('ts')}
                        elif row.get('event') in ('reject_rollback', 'task_blocked'):
                            accepted_map.pop(tid, None)
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
        plan_stale = False
        if has_plan:
            try:
                with open(plan_file, 'r', encoding='utf-8') as f:
                    plan_data = json.load(f)
                    if isinstance(plan_data, dict) and isinstance(plan_data.get('tasks'), list):
                        for t in plan_data['tasks']:
                            if isinstance(t, dict) and 'task_id' in t:
                                task_ids.append(t['task_id'])
                try:
                    stamped = plan_data.get('source_brief_sha256') if isinstance(plan_data, dict) else None
                    if isinstance(stamped, str) and stamped:
                        current_sha = hashlib.sha256(p.read_bytes()).hexdigest()
                        if stamped != current_sha:
                            has_plan = False
                            plan_stale = True
                    elif plan_file.stat().st_mtime < p.stat().st_mtime:
                        has_plan = False
                        plan_stale = True
                except Exception:
                    pass
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
        blocked = [tid for tid in task_ids if ((state_dir / 'tasks' / 'blocked' / f'{tid}.json').exists() or (state_dir / 'tasks' / 'blocked' / f'{tid}.exhausted').exists() or (state_dir / 'control' / 'autowork' / 'selfheal_skip' / tid).exists()) and tid not in accepted_map]
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
        elif processed_unaccepted and all((tid in processed_unaccepted for tid in remaining)):
            state = 'zombie'
        else:
            state = 'queued'
        staged_or_done = set(queued) | set(processing) | set(processed_unaccepted) | set(blocked) | {a['task_id'] for a in accepted_for_brief}
        unstaged_task_ids = [tid for tid in task_ids if tid not in staged_or_done]
        records.append({'slug': slug, 'brief_filename': p.name, 'brief_mtime': p.stat().st_mtime, 'has_plan': has_plan, 'plan_filename': plan_filename, 'plan_stale': plan_stale, 'task_ids': task_ids, 'queued': queued, 'processing': processing, 'processed_unaccepted': processed_unaccepted, 'accepted': accepted_for_brief, 'blocked': blocked, 'remaining': remaining, 'state': state, 'unstaged_task_ids': unstaged_task_ids})
    records.sort(key=lambda x: x['brief_mtime'], reverse=True)
    return records

def _resolve_allowlisted_child_slugs(repo_root, allow) -> set:
    if not allow:
        return set()
    epic_children: dict = {}
    try:
        paths = sorted(Path(repo_root).glob('plan_hooks_*.json'))
    except Exception:
        return set()
    for path in paths:
        try:
            rec = json.loads(path.read_text(encoding='utf-8'))
        except Exception:
            continue
        if not isinstance(rec, dict) or rec.get('plan_kind') != 'epic':
            continue
        es = rec.get('epic_slug')
        cs = rec.get('child_slugs') or []
        if isinstance(es, str) and es and isinstance(cs, list):
            epic_children.setdefault(es, []).extend([c for c in cs if isinstance(c, str) and c])
    admitted: set = set()
    frontier = [e for e in allow if e in epic_children]
    seen: set = set()
    while frontier:
        e = frontier.pop()
        if e in seen:
            continue
        seen.add(e)
        for c in epic_children.get(e, []):
            if c not in admitted:
                admitted.add(c)
                if c in epic_children:
                    frontier.append(c)
    return admitted

def compute_autowork_eligibility(repo_root: Path, state_dir: Path, now=None, max_age_sec: int=604800, config=None) -> dict:
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
    effective_allow = allow
    if config is not None and config.get('hierarchical_planning', {}).get('enabled', False) and allow:
        effective_allow = allow | _resolve_allowlisted_child_slugs(repo_root, allow)
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
        elif slug not in (effective_allow or set()):
            blocked.append({'slug': slug, 'reason': 'allowlist_missing' if allow is None else 'not_in_allowlist'})
        else:
            eligible.append(slug)
            if record.get('unstaged_task_ids'):
                dispatchable.append(slug)
    return {'eligible': eligible, 'blocked': blocked, 'eligible_count': len(eligible), 'blocked_count': len(blocked), 'allowlist_present': allow is not None, 'allowlist_slugs': sorted(allow) if allow else [], 'max_age_sec': int(max_age_sec), 'dispatchable': dispatchable, 'parked': parked}

def compute_epic_status(repo_root: Path, state_dir: Path, config=None) -> list[dict]:
    records = compute_brief_status(repo_root, state_dir)
    index = {r['slug']: r['state'] for r in records}
    accepted_map: dict = {}
    ledger_path = state_dir / 'impl_progress.jsonl'
    if ledger_path.exists():
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        row = json.loads(line)
                        if not isinstance(row, dict):
                            continue
                        tid = row.get('task_id')
                        if not tid:
                            continue
                        if row.get('phase') == 'accepted' and row.get('event') == 'auto_commit':
                            accepted_map[tid] = True
                        elif row.get('event') in ('reject_rollback', 'task_blocked'):
                            accepted_map.pop(tid, None)
                    except json.JSONDecodeError:
                        pass
        except OSError:
            pass

    def _child_slug_marker_failed(cs) -> bool:
        if not isinstance(cs, str) or not cs:
            return False
        if cs in accepted_map:
            return False
        return (state_dir / 'tasks' / 'blocked' / f'{cs}.json').exists() or (state_dir / 'tasks' / 'blocked' / f'{cs}.exhausted').exists() or (state_dir / 'control' / 'autowork' / 'selfheal_skip' / cs).exists()
    failure_propagation = False
    if isinstance(config, dict):
        hp = config.get('hierarchical_planning')
        if isinstance(hp, dict):
            failure_propagation = bool(hp.get('failure_propagation'))
    epic_children = _build_epic_children_map(repo_root) if failure_propagation else {}
    result: list[dict] = []
    for p in sorted(repo_root.glob('plan_hooks_*.json')):
        try:
            with open(p, 'r', encoding='utf-8') as f:
                rec = json.load(f)
        except Exception:
            continue
        if not isinstance(rec, dict) or rec.get('plan_kind') != 'epic':
            continue
        epic_slug = rec.get('epic_slug')
        if not epic_slug:
            epic_slug = p.stem.removeprefix('plan_hooks_')
        child_slugs = rec.get('child_slugs') or []
        children = [{'slug': cs, 'state': index.get(cs, 'unplanned')} for cs in child_slugs]
        direct_failed = any(_child_slug_marker_failed(cs) for cs in child_slugs)
        if not children:
            state = 'planned'
        elif direct_failed or any((c['state'] in {'blocked', 'zombie'} for c in children)):
            state = 'blocked'
        elif all((c['state'] == 'complete' for c in children)):
            state = 'complete'
        else:
            state = 'in_flight'
        if failure_propagation and state != 'blocked':
            if epic_has_failed_descendant(epic_slug, epic_children, index):
                state = 'blocked'
        result.append({'epic_slug': epic_slug, 'state': state, 'children': children})
    return result

def record_epic_complete(epic_slug: str, state_dir: Path) -> None:
    try:
        import time
        from harness._journal import write_jsonl_row
        write_jsonl_row(Path(state_dir) / 'impl_progress.jsonl', {'ts': time.time(), 'phase': 'epic', 'event': 'epic_complete', 'epic_slug': epic_slug})
    except Exception:
        pass

def compute_autowork_backlog(repo_root: Path, state_dir: Path, now=None, max_age_sec: int=604800, config=None) -> dict:
    eligibility = compute_autowork_eligibility(repo_root, state_dir, now, max_age_sec, config)
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
_FAILED_CHILD_STATES = frozenset({'blocked', 'zombie'})

def _build_epic_children_map(repo_root: Path) -> dict:
    """Read-derived epic -> direct child slug map built from plan_hooks_*.json.

    Mirrors the substrate _resolve_allowlisted_child_slugs already reads; performs
    no new I/O beyond globbing the same plan files and writes nothing.
    """
    epic_children: dict = {}
    try:
        paths = sorted(Path(repo_root).glob('plan_hooks_*.json'))
    except Exception:
        return epic_children
    for path in paths:
        try:
            rec = json.loads(path.read_text(encoding='utf-8'))
        except Exception:
            continue
        if not isinstance(rec, dict) or rec.get('plan_kind') != 'epic':
            continue
        es = rec.get('epic_slug')
        if not es:
            es = path.stem.removeprefix('plan_hooks_')
        cs = rec.get('child_slugs') or []
        if isinstance(es, str) and es and isinstance(cs, list):
            epic_children.setdefault(es, []).extend([c for c in cs if isinstance(c, str) and c])
    return epic_children

def epic_has_failed_descendant(epic_slug, epic_children, status_index) -> bool:
    """Read-derived: True if any transitive descendant of ``epic_slug`` is in a
    failed leaf/child state (blocked/zombie) per the existing brief-status index.

    Walks the epic -> child relation (``epic_children``) breadth/depth first over
    the full transitive closure, cycle-safe, consulting only ``status_index``
    (the same slug->state roll-up Phase-1 already reads). No I/O, no persistence.
    """
    if not isinstance(epic_slug, str) or not epic_slug:
        return False
    children = epic_children or {}
    statuses = status_index or {}
    seen: set = set()
    frontier = [c for c in children.get(epic_slug, []) if isinstance(c, str) and c]
    while frontier:
        slug = frontier.pop()
        if slug in seen:
            continue
        seen.add(slug)
        if statuses.get(slug) in _FAILED_CHILD_STATES:
            return True
        for grandchild in children.get(slug, []):
            if isinstance(grandchild, str) and grandchild and (grandchild not in seen):
                frontier.append(grandchild)
    return False
import hashlib