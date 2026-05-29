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
