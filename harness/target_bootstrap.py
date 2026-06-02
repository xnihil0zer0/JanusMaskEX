"""Idempotent bootstrap for an EXTERNAL target repository.

REV22 §4-7 (external-project capability). Given a ``working_dir`` that the
caller has ALREADY classified as NOT-self (via
``harness.paths._target_is_self``), make the external repo ready for
JanusMask to stage work into it:

* a git repo exists (``git init`` if absent) with a JM ``.gitignore``,
* an optional ``.venv`` with deps installed (best-effort, bounded),
* a JM-owned ``janusmask/work`` branch exists (CR-10 — accepted external
  output later advances THIS branch by ref-update, never the user's branch),
* the JanusMask external-staging root dir exists (CR-3 —
  ``agent_workroot()/external_staging``; per-task worktrees are created
  later by ``create_staging_worktree``),
* a JM ownership marker ``.janusmask/bootstrap.json`` is written/refreshed.

OWNERSHIP SIGNAL (design): JanusMask owns an external tree iff it finds a
well-formed ``.janusmask/bootstrap.json`` marker at the repo root that it
itself wrote (schema-tagged ``{"owner": "janusmask", "schema": 1, ...}``).
This is the single source of truth for ownership: it is created only by
this bootstrap, lives at a JM-namespaced path, and is gitignored so it
never leaks into the user's history. A ``.git`` WITHOUT a valid marker is
treated as FOREIGN and REFUSED — JanusMask must never mutate a repo it did
not provision.

IDEMPOTENCE: a valid marker present ⇒ early no-op return (still ensures the
staging root + work branch exist, both idempotent). Re-running never
clobbers user content.

SAFETY (REV22 trust rules):
* ``.resolve()`` FIRST, before any marker/ownership check.
* REFUSE a DIRTY working tree (never bootstrap over uncommitted user work).
* REFUSE a FOREIGN ``.git`` (has ``.git`` but no valid JM marker).
* Caller is responsible for the not-self classification; this module does
  NOT relax any self-protection.
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from harness.paths import agent_workroot
_MARKER_REL = '.janusmask/bootstrap.json'
_MARKER_OWNER = 'janusmask'
_MARKER_SCHEMA = 1
_WORK_BRANCH = 'janusmask/work'
_GIT_TIMEOUT = 60
_VENV_TIMEOUT = 300
_GITIGNORE_LINES = ('# JanusMask-managed (created by harness/target_bootstrap.py)', '.janusmask/', '.venv/', '__pycache__/', '*.pyc')

class BootstrapRefused(RuntimeError):
    """Raised when an external tree must NOT be bootstrapped (dirty/foreign)."""

def _git(args: list[str], cwd: Path, check: bool=True) -> subprocess.CompletedProcess:
    return subprocess.run(['git', *args], cwd=str(cwd), capture_output=True, text=True, check=check, timeout=_GIT_TIMEOUT)

def _marker_path(root: Path) -> Path:
    return root / _MARKER_REL

def _read_valid_marker(root: Path) -> dict | None:
    """Return the parsed marker dict iff it is a well-formed JM marker."""
    mp = _marker_path(root)
    if not mp.is_file():
        return None
    try:
        obj = json.loads(mp.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(obj, dict):
        return None
    if obj.get('owner') != _MARKER_OWNER or obj.get('schema') != _MARKER_SCHEMA:
        return None
    return obj

def _has_git(root: Path) -> bool:
    return (root / '.git').exists()

def _is_dirty(root: Path) -> bool:
    res = _git(['status', '--porcelain'], cwd=root, check=False)
    if res.returncode != 0:
        return False
    return bool(res.stdout.strip())

def external_staging_root() -> Path:
    """CR-3: the JanusMask-owned root for external staging worktrees."""
    return agent_workroot() / 'external_staging'

def _ensure_staging_root() -> Path:
    root = external_staging_root()
    root.mkdir(parents=True, exist_ok=True)
    return root

def _ensure_gitignore(root: Path) -> None:
    gi = root / '.gitignore'
    existing = ''
    if gi.is_file():
        try:
            existing = gi.read_text(encoding='utf-8')
        except OSError:
            existing = ''
    needed = [ln for ln in _GITIGNORE_LINES if ln not in existing]
    if not needed:
        return
    sep = '' if not existing or existing.endswith('\n') else '\n'
    gi.write_text(existing + sep + '\n'.join(needed) + '\n', encoding='utf-8')

def _ensure_work_branch(root: Path) -> None:
    """CR-10: ensure a JM-owned ``janusmask/work`` branch exists.

    Created off the current HEAD without checking it out (so the user's
    checked-out branch is untouched). Idempotent.
    """
    show = _git(['show-ref', '--verify', '--quiet', f'refs/heads/{_WORK_BRANCH}'], cwd=root, check=False)
    if show.returncode == 0:
        return
    _git(['branch', _WORK_BRANCH], cwd=root, check=True)

def _ensure_venv(root: Path) -> None:
    """Best-effort, bounded ``.venv`` + deps. Never hangs on the network."""
    venv = root / '.venv'
    req = None
    for name in ('requirements.txt', 'requirements-dev.txt'):
        cand = root / name
        if cand.is_file():
            req = cand
            break
    if req is None:
        return
    if not venv.exists():
        try:
            subprocess.run([sys.executable, '-m', 'venv', str(venv)], capture_output=True, text=True, check=True, timeout=_VENV_TIMEOUT)
        except (subprocess.SubprocessError, OSError):
            return
    pip = venv / 'bin' / 'pip'
    if not pip.is_file():
        return
    try:
        subprocess.run([str(pip), 'install', '--no-input', '--disable-pip-version-check', '-r', str(req)], capture_output=True, text=True, check=False, timeout=_VENV_TIMEOUT)
    except (subprocess.SubprocessError, OSError):
        return

def _write_marker(root: Path) -> None:
    mp = _marker_path(root)
    mp.parent.mkdir(parents=True, exist_ok=True)
    payload = {'owner': _MARKER_OWNER, 'schema': _MARKER_SCHEMA, 'bootstrapped_at': time.time(), 'work_branch': _WORK_BRANCH}
    mp.write_text(json.dumps(payload, indent=2) + '\n', encoding='utf-8')

def bootstrap_target(working_dir: str | os.PathLike) -> Path:
    """Idempotently bootstrap the external repo at ``working_dir``.

    Returns the resolved repo root. Raises ``BootstrapRefused`` for a dirty
    tree or a foreign ``.git`` (no valid JM marker).

    The caller MUST have already classified ``working_dir`` as not-self.
    """
    root = Path(working_dir).resolve()
    if not root.exists():
        root.mkdir(parents=True, exist_ok=True)
    has_git = _has_git(root)
    marker = _read_valid_marker(root)
    if marker is not None:
        _ensure_staging_root()
        if has_git:
            _ensure_work_branch(root)
        return root
    if has_git:
        if _is_dirty(root):
            raise BootstrapRefused(f'refusing to bootstrap {root}: working tree is dirty (uncommitted changes)')
        raise BootstrapRefused(f'refusing to bootstrap {root}: it is a git repo with no JanusMask ownership marker ({_MARKER_REL}) — treated as foreign')
    _git(['init'], cwd=root, check=True)
    _git(['config', 'user.email', 'rebuild-engine@janusmask.local'], cwd=root, check=False)
    _git(['config', 'user.name', 'JanusMask Rebuild Engine'], cwd=root, check=False)
    _ensure_gitignore(root)
    _ensure_venv(root)
    _git(['add', '-A'], cwd=root, check=False)
    _git(['commit', '-m', 'JanusMask bootstrap'], cwd=root, check=False)
    _ensure_work_branch(root)
    _ensure_staging_root()
    _write_marker(root)
    return root