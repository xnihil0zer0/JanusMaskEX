__JANUSMASK_MANIFEST__ = {
    'harness/state_reconciler.py': r'''"""Shared serialization primitive for stale-state reconciliation.

This stdlib-only module exposes a single public helper,
:func:`state_reconcile_lock`, the ONE dedicated mutex that serializes slow,
destructive state-reconciliation sections (e.g. the brief reaper's archive
move) across cooperating processes.

The lock is deliberately distinct from the autowork ``git_commit.lock``:
holding ``state_reconcile.lock`` across a slow destructive op leaves
``git_commit.lock`` free, so commit progress is never blocked by reconciliation.

The fcntl import is performed in-body (matching the daemon's convention) so
that on a platform without ``fcntl`` the context manager still yields a
best-effort advisory lock rather than raising.
"""
import os
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def state_reconcile_lock(state_dir):
    """Acquire the single dedicated state-reconcile lock for ``state_dir``.

    Opens/creates ``<state_dir>/control/autowork/state_reconcile.lock``
    (creating parent directories as needed), takes an exclusive
    ``fcntl.flock(LOCK_EX)``, yields, and releases the lock (``LOCK_UN`` +
    ``close``) in a ``finally`` so two callers serialize on this ONE file.

    This lock never opens, acquires, or releases ``git_commit.lock``; a slow
    destructive section held under it leaves ``git_commit.lock`` free.

    If ``fcntl`` is unavailable the context manager degrades to a best-effort
    advisory lock (it still creates/opens the file and yields) without raising.
    """
    try:
        import fcntl
    except Exception:
        fcntl = None

    lock_dir = Path(state_dir) / 'control' / 'autowork'
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / 'state_reconcile.lock'

    fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        if fcntl is not None:
            fcntl.flock(fd, fcntl.LOCK_EX)
        yield lock_path
    finally:
        try:
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_UN)
        except Exception:
            pass
        try:
            os.close(fd)
        except Exception:
            pass
''',
    'tools/brief_reaper.py': r'''"""Archive-on-integrate reaper for brief + plan paperwork.

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

    def _integrated_task_ids(root: Path) -> set:
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
            if isinstance(tid, str) and tid and (row.get('phase') == 'accepted' or row.get('event') == 'no_diff'):
                ids.add(tid)
        return ids

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

    def _move_no_clobber(src: Path, dst_dir: Path, repo: Path) -> bool:
        dst = dst_dir / src.name
        if dst.exists():
            return False
        try:
            proc = subprocess.run(['git', 'mv', str(src), str(dst)], cwd=str(repo), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if proc.returncode == 0:
                return True
        except (OSError, subprocess.SubprocessError):
            pass
        shutil.move(str(src), str(dst))
        try:
            subprocess.run(['git', 'add', str(dst)], cwd=str(repo), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError):
            pass
        return True

    try:
        from harness.state_reconciler import state_reconcile_lock
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
        if not all(tid in integrated for tid in plan_ids):
            return []
        if not archive:
            return [slug]
        plan_path = root / f'plan_hooks_{slug}.json'
        with state_reconcile_lock(root / 'state'):
            dest = root / '_autowork_archive' / stamp / 'reconciled'
            dest.mkdir(parents=True, exist_ok=True)
            if brief_path.exists():
                _move_no_clobber(brief_path, dest, root)
            if plan_path.exists():
                _move_no_clobber(plan_path, dest, root)
        return [slug]
    except Exception:
        return []
''',
}
