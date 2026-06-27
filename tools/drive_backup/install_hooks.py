import argparse
from dataclasses import dataclass
import os
import shutil
from typing import List
from typing import Optional
DEFAULT_REPOS = ['/home/xnihil0zer0/AI-Data/JanusMaskEX', '/home/xnihil0zer0/NobleGreedv2']
SENTINEL = '# >>> janusmask-drive-backup >>>'

@dataclass
class InstallResult:
    repo: str
    hook_path: str
    action: str
    ok: bool

class RealFS:

    def exists(self, path: str) -> bool:
        return os.path.exists(path)

    def read_text(self, path: str) -> str:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()

    def write_text(self, path: str, text: str) -> None:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)

    def move(self, src: str, dst: str) -> None:
        shutil.move(src, dst)

    def chmod(self, path: str, mode: int) -> None:
        os.chmod(path, mode)

    def makedirs(self, path: str, exist_ok: bool=True) -> None:
        os.makedirs(path, exist_ok=exist_ok)

def render_shim(janusmask_root: str, *, chained_hook: Optional[str]=None) -> str:
    abs_root = os.path.abspath(janusmask_root)
    lines = ['#!/usr/bin/env bash', SENTINEL, '# Managed by the janusmask drive-backup installer.', '# Do not edit between the sentinel markers; rerun the installer instead.', 'set -u', f'JANUSMASK_ROOT="{abs_root}"', '', '# Buffer the pushed refs from stdin so they can be replayed below.', '_jm_stdin="$(cat)"', '']
    if chained_hook:
        lines.extend(['# Run the saved original hook first.', f'''printf '%s' "$_jm_stdin" | "{chained_hook}" "$@"''', 'exit_code=$?', 'if [ $exit_code -ne 0 ]; then', '    exit $exit_code', 'fi', ''])
    lines.extend(['# Capture the repo being pushed BEFORE cd-ing into JANUSMASK_ROOT.', "# git invokes pre-push with cwd = the pushed repo's top-level, so this", '# resolves the ACTUAL repo. Exported as JM_PUSH_REPO and honored first', '# by hook_runner._resolve_repo_root -- without it, GIT_DIR (relative', "# '.git') resolves against the JanusMask cwd and every repo's push", '# would back up the JanusMask tree instead of itself.', 'JM_PUSH_REPO="$(git rev-parse --show-toplevel 2>/dev/null || true)"', '', '# Drive-backup step: FULLY DETACHED so git never waits on the upload.', '# setsid (new session) + </dev/null + >/dev/null 2>&1 + & means the', "# uploader holds none of git's pipes/FDs open, so the push returns", '# immediately. A synchronous backup parks git in do_wait for the entire', '# ~15-min rclone upload. Never changes the push exit code.', 'export JANUSMASK_ROOT JM_PUSH_REPO', 'JM_STDIN="$_jm_stdin" setsid bash -c \'cd "$JANUSMASK_ROOT" && printf "%s" "$JM_STDIN" | JM_PUSH_REPO="$JM_PUSH_REPO" python -m tools.drive_backup.hook_runner "$@"\' bash "$@" </dev/null >/dev/null 2>&1 &', 'exit 0', '# <<< janusmask-drive-backup <<<'])
    return '\n'.join(lines) + '\n'

def install(repo_roots: List[str]=DEFAULT_REPOS, *, fs, janusmask_root: str, dry_run: bool=False) -> List[InstallResult]:
    results = []
    for repo in repo_roots:
        hooks_dir = f'{repo}/.git/hooks'
        hook_path = f'{hooks_dir}/pre-push'
        try:
            if not fs.exists(hook_path):
                action = 'created'
                if dry_run:
                    action = 'created:dry'
                else:
                    fs.makedirs(hooks_dir, exist_ok=True)
                    shim_content = render_shim(janusmask_root)
                    fs.write_text(hook_path, shim_content)
                    fs.chmod(hook_path, 493)
            else:
                existing_content = fs.read_text(hook_path)
                if SENTINEL in existing_content:
                    action = 'updated'
                    if dry_run:
                        action = 'updated:dry'
                    else:
                        sidecar_path = f'{hook_path}.pre-janusmask'
                        chained_hook = sidecar_path if fs.exists(sidecar_path) else None
                        shim_content = render_shim(janusmask_root, chained_hook=chained_hook)
                        fs.write_text(hook_path, shim_content)
                        fs.chmod(hook_path, 493)
                else:
                    action = 'chained'
                    if dry_run:
                        action = 'chained:dry'
                    else:
                        fs.makedirs(hooks_dir, exist_ok=True)
                        sidecar_path = f'{hook_path}.pre-janusmask'
                        fs.move(hook_path, sidecar_path)
                        shim_content = render_shim(janusmask_root, chained_hook=sidecar_path)
                        fs.write_text(hook_path, shim_content)
                        fs.chmod(hook_path, 493)
            results.append(InstallResult(repo=repo, hook_path=hook_path, action=action, ok=True))
        except Exception:
            results.append(InstallResult(repo=repo, hook_path=hook_path, action='error', ok=False))
    return results

def main(argv: Optional[List[str]]=None, *, fs=None) -> int:
    if fs is None:
        fs = RealFS()
    try:
        janusmask_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    except NameError:
        janusmask_root = '/home/xnihil0zer0/AI-Data/JanusMaskEX'
    parser = argparse.ArgumentParser(description='Install drive-backup hooks.')
    parser.add_argument('--dry-run', action='store_true', help='Dry run mode')
    parser.add_argument('repos', nargs='*', help='Optional repository path overrides')
    args = parser.parse_args(argv)
    repos = args.repos if args.repos else DEFAULT_REPOS
    install(repos, fs=fs, janusmask_root=janusmask_root, dry_run=args.dry_run)
    return 0