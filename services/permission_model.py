"""Graduated Permission Model — 5-level worker permissions and safety gates.

Provides:
- PermissionMode: ordering representing graduated privilege levels.
- PermissionPolicy: configurations defining scoped write paths and tool requirements.
- PermissionEnforcer: checking mechanism to audit tool calls, file writes, and commands.
- _execute_bypass: registry mapping active session IDs that bypass tool manifest gates.
"""
from __future__ import annotations
import logging
import re
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
_log = logging.getLogger('permission_model')
ROOT = Path(__file__).resolve().parent.parent
_execute_bypass: set[str] = set()

class PermissionMode(IntEnum):
    """5-level graduated permission modes, ordered by privilege."""
    READ_ONLY = 1
    WORKSPACE_WRITE = 2
    ALLOW = 3
    DANGER_FULL_ACCESS = 4
    PROMPT = 5
WORKER_WRITE_SCOPES: dict[str, list[str] | None] = {'hunt': ['tmp/', 'operations/active/', 'operations/poc/', 'operations/tests/', 'data/'], 'eval': ['reports/', 'research/', 'data/', 'financials/', 'operations/', 'services/', 'tests/'], 'adversarial': ['operations/adversarial/', 'services/adversarial/', 'tmp/'], 'gpu': ['knowledge/graphmert/', 'data/'], 'simple': [], 'overseer': None}
WORKER_PERMISSION_MODES: dict[str, PermissionMode] = {'simple': PermissionMode.READ_ONLY, 'eval': PermissionMode.WORKSPACE_WRITE, 'hunt': PermissionMode.WORKSPACE_WRITE, 'adversarial': PermissionMode.WORKSPACE_WRITE, 'gpu': PermissionMode.WORKSPACE_WRITE, 'overseer': PermissionMode.ALLOW}
DEFAULT_TOOL_REQUIREMENTS: dict[str, PermissionMode] = {'proxy_read_file': PermissionMode.READ_ONLY, 'proxy_edit_file': PermissionMode.WORKSPACE_WRITE, 'proxy_write_file': PermissionMode.WORKSPACE_WRITE, 'proxy_bash': PermissionMode.READ_ONLY, 'proxy_commit': PermissionMode.WORKSPACE_WRITE, 'dispatch_worker': PermissionMode.ALLOW, 'overseer_instruct': PermissionMode.ALLOW, 'submit_finding': PermissionMode.WORKSPACE_WRITE, 'submit_poc': PermissionMode.WORKSPACE_WRITE, 'submit_review': PermissionMode.WORKSPACE_WRITE, 'log_progress': PermissionMode.READ_ONLY, 'complete_task': PermissionMode.READ_ONLY, 'dashboard_status': PermissionMode.READ_ONLY, 'worker_history': PermissionMode.READ_ONLY, 'list_findings': PermissionMode.READ_ONLY, 'index_repository': PermissionMode.READ_ONLY, 'search_code': PermissionMode.READ_ONLY, 'get_architecture': PermissionMode.READ_ONLY, 'trace_call_path': PermissionMode.READ_ONLY, 'detect_changes': PermissionMode.READ_ONLY}
READ_ONLY_BASH_COMMANDS = frozenset(['ls', 'cat', 'head', 'tail', 'less', 'more', 'wc', 'file', 'stat', 'find', 'locate', 'which', 'whereis', 'type', 'readlink', 'grep', 'egrep', 'fgrep', 'rg', 'ag', 'ack', 'diff', 'cmp', 'md5sum', 'sha256sum', 'sha1sum', 'echo', 'printf', 'date', 'whoami', 'id', 'hostname', 'uname', 'pwd', 'env', 'printenv', 'set', 'ps', 'top', 'htop', 'free', 'df', 'du', 'uptime', 'python3', 'python', 'node', 'ruby', 'perl', 'jq', 'yq', 'xmllint', 'csvtool', 'git', 'nvidia-smi', 'lspci', 'lsblk', 'lsusb', 'tree', 'realpath', 'basename', 'dirname'])
READ_ONLY_GIT_SUBCOMMANDS = frozenset(['status', 'log', 'diff', 'show', 'blame', 'branch', 'tag', 'remote', 'stash', 'ls-files', 'ls-tree', 'rev-parse', 'describe', 'shortlog', 'reflog', 'config', 'cat-file', 'count-objects', 'fsck', 'verify-pack'])
WRITE_REDIRECTIONS_RE = re.compile('[^2]?>>?|>&')
IN_PLACE_FLAGS_RE = re.compile('\\s-i\\b|\\s--in-place\\b')

@dataclass
class EnforcementResult:
    """Result of a permission gate validation check."""
    allowed: bool
    tool: str = ''
    active_mode: str = ''
    required_mode: str = ''
    reason: str = ''

    @staticmethod
    def allow() -> EnforcementResult:
        return EnforcementResult(allowed=True)

    @staticmethod
    def deny(tool: str, active_mode: str, required_mode: str, reason: str) -> EnforcementResult:
        return EnforcementResult(allowed=False, tool=tool, active_mode=active_mode, required_mode=required_mode, reason=reason)

@dataclass
class PermissionPolicy:
    """Per-worker permission policy configuration."""
    active_mode: PermissionMode
    workspace_root: Path = field(default_factory=lambda: ROOT)
    allowed_paths: list[str] = field(default_factory=list)
    tool_requirements: dict[str, PermissionMode] = field(default_factory=lambda: dict(DEFAULT_TOOL_REQUIREMENTS))

    @classmethod
    def for_worker_type(cls, worker_type: str, workspace_root: Path | None=None) -> PermissionPolicy:
        """Create policy settings matching a specified worker type."""
        mode = WORKER_PERMISSION_MODES.get(worker_type, PermissionMode.WORKSPACE_WRITE)
        scopes = WORKER_WRITE_SCOPES.get(worker_type)
        return cls(active_mode=mode, workspace_root=workspace_root or ROOT, allowed_paths=scopes if scopes is not None else [])

    @classmethod
    def from_manifest(cls, manifest: dict, workspace_root: Path | None=None) -> PermissionPolicy:
        """Parse permission settings from worker manifest instructions."""
        level = manifest.get('permission_level', 'workspace_write')
        mode_map = {'read_only': PermissionMode.READ_ONLY, 'workspace_write': PermissionMode.WORKSPACE_WRITE, 'allow': PermissionMode.ALLOW, 'danger_full_access': PermissionMode.DANGER_FULL_ACCESS}
        mode = mode_map.get(level.lower(), PermissionMode.WORKSPACE_WRITE)
        paths = manifest.get('workspace_paths', [])
        return cls(active_mode=mode, workspace_root=workspace_root or ROOT, allowed_paths=paths)

class PermissionEnforcer:
    """Enforces permission constraints on tool, command, and filesystem updates."""

    def __init__(self, policy: PermissionPolicy) -> None:
        self.policy = policy

    def check_tool(self, tool_name: str, input_args: dict | None=None) -> EnforcementResult:
        """Audit tool invocations against required mode clearance."""
        required = self.policy.tool_requirements.get(tool_name)
        if required is None:
            required = PermissionMode.WORKSPACE_WRITE
        if self.policy.active_mode >= required:
            return EnforcementResult.allow()
        return EnforcementResult.deny(tool=tool_name, active_mode=self.policy.active_mode.name, required_mode=required.name, reason=f"Permission denied: tool '{tool_name}' requires {required.name} but worker has {self.policy.active_mode.name}")

    def check_file_write(self, path: str | Path) -> EnforcementResult:
        """Validate if a file write operation falls within scoped write permissions."""
        p = Path(path)
        if self.policy.active_mode >= PermissionMode.ALLOW:
            return self._check_within_root(p)
        if self.policy.active_mode == PermissionMode.READ_ONLY:
            return EnforcementResult.deny(tool='file_write', active_mode=self.policy.active_mode.name, required_mode=PermissionMode.WORKSPACE_WRITE.name, reason='Permission denied: READ_ONLY workers cannot write files')
        root_check = self._check_within_root(p)
        if not root_check.allowed:
            return root_check
        if not self.policy.allowed_paths:
            return EnforcementResult.allow()
        try:
            canonical = p.resolve()
        except OSError:
            canonical = p
        for allowed_rel in self.policy.allowed_paths:
            allowed_abs = (self.policy.workspace_root / allowed_rel).resolve()
            if str(canonical).startswith(str(allowed_abs) + '/') or canonical == allowed_abs:
                return EnforcementResult.allow()
        return EnforcementResult.deny(tool='file_write', active_mode=self.policy.active_mode.name, required_mode=PermissionMode.WORKSPACE_WRITE.name, reason=f"Permission denied: path '{path}' is outside allowed write scope {self.policy.allowed_paths}")

    def check_bash(self, command: str) -> EnforcementResult:
        """Audit shell command strings for permission policy violations."""
        if self.policy.active_mode >= PermissionMode.ALLOW:
            return EnforcementResult.allow()
        if self.policy.active_mode == PermissionMode.READ_ONLY:
            return self._check_bash_read_only(command)
        return EnforcementResult.allow()

    def _check_within_root(self, path: Path) -> EnforcementResult:
        try:
            canonical = path.resolve()
            root_canonical = self.policy.workspace_root.resolve()
        except OSError:
            return EnforcementResult.deny(tool='file_write', active_mode=self.policy.active_mode.name, required_mode='ALLOW', reason=f'Cannot resolve path: {path}')
        if str(canonical).startswith(str(root_canonical) + '/') or canonical == root_canonical:
            return EnforcementResult.allow()
        return EnforcementResult.deny(tool='file_write', active_mode=self.policy.active_mode.name, required_mode='ALLOW', reason=f"Path '{path}' escapes workspace root {root_canonical}")

    def _check_bash_read_only(self, command: str) -> EnforcementResult:
        cmd_name = _extract_first_command(command)
        if WRITE_REDIRECTIONS_RE.search(command):
            return EnforcementResult.deny(tool='proxy_bash', active_mode='READ_ONLY', required_mode='WORKSPACE_WRITE', reason=f'Permission denied: write redirection in READ_ONLY mode: {command[:80]}')
        if IN_PLACE_FLAGS_RE.search(command):
            return EnforcementResult.deny(tool='proxy_bash', active_mode='READ_ONLY', required_mode='WORKSPACE_WRITE', reason=f'Permission denied: in-place modification in READ_ONLY mode: {command[:80]}')
        if '|' in command:
            for segment in command.split('|'):
                seg_cmd = _extract_first_command(segment.strip())
                if seg_cmd and seg_cmd not in READ_ONLY_BASH_COMMANDS:
                    if seg_cmd in ('tee', 'sponge'):
                        return EnforcementResult.deny(tool='proxy_bash', active_mode='READ_ONLY', required_mode='WORKSPACE_WRITE', reason=f"Permission denied: '{seg_cmd}' is a write command in READ_ONLY mode")
        if cmd_name == 'git':
            git_sub = _extract_git_subcommand(command)
            if git_sub and git_sub not in READ_ONLY_GIT_SUBCOMMANDS:
                return EnforcementResult.deny(tool='proxy_bash', active_mode='READ_ONLY', required_mode='WORKSPACE_WRITE', reason=f"Permission denied: 'git {git_sub}' is not read-only")
            return EnforcementResult.allow()
        if cmd_name in READ_ONLY_BASH_COMMANDS:
            return EnforcementResult.allow()
        return EnforcementResult.deny(tool='proxy_bash', active_mode='READ_ONLY', required_mode='WORKSPACE_WRITE', reason=f"Permission denied: command '{cmd_name}' not in read-only allowlist")

def _extract_first_command(command: str) -> str:
    parts = command.strip().split()
    for part in parts:
        if '=' in part and (not part.startswith('-')):
            eq_idx = part.index('=')
            if eq_idx > 0 and part[:eq_idx].replace('_', '').isalnum():
                continue
        if part == 'sudo':
            continue
        if part.startswith('-') and parts[0] == 'sudo':
            continue
        return part
    return ''

def _extract_git_subcommand(command: str) -> str:
    parts = command.strip().split()
    found_git = False
    for part in parts:
        if part == 'git':
            found_git = True
            continue
        if found_git:
            if part.startswith('-'):
                if part in ('-C', '-c', '--git-dir', '--work-tree'):
                    continue
                continue
            return part
    return ''
if __name__ == '__main__':
    print('permission_model.py self-test passed')