"""Deterministic, stdlib-only bash-command validation pipeline.

This module is *pure*: it inspects a command *string* and never spawns a
subprocess, opens a socket, or calls an LLM. It exposes a graduated
permission model (:class:`PermissionMode`), six string-analysis stages that
return plain result dicts, an 8-way semantic classifier
(:class:`CommandIntent`), and a pipeline entry point :func:`validate_command`
that returns the first non-allow stage result.

All behaviour is a deterministic function of the inputs.
"""
from __future__ import annotations
import re
from enum import Enum
from pathlib import Path
from typing import Dict, FrozenSet, List
__all__ = ['PermissionMode', 'CommandIntent', 'ValidationResult', 'validate_command', 'validate_read_only', 'check_destructive', 'validate_mode', 'validate_sed', 'validate_paths', 'classify_command', 'extract_first_command']

class PermissionMode(Enum):
    """Graduated permission levels for command execution."""
    READ_ONLY = 1
    WORKSPACE_WRITE = 2
    DANGER_FULL_ACCESS = 3
    PROMPT = 4
    ALLOW = 5

class CommandIntent(Enum):
    """Semantic classification of a bash command."""
    READ_ONLY = 'read_only'
    WRITE = 'write'
    DESTRUCTIVE = 'destructive'
    NETWORK = 'network'
    PROCESS_MANAGEMENT = 'process_management'
    PACKAGE_MANAGEMENT = 'package_management'
    SYSTEM_ADMIN = 'system_admin'
    UNKNOWN = 'unknown'

class ValidationResult:
    """Factory for the plain result dicts returned by every stage."""

    @staticmethod
    def allow() -> Dict[str, str]:
        return {'result': 'allow'}

    @staticmethod
    def block(reason: str) -> Dict[str, str]:
        return {'result': 'block', 'reason': reason}

    @staticmethod
    def warn(message: str) -> Dict[str, str]:
        return {'result': 'warn', 'message': message}
_ASSIGN_RE = re.compile('^[A-Za-z_][A-Za-z0-9_]*=')
READ_ONLY_COMMANDS: FrozenSet[str] = frozenset({'cat', 'ls', 'grep', 'egrep', 'fgrep', 'find', 'head', 'tail', 'echo', 'pwd', 'wc', 'sort', 'uniq', 'diff', 'less', 'more', 'stat', 'file', 'which', 'whereis', 'env', 'printenv', 'date', 'whoami', 'id', 'tree', 'du', 'df', 'ps', 'top', 'basename', 'dirname', 'realpath', 'readlink', 'cut', 'tr', 'comm', 'cmp', 'hexdump', 'od', 'xxd', 'type', 'hostname', 'uname'})
WRITE_COMMANDS: FrozenSet[str] = frozenset({'cp', 'mv', 'mkdir', 'rmdir', 'touch', 'ln', 'dd', 'tee', 'install', 'truncate', 'rsync'})
DESTRUCTIVE_COMMANDS: FrozenSet[str] = frozenset({'rm', 'shred', 'mkfs', 'fdisk', 'wipefs', 'srm'})
NETWORK_COMMANDS: FrozenSet[str] = frozenset({'curl', 'wget', 'ssh', 'scp', 'sftp', 'ftp', 'nc', 'netcat', 'ping', 'telnet', 'dig', 'host', 'nslookup', 'traceroute'})
PROCESS_COMMANDS: FrozenSet[str] = frozenset({'kill', 'killall', 'pkill', 'nice', 'renice', 'nohup', 'bg', 'fg', 'jobs', 'wait', 'disown'})
PACKAGE_COMMANDS: FrozenSet[str] = frozenset({'pip', 'pip3', 'apt', 'apt-get', 'aptitude', 'yum', 'dnf', 'pacman', 'brew', 'npm', 'yarn', 'pnpm', 'gem', 'cargo', 'conda', 'poetry'})
SYSTEM_ADMIN_COMMANDS: FrozenSet[str] = frozenset({'sudo', 'su', 'chmod', 'chown', 'chgrp', 'mount', 'umount', 'systemctl', 'service', 'useradd', 'userdel', 'usermod', 'groupadd', 'passwd', 'visudo', 'sysctl'})
GIT_READ_ONLY_SUBCOMMANDS: FrozenSet[str] = frozenset({'status', 'log', 'diff', 'show', 'branch', 'tag', 'remote', 'describe', 'blame', 'ls-files', 'ls-tree', 'rev-parse', 'cat-file', 'shortlog', 'reflog', 'whatchanged', 'grep', 'config', 'bisect'})
SYSTEM_PATH_PREFIXES = ('/etc', '/usr', '/bin', '/sbin', '/var', '/sys', '/proc', '/boot', '/lib', '/lib64', '/dev', '/root', '/opt')

def _significant_tokens(command: str) -> List[str]:
    """Tokens with leading ``VAR=value`` env assignments removed."""
    return [t for t in command.split() if not _ASSIGN_RE.match(t)]

def extract_first_command(command: str) -> str:
    """Return the first real command token, skipping env assignments."""
    for token in command.split():
        if _ASSIGN_RE.match(token):
            continue
        return token
    return ''

def _effective_command(command: str) -> str:
    """First command token with leading env assignments and ``sudo`` stripped."""
    tokens = _significant_tokens(command)
    if tokens and tokens[0] == 'sudo':
        tokens = tokens[1:]
    return tokens[0] if tokens else ''

def _git_subcommand(command: str) -> str:
    tokens = _significant_tokens(command)
    if tokens and tokens[0] == 'sudo':
        tokens = tokens[1:]
    for token in tokens[1:]:
        if token.startswith('-'):
            continue
        return token
    return ''

def _collect_flags(tokens: List[str]) -> FrozenSet[str]:
    """Collect single-letter flag characters and known long flags."""
    flags = set()
    for token in tokens:
        if token == '--recursive':
            flags.add('r')
        elif token == '--force':
            flags.add('f')
        elif token.startswith('-') and (not token.startswith('--')) and (len(token) > 1):
            flags.update(token[1:])
    return frozenset(flags)

def _has_redirection(command: str) -> bool:
    return '>' in command

def _touches_system_path(command: str) -> bool:
    for token in command.split():
        for prefix in SYSTEM_PATH_PREFIXES:
            if token == prefix or token.startswith(prefix + '/'):
                return True
    return False

def _sed_in_place(command: str) -> bool:
    for token in command.split():
        if token in ('-i', '--in-place'):
            return True
        if token.startswith('--in-place='):
            return True
        if token.startswith('-i') and (not token.startswith('--')):
            return True
    return False

def classify_command(command: str) -> CommandIntent:
    """Classify a command string into one of the eight intents."""
    first = extract_first_command(command)
    if not first:
        return CommandIntent.UNKNOWN
    if first == 'git':
        sub = _git_subcommand(command)
        if sub in GIT_READ_ONLY_SUBCOMMANDS:
            return CommandIntent.READ_ONLY
        return CommandIntent.WRITE
    if first == 'sed':
        if _sed_in_place(command):
            return CommandIntent.WRITE
        return CommandIntent.READ_ONLY
    if first in SYSTEM_ADMIN_COMMANDS:
        return CommandIntent.SYSTEM_ADMIN
    if first in PACKAGE_COMMANDS:
        return CommandIntent.PACKAGE_MANAGEMENT
    if first in NETWORK_COMMANDS:
        return CommandIntent.NETWORK
    if first in PROCESS_COMMANDS:
        return CommandIntent.PROCESS_MANAGEMENT
    if first in DESTRUCTIVE_COMMANDS:
        return CommandIntent.DESTRUCTIVE
    if first in WRITE_COMMANDS:
        return CommandIntent.WRITE
    if first in READ_ONLY_COMMANDS:
        return CommandIntent.READ_ONLY
    return CommandIntent.UNKNOWN

def validate_read_only(command: str, mode: PermissionMode) -> Dict[str, str]:
    """In READ_ONLY mode, block writes/redirections; pass through otherwise."""
    if mode != PermissionMode.READ_ONLY:
        return ValidationResult.allow()
    if _has_redirection(command):
        return ValidationResult.block('output redirection is not allowed in read-only mode')
    if classify_command(command) == CommandIntent.READ_ONLY:
        return ValidationResult.allow()
    return ValidationResult.block('command modifies state and is not allowed in read-only mode')

def check_destructive(command: str) -> Dict[str, str]:
    """Warn on irreversible commands (``shred``, recursive+forced ``rm``)."""
    first = _effective_command(command)
    if first in DESTRUCTIVE_COMMANDS and first != 'rm':
        return ValidationResult.warn('potentially destructive command')
    if first == 'rm':
        flags = _collect_flags(command.split())
        if 'r' in flags and 'f' in flags:
            return ValidationResult.warn('recursive forced removal is destructive')
    return ValidationResult.allow()

def validate_mode(command: str, mode: PermissionMode) -> Dict[str, str]:
    """Apply mode-graduated policy to a command."""
    if mode == PermissionMode.READ_ONLY:
        return validate_read_only(command, mode)
    if mode == PermissionMode.WORKSPACE_WRITE:
        intent = classify_command(command)
        if intent in (CommandIntent.WRITE, CommandIntent.DESTRUCTIVE):
            if _touches_system_path(command):
                return ValidationResult.warn('write targets a system path outside the workspace')
        return ValidationResult.allow()
    return ValidationResult.allow()

def validate_sed(command: str, mode: PermissionMode) -> Dict[str, str]:
    """Block in-place ``sed -i`` edits while in READ_ONLY mode."""
    if _effective_command(command) != 'sed':
        return ValidationResult.allow()
    if _sed_in_place(command) and mode == PermissionMode.READ_ONLY:
        return ValidationResult.block('in-place sed edit is not allowed in read-only mode')
    return ValidationResult.allow()

def validate_paths(command: str, workspace: Path) -> Dict[str, str]:
    """Flag suspicious path usage (traversal, home, $HOME, /tmp clone)."""
    first = _effective_command(command)
    tokens = command.split()
    if first == 'git' and 'clone' in tokens:
        for token in tokens:
            if token == '/tmp' or token.startswith('/tmp/'):
                return ValidationResult.block('cloning into /tmp is not allowed')
    if '../' in command:
        return ValidationResult.warn('path traversal detected')
    if '~' in command:
        return ValidationResult.warn('home directory reference detected')
    if '$HOME' in command:
        return ValidationResult.warn('home directory expansion detected')
    return ValidationResult.allow()

def validate_command(command: str, mode: PermissionMode, workspace: Path) -> Dict[str, str]:
    """Run the validation pipeline and return the first non-allow result."""
    stages = (validate_mode(command, mode), validate_sed(command, mode), check_destructive(command), validate_paths(command, workspace))
    for result in stages:
        if result.get('result') != 'allow':
            return result
    return ValidationResult.allow()