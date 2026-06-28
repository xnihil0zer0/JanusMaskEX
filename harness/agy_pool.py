"""Project-local pool of isolated agy worker HOMEs.

JanusMask runs up to ``POOL_SIZE`` *worker* agy processes concurrently. Each
worker gets a private ``$HOME`` under ``<repo>/.agents/agy-pool`` so that the
Antigravity registry of one worker never corrupts another. A slot's home is
seeded with ONLY the small auth/config set (the ``~/.gemini`` credential files
plus the gcloud Application Default Credentials) -- NEVER the multi-GB
``~/.gemini`` cache.

All filesystem effects flow through injected ``copy``/``exists``/``makedirs``
seams, so this module performs no real I/O, no agy spawn, and no network calls.
Stdlib only.
"""
from __future__ import annotations
import os
from pathlib import Path
from typing import Callable
from typing import List
from typing import Tuple
POOL_SIZE = 4
_SEED_RELS: Tuple[str, ...] = ('.gemini/oauth_creds.json', '.gemini/google_accounts.json', '.gemini/settings.json', '.gemini/trustedFolders.json', '.gemini/state.json', '.gemini/projects.json', '.config/gcloud/application_default_credentials.json', '.gemini/antigravity-cli/history.db')

def pool_root(repo_root: str) -> Path:
    """Project-local root holding every worker's private home."""
    return Path(repo_root) / '.agents' / 'agy-pool'

def worker_home(repo_root: str, slot: int) -> Path:
    """A distinct private ``$HOME`` for ``slot`` under the pool root."""
    return pool_root(repo_root) / f'w{slot}'

def agy_seed_plan(home: str) -> List[Tuple[str, str]]:
    """Return the ``(abs_src, rel_dst)`` pairs for the auth/config seed set.

    ``abs_src`` is resolved against the operator's real ``home``; ``rel_dst`` is
    home-relative so copies land inside a slot's private home without leaking
    the operator's path. The multi-GB cache is never included.
    """
    return [(os.path.join(home, rel), rel) for rel in _SEED_RELS]

def ensure_seeded(repo_root: str, slot: int, *, home: str, copy: Callable[[str, str], object], exists: Callable[[str], bool], makedirs: Callable[[str], object], isdir: Callable[[str], bool]=os.path.isdir, remove: Callable[[str], object]=os.remove, lexists: Callable[[str], bool]=os.path.lexists) -> List[str]:
    """Idempotently seed ``slot``'s private home from the operator ``home``.

    For each planned ``(src, rel)`` pair, copy only when ``src`` exists and the
    destination is absent -- creating the destination's parent directory first.
    Returns the list of ``rel`` names actually copied. Re-running with all
    destinations present copies nothing.
    """
    wh = str(worker_home(repo_root, slot))
    copied: List[str] = []
    for src, rel in agy_seed_plan(home):
        dst = os.path.join(wh, rel)
        if exists(src) and (not exists(dst)):
            makedirs(os.path.dirname(dst))
            copy(src, dst)
            copied.append(rel)
    config = os.path.join(wh, '.gemini', 'config')
    projects = os.path.join(config, 'projects')
    if lexists(config) and (not isdir(config)):
        try:
            remove(config)
        except FileNotFoundError:
            pass
    makedirs(projects)
    return copied

def allocate_slot(busy: set[int] | list[int], size: int=POOL_SIZE, allow_home_fallback: bool=False, repo_root: str | None=None) -> int | None:
    """Return the lowest free slot in ``range(size)``, or ``None`` when full.

    If allow_home_fallback is False and all slots are busy/locked, raises a RuntimeError.
    """
    if size <= 0:
        if repo_root is not None and not allow_home_fallback:
            raise RuntimeError('No slot available')
        return None
    for i in range(size):
        cleanup_stale_lockfiles(i)
        if i in busy:
            continue
        if repo_root is not None:
            root = pool_root(repo_root)
            os.makedirs(root, exist_ok=True)
            lock_path = root / f'w{i}.lock'
            if lock_path.exists():
                if _is_lock_stale(lock_path):
                    try:
                        os.remove(lock_path)
                    except Exception:
                        continue
                else:
                    continue
            if _acquire_lock(lock_path):
                return i
            else:
                continue
        else:
            return i
    if not allow_home_fallback:
        raise RuntimeError('No slot available')
    return None

def cleanup_stale_lockfiles(slot_id: int) -> None:
    lock_path = Path(f'/tmp/.X{100 + slot_id}-lock')
    if not lock_path.exists():
        return
    should_remove = False
    try:
        content = lock_path.read_text().strip()
        if not content:
            should_remove = True
        else:
            first_line = content.split('\n')[0].strip()
            pid = int(first_line)
            if not _is_pid_alive(pid):
                should_remove = True
            else:
                # Check if it is actually Xvfb
                is_xvfb = False
                try:
                    with open(f"/proc/{pid}/cmdline", "r") as f_cmd:
                        cmdline = f_cmd.read()
                    if "Xvfb" in cmdline:
                        is_xvfb = True
                except Exception:
                    pass
                if not is_xvfb:
                    should_remove = True
    except ValueError:
        should_remove = True
    except IOError:
        pass
    if should_remove:
        try:
            lock_path.unlink()
        except IOError:
            pass
class PoolInvariantError(ValueError):
    """Raised when an enabled pool's ``size`` cannot cover ``parallel_cap``.

    A ``ValueError`` subclass so existing ``except ValueError`` handlers still
    catch it, while a named type lets callers distinguish the pool-sizing
    footgun (a concurrent worker beyond ``size`` would get no slot and silently
    fall back to the shared HOME).
    """

def effective_pool_size(*, enabled: bool, size: int, parallel_cap: int) -> int:
    """Return the pool size the runtime MUST use.

    When the pool is ``enabled`` the result can never be below ``parallel_cap``
    (auto-clamps UP) so every concurrent worker is guaranteed a private slot.
    When disabled the requested ``size`` is returned unchanged (no pooling).
    """
    if not enabled:
        return size
    return size if size >= parallel_cap else parallel_cap

def assert_pool_invariant(*, enabled: bool, size: int, parallel_cap: int) -> None:
    """Fail-closed guard: raise ``PoolInvariantError`` if the invariant breaks.

    Raises when the pool is ``enabled`` and ``size < parallel_cap`` (the message
    surfaces both the offending ``size`` and ``parallel_cap``); a no-op when the
    invariant holds or the pool is disabled.
    """
    if enabled and size < parallel_cap:
        raise PoolInvariantError(f'agy pool enabled with size={size} < parallel_cap={parallel_cap}: concurrent workers beyond size would fall back to the shared HOME')

def worker_env(repo_root: str, slot: int, base_env: dict) -> dict:
    """Return a new env dict: ``base_env`` + private HOME + GCA flag.

    ``base_env`` is never mutated.
    """
    env = dict(base_env)
    env['HOME'] = str(worker_home(repo_root, slot))
    env['GOOGLE_GENAI_USE_GCA'] = '1'
    return env
import errno
import json

def get_process_start_time(pid: int) -> int | None:
    """Read the starttime field (field 22, which is 20th field after comm name) from /proc/<pid>/stat."""
    try:
        with open(f'/proc/{pid}/stat', 'r') as f:
            content = f.read()
        rparen_idx = content.rfind(')')
        if rparen_idx == -1:
            return None
        remainder = content[rparen_idx + 1:].strip()
        fields = remainder.split()
        if len(fields) < 20:
            return None
        return int(fields[19])
    except (FileNotFoundError, PermissionError, ValueError, IndexError):
        return None

def _is_pid_alive(pid: int) -> bool:
    """Check if process pid is alive using signal 0."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError as e:
        return e.errno == errno.EPERM

def _is_lock_stale(lock_path: Path) -> bool:
    """Return True if lock file is stale or corrupt, False if it is valid and active."""
    try:
        if not lock_path.exists():
            return True
        with open(lock_path, 'r') as f:
            content = f.read()
        lock_data = json.loads(content)
        if not isinstance(lock_data, dict):
            return True
        pid = lock_data.get('pid')
        if not isinstance(pid, int):
            return True
        if not _is_pid_alive(pid):
            return True
        start_time = lock_data.get('start_time')
        if start_time is not None:
            curr_start = get_process_start_time(pid)
            if curr_start is not None and curr_start != start_time:
                return True
        return False
    except Exception:
        return True

def _acquire_lock(lock_path: Path) -> bool:
    """Atomic creation and writing of the lock file."""
    fd = None
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        pid = os.getpid()
        start_time = get_process_start_time(pid)
        lock_data = json.dumps({'pid': pid, 'start_time': start_time})
        with os.fdopen(fd, 'w') as f:
            f.write(lock_data)
        return True
    except FileExistsError:
        return False
    except Exception:
        if fd is not None:
            try:
                os.close(fd)
            except Exception:
                pass
        try:
            os.remove(lock_path)
        except Exception:
            pass
        return False