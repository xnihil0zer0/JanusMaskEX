"""Archive-on-integrate reaper for brief + plan paperwork.

This stdlib-only module exposes a single public helper,
:func:`reap_for_task`, the targeted half of archive-on-integrate: when a
build task lands, it archives that task's ``brief_hooks_<slug>.md`` and
``plan_hooks_<slug>.json`` from the repository root IFF the whole plan is
now integrated (every distinct verification command is green).

The function runs on the worker's hot accept path and is therefore fully
fail-safe: ANY unexpected error results in an empty list and never
propagates.
"""
import json
import re
import shutil
import subprocess
import sys
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

def _distinct_commands(tasks: list) -> list[str]:
    """Distinct non-blank verification_command strings, order preserved."""
    seen: set[str] = set()
    out: list[str] = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        cmd = task.get('verification_command')
        if not isinstance(cmd, str):
            continue
        cmd = cmd.strip()
        if not cmd or cmd in seen:
            continue
        seen.add(cmd)
        out.append(cmd)
    return out

def _all_green(commands: list[str], repo_root: Path) -> bool:
    """Run each command at repo_root; True iff every one exits 0."""
    for cmd in commands:
        try:
            proc = subprocess.run(cmd, shell=True, cwd=str(repo_root), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=600)
        except (subprocess.TimeoutExpired, OSError):
            return False
        if proc.returncode != 0:
            return False
    return True

def _move(src: Path, dst_dir: Path, repo_root: Path) -> None:
    """Move src into dst_dir, preferring git mv, falling back to shutil.move."""
    dst = dst_dir / src.name
    used_git = False
    try:
        proc = subprocess.run(['git', 'mv', str(src), str(dst)], cwd=str(repo_root), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        used_git = proc.returncode == 0
    except (OSError, subprocess.SubprocessError):
        used_git = False
    if not used_git:
        shutil.move(str(src), str(dst))

def reap_for_task(repo_root, task_id, *, stamp, archive=True) -> list[str]:
    """Archive a task's brief+plan iff its whole plan is integrated (green).

    Returns the list of archived brief slugs (0 or 1). Never raises.
    """
    try:
        root = Path(repo_root)
        if not root.exists() or not root.is_dir():
            return []
        slug = None
        plan_tasks = None
        for plan_path in sorted(root.glob('plan_hooks_*.json')):
            try:
                data = json.loads(plan_path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                continue
            if not isinstance(data, dict):
                continue
            tasks = data.get('tasks')
            if not isinstance(tasks, list):
                continue
            if any((isinstance(t, dict) and t.get('task_id') == task_id for t in tasks)):
                name = plan_path.name
                slug = name[len('plan_hooks_'):-len('.json')]
                plan_tasks = tasks
                break
        if slug is None or plan_tasks is None:
            return []
        brief_path = root / f'brief_hooks_{slug}.md'
        if brief_path.exists() and _is_epic(brief_path):
            return []
        commands = _distinct_commands(plan_tasks)
        if not commands:
            return []
        if not _all_green(commands, root):
            return []
        if not archive:
            return [slug]
        dest = root / '_autowork_archive' / stamp / 'reconciled'
        dest.mkdir(parents=True, exist_ok=True)
        plan_path = root / f'plan_hooks_{slug}.json'
        if brief_path.exists():
            _move(brief_path, dest, root)
        if plan_path.exists():
            _move(plan_path, dest, root)
        return [slug]
    except Exception:
        return []