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

def _working_dir_allowed(working_dir: str | os.PathLike) -> bool:
    """External-roots PATH allowlist gate (DENY-ALL by default, fail-closed).

    Resolves the allowlist file from ``JANUSMASK_EXTERNAL_ROOTS_ALLOW`` if set,
    else ``STATE_DIR / 'control' / 'autowork' / 'external_roots.allow'`` (with
    ``STATE_DIR`` imported lazily so this module stays import-portable). Each
    non-blank, non-comment line is resolved into a path prefix. Returns True iff
    the resolved ``working_dir`` equals an approved prefix or is strictly under
    one. Returns False when the allowlist is missing/unreadable/empty/comment-only
    or on ANY error (fail-closed).
    """
    try:
        allow_env = os.environ.get('JANUSMASK_EXTERNAL_ROOTS_ALLOW')
        if allow_env:
            allow_path = Path(allow_env)
        else:
            from harness.paths import STATE_DIR
            allow_path = STATE_DIR / 'control' / 'autowork' / 'external_roots.allow'
        if not allow_path.is_file():
            return False
        try:
            raw = allow_path.read_text(encoding='utf-8')
        except OSError:
            return False
        prefixes: list[Path] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            try:
                prefixes.append(Path(line).resolve())
            except (OSError, ValueError):
                continue
        if not prefixes:
            return False
        target = Path(working_dir).resolve()
        for prefix in prefixes:
            if target == prefix or prefix in target.parents:
                return True
        return False
    except Exception:
        return False
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

def _resolve_target_interpreter(root: Path) -> str:
    """Resolve the interpreter used to create the target's venv.

    Honors, in order: the target's ``.python-version`` (first non-blank,
    non-comment line), then a python requirement pin in ``pyproject.toml``
    (``requires-python``) or ``setup.cfg`` (``python_requires``). Falls back to
    the current ``sys.executable`` when no pin is found (README ABI caveat: a
    target pinning e.g. 3.11 must steer venv creation to a 3.11 interpreter).
    Always returns a non-empty interpreter string.
    """
    import re
    pv = root / '.python-version'
    if pv.is_file():
        try:
            raw = pv.read_text(encoding='utf-8')
        except OSError:
            raw = ''
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            m = re.search('(\\d+\\.\\d+(?:\\.\\d+)?)', line)
            if m:
                return 'python' + m.group(1)
            return line
    for name in ('pyproject.toml', 'setup.cfg'):
        cand = root / name
        if not cand.is_file():
            continue
        try:
            text = cand.read_text(encoding='utf-8')
        except OSError:
            continue
        m = re.search('requires-python\\s*=\\s*["\\\']?[^0-9]*?(\\d+\\.\\d+)', text)
        if m is None:
            m = re.search('python_requires\\s*=\\s*[^0-9]*?(\\d+\\.\\d+)', text)
        if m:
            return 'python' + m.group(1)
    return sys.executable

def _external_venv_dir(root: Path) -> Path:
    """Outside-repo scratch dir for the target's venv (CR-3 / P0.2).

    Keyed by a stable hash of the resolved target root so re-bootstrapping the
    same target reuses its scratch venv, and so the venv never lives inside the
    (read-only-bound) target tree.
    """
    import hashlib
    key = str(Path(root).resolve())
    digest = hashlib.sha256(key.encode('utf-8')).hexdigest()[:16]
    return agent_workroot() / 'external_venvs' / digest

def _jailed_install_argv(*, root: Path, venv: Path, req: Path, pip: Path) -> list[str]:
    """Pure helper: the bwrap-jailed, network-unshared, lockfile-only install argv.

    Builds the dependency-install command via
    :func:`harness.agent_jail.build_jail_argv` with ``bind_credentials=False``
    (drops the entire ~/.gemini / ~/.claude credential surface and adds
    ``--unshare-net`` -- no host network, no exfil) and ``extra_rw=[str(venv)]``
    (the venv scratch is the ONLY writable host bind so the jailed pip can
    install into it). The target tree is bound READ-ONLY (``repo_root=root``) so
    pip can read the lockfile but cannot tamper with the source. The install is
    driven ONLY by the lockfile (``-r <req>``) -- never a loose, stderr-named
    package. Raises ``FileNotFoundError`` (from ``build_jail_argv``) when
    ``bwrap`` is absent; the caller fails closed on that.
    """
    from harness.agent_jail import build_jail_argv
    from harness.paths import STATE_DIR
    cmd = [str(pip), 'install', '--no-input', '--disable-pip-version-check', '-r', str(req)]
    return build_jail_argv(cmd, repo_root=root, work_dir=venv, state_dir=STATE_DIR, extra_rw=[str(venv)], bind_credentials=False)
def _ensure_venv(root: Path) -> None:
    """Best-effort, bounded venv + deps, installed inside a credential-free,
    network-unshared bwrap jail, from the target's OWN lockfile only.

    No unjailed host ``pip install`` ever runs: the install dispatches through
    :func:`_jailed_install_argv`. The venv lives at outside-repo scratch (under
    ``agent_workroot()``) and is created with the target's resolved interpreter
    (falling back to ``sys.executable`` so venv creation never hard-fails on a
    missing pinned interpreter). Fail-closed when ``bwrap`` is absent: the
    ``FileNotFoundError`` raised by ``build_jail_argv`` is swallowed and we
    return WITHOUT any host fallback install. Never hangs on the network.
    """
    req = None
    for name in ('requirements.txt', 'requirements-dev.txt'):
        cand = root / name
        if cand.is_file():
            req = cand
            break
    if req is None:
        return
    venv = _external_venv_dir(root)
    if not (venv / 'bin' / 'python').exists():
        try:
            venv.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            return
        interpreter = _resolve_target_interpreter(root)
        created = False
        for candidate in (interpreter, sys.executable):
            if not candidate:
                continue
            try:
                subprocess.run([candidate, '-m', 'venv', str(venv)], capture_output=True, text=True, check=True, timeout=_VENV_TIMEOUT)
                created = True
                break
            except (subprocess.SubprocessError, OSError):
                continue
        if not created:
            return
    pip = venv / 'bin' / 'pip'
    if not pip.is_file():
        return
    try:
        argv = _jailed_install_argv(root=root, venv=venv, req=req, pip=pip)
    except FileNotFoundError:
        return
    try:
        subprocess.run(argv, capture_output=True, text=True, check=False, timeout=_VENV_TIMEOUT)
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
    if not _working_dir_allowed(root):
        raise BootstrapRefused(f'refusing to bootstrap {root}: not under an approved external root')
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
    if not _working_dir_allowed(root):
        raise BootstrapRefused(f'refusing to bootstrap {root}: not under an approved external root')
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