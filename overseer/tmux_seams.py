"""Real seam construction for the claude-tmux backend.

This module builds the REAL injected seams that ``run_tmux_turn`` consumes,
plus the per-conversation ``CLAUDE_CONFIG_DIR`` isolation that makes parallel
claude-tmux agents safe. Every agent gets a private ``~/.claude`` tree seeded
with just the auth/config files it needs, kept OUTSIDE the repo so concurrent
conversations never clobber one another.

Stdlib only (os, time, subprocess, pathlib). All real I/O lives inside the
returned callables -- construction performs no subprocess, network, or model
work.
"""
from __future__ import annotations
import os
import subprocess
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple
__all__ = ['safe', 'overseer_config_dir', 'config_seed_plan', 'seed_config_dir', 'build_interactive_argv', 'make_tmux_seams']

def safe(cid: str) -> str:
    """Sanitise a conversation id to a filesystem-safe leaf.

    Any character not an ASCII alphanumeric, ``-``, or ``_`` becomes ``_``,
    so the result can never escape its parent dir (``/``, ``.``, spaces, etc.
    are all neutralised).
    """
    return ''.join((c if c.isalnum() or c in '-_' else '_' for c in str(cid)))

def overseer_config_dir(repo_root, cid: str) -> Path:
    """Per-cid ``CLAUDE_CONFIG_DIR`` OUTSIDE the repo.

    ``repo.parent / '<repo>_agentwork' / 'overseer_cfg' / safe(cid)`` -- a
    sibling of the agent work dir, namespaced by cid so distinct conversations
    get distinct, isolated config trees.
    """
    repo = Path(repo_root)
    return repo.parent / f'{repo.name}_agentwork' / 'overseer_cfg' / safe(cid)

def config_seed_plan(home) -> List[Tuple[str, str]]:
    """The small auth/config set a fresh ``CLAUDE_CONFIG_DIR`` needs.

    Returns the three ``(src, dst-name)`` pairs -- ``.credentials.json`` and
    ``settings.json`` from ``~/.claude``, and the big top-level
    ``~/.claude.json`` -- NOT the whole tree (no ``projects`` cache).
    """
    home_s = str(home)
    return [(os.path.join(home_s, '.claude', '.credentials.json'), '.credentials.json'), (os.path.join(home_s, '.claude', 'settings.json'), 'settings.json'), (os.path.join(home_s, '.claude.json'), '.claude.json')]

def seed_config_dir(config_dir, *, home, copy: Callable[[str, str], object], exists: Callable[[str], bool], makedirs: Callable[[str], object]) -> List[str]:
    """Idempotently seed ``config_dir`` with the auth/config files.

    For each ``(src, dst)`` in :func:`config_seed_plan`, if ``src`` exists and
    its destination does not yet exist, create ``config_dir`` via the injected
    ``makedirs`` seam and copy it across. Never guards on whether
    ``config_dir`` already exists -- a needed copy always creates it first.
    Copies only existing sources whose dst is absent (idempotent), and returns
    the copied dst names.
    """
    copied: List[str] = []
    for src, dst in config_seed_plan(home):
        full = os.path.join(str(config_dir), dst)
        if exists(src) and (not exists(full)):
            makedirs(str(config_dir))
            copy(src, full)
            copied.append(dst)
    return copied

def build_interactive_argv(claude_bin, config_dir, *, model: Optional[str]=None, tools: Optional[Sequence[str]]=None, system_prompt: Optional[str]=None, session_id: Optional[str]=None, skip_permissions: bool=True) -> List[str]:
    """Build the INTERACTIVE claude argv (env-prefixed, never headless).

    ``['env', 'CLAUDE_CONFIG_DIR=<dir>', '<bin>', ...]`` threading
    ``--model`` / ``--tools`` (comma-joined) / ``--append-system-prompt`` /
    ``--resume`` when given, plus ``--dangerously-skip-permissions``. The
    cost-billed headless flags (``-p`` / ``--print`` / ``--output-format``)
    are NEVER emitted.
    """
    argv: List[str] = ['env', f'CLAUDE_CONFIG_DIR={config_dir}', str(claude_bin)]
    if model:
        argv += ['--model', str(model)]
    if tools:
        argv += ['--tools', ','.join((str(t) for t in tools))]
    if system_prompt:
        argv += ['--append-system-prompt', str(system_prompt)]
    if session_id:
        argv += ['--resume', str(session_id)]
    if skip_permissions:
        argv.append('--dangerously-skip-permissions')
    return argv

def make_tmux_seams(*, config: dict, repo_root, cid: str, work_dir, state_dir, timeout: int=600) -> Dict[str, object]:
    """Bundle the real callables + derived ``config_dir`` / ``session``.

    All real I/O lives inside the returned callables; nothing runs at
    construction time.
    """

    def tmux_exec(argv: Sequence[str]) -> str:
        return subprocess.run(list(argv), capture_output=True, text=True, timeout=timeout).stdout

    def sleep(seconds: float) -> None:
        time.sleep(seconds)

    def read_text(path) -> str:
        return Path(path).read_text(encoding='utf-8', errors='replace')

    def list_dir(path) -> List[str]:
        try:
            return os.listdir(path)
        except OSError:
            return []
    return {'tmux_exec': tmux_exec, 'sleep': sleep, 'read_text': read_text, 'list_dir': list_dir, 'config_dir': str(overseer_config_dir(repo_root, cid)), 'session': f'ovr_{safe(cid)}'}