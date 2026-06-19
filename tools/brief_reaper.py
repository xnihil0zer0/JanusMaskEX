"""Archive-on-integrate reaper for brief + plan paperwork.

This stdlib-only module exposes a single public helper,
:func:`reap_for_task`, the targeted half of archive-on-integrate: when a
build task lands, it archives that task's ``brief_hooks_<slug>.md`` and
``plan_hooks_<slug>.json`` from the repository root IFF the whole plan is
now integrated. "Integrated" is decided from GROUND-TRUTH evidence -- the
reaped task plus the integration ledger ``state/impl_progress.jsonl`` -- and
NEVER by re-running a plan's verification_command.

The function runs on the worker's hot accept path and is therefore fully
fail-safe: ANY unexpected error results in an empty list and never
propagates.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path
_FRONTMATTER_RE = re.compile('\\A---\\s*\\n(.*?)\\n---\\s*(?:\\n|\\Z)', re.DOTALL)
_EPIC_RE = re.compile('^\\s*epic\\s*:\\s*true\\s*$', re.IGNORECASE | re.MULTILINE)

def _is_epic(brief_path: Path) -> bool:
    """Return True if the brief's leading frontmatter declares epic: true."""
    try:
        text = brief_path.read_text(encoding='utf-8')
    except OSError:
        return False
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return False
    return bool(_EPIC_RE.search(m.group(1)))

def reap_for_task(repo_root, task_id, *, stamp, archive=True) -> list[str]:
    """Archive a task's brief+plan iff its whole plan is integrated.

    'Integrated' is decided from GROUND-TRUTH evidence -- the reaped
    ``task_id`` (counts implicitly) plus the integration ledger
    ``<repo_root>/state/impl_progress.jsonl`` -- and NEVER by re-running a
    plan's verification_command. Returns the archived brief slugs (0 or 1).
    Fully fail-safe: any error returns [] and never raises.
    """

    def _plan_is_epic(data) -> bool:
        if not isinstance(data, dict):
            return False
        if str(data.get('plan_kind', '')).strip().lower() == 'epic':
            return True
        return data.get('epic') is True

    def _plan_task_ids(data) -> list:
        tasks = data.get('tasks') if isinstance(data, dict) else None
        if not isinstance(tasks, list):
            return []
        ids = []
        for t in tasks:
            if isinstance(t, dict):
                tid = t.get('task_id')
                if isinstance(tid, str) and tid:
                    ids.append(tid)
        return ids

    def _load_plan(plan_path: Path):
        try:
            data = json.loads(plan_path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def _find_brief_paired_plan(root: Path, tid: str):
        matches = []
        for plan_path in sorted(root.glob('plan_hooks_*.json')):
            data = _load_plan(plan_path)
            if data is None or tid not in _plan_task_ids(data):
                continue
            name = plan_path.name
            slug = name[len('plan_hooks_'):-len('.json')]
            if not (root / f'brief_hooks_{slug}.md').exists():
                continue
            matches.append((slug, data))
        return matches[0] if len(matches) == 1 else (None, None)

    def _move_no_clobber(src: Path, dst_dir: Path) -> bool:
        dst = dst_dir / src.name
        if dst.exists():
            return False
        shutil.move(str(src), str(dst))
        return True

    def _stage_deletion(root: Path, name: str) -> None:
        """Fail-safe: stage the moved-from path's deletion in git's index.

        Records a clean STAGED deletion (``git rm --cached``) so the worker's
        existing auto-commit captures the source path's removal. MOVE-not-delete
        is preserved: the archived copy under _autowork_archive/ is never
        touched and ``git mv`` is never used. ANY error (not a git repo, git
        missing, path already untracked, lock contention) is swallowed.
        """
        try:
            subprocess.run(['git', '-C', str(root), 'rm', '--cached', '--quiet', '--', name], capture_output=True, check=False)
        except Exception:
            pass
    try:
        root = Path(repo_root)
        if not root.exists() or not root.is_dir():
            return []
        if not isinstance(task_id, str) or not task_id:
            return []
        slug, data = _find_brief_paired_plan(root, task_id)
        if slug is None:
            return []
        if _plan_is_epic(data):
            return []
        brief_path = root / f'brief_hooks_{slug}.md'
        if brief_path.exists() and _is_epic(brief_path):
            return []
        plan_ids = _plan_task_ids(data)
        if not plan_ids:
            return []
        integrated = _integrated_task_ids(root)
        integrated.add(task_id)
        if not all((tid in integrated for tid in plan_ids)):
            return []
        if not archive:
            return [slug]
        plan_path = root / f'plan_hooks_{slug}.json'
        state_dir = root / 'state'
        with state_reconcile_lock(state_dir):
            dest = root / '_autowork_archive' / stamp / 'reconciled'
            dest.mkdir(parents=True, exist_ok=True)
            moved = []
            if brief_path.exists() and _move_no_clobber(brief_path, dest):
                moved.append(brief_path.name)
            if plan_path.exists() and _move_no_clobber(plan_path, dest):
                moved.append(plan_path.name)
            for name in moved:
                _stage_deletion(root, name)
        return [slug]
    except Exception:
        return []
from harness.state_reconciler import state_reconcile_lock
'Archive-on-integrate reaper for brief + plan paperwork.\n\nThis stdlib-only module exposes a single public helper,\n:func:`reap_for_task`, the targeted half of archive-on-integrate: when a\nbuild task lands, it archives that task\'s ``brief_hooks_<slug>.md`` and\n``plan_hooks_<slug>.json`` from the repository root IFF the whole plan is\nnow integrated. "Integrated" is decided from GROUND-TRUTH evidence -- the\nreaped task plus the integration ledger ``state/impl_progress.jsonl`` -- and\nNEVER by re-running a plan\'s verification_command.\n\nThe archive move serializes on the single dedicated ``state_reconcile.lock``\n(see :func:`harness.state_reconciler.state_reconcile_lock`) so this third\nmutating path joins the in-loop sweep and the standalone apply on the ONE\nshared lock; the slow destructive section is never held under the short\n``git_commit.lock``. The move is a MOVE (never a delete), never uses ``git\nmv``, and never rewrites brief bytes or touches the brief mtime.\n\nThe function runs on the worker\'s hot accept path and is therefore fully\nfail-safe: ANY unexpected error results in an empty list and never\npropagates.\n'

def _integrated_task_ids(root: Path) -> set:
    """Tids that count as integrated from an ORDERED scan of the ledger.

    Hoisted to MODULE scope (lifted out of :func:`reap_for_task`) so
    ``tools.brief_reaper._integrated_task_ids(root)`` resolves as a module
    attribute. A tid is COUNTED when an ``accepted`` (or ``no_diff``) row for it
    is seen and UN-COUNTED again when a LATER ``reject_rollback`` or
    ``task_blocked`` row for the SAME tid is seen during the ordered scan, so a
    tid whose accepted commit was subsequently reverted no longer counts as
    integrated. Matching is exact (substring-proof: ``t1`` never matches
    ``t12``). Reads are fail-soft: a missing ledger yields the empty set and
    malformed / non-dict lines are skipped.
    """
    ids: set = set()
    try:
        text = (root / 'state' / 'impl_progress.jsonl').read_text(encoding='utf-8')
    except OSError:
        return ids
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        tid = row.get('task_id')
        if not (isinstance(tid, str) and tid):
            continue
        event = row.get('event')
        if row.get('phase') == 'accepted' or event == 'no_diff':
            ids.add(tid)
        elif event in ('reject_rollback', 'task_blocked'):
            ids.discard(tid)
    return ids