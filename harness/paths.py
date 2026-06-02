"""Canonical path constants for the JanusMask project tree.

Derived at import time from ``__file__`` so the harness is portable
across checkouts and hosts. Use these constants instead of hardcoding
``/home/xnihil0zer0/JanusMask/...`` anywhere in ``harness/*.py`` or
``harness/config.yaml``.

String variants (``*_STR``) are provided for callers that need to
interpolate into YAML/JSON or compare against ``str``-typed ledger rows.
"""
from __future__ import annotations

import os
from pathlib import Path

HARNESS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = HARNESS_DIR.parent
CONFIG_DIR = PROJECT_ROOT / "config"
STATE_DIR = PROJECT_ROOT / "state"

HARNESS_DIR_STR = str(HARNESS_DIR)
PROJECT_ROOT_STR = str(PROJECT_ROOT)
CONFIG_DIR_STR = str(CONFIG_DIR)
STATE_DIR_STR = str(STATE_DIR)


def agent_workroot() -> Path:
    """Root directory for per-agent isolated workdirs, OUTSIDE the repo tree.

    AGENT-ISOLATION §3.1: agents are launched with ``cwd=<their workdir>``
    under this root so (a) ``git`` cannot auto-discover the repo's ``.git`` by
    walking up from CWD and (b) bare *relative* paths (``harness/orchestrator.py``)
    no longer resolve into the live source tree. This is a *necessary but not
    sufficient* barrier — it is NOT a filesystem jail (an agent can still open
    an absolute repo path). The authoritative apply-time barrier is the §1b
    target-scoping in ``harness/git_integration.py``.

    Derived from ``PROJECT_ROOT`` (the real repo, fixed at import from
    ``__file__``) — NOT from any caller-supplied ``state_dir``. Planning spawns
    pass per-agent session dirs as ``state_dir`` (the ``_PerAgentConfig``
    trick), so a state-dir-relative root would land *inside* the repo and
    silently break isolation. Anchoring on ``PROJECT_ROOT`` also guarantees
    every spawn site and every workdir consumer (the orchestrator, both
    ``autowork_daemon`` self-heal spawns, the ``harness.hooks._env`` fallback,
    ``impl_outbox_watcher``, ``planner.blind_draft`` and ``_collect_traceback``)
    compute the SAME root and never disagree about where a submission landed.

    Override with ``$JANUSMASK_AGENT_WORKROOT`` (absolute path; used by tests so
    a tmp run does not pollute the real sibling dir).
    """
    raw = os.environ.get("JANUSMASK_AGENT_WORKROOT")
    if raw:
        # NOTE: deliberately NOT expanduser() — the override must be an absolute
        # path (keeps harness/ Path.home()-free for clone portability).
        resolved = Path(raw).resolve()
        # GAP_H3: fail-closed if the override re-anchors agent workdirs INSIDE the
        # repo. CWD relocation is the *primary* containment after the isolation
        # fix; an inside-repo override — or a relative one, which .resolve()s
        # against CWD and lands in the repo when launched from the repo root —
        # silently defeats Layer A for ALL THREE spawn sites at once. A
        # misconfigured isolation root must abort the spawn, not weaken it.
        if resolved == PROJECT_ROOT or PROJECT_ROOT in resolved.parents:
            raise ValueError(
                f"JANUSMASK_AGENT_WORKROOT={raw!r} resolves to {resolved}, which is "
                f"inside the repo ({PROJECT_ROOT}). The agent workroot MUST be an "
                f"absolute path OUTSIDE the repo tree, or CWD-relocation containment "
                f"is silently defeated (AGENT-ISOLATION §3.1 / GAP_H3)."
            )
        return resolved
    return PROJECT_ROOT.parent / f"{PROJECT_ROOT.name}_agentwork"


def _target_is_self(working_dir: str | os.PathLike | None=None) -> bool:
    """Classify whether ``working_dir`` refers to the harness/repo itself.

    Returns ``True`` (fail-safe / fail-closed) when ``working_dir`` is
    absent, when it resolves to the repo, a parent of it, a subdirectory
    of it (e.g. a symlink to ``harness/``), or anywhere inside ``STATE_DIR``
    or ``agent_workroot()``. Any error during resolution or comparison also
    classifies as self so traversal and symlink escapes fail closed.
    """
    if not working_dir:
        return True
    try:
        resolved = Path(working_dir).resolve()
        project_root = PROJECT_ROOT.resolve()
        if resolved == project_root:
            return True
        if resolved in project_root.parents:
            return True
        if project_root in resolved.parents:
            return True
        state_dir = STATE_DIR.resolve()
        if resolved == state_dir or state_dir in resolved.parents:
            return True
        workroot = agent_workroot().resolve()
        if resolved == workroot or workroot in resolved.parents:
            return True
        return False
    except (OSError, ValueError, RuntimeError, Exception):
        return True

def relax_external_for(task: dict, content: str | None=None) -> bool:
    """Shared predicate gating whether external constructs (eval/exec/
    ``__import__``) are relaxed at submit/commit time.

    RELAX_PREDICATE: closes the CRITICAL self-target bypass where a
    ``working_dir``-only check (``not _target_is_self(...)``) relaxed AST
    validation even when the *targets* the submission would overwrite
    actually resolve back INSIDE ``PROJECT_ROOT``. The predicate now also
    inspects the resolved target set so an external workdir cannot smuggle
    an inside-repo write past the relaxed gate.

    Returns ``True`` if and only if ``working_dir`` is non-self AND every
    resolved target path lands strictly OUTSIDE ``PROJECT_ROOT``. Fail-closed
    (returns ``False``) when ``working_dir`` is absent/self, when the target
    set is empty, or when any target path is unresolvable.

    The target set is built from ``task['files_touched']`` (when a list),
    ``task.get('target_file')`` (when present), and the relative keys of any
    ``__JANUSMASK_MANIFEST__`` dict assignment found in ``content`` (parsed
    via ``ast``; unparseable content falls back to ``files_touched`` only).
    Absolute targets resolve directly; relative targets resolve against
    ``effective_target_root(working_dir)``.

    Lazy in-body ``ast`` import (no new module-level imports per the
    paths.py clone-portability constraint).
    """
    import ast as _ast
    working_dir = task.get('working_dir')
    if _target_is_self(working_dir):
        return False
    root = effective_target_root(working_dir)
    targets: list[str] = []
    files_touched = task.get('files_touched')
    if isinstance(files_touched, list):
        targets.extend((str(f) for f in files_touched))
    target_file = task.get('target_file')
    if target_file:
        targets.append(str(target_file))
    if content:
        try:
            tree = _ast.parse(content)
        except (SyntaxError, ValueError):
            tree = None
        if tree is not None:
            for node in tree.body:
                if not isinstance(node, _ast.Assign):
                    continue
                if len(node.targets) != 1:
                    continue
                tgt = node.targets[0]
                if not isinstance(tgt, _ast.Name) or tgt.id != '__JANUSMASK_MANIFEST__':
                    continue
                if not isinstance(node.value, _ast.Dict):
                    continue
                for key in node.value.keys:
                    if isinstance(key, _ast.Constant) and isinstance(key.value, str):
                        targets.append(key.value)
    if not targets:
        return False
    try:
        project_root = PROJECT_ROOT.resolve()
        for raw in targets:
            candidate = Path(raw)
            if candidate.is_absolute():
                resolved = candidate.resolve()
            else:
                resolved = (Path(root) / candidate).resolve()
            if resolved == project_root or project_root in resolved.parents:
                return False
    except (OSError, ValueError, RuntimeError, Exception):
        return False
    return True
def effective_target_root(working_dir: str | os.PathLike | None=None) -> Path:
    """Normalize ``working_dir`` to an effective target root.

    Returns ``PROJECT_ROOT`` when ``working_dir`` classifies as self,
    otherwise the resolved external path. Falls back to ``PROJECT_ROOT``
    on any error.
    """
    if _target_is_self(working_dir):
        return PROJECT_ROOT
    try:
        return Path(working_dir).resolve()
    except (OSError, ValueError, RuntimeError, Exception):
        return PROJECT_ROOT
def agent_work_dir(agent: str, session_slug: str) -> Path:
    """Per-spawn isolated workdir: ``<agent_workroot>/<agent>/<session_slug>``."""
    return agent_workroot() / agent / session_slug


__all__ = [
    "HARNESS_DIR",
    "PROJECT_ROOT",
    "CONFIG_DIR",
    "STATE_DIR",
    "HARNESS_DIR_STR",
    "PROJECT_ROOT_STR",
    "CONFIG_DIR_STR",
    "STATE_DIR_STR",
    "agent_workroot",
    "agent_work_dir",
]
