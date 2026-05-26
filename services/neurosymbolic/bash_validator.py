#!/usr/bin/env python3
"""Bash command validation pipeline.

Provides 6 semantic validation modules to audit bash commands:
1. validate_read_only — Block write/state-modifying commands in READ_ONLY mode.
2. check_destructive  — Warn on dangerous destructive patterns.
3. validate_mode      — Enforce permission mode constraints.
4. validate_sed       — Validate sed expressions.
5. validate_paths     — Detect suspicious path patterns.
6. classify_command   — Semantic classification.
"""

from __future__ import annotations

import re
from enum import Enum, auto
from pathlib import Path
from typing import Optional

__all__ = [
    "ValidationResult",
    "CommandIntent",
    "PermissionMode",
    "validate_command",
    "validate_read_only",
    "check_destructive",
    "validate_mode",
    "validate_sed",
    "validate_paths",
    "classify_command",
]


class PermissionMode(Enum):
    """5-level graduated permission modes, ordered by privilege."""
    READ_ONLY = 1
    WORKSPACE_WRITE = 2
    DANGER_FULL_ACCESS = 3
    PROMPT = 4
    ALLOW = 5


class CommandIntent(Enum):
    """Semantic classification of a bash command's intent."""
    READ_ONLY = auto()
    WRITE = auto()
    DESTRUCTIVE = auto()
    NETWORK = auto()
    PROCESS_MANAGEMENT = auto()
    PACKAGE_MANAGEMENT = auto()
    SYSTEM_ADMIN = auto()
    UNKNOWN = auto()


class ValidationResult:
    """Factory for validation result dicts."""
    @staticmethod
    def allow() -> dict:
        return {"result": "allow"}

    @staticmethod
    def block(reason: str) -> dict:
        return {"result": "block", "reason": reason}

    @staticmethod
    def warn(message: str) -> dict:
        return {"result": "warn", "message": message}


# Command lists
WRITE_COMMANDS: frozenset[str] = frozenset([
    "cp", "mv", "rm", "mkdir", "rmdir", "touch", "chmod", "chown", "chgrp",
    "ln", "install", "tee", "truncate", "shred", "mkfifo", "mknod", "dd",
])

STATE_MODIFYING_COMMANDS: frozenset[str] = frozenset([
    "apt", "apt-get", "yum", "dnf", "pacman", "brew",
    "pip", "pip3", "npm", "yarn", "pnpm", "bun", "cargo", "gem", "go", "rustup",
    "docker", "systemctl", "service", "mount", "umount", "kill", "pkill", "killall",
    "reboot", "shutdown", "halt", "poweroff", "useradd", "userdel", "usermod",
    "groupadd", "groupdel", "crontab", "at",
])

WRITE_REDIRECTIONS: tuple[str, ...] = (">", ">>", ">&")

GIT_READ_ONLY_SUBCOMMANDS: frozenset[str] = frozenset([
    "status", "log", "diff", "show", "branch", "tag", "stash", "remote",
    "fetch", "ls-files", "ls-tree", "cat-file", "rev-parse", "describe",
    "shortlog", "blame", "bisect", "reflog", "config",
])

DESTRUCTIVE_PATTERNS: list[tuple[str, str]] = [
    ("rm -rf /",    "Recursive forced deletion at root — this will destroy the system"),
    ("rm -rf ~",    "Recursive forced deletion of home directory"),
    ("rm -rf *",    "Recursive forced deletion of all files in current directory"),
    ("rm -rf .",    "Recursive forced deletion of current directory"),
    ("mkfs",        "Filesystem creation will destroy existing data on the device"),
    ("dd if=",      "Direct disk write — can overwrite partitions or devices"),
    ("> /dev/sd",   "Writing to raw disk device"),
    ("chmod -R 777", "Recursively setting world-writable permissions"),
    ("chmod -R 000", "Recursively removing all permissions"),
    (":(){ :|:& };:", "Fork bomb — will crash the system"),
]

ALWAYS_DESTRUCTIVE_COMMANDS: frozenset[str] = frozenset(["shred", "wipefs"])

SEMANTIC_READ_ONLY_COMMANDS: frozenset[str] = frozenset([
    "ls", "cat", "head", "tail", "less", "more", "wc", "sort", "uniq",
    "grep", "egrep", "fgrep", "find", "which", "whereis", "whatis",
    "man", "info", "file", "stat", "du", "df", "free", "uptime", "uname",
    "hostname", "whoami", "id", "groups", "env", "printenv",
    "echo", "printf", "date", "cal", "bc", "expr", "test", "true", "false",
    "pwd", "tree", "diff", "cmp", "md5sum", "sha256sum", "sha1sum",
    "xxd", "od", "hexdump", "strings", "readlink", "realpath",
    "basename", "dirname", "seq", "yes", "tput", "column",
    "jq", "yq", "xargs", "tr", "cut", "paste", "awk", "sed",
])

NETWORK_COMMANDS: frozenset[str] = frozenset([
    "curl", "wget", "ssh", "scp", "rsync", "ftp", "sftp",
    "nc", "ncat", "telnet", "ping", "traceroute",
    "dig", "nslookup", "host", "whois",
    "ifconfig", "ip", "netstat", "ss", "nmap",
])

PROCESS_COMMANDS: frozenset[str] = frozenset([
    "kill", "pkill", "killall", "ps", "top", "htop",
    "bg", "fg", "jobs", "nohup", "disown", "wait", "nice", "renice",
])

PACKAGE_COMMANDS: frozenset[str] = frozenset([
    "apt", "apt-get", "yum", "dnf", "pacman", "brew",
    "pip", "pip3", "npm", "yarn", "pnpm", "bun",
    "cargo", "gem", "go", "rustup", "snap", "flatpak",
])

SYSTEM_ADMIN_COMMANDS: frozenset[str] = frozenset([
    "sudo", "su", "chroot",
    "mount", "umount", "fdisk", "parted", "lsblk", "blkid",
    "systemctl", "service", "journalctl", "dmesg",
    "modprobe", "insmod", "rmmod",
    "iptables", "ufw", "firewall-cmd", "sysctl",
    "crontab", "at",
    "useradd", "userdel", "usermod", "groupadd", "groupdel",
    "passwd", "visudo",
])

SYSTEM_PATHS: tuple[str, ...] = (
    "/etc/", "/usr/", "/var/", "/boot/", "/sys/",
    "/proc/", "/dev/", "/sbin/", "/lib/", "/opt/",
)


def _find_end_of_value(s: str) -> Optional[int]:
    s = s.lstrip()
    if not s:
        return None

    first = s[0]
    if first in ('"', "'"):
        quote = first
        i = 1
        while i < len(s):
            if s[i] == quote and (i == 0 or s[i - 1] != '\\'):
                i += 1
                while i < len(s) and not s[i].isspace():
                    i += 1
                return i if i < len(s) else None
            i += 1
        return None
    else:
        for i, ch in enumerate(s):
            if ch.isspace():
                return i
        return None


def extract_first_command(command: str) -> str:
    remaining = command.strip()
    while remaining:
        remaining = remaining.lstrip()
        eq_pos = remaining.find('=')
        if eq_pos > 0:
            before_eq = remaining[:eq_pos]
            if before_eq and all(c.isalnum() or c == '_' for c in before_eq):
                after_eq = remaining[eq_pos + 1:]
                space = _find_end_of_value(after_eq)
                if space is not None:
                    remaining = after_eq[space:]
                    continue
                return ""
        break

    parts = remaining.split()
    return parts[0] if parts else ""


def extract_sudo_inner(command: str) -> str:
    parts = command.split()
    try:
        sudo_idx = parts.index("sudo")
    except ValueError:
        return ""

    rest = parts[sudo_idx + 1:]
    for part in rest:
        if not part.startswith('-'):
            offset = command.find(part, command.find("sudo") + 4)
            if offset >= 0:
                return command[offset:]
            return ""
    return ""


def _validate_git_read_only(command: str) -> dict:
    parts = command.split()
    subcommand = None
    for part in parts[1:]:
        if not part.startswith('-'):
            subcommand = part
            break

    if subcommand is None:
        return ValidationResult.allow()

    if subcommand in GIT_READ_ONLY_SUBCOMMANDS:
        return ValidationResult.allow()

    return ValidationResult.block(
        f"Git subcommand '{subcommand}' modifies repository state and is not allowed in read-only mode"
    )


def validate_read_only(command: str, mode: PermissionMode) -> dict:
    if mode != PermissionMode.READ_ONLY:
        return ValidationResult.allow()

    first_command = extract_first_command(command)

    if first_command in WRITE_COMMANDS:
        return ValidationResult.block(
            f"Command '{first_command}' modifies the filesystem and is not allowed in read-only mode"
        )

    if first_command in STATE_MODIFYING_COMMANDS:
        return ValidationResult.block(
            f"Command '{first_command}' modifies system state and is not allowed in read-only mode"
        )

    if first_command == "sudo":
        inner = extract_sudo_inner(command)
        if inner:
            inner_result = validate_read_only(inner, mode)
            if inner_result["result"] != "allow":
                return inner_result

    for redir in WRITE_REDIRECTIONS:
        if redir in command:
            return ValidationResult.block(
                f"Command contains write redirection '{redir}' which is not allowed in read-only mode"
            )

    if first_command == "git":
        return _validate_git_read_only(command)

    return ValidationResult.allow()


def check_destructive(command: str) -> dict:
    for pattern, warning in DESTRUCTIVE_PATTERNS:
        if pattern in command:
            return ValidationResult.warn(
                f"Destructive command detected: {warning}"
            )

    first = extract_first_command(command)
    if first in ALWAYS_DESTRUCTIVE_COMMANDS:
        return ValidationResult.warn(
            f"Command '{first}' is inherently destructive and may cause data loss"
        )

    if "rm " in command or command.startswith("rm"):
        has_r = bool(re.search(r'\s-[a-zA-Z]*r', command))
        has_f = bool(re.search(r'\s-[a-zA-Z]*f', command))
        if has_r and has_f:
            return ValidationResult.warn(
                "Recursive forced deletion detected — verify the target path is correct"
            )

    return ValidationResult.allow()


def _command_targets_outside_workspace(command: str) -> bool:
    first = extract_first_command(command)
    is_write_cmd = first in WRITE_COMMANDS or first in STATE_MODIFYING_COMMANDS

    if not is_write_cmd:
        return False

    for sys_path in SYSTEM_PATHS:
        if sys_path in command:
            return True

    return False


def validate_mode(command: str, mode: PermissionMode) -> dict:
    if mode == PermissionMode.READ_ONLY:
        return validate_read_only(command, mode)

    if mode == PermissionMode.WORKSPACE_WRITE:
        if _command_targets_outside_workspace(command):
            return ValidationResult.warn(
                "Command appears to target files outside the workspace — requires elevated permission"
            )
        return ValidationResult.allow()

    return ValidationResult.allow()


def validate_sed(command: str, mode: PermissionMode) -> dict:
    first = extract_first_command(command)
    if first != "sed":
        return ValidationResult.allow()

    if mode == PermissionMode.READ_ONLY and " -i" in command:
        return ValidationResult.block(
            "sed -i (in-place editing) is not allowed in read-only mode"
        )

    return ValidationResult.allow()


def validate_paths(command: str, workspace: Path) -> dict:
    if "../" in command:
        workspace_str = str(workspace)
        if workspace_str not in command:
            return ValidationResult.warn(
                "Command contains directory traversal pattern '../' — verify the target path resolves within the workspace"
            )

    if "~/" in command or "$HOME" in command:
        return ValidationResult.warn(
            "Command references home directory — verify it stays within the workspace scope"
        )

    if re.search(r'git\s+clone\b.*\s+/tmp/', command, re.IGNORECASE):
        return ValidationResult.block(
            "Clone location /tmp/ is not allowed — clone to NobleJanus/tmp/ instead"
        )

    return ValidationResult.allow()


def _classify_git_command(command: str) -> CommandIntent:
    parts = command.split()
    subcommand = None
    for part in parts[1:]:
        if not part.startswith('-'):
            subcommand = part
            break

    if subcommand is not None and subcommand in GIT_READ_ONLY_SUBCOMMANDS:
        return CommandIntent.READ_ONLY
    return CommandIntent.WRITE


def classify_command(command: str) -> CommandIntent:
    first = extract_first_command(command)

    if first in SEMANTIC_READ_ONLY_COMMANDS:
        if first == "sed" and " -i" in command:
            return CommandIntent.WRITE
        return CommandIntent.READ_ONLY

    if first in ALWAYS_DESTRUCTIVE_COMMANDS or first == "rm":
        return CommandIntent.DESTRUCTIVE

    if first in WRITE_COMMANDS:
        return CommandIntent.WRITE

    if first in NETWORK_COMMANDS:
        return CommandIntent.NETWORK

    if first in PROCESS_COMMANDS:
        return CommandIntent.PROCESS_MANAGEMENT

    if first in PACKAGE_COMMANDS:
        return CommandIntent.PACKAGE_MANAGEMENT

    if first in SYSTEM_ADMIN_COMMANDS:
        return CommandIntent.SYSTEM_ADMIN

    if first == "git":
        return _classify_git_command(command)

    return CommandIntent.UNKNOWN


def validate_command(
    command: str,
    mode: PermissionMode,
    workspace: Path,
) -> dict:
    # 1. Mode-level validation
    result = validate_mode(command, mode)
    if result["result"] != "allow":
        return result

    # 2. Sed validation
    result = validate_sed(command, mode)
    if result["result"] != "allow":
        return result

    # 3. Destructive validation
    result = check_destructive(command)
    if result["result"] != "allow":
        return result

    # 4. Path validation
    return validate_paths(command, workspace)
