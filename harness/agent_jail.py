"""CONTAIN C2: OS-level jail (bubblewrap) for agent subprocess spawns.

CWD relocation (``harness/paths.py``) and the §1b apply-scope gate are necessary
but not sufficient containment: an agent can still open an ABSOLUTE repo path and
write ``harness/*.py`` directly -- the GAP_H4 breach, where gemini's rejected
submission landed in ``harness/ast_retry.py`` despite a clean reject. This module
wraps the agent argv in ``bwrap`` so the repository is bind-mounted READ-ONLY: a
write to any tracked source file is denied by the kernel, not by a ``-p``-mode
hook that may not load.

Writable surfaces are minimised to exactly what a spawn legitimately needs:
  * the per-spawn ``work_dir`` (outbox submission + inbox staging),
  * ``<repo>/state`` (the hook ledger + lifecycle journal write here),
  * ``$HOME`` (agy registers ``~/.gemini/antigravity-cli/mcp_config.json``; the
    vendored node runtime lives under ``~/.nvm``; claude writes ``~/.claude``).
Everything else (``harness/*.py`` and all other tracked source) is read-only.

Config-gated via ``config.yaml`` ``agent_sandbox.bwrap`` and FAIL-CLOSED: if the
key is true but ``bwrap`` is not on PATH the spawn is ABORTED rather than silently
running an un-jailed agent. CONTAIN keeps the gate togglable so the mount set can
be tuned empirically (C6) without editing code.

Scope note: CONTAIN targets live-tree *tamper* (writing harness logic), not
exfiltration. ``--share-net`` is required (agents call model APIs) and HOME is
readable, so this jail is not an exfil boundary -- only a write boundary on the
repo source tree.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Iterable, Sequence

# Read-only system directories every CLI runtime needs. Missing ones are skipped.
_SYSTEM_RO = ("/usr", "/bin", "/sbin", "/lib", "/lib32", "/lib64", "/etc", "/opt")


def bwrap_available() -> bool:
    return shutil.which("bwrap") is not None


def sandbox_enabled(config: dict | None) -> bool:
    """True iff ``config['agent_sandbox']['bwrap']`` is truthy."""
    sb = (config or {}).get("agent_sandbox") or {}
    return bool(sb.get("bwrap", False))


def build_jail_argv(
    cmd: Sequence[str],
    *,
    repo_root: str | Path,
    work_dir: str | Path,
    state_dir: str | Path,
    home: str | Path | None = None,
    extra_ro: Iterable[str | Path] = (),
) -> list[str]:
    """Wrap ``cmd`` in a ``bwrap`` argv that makes ``repo_root`` read-only.

    Raises ``FileNotFoundError`` if ``bwrap`` is unavailable -- callers gate on
    :func:`sandbox_enabled` first, so reaching here without bwrap is a hard,
    fail-closed error (never a silent un-jailed spawn).
    """
    bwrap = shutil.which("bwrap")
    if bwrap is None:
        raise FileNotFoundError(
            "agent_sandbox.bwrap is enabled but 'bwrap' is not on PATH; refusing "
            "to spawn an un-jailed agent (fail-closed)."
        )
    repo_root = str(Path(repo_root).resolve())
    work_dir = str(Path(work_dir).resolve())
    state_dir = str(Path(state_dir).resolve())
    home = str(Path(home or os.environ.get("HOME", "/tmp")).resolve())

    # Namespace policy (C6-tuned, empirical): the repo-read-only guarantee comes
    # PURELY from the --ro-bind below, NOT from namespace unsharing (verified: a jail
    # with no --unshare-* still denies a write to the ro-bound repo). We deliberately
    # do NOT unshare any namespace -- both --unshare-all (via --unshare-user's UID
    # remap on the mode-600 ~/.gemini/oauth_creds.json) AND --unshare-pid drop the agy
    # (gemini CLI) into an interactive-OAuth loop ("authentication timed out"). The
    # mount namespace bwrap always creates is sufficient for the filesystem barrier;
    # net/ipc/pid/user stay shared so agy's credential read + token refresh and the
    # model-API calls work. CONTAIN's scope is live-tree tamper, not pid/net isolation.
    argv: list[str] = [
        bwrap,
        "--die-with-parent",
        "--proc", "/proc",
        "--dev", "/dev",
        "--tmpfs", "/tmp",
    ]
    for d in _SYSTEM_RO:
        if os.path.exists(d):
            argv += ["--ro-bind", d, d]
    # DNS under --share-net: /etc/resolv.conf is usually a symlink into /run
    # (systemd-resolved stub). /etc is bound above but the symlink TARGET dir is
    # not, so bind it explicitly or name resolution fails (model-API calls die).
    try:
        resolv = os.path.realpath("/etc/resolv.conf")
        rdir = os.path.dirname(resolv)
        if os.path.exists(resolv) and rdir and not rdir.startswith("/etc") and os.path.exists(rdir):
            argv += ["--ro-bind", rdir, rdir]
    except OSError:
        pass
    for d in extra_ro:
        d = str(d)
        if d and os.path.exists(d):
            argv += ["--ro-bind", d, d]
    # HOME writable FIRST so the later repo ro-bind overlays it (the repo lives
    # under HOME). Covers ~/.nvm node runtime, ~/.gemini, ~/.claude.
    if os.path.exists(home):
        argv += ["--bind", home, home]
    # XDG_RUNTIME_DIR (/run/user/<uid>): the D-Bus session bus + keyring socket live
    # here. agy (gemini CLI) validates/refreshes its OAuth credential through the
    # session keyring; without this bind it loops on "authentication timed out" even
    # though ~/.gemini/oauth_creds.json is readable. Bind writable (agy writes sockets).
    xdg = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    if os.path.isdir(xdg):
        argv += ["--bind", xdg, xdg]
    # The load-bearing barrier: repository source READ-ONLY.
    argv += ["--ro-bind", repo_root, repo_root]
    # state/ writable (overlays the ro repo bind) for the hook ledger + journal.
    if os.path.exists(state_dir):
        argv += ["--bind", state_dir, state_dir]
    # Per-spawn work_dir writable (outbox + inbox). Outside the repo tree.
    argv += ["--bind", work_dir, work_dir]
    argv += ["--chdir", work_dir, "--"]
    argv += list(cmd)
    return argv
