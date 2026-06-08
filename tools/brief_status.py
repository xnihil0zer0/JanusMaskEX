"""Ground-truth brief classifier.

This single-file, stdlib-only module inspects a repository for
``brief_hooks_<slug>.md`` briefs and their companion
``plan_hooks_<slug>.json`` plans and derives, from ground truth, the
status of each brief. It is used as a pre-dispatch guard so the pipeline
never spends a build cycle on work that is already done and so genuinely
planless leaves are surfaced.

Two public functions are exposed:

* :func:`classify_briefs` -- classify every brief / orphan plan in a repo.
* :func:`status_of` -- the status string for one slug (or ``None``).

Status values: ``'EPIC'``, ``'DONE'``, ``'PENDING'``, ``'NEEDS-PLAN'`` and
``'ORPHAN-PLAN'``. Both functions are fail-safe over malformed inputs.
"""
import json
import re
import subprocess
import sys
from pathlib import Path
_BRIEF_PREFIX = 'brief_hooks_'
_BRIEF_SUFFIX = '.md'
_PLAN_PREFIX = 'plan_hooks_'
_PLAN_SUFFIX = '.json'
_COMMAND_TIMEOUT = 600
_FRONTMATTER_RE = re.compile('^---\\s*\\n(.*?)\\n---', re.DOTALL)
_EPIC_RE = re.compile('^\\s*epic\\s*:\\s*true\\s*$', re.MULTILINE | re.IGNORECASE)
_BODY_CMD_RE = re.compile('verification_command\\s*:\\s*"(.+)"\\s*$', re.MULTILINE)
_PYTEST_RE = re.compile('^\\s*(python\\s+-m\\s+pytest\\s+.*\\S)\\s*$', re.MULTILINE)

def classify_briefs(repo_root) -> list:
    """Classify every brief and orphan plan found under ``repo_root``.

    Returns a list of ``{'slug', 'status', 'detail'}`` dicts: one per
    ``brief_hooks_<slug>.md`` and one per ``plan_hooks_<slug>.json`` that
    has no matching brief.
    """
    repo_root = Path(repo_root)
    rows = []
    brief_slugs = _slugs(repo_root, _BRIEF_PREFIX, _BRIEF_SUFFIX)
    plan_slugs = _slugs(repo_root, _PLAN_PREFIX, _PLAN_SUFFIX)
    for slug in sorted(brief_slugs):
        status, detail = _classify_brief(repo_root, slug)
        rows.append({'slug': slug, 'status': status, 'detail': detail})
    for slug in sorted(plan_slugs - brief_slugs):
        rows.append({'slug': slug, 'status': 'ORPHAN-PLAN', 'detail': 'plan with no matching brief'})
    return rows

def status_of(repo_root, slug):
    """Return the status string for one ``slug`` (or ``None``).

    ``None`` is returned when neither ``brief_hooks_<slug>.md`` nor
    ``plan_hooks_<slug>.json`` exists for the slug.
    """
    repo_root = Path(repo_root)
    brief_path = repo_root / f'{_BRIEF_PREFIX}{slug}{_BRIEF_SUFFIX}'
    plan_path = repo_root / f'{_PLAN_PREFIX}{slug}{_PLAN_SUFFIX}'
    if brief_path.exists():
        status, _detail = _classify_brief(repo_root, slug)
        return status
    if plan_path.exists():
        return 'ORPHAN-PLAN'
    return None

def _slugs(repo_root: Path, prefix: str, suffix: str) -> set:
    """Collect slugs from files matching ``<prefix>*<suffix>`` in ``repo_root``."""
    found = set()
    try:
        entries = list(repo_root.iterdir())
    except OSError:
        return found
    for entry in entries:
        name = entry.name
        if name.startswith(prefix) and name.endswith(suffix):
            slug = name[len(prefix):len(name) - len(suffix)]
            if slug:
                found.add(slug)
    return found

def _classify_brief(repo_root: Path, slug: str):
    """Return ``(status, detail)`` for a single brief slug."""
    brief_path = repo_root / f'{_BRIEF_PREFIX}{slug}{_BRIEF_SUFFIX}'
    plan_path = repo_root / f'{_PLAN_PREFIX}{slug}{_PLAN_SUFFIX}'
    body = _read_text(brief_path)
    if _is_epic(body):
        return ('EPIC', 'frontmatter epic: true')
    if plan_path.exists():
        commands = _plan_commands(plan_path)
        if not commands:
            return ('PENDING', 'plan has no usable verification_command')
        if all((_command_green(cmd, repo_root) for cmd in commands)):
            return ('DONE', 'all plan verification commands green')
        return ('PENDING', 'a plan verification command is red')
    cmd = _body_command(body)
    if cmd and _command_green(cmd, repo_root):
        return ('DONE', 'brief body oracle green')
    return ('NEEDS-PLAN', 'no plan and brief not already green')

def _read_text(path: Path) -> str:
    """Read a file's text, returning '' on any error."""
    try:
        return path.read_text(encoding='utf-8')
    except OSError:
        return ''

def _is_epic(body: str) -> bool:
    """True when the leading frontmatter block declares ``epic: true``."""
    match = _FRONTMATTER_RE.search(body)
    if not match:
        return False
    return bool(_EPIC_RE.search(match.group(1)))

def _body_command(body: str):
    """Best-effort verification command parsed from the brief body."""
    match = _BODY_CMD_RE.search(body)
    if match:
        return match.group(1).strip()
    pytest_match = _PYTEST_RE.search(body)
    if pytest_match:
        return pytest_match.group(1).strip()
    return None

def _plan_commands(plan_path: Path) -> list:
    """Distinct verification commands across a plan's tasks (order-preserving).

    Malformed JSON or unreadable files are skipped, yielding no commands.
    """
    try:
        with plan_path.open(encoding='utf-8') as handle:
            data = json.load(handle)
    except (json.JSONDecodeError, OSError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    tasks = data.get('tasks')
    if not isinstance(tasks, list):
        return []
    commands = []
    seen = set()
    for task in tasks:
        if not isinstance(task, dict):
            continue
        cmd = task.get('verification_command')
        if isinstance(cmd, str):
            cmd = cmd.strip()
            if cmd and cmd not in seen:
                seen.add(cmd)
                commands.append(cmd)
    return commands

def _command_green(cmd: str, repo_root: Path) -> bool:
    """Run ``cmd`` under a shell with output suppressed; True iff it exits 0.

    A timeout or any OSError is treated as a failing (non-zero) command.
    """
    if not cmd:
        return False
    try:
        result = subprocess.run(cmd, shell=True, cwd=str(repo_root), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=_COMMAND_TIMEOUT)
    except (subprocess.TimeoutExpired, OSError):
        return False
    return result.returncode == 0