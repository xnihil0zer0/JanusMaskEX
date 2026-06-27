from ngv2.contracts import Target
import os
import re
import shutil
import stat
import subprocess
from typing import Callable, Optional, Tuple, Sequence
var_0 = '1970-01-01T00:00:00Z'
var_1 = {'.py': 'python', '.go': 'go', '.js': 'javascript', '.jsx': 'javascript', '.ts': 'javascript', '.tsx': 'javascript', '.java': 'java', '.php': 'php', '.rb': 'ruby', '.c': 'c', '.h': 'c', '.cpp': 'c', '.hpp': 'c', '.cc': 'c', '.cxx': 'c'}

class CloneError(RuntimeError):
    pass

def _default_now() -> str:
    return var_0

def _slug(repo_url: str) -> str:
    name = repo_url.rstrip('/').split('/')[-1]
    if name.endswith('.git'):
        name = name[:-4]
    owner = repo_url.rstrip('/').split('/')[-2] if '/' in repo_url.rstrip('/')[:-1] else ''
    base = owner + '-' + name if owner else name
    base = re.sub('[^a-zA-Z0-9]+', '-', base)
    base = base.strip('-')
    return base or 'repo'

def _dir_size_bytes(dir_path: str) -> int:
    var_2 = 0
    for var_3, var_4, var_5 in os.walk(dir_path):
        for var_6 in var_5:
            var_7 = os.path.join(var_3, var_6)
            if os.path.islink(var_7):
                continue
            try:
                var_2 += os.path.getsize(var_7)
            except (OSError, IOError):
                continue
    return var_2

def _detect_language(dir_path: str) -> str:
    var_2 = {}
    for var_4, var_5, var_6 in os.walk(dir_path):
        if '.git' in var_5:
            var_5.remove('.git')
        for var_7 in var_6:
            var_8 = os.path.join(var_4, var_7)
            if os.path.islink(var_8):
                continue
            var_9 = os.path.splitext(var_7)[1].lower()
            if var_9 in var_1:
                var_10 = var_1[var_9]
                var_2[var_10] = var_2.get(var_10, 0) + 1
    if not var_2:
        return 'unknown'
    var_3 = min(var_2, key=lambda l: (-var_2[l], l))
    return var_3

def _count_loc(dir_path: str) -> int:
    var_2 = 0
    for var_3, var_4, var_5 in os.walk(dir_path):
        if '.git' in var_4:
            var_4.remove('.git')
        for var_6 in var_5:
            var_7 = os.path.join(var_3, var_6)
            if os.path.islink(var_7):
                continue
            var_8 = os.path.splitext(var_6)[1].lower()
            if var_8 in var_1:
                try:
                    with open(var_7, 'rb') as var_9:
                        var_10 = var_9.read()
                        var_2 += var_10.count(b'\n')
                except (OSError, IOError):
                    continue
    return var_2

def _rmtree(dir_path: str) -> None:

    def _handle_error(func, path, exc_info):
        try:
            os.chmod(path, stat.S_IWRITE)
            func(path)
        except Exception:
            pass
    if os.path.isdir(dir_path) and (not os.path.islink(dir_path)):
        shutil.rmtree(dir_path, onerror=_handle_error)
    elif os.path.exists(dir_path) or os.path.islink(dir_path):
        try:
            os.unlink(dir_path)
        except Exception:
            pass

def make_subprocess_runner() -> Callable[[Sequence[str], Optional[str]], Tuple[int, str, str]]:

    def runner(argv: Sequence[str], cwd: Optional[str]) -> Tuple[int, str, str]:
        var_2 = str(cwd) if cwd is not None else None
        var_3 = [str(var_5) for var_5 in argv]
        try:
            var_4 = subprocess.run(var_3, cwd=var_2, capture_output=True, text=True, errors='replace')
            return (var_4.returncode, var_4.stdout, var_4.stderr)
        except Exception as e:
            return (-1, '', str(e))
    return runner

def clone_target(repo_url: str, *, dest_root: str='tmp', runner: Optional[Callable[[Sequence[str], Optional[str]], Tuple[int, str, str]]]=None, now: Optional[Callable[[], str]]=None, size_cap_mb: int=500, archived: bool=False, reuse: bool=True) -> Target:
    if archived:
        raise CloneError('Repository is archived and cannot be cloned.')
    var_2 = _slug(repo_url)
    var_3 = os.path.abspath(os.path.join(dest_root, var_2))
    var_4 = runner if runner is not None else make_subprocess_runner()
    if now is None:
        var_11 = _default_now()
    elif callable(now):
        var_11 = now()
    else:
        var_11 = str(now)
    var_5 = False
    if os.path.exists(var_3):
        try:
            var_12 = os.listdir(var_3)
        except Exception:
            var_12 = []
        if reuse and var_12:
            var_5 = True
        else:
            _rmtree(var_3)
    if not var_5:
        os.makedirs(dest_root, exist_ok=True)
        var_13 = ['git', 'clone', '--depth', '1', repo_url, var_3]
        var_14, var_15, var_16 = var_4(var_13, None)
        if var_14 != 0:
            raise CloneError(f'git clone failed (rc={var_14}): {var_16.strip()}')
    var_6 = ['git', 'rev-parse', 'HEAD']
    var_14, var_15, var_16 = var_4(var_6, var_3)
    if var_14 != 0:
        raise CloneError(f'git rev-parse failed (rc={var_14}): {var_16.strip()}')
    var_7 = var_15.strip()
    var_8 = _dir_size_bytes(var_3)
    if var_8 > size_cap_mb * 1024 * 1024:
        _rmtree(var_3)
        raise CloneError(f'Size cap exceeded: {var_8} bytes (cap is {size_cap_mb} MB)')
    var_9 = _detect_language(var_3)
    var_10 = _count_loc(var_3)
    var_17 = Target(repo_url=repo_url, repo_root=var_3, pinned_commit=var_7, language=var_9, loc=var_10, cloned_at=var_11)
    var_17.validate()
    return var_17