"""Deterministic graduated permission model for NobleGreedv2 workers.

Pure stdlib. Provides a 5-level :class:`PermissionMode` IntEnum, a
per-worker :class:`PermissionPolicy`, and a :class:`PermissionEnforcer`
that gates tool calls, file writes (scoped to a workspace root plus an
allow-list), and bash commands (a read-only heuristic).

No clock / network / random is used; the only IO is path resolution
performed against caller-supplied paths.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Set, Union
__all__ = ['PermissionMode', 'PermissionPolicy', 'PermissionEnforcer', 'EnforcementResult', 'WORKER_WRITE_SCOPES', 'WORKER_PERMISSION_MODES', 'DEFAULT_TOOL_REQUIREMENTS', '_execute_bypass']

class PermissionMode(IntEnum):
    """Graduated privilege levels; higher value == more privilege."""
    READ_ONLY = 1
    WORKSPACE_WRITE = 2
    ALLOW = 3
    DANGER_FULL_ACCESS = 4
    PROMPT = 5

    @classmethod
    def from_name(cls, name: Optional[str]) -> Optional['PermissionMode']:
        """Resolve a (case-insensitive) mode name, or ``None`` if unknown."""
        if not isinstance(name, str):
            return None
        ident = name.strip().upper()
        return cls.__members__.get(ident)
WORKER_PERMISSION_MODES: Dict[str, PermissionMode] = {'simple': PermissionMode.READ_ONLY, 'hunt': PermissionMode.WORKSPACE_WRITE, 'eval': PermissionMode.WORKSPACE_WRITE, 'overseer': PermissionMode.ALLOW}
WORKER_WRITE_SCOPES: Dict[str, Optional[List[str]]] = {'simple': [], 'hunt': ['tmp/', 'artifacts/'], 'eval': ['tmp/', 'artifacts/'], 'overseer': None}
DEFAULT_TOOL_REQUIREMENTS: Dict[str, PermissionMode] = {name: mode for name, mode in (('proxy_read_file', PermissionMode.READ_ONLY), ('proxy_list_dir', PermissionMode.READ_ONLY), ('proxy_grep', PermissionMode.READ_ONLY), ('proxy_glob', PermissionMode.READ_ONLY), ('proxy_write_file', PermissionMode.WORKSPACE_WRITE), ('proxy_edit_file', PermissionMode.WORKSPACE_WRITE), ('proxy_bash', PermissionMode.WORKSPACE_WRITE), ('proxy_delete_file', PermissionMode.ALLOW))}

@dataclass
class EnforcementResult:
    """Outcome of a permission check."""
    allowed: bool
    tool: Optional[str] = None
    active_mode: Optional[str] = None
    required_mode: Optional[str] = None
    reason: str = ''

    @classmethod
    def allow(cls, tool: Optional[str]=None) -> 'EnforcementResult':
        return cls(allowed=True, tool=tool)

    @classmethod
    def deny(cls, tool: Optional[str]=None, active_mode: Optional[str]=None, required_mode: Optional[str]=None, reason: str='') -> 'EnforcementResult':
        return cls(allowed=False, tool=tool, active_mode=active_mode, required_mode=required_mode, reason=reason)

def _normalize_scopes(scopes: Optional[List[str]]) -> List[str]:
    """``None`` -> ``[]``; otherwise a fresh copy of the scope list."""
    if scopes is None:
        return []
    return list(scopes)

@dataclass
class PermissionPolicy:
    """Per-worker permission configuration."""
    active_mode: PermissionMode = PermissionMode.WORKSPACE_WRITE
    workspace_root: Path = field(default_factory=lambda: Path('.'))
    allowed_paths: List[str] = field(default_factory=list)
    tool_requirements: Dict[str, PermissionMode] = field(default_factory=lambda: dict(DEFAULT_TOOL_REQUIREMENTS))

    @classmethod
    def for_worker_type(cls, worker_type: str, workspace_root: Optional[Union[str, Path]]=None) -> 'PermissionPolicy':
        mode = WORKER_PERMISSION_MODES.get(worker_type, PermissionMode.WORKSPACE_WRITE)
        scopes = WORKER_WRITE_SCOPES.get(worker_type, [])
        root = Path(workspace_root) if workspace_root is not None else Path('.')
        return cls(active_mode=mode, workspace_root=root, allowed_paths=_normalize_scopes(scopes), tool_requirements=dict(DEFAULT_TOOL_REQUIREMENTS))

    @classmethod
    def from_manifest(cls, manifest: Mapping[str, Any], workspace_root: Optional[Union[str, Path]]=None) -> 'PermissionPolicy':
        mode = PermissionMode.from_name(manifest.get('permission_level'))
        if mode is None:
            mode = PermissionMode.WORKSPACE_WRITE
        raw_paths = manifest.get('workspace_paths')
        allowed = list(raw_paths) if isinstance(raw_paths, (list, tuple)) else []
        root = Path(workspace_root) if workspace_root is not None else Path('.')
        return cls(active_mode=mode, workspace_root=root, allowed_paths=allowed, tool_requirements=dict(DEFAULT_TOOL_REQUIREMENTS))
_READ_ONLY_COMMANDS: Set[str] = {'ls', 'cat', 'grep', 'egrep', 'fgrep', 'rg', 'find', 'head', 'tail', 'wc', 'pwd', 'echo', 'stat', 'file', 'awk', 'sed', 'sort', 'uniq', 'cut', 'tr', 'diff', 'less', 'more', 'tree', 'du', 'df', 'ps', 'env', 'which', 'whoami', 'hostname', 'basename', 'dirname', 'realpath', 'readlink', 'nl', 'tac', 'column', 'printf', 'test', 'true', 'false'}
_READ_ONLY_GIT_SUBCOMMANDS: Set[str] = {'status', 'log', 'diff', 'show', 'branch', 'describe', 'blame', 'rev-parse', 'ls-files', 'ls-tree', 'cat-file', 'remote', 'config', 'shortlog', 'tag', 'reflog'}
_IN_PLACE_COMMANDS: Set[str] = {'sed', 'perl'}
_REDIRECT_RE = re.compile('>')
_IN_PLACE_RE = re.compile('(^|\\s)-i\\b')

class PermissionEnforcer:
    """Gates tool calls, file writes, and bash commands against a policy."""

    def __init__(self, policy: PermissionPolicy) -> None:
        self.policy = policy

    @property
    def active_mode(self) -> PermissionMode:
        return self.policy.active_mode

    def active_mode_allows_everything(self) -> bool:
        return self.policy.active_mode >= PermissionMode.ALLOW

    @staticmethod
    def _is_within(child: Path, parent: Path) -> bool:
        try:
            child.relative_to(parent)
            return True
        except ValueError:
            return False

    def check_tool(self, tool_name: str) -> EnforcementResult:
        required = self.policy.tool_requirements.get(tool_name, PermissionMode.WORKSPACE_WRITE)
        if self.policy.active_mode >= required:
            return EnforcementResult.allow(tool=tool_name)
        return EnforcementResult.deny(tool=tool_name, active_mode=self.policy.active_mode.name, required_mode=required.name, reason='tool %r requires %s but active mode is %s' % (tool_name, required.name, self.policy.active_mode.name))

    def check_file_write(self, path: Union[str, Path]) -> EnforcementResult:
        active = self.policy.active_mode
        if active < PermissionMode.WORKSPACE_WRITE:
            return EnforcementResult.deny(tool='file_write', active_mode=active.name, required_mode=PermissionMode.WORKSPACE_WRITE.name, reason='writes are not permitted in READ_ONLY mode')
        root = Path(self.policy.workspace_root).resolve()
        target = Path(path).resolve()
        if not self._is_within(target, root):
            return EnforcementResult.deny(tool='file_write', active_mode=active.name, required_mode=active.name, reason='path escapes the workspace root')
        if active >= PermissionMode.ALLOW:
            return EnforcementResult.allow(tool='file_write')
        scopes = self.policy.allowed_paths
        if not scopes:
            return EnforcementResult.allow(tool='file_write')
        for scope in scopes:
            scope_root = (root / scope).resolve()
            if self._is_within(target, scope_root):
                return EnforcementResult.allow(tool='file_write')
        return EnforcementResult.deny(tool='file_write', active_mode=active.name, required_mode=active.name, reason='path is outside the allowed write scopes')

    def check_bash(self, command: str) -> EnforcementResult:
        active = self.policy.active_mode
        if active >= PermissionMode.WORKSPACE_WRITE:
            return EnforcementResult.allow(tool='bash')
        cmd_text = command or ''
        if _REDIRECT_RE.search(cmd_text):
            return self._deny_bash(active, 'write redirection is not read-only')
        tokens = cmd_text.split()
        name = self._command_name(tokens)
        if name is None:
            return self._deny_bash(active, 'empty command')
        if name == 'git':
            sub = self._git_subcommand(tokens)
            if sub in _READ_ONLY_GIT_SUBCOMMANDS:
                return EnforcementResult.allow(tool='bash')
            return self._deny_bash(active, 'mutating git subcommand')
        if name in _READ_ONLY_COMMANDS:
            if name in _IN_PLACE_COMMANDS and _IN_PLACE_RE.search(cmd_text):
                return self._deny_bash(active, 'in-place edit is not read-only')
            return EnforcementResult.allow(tool='bash')
        return self._deny_bash(active, 'command %r is not read-only' % name)

    def _deny_bash(self, active: PermissionMode, reason: str) -> EnforcementResult:
        return EnforcementResult.deny(tool='bash', active_mode=active.name, required_mode=PermissionMode.WORKSPACE_WRITE.name, reason=reason)

    @staticmethod
    def _command_name(tokens: List[str]) -> Optional[str]:
        for tok in tokens:
            if '=' in tok and (not tok.startswith('-')):
                continue
            if tok == 'sudo':
                continue
            return tok
        return None

    @staticmethod
    def _git_subcommand(tokens: List[str]) -> Optional[str]:
        seen_git = False
        for tok in tokens:
            if '=' in tok and (not tok.startswith('-')) and (not seen_git):
                continue
            if tok == 'sudo':
                continue
            if not seen_git:
                if tok == 'git':
                    seen_git = True
                continue
            if tok.startswith('-'):
                continue
            return tok
        return None
_execute_bypass: Set[str] = set()