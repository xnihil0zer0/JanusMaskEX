import json
from pathlib import Path

def compute_brief_status(repo_root: Path, state_dir: Path) -> list[dict]:
    """Summarise the planning state of every brief found in ``repo_root``.

    A *brief* is a ``brief_*.md`` file living at the top level of the repo. Its
    matching *plan* is the sibling file with the ``brief_`` prefix swapped for
    ``plan_`` and a ``.json`` suffix (e.g. ``brief_hooks_beta.md`` pairs with
    ``plan_hooks_beta.json``). The display ``slug`` is the trailing
    underscore-delimited component of the brief's stem (``brief_hooks_beta`` ->
    ``beta``).

    A plan lists tasks under its ``"tasks"`` key, each carrying a ``task_id``. A
    task counts as accepted when ``state_dir/impl_progress.jsonl`` holds an event
    whose ``phase`` is ``"accepted"`` for that ``task_id``.

    Each returned row is a dict with:
      - ``slug``: the brief's slug.
      - ``brief``: the brief file name.
      - ``has_plan``: whether the matching plan file exists.
      - ``state``: one of ``"unplanned"`` (no plan), ``"complete"`` (every plan
        task accepted), ``"planned"`` (a plan exists but nothing accepted yet) or
        ``"in_progress"`` (some but not all plan tasks accepted).
      - ``remaining``: the plan task_ids that are not yet accepted.
      - ``total``: the number of tasks in the plan.
      - ``accepted``: the number of accepted plan tasks.
      - ``mtime``: the brief file's modification time.

    Rows are returned sorted by brief file name for deterministic output.
    """
    repo_root = Path(repo_root)
    state_dir = Path(state_dir)
    accepted = _load_accepted_task_ids(state_dir / 'impl_progress.jsonl')
    rows: list[dict] = []
    for brief_path in sorted(repo_root.glob('brief_*.md')):
        slug = brief_path.stem.split('_')[-1]
        plan_path = brief_path.with_name('plan_' + brief_path.name[len('brief_'):]).with_suffix('.json')
        has_plan = plan_path.is_file()
        plan_task_ids = _load_plan_task_ids(plan_path) if has_plan else []
        remaining = [tid for tid in plan_task_ids if tid not in accepted]
        if not has_plan:
            state = 'unplanned'
        elif not remaining:
            state = 'complete'
        elif len(remaining) == len(plan_task_ids):
            state = 'planned'
        else:
            state = 'in_progress'
        rows.append({'slug': slug, 'brief': brief_path.name, 'has_plan': has_plan, 'state': state, 'remaining': remaining, 'total': len(plan_task_ids), 'accepted': len(plan_task_ids) - len(remaining), 'mtime': brief_path.stat().st_mtime})
    return rows

def compute_autowork_eligibility(repo_root: Path, state_dir: Path, now=None, max_age_sec: int=604800) -> dict:
    """Decide which briefs autowork may act on, and why the rest are blocked.

    A brief is *eligible* only when both gates pass:
      - the auto-promote allowlist file
        (``state_dir/control/autowork/auto_promote.allowlist``, one slug per
        line) exists and lists the brief's slug, and
      - the brief is fresh -- ``now - mtime`` does not exceed ``max_age_sec``.

    When the allowlist file is absent every brief is blocked with reason
    ``"allowlist_missing"``; a slug not named in an existing allowlist is blocked
    with ``"not_allowlisted"``; an allowlisted but aged brief is blocked with
    ``"stale"``. ``now`` defaults to the wall clock when not supplied.

    Returns a dict with ``eligible`` (list of slugs), ``eligible_count``,
    ``blocked`` (list of ``{"slug", "reason"}`` dicts) and ``allowlist_present``.
    """
    import time
    repo_root = Path(repo_root)
    state_dir = Path(state_dir)
    if now is None:
        now = time.time()
    allowlist_path = state_dir / 'control' / 'autowork' / 'auto_promote.allowlist'
    allowlist_present = allowlist_path.is_file()
    allowed: set = set()
    if allowlist_present:
        try:
            text = allowlist_path.read_text(encoding='utf-8')
        except OSError:
            text = ''
        for line in text.splitlines():
            line = line.strip()
            if line:
                allowed.add(line)
    eligible: list = []
    blocked: list = []
    for row in compute_brief_status(repo_root, state_dir):
        slug = row['slug']
        if not allowlist_present:
            blocked.append({'slug': slug, 'reason': 'allowlist_missing'})
            continue
        if slug not in allowed:
            blocked.append({'slug': slug, 'reason': 'not_allowlisted'})
            continue
        if now - row['mtime'] > max_age_sec:
            blocked.append({'slug': slug, 'reason': 'stale'})
            continue
        eligible.append(slug)
    return {'eligible': eligible, 'eligible_count': len(eligible), 'blocked': blocked, 'allowlist_present': allowlist_present}

def compute_autowork_backlog(repo_root: Path, state_dir: Path, now=None, max_age_sec: int=604800) -> dict:
    raise NotImplementedError

def _load_accepted_task_ids(progress_path: Path) -> set:
    """Return the set of task_ids that have an ``accepted``-phase event."""
    accepted: set = set()
    if not progress_path.is_file():
        return accepted
    try:
        text = progress_path.read_text(encoding='utf-8')
    except OSError:
        return accepted
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(event, dict):
            continue
        if event.get('phase') == 'accepted':
            task_id = event.get('task_id')
            if task_id is not None:
                accepted.add(task_id)
    return accepted

def _load_plan_task_ids(plan_path: Path) -> list:
    """Return the ordered list of task_ids declared by a plan file."""
    try:
        plan = json.loads(plan_path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError, ValueError):
        return []
    if not isinstance(plan, dict):
        return []
    task_ids: list = []
    for task in plan.get('tasks') or []:
        if isinstance(task, dict):
            task_id = task.get('task_id')
            if task_id is not None:
                task_ids.append(task_id)
        elif isinstance(task, str):
            task_ids.append(task)
    return task_ids