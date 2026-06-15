---
interfaces: "exposes `clone_target(repo_url, *, dest_root='tmp', runner=None, now=None, size_cap_mb=500, archived=False, reuse=True) -> ngv2.contracts.Target`, `make_subprocess_runner() -> Runner`, and `CloneError`. Shallow git clone into in-tree tmp/, pins HEAD SHA, enforces size cap, detects language+LOC, refuses archived, caches/reuses."
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

Target cloner (ngv2/acquisition/cloner.py): shallow git clone into in-tree tmp/ returning a typed Target with pinned SHA, size cap, language detection, cache reuse

# Scope

Build a NEW io_adapter module ngv2/acquisition/cloner.py that clones a target repository and returns a typed ngv2.contracts.Target. It performs `git clone --depth 1` into an IN-TREE `tmp/` directory (NEVER /tmp), records the pinned HEAD commit SHA, enforces a size cap (CloneError on breach), detects the primary language by source-file count plus LOC, refuses archived repos up front, and supports a clone cache/reuse (an already-populated clone dir is reused instead of re-cloning). io_adapter discipline: the only impure operations -- running git via subprocess and walking the cloned tree -- are behind INJECTED seams (`runner(argv, cwd) -> (rc, stdout, stderr)` for git; `now() -> str` for the clock). `make_subprocess_runner()` returns the production urllib/subprocess-backed seam. Emit the whole file verbatim from Deliverables. Name the committed oracle tests/test_cloner_wired.py in the verification_command.

# Non-Goals

Do NOT clone into /tmp (legacy bash-guard lesson -- use in-tree tmp/). Do NOT call the network or git directly in the pure paths -- everything git goes through the injected `runner` seam (default `make_subprocess_runner()`). Do NOT change ngv2.contracts or harness/target_bootstrap.py. Do NOT auto-submit, scan, or detonate. No LLM, randomness. Single new file (a new sub-package module ngv2/acquisition/cloner.py importable as ngv2.acquisition.cloner -- no separate __init__.py needed, Python namespace packages resolve it); touch no other module.

# Inputs

Returns ngv2.contracts.Target(repo_url, repo_root, pinned_commit, language, loc=0, cloned_at='') whose validate() requires non-empty repo_url/repo_root/pinned_commit/language and loc>=0. The injected `runner(argv, cwd)` returns (returncode:int, stdout:str, stderr:str); production seam shells out to real `git`. The oracle drives a real-git runner against a LOCAL bare-repo fixture over file:// so it is hermetic.

# Deliverables

ngv2/acquisition/cloner.py with EXACTLY this content:

```python
"""Target repository cloner (ngv2.acquisition.cloner).

UPGRADE of legacy's ad-hoc ``git clone`` shell into a real module that returns a
typed :class:`ngv2.contracts.Target`. It performs a shallow ``git clone --depth 1``
into an IN-TREE ``tmp/`` directory (never ``/tmp`` -- legacy bash-guard lesson),
records the pinned commit SHA, enforces a size cap, detects the primary language,
refuses archived repos, and supports a clone cache/reuse.

io_adapter discipline: the only impure operations -- running git and walking the
cloned tree on disk -- are behind INJECTED seams (``runner`` for subprocess,
``now`` for the clock). The oracle injects a real-git runner pointed at a LOCAL
bare-repo fixture (file:// clone), so it is hermetic (no network) yet exercises
the real clone path. ``make_subprocess_runner`` returns the production seam.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Sequence, Tuple

from ngv2.contracts import Target

# runner(argv, cwd) -> (returncode, stdout, stderr)
Runner = Callable[[Sequence[str], Optional[str]], Tuple[int, str, str]]

DEFAULT_DEST_ROOT = 'tmp'
DEFAULT_SIZE_CAP_MB = 500

# Extension -> language for primary-language detection (by file count).
_LANG_BY_EXT = {
    '.py': 'python', '.js': 'javascript', '.ts': 'typescript', '.jsx': 'javascript',
    '.tsx': 'typescript', '.go': 'go', '.rb': 'ruby', '.java': 'java',
    '.rs': 'rust', '.php': 'php', '.c': 'c', '.cpp': 'cpp', '.cc': 'cpp',
    '.cs': 'csharp', '.scala': 'scala', '.kt': 'kotlin',
}


class CloneError(RuntimeError):
    """Raised when a clone is refused or fails (archived, oversize, git error)."""


def make_subprocess_runner() -> Runner:
    """Return the production runner seam backed by real ``git`` subprocess calls."""
    def _runner(argv: Sequence[str], cwd: Optional[str]) -> Tuple[int, str, str]:
        proc = subprocess.run(list(argv), cwd=cwd, capture_output=True, text=True)
        return proc.returncode, proc.stdout, proc.stderr
    return _runner


def _slug(repo_url: str) -> str:
    """Derive a filesystem-safe directory slug from a repo URL."""
    name = repo_url.rstrip('/').split('/')[-1]
    if name.endswith('.git'):
        name = name[:-4]
    owner = repo_url.rstrip('/').split('/')[-2] if '/' in repo_url.rstrip('/')[:-1] else ''
    base = (owner + '-' + name) if owner else name
    return ''.join(c if (c.isalnum() or c in '-_.') else '-' for c in base) or 'repo'


def _dir_size_bytes(root: Path) -> int:
    """Sum the on-disk byte size of every regular file under ``root``."""
    total = 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            fp = Path(dirpath) / fn
            try:
                if fp.is_file() and not fp.is_symlink():
                    total += fp.stat().st_size
            except OSError:
                continue
    return total


def _detect_language(root: Path) -> str:
    """Return the primary language by source-file count, or 'unknown'."""
    counts: dict[str, int] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        if '.git' in dirnames:
            dirnames.remove('.git')
        for fn in filenames:
            lang = _LANG_BY_EXT.get(Path(fn).suffix.lower())
            if lang:
                counts[lang] = counts.get(lang, 0) + 1
    if not counts:
        return 'unknown'
    return max(sorted(counts), key=lambda k: counts[k])


def _count_loc(root: Path) -> int:
    """Count newline-terminated lines across detected source files."""
    loc = 0
    for dirpath, dirnames, filenames in os.walk(root):
        if '.git' in dirnames:
            dirnames.remove('.git')
        for fn in filenames:
            if Path(fn).suffix.lower() in _LANG_BY_EXT:
                try:
                    with open(Path(dirpath) / fn, 'rb') as fh:
                        loc += fh.read().count(b'\n')
                except OSError:
                    continue
    return loc


def clone_target(repo_url: str, *,
                 dest_root: str = DEFAULT_DEST_ROOT,
                 runner: Optional[Runner] = None,
                 now: Optional[Callable[[], str]] = None,
                 size_cap_mb: int = DEFAULT_SIZE_CAP_MB,
                 archived: bool = False,
                 reuse: bool = True) -> Target:
    """Shallow-clone ``repo_url`` into ``dest_root`` and return a typed Target.

    Refuses archived repos up front. With ``reuse=True`` an existing populated
    clone dir is reused (cache) instead of re-cloning. After cloning, the pinned
    HEAD SHA is recorded, the size cap enforced (CloneError on breach), and the
    primary language + LOC detected.
    """
    if archived:
        raise CloneError('refusing archived repo: %s' % repo_url)
    run = runner if runner is not None else make_subprocess_runner()
    clock = now if now is not None else _default_now
    dest_root_path = Path(dest_root)
    dest_root_path.mkdir(parents=True, exist_ok=True)
    repo_root = dest_root_path / _slug(repo_url)

    cached = reuse and repo_root.exists() and any(repo_root.iterdir())
    if not cached:
        if repo_root.exists():
            _rmtree(repo_root)
        rc, _out, err = run(['git', 'clone', '--depth', '1', repo_url, str(repo_root)], None)
        if rc != 0:
            raise CloneError('git clone failed (rc=%s): %s' % (rc, err.strip()))

    size_bytes = _dir_size_bytes(repo_root)
    if size_bytes > size_cap_mb * 1024 * 1024:
        raise CloneError('clone exceeds size cap (%d MB): %s' % (size_cap_mb, repo_url))

    rc, out, err = run(['git', 'rev-parse', 'HEAD'], str(repo_root))
    if rc != 0:
        raise CloneError('git rev-parse failed (rc=%s): %s' % (rc, err.strip()))
    pinned = out.strip()

    target = Target(
        repo_url=repo_url,
        repo_root=str(repo_root.resolve()),
        pinned_commit=pinned,
        language=_detect_language(repo_root),
        loc=_count_loc(repo_root),
        cloned_at=clock(),
    )
    target.validate()
    return target


def _rmtree(path: Path) -> None:
    import shutil
    shutil.rmtree(path, ignore_errors=True)


def _default_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
```

Verification: `cd /home/xnihil0zer0/NobleGreedv2 && .venv/bin/python -m pytest tests/test_cloner_wired.py -q`
