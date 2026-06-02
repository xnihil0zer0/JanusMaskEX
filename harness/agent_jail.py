"""CONTAIN C2: OS-level jail (bubblewrap) for agent subprocess spawns.

CWD relocation (``harness/paths.py``) and the §1b apply-scope gate are necessary
but not sufficient containment: an agent can still open an ABSOLUTE repo path and
write ``harness/*.py`` directly -- the GAP_H4 breach, where gemini's rejected
submission landed in ``harness/ast_retry.py`` despite a clean reject. This module
wraps the agent argv in ``bwrap`` so the repository is bind-mounted READ-ONLY: a
write to any tracked source file is denied by the kernel, not by a ``-p``-mode
hook that may not load.

Writable surfaces are minimised to exactly what a spawn legitimately needs
(C-HARDEN M-1/M-2 narrowed these from the original whole-state / whole-HOME binds):
  * the per-spawn ``work_dir`` (outbox submission + inbox staging),
  * ``<repo>/state/sessions/`` (hook ledger + canonical submission record) AND
    ``<repo>/state/planning/sessions/`` (blind-draft / reconciliation drafts a jailed
    planning spawn persists and the planner reads back -- C-HARDEN-2 CH2-2). The rest
    of ``state/`` (``control/**`` full_stop/decisions/allowlist, ``tasks/**``) is
    READ-ONLY: the §1b commit-gate does not cover ``state/**``, so a writable state let
    an agent self-approve / un-halt / queue work via the FS. NOTE (CH2-1): the
    track-record book (``track_record_events.jsonl`` / ``track_record.lock``) and the
    shadow-hook log (``state/hooks/shadow/``) are deliberately ro -- those hook writes
    are fail-open, so this only pauses telemetry under the jail (accepted), and keeping
    them ro avoids a fabricated-event self-influence vector.
  * three HOME subdirs ONLY: ``~/.nvm`` (vendored node), ``~/.gemini`` (agy OAuth +
    antigravity-cli), ``~/.claude`` (claude state) -- with every
    ``~/.claude/projects/*/memory`` ro-overlaid so an agent cannot poison the
    session-memory that steers future Claude runs, AND (C-HARDEN-2 CH2-3) the global
    CLI config that runs operator-side code re-overlaid read-only:
    ``~/.claude/settings*.json`` (``hooks`` blocks), ``~/.claude/skills``,
    ``~/.claude/plugins``, ``~/.gemini/GEMINI.md``, ``~/.gemini/config``. The rest of
    ``$HOME`` is unbound.
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
    extra_rw: Iterable[str | Path] = (),
    dbus_proxy_socket: str | None = None,
    bind_credentials: bool = True,
) -> list[str]:
    """Wrap ``cmd`` in a ``bwrap`` argv that makes ``repo_root`` read-only.

    Raises ``FileNotFoundError`` if ``bwrap`` is unavailable -- callers gate on
    :func:`sandbox_enabled` first, so reaching here without bwrap is a hard,
    fail-closed error (never a silent un-jailed spawn).

    CRED-EXFIL (execute path): when ``bind_credentials`` is False the jail drops
    the entire credential surface -- the ``~/.gemini`` / ``~/.claude`` directory
    binds, the throwaway ``~/.claude.json`` copy/bind, the
    ``~/.claude/projects/*/memory`` overlays, and the sensitive global CLI config
    overlays (``settings*.json``, ``skills``, ``plugins``, ``GEMINI.md``,
    ``config``) are all skipped (only the ``~/.nvm`` ro-bind is kept so the node
    runtime resolves). The LOAD-BEARING control is ``--unshare-net`` (added with
    ``--unshare-ipc`` right after ``--die-with-parent``): with the network
    namespace unshared, any credential a jailed execute-path process can still
    read cannot be exfiltrated off-host. ``bind_credentials`` defaults to True so
    the synthesis path keeps every credential bind and the shared net/ipc
    namespaces (agents call model APIs and refresh OAuth) -- byte-for-byte the
    prior behavior.
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
    home = str(Path(home or os.environ.get("HOME", "/tmp")).resolve())  # home-free: allow (jail must bind the operator $HOME so agy ~/.gemini OAuth + ~/.nvm node runtime + ~/.claude resolve; deliberate, documented coupling per AGENT-ISOLATION §8)

    # Namespace policy (C6-tuned, empirical): the repo-read-only guarantee comes
    # PURELY from the --ro-bind below, NOT from namespace unsharing (verified: a jail
    # with no --unshare-* still denies a write to the ro-bound repo). On the SYNTHESIS
    # path we deliberately do NOT unshare any namespace -- both --unshare-all (via
    # --unshare-user's UID remap on the mode-600 ~/.gemini/oauth_creds.json) AND
    # --unshare-pid drop the agy (gemini CLI) into an interactive-OAuth loop
    # ("authentication timed out"). The mount namespace bwrap always creates is
    # sufficient for the filesystem barrier; net/ipc/pid/user stay shared so agy's
    # credential read + token refresh and the model-API calls work. CONTAIN's scope
    # is live-tree tamper, not pid/net isolation.
    #
    # CRED-EXFIL: the EXECUTE path (bind_credentials=False) does NOT call model APIs
    # or refresh OAuth, so it can -- and MUST -- unshare the network/IPC namespaces.
    # --unshare-net is the mandatory, load-bearing exfil control here (NOT optional):
    # the keyring/<xdg>/bus sockets and any residual credential reachable in the jail
    # become un-exfiltratable off-host once the network namespace is gone. Inserted
    # right after --die-with-parent so it brackets the whole spawn.
    argv: list[str] = [
        bwrap,
        "--die-with-parent",
    ]
    if not bind_credentials:
        argv += ["--unshare-net", "--unshare-ipc"]
    argv += [
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
    # SEC-5a: config-driven read-WRITE allowlist (agent_sandbox.verify_extra_rw,
    # threaded in by run_embedded_tests / the orchestrator verify path). Mirrors the
    # extra_ro loop above but emits a read-write --bind so a verify spawn can persist
    # into an explicitly-allowlisted host path. Non-existent or empty paths are
    # skipped gracefully -- a bind over an absent source would fail bwrap boot.
    for d in extra_rw:
        d = str(d)
        if d and os.path.exists(d):
            argv += ["--bind", d, d]
    # CONTAIN C-HARDEN M-2: bind ONLY the specific HOME subdirs an agent legitimately
    # needs writable -- NOT all of $HOME. Before this, the whole home was rw, so a
    # jailed agent could write the <repo>_agentwork workroot (poisoned-inbox residue)
    # or, crucially, ~/.claude/.../memory/*.md (which steers FUTURE Claude sessions).
    # Covers: ~/.nvm (vendored node runtime), ~/.gemini (agy OAuth + antigravity-cli),
    # ~/.claude (claude session/project state). Bound FIRST so the later repo ro-bind
    # overlays any overlap (the repo lives under HOME). (plan rev3.1 M-2 / R-CONTAIN-state/HOME)
    #
    # H_JAIL_A: ~/.nvm is a version-manager INSTALLATION directory -- node/agy read
    # the vendored runtime from it but never need to write under it at runtime. A
    # writable ~/.nvm is a node-wrapper host-hijack vector (an agent could overwrite a
    # shim/binary that later runs operator-side). Bind it READ-ONLY (--ro-bind) while
    # ~/.gemini and ~/.claude stay read-write (--bind) for credential refresh + cached
    # state writes. Missing subdirs are skipped gracefully.
    #
    # CRED-EXFIL: under bind_credentials=False (execute path) the ~/.gemini and
    # ~/.claude credential dirs are dropped entirely -- only ~/.nvm (the read-only
    # node runtime, needed for the interpreter, not a credential) is bound.
    _ro_home_subs = frozenset({".nvm"})
    _home_subs = (".nvm", ".gemini", ".claude") if bind_credentials else (".nvm",)
    for _sub in _home_subs:
        _hp = os.path.join(home, _sub)
        if os.path.exists(_hp):
            _mode = "--ro-bind" if _sub in _ro_home_subs else "--bind"
            argv += [_mode, _hp, _hp]
    # The credential-bearing HOME-root file + project-memory + global-config overlays
    # below are bound ONLY on the synthesis path. On the execute path
    # (bind_credentials=False) they are skipped -- the dir binds they overlay are gone
    # and --unshare-net closes the exfil surface regardless.
    if bind_credentials:
        # claude-code's PRIMARY config is ``$HOME/.claude.json`` -- a FILE at HOME root,
        # NOT under ``~/.claude/`` -- so the ``.claude`` subdir bind above does NOT cover
        # it. Without it the jailed claude aborts at startup ("Claude configuration file
        # not found at ~/.claude.json") and never submits -- the gap that made EVERY prior
        # jailed claude probe fail (M-2 narrowed HOME to subdirs and missed this root file).
        #
        # Phase J1: claude WRITES ~/.claude.json during a normal session (lastSessionId,
        # mcp cache, project bookkeeping, usage counters). A pure --ro-bind makes those
        # writes EROFS, which a full agentic run surfaces as a fatal "unable to update
        # config" abort -- exactly the "claude never actually finished" failure-class the
        # claude-jail-fix just closed, only deferred to mid-run. So instead of ro-binding
        # the operator's real file we COPY it into the per-spawn (outside-repo) work_dir
        # and rw-bind that THROWAWAY copy at ~/.claude.json inside the jail: the jailed
        # claude reads + freely writes its ephemeral copy, while the operator's real
        # ~/.claude.json stays byte-for-byte unchanged (no project-list / account
        # poisoning, no EROFS abort). The copy dies with the per-spawn work_dir (same GC
        # as outbox/inbox). No new exfil surface -- the OAuth credential is already
        # readable via ``~/.claude/.credentials.json``; this jail is a write boundary, not
        # an exfil one. Skipped gracefully if the operator file is absent; on copy failure
        # we fall back to the read-only bind so claude can at least start.
        _claude_json = os.path.join(home, ".claude.json")
        if os.path.exists(_claude_json):
            _claude_json_copy = os.path.join(work_dir, ".claude.json.jail")
            try:
                shutil.copyfile(_claude_json, _claude_json_copy)
                argv += ["--bind", _claude_json_copy, _claude_json]
            except OSError:
                argv += ["--ro-bind", _claude_json, _claude_json]
        # Protect the operator session-memory store: ro-overlay every
        # ~/.claude/projects/*/memory (rw-bound just above) so a jailed agent cannot
        # poison the memory files that steer future Claude sessions. The rest of each
        # project dir stays writable (claude-code writes its own session/todo state).
        _claude_projects = os.path.join(home, ".claude", "projects")
        try:
            if os.path.isdir(_claude_projects):
                for _proj in sorted(os.listdir(_claude_projects)):
                    _mem = os.path.join(_claude_projects, _proj, "memory")
                    if os.path.isdir(_mem):
                        argv += ["--ro-bind", _mem, _mem]
        except OSError:
            pass
        # CONTAIN C-HARDEN-2 CH2-3: the ~/.claude / ~/.gemini rw binds above leave the
        # operator's GLOBAL CLI configuration writable. ~/.claude/settings.json &
        # settings.local.json each carry a `hooks` block whose `command` executes on the
        # operator's NEXT interactive Claude-Code session; ~/.claude/skills, .../plugins,
        # ~/.gemini/GEMINI.md and ~/.gemini/config likewise steer future operator runs.
        # A jailed agent overwriting any of these is STRICTLY MORE dangerous than the
        # ~/.claude/.../memory poisoning M-2 closed -- it runs operator-side code, not just
        # bias text. ro-overlay each (mirroring the memory overlay; later binds win). The
        # rest of ~/.claude / ~/.gemini stays writable (the CLIs write session/todo/oauth
        # state). Missing paths are skipped. (plan rev4 CH2-3 / R-CH2-3 -- Phase-A precond)
        #
        # H-JAIL_B: a missing sensitive overlay path is STILL a hole -- without an explicit
        # bind it lives inside the writable ~/.claude / ~/.gemini parent, so a jailed agent
        # could CREATE it (e.g. write a fresh settings.json hooks block) and steer the
        # operator's next session. ro-bind /dev/null over each ABSENT target whose parent
        # is a real host directory: bwrap creates the mountpoint as a /dev/null-backed file
        # that denies creating the path, replacing it (EBUSY on unlink), and -- for the
        # dir-shaped targets -- creating any child inside it (ENOENT). One uniform
        # --ro-bind /dev/null handles both file- and dir-shaped absent targets. If the
        # parent dir is absent on the host, skip entirely (a bind would fail bwrap boot).
        for _ro in (
            os.path.join(home, ".claude", "settings.json"),
            os.path.join(home, ".claude", "settings.local.json"),
            os.path.join(home, ".claude", "skills"),
            os.path.join(home, ".claude", "plugins"),
            os.path.join(home, ".gemini", "GEMINI.md"),
            os.path.join(home, ".gemini", "config"),
        ):
            if os.path.exists(_ro):
                argv += ["--ro-bind", _ro, _ro]
            elif os.path.isdir(os.path.dirname(_ro)):
                argv += ["--ro-bind", "/dev/null", _ro]
    # XDG_RUNTIME_DIR (/run/user/<uid>): the D-Bus session bus + keyring socket live
    # here. agy (gemini CLI) validates/refreshes its OAuth credential through the
    # session keyring; without these the auth loops on "authentication timed out".
    #
    # H-JAIL_C: binding the ENTIRE XDG_RUNTIME_DIR read-write exposes the systemd user
    # PRIVATE socket (and every other live runtime socket) to the jailed agent -- a
    # containment-escape vector (the agent can talk to the user's systemd manager,
    # start transient units / scopes outside the jail). Instead mount a fresh TMPFS
    # over XDG_RUNTIME_DIR so the dir resolves but is EMPTY, then rw-bind back ONLY the
    # minimal sockets/dirs agy's OAuth needs: the session bus (``<xdg>/bus``) and the
    # keyring (``<xdg>/keyring``). Each is bound only if it exists on the host;
    # otherwise it is skipped (a bind over an absent source would fail bwrap boot).
    xdg = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    if os.path.isdir(xdg):
        argv += ["--tmpfs", xdg]
        for _xdg_sub in ("bus", "keyring"):
            _xp = os.path.join(xdg, _xdg_sub)
            if _xdg_sub == "bus" and dbus_proxy_socket is not None:
                # SEC-1b: when a dbus proxy socket is supplied, bind THAT mediated
                # socket at the in-jail ``<xdg>/bus`` path instead of the host's real
                # session bus -- the jailed agent talks only to the filtering proxy.
                argv += ["--bind", dbus_proxy_socket, _xp]
            elif os.path.exists(_xp):
                argv += ["--bind", _xp, _xp]
        # SEC-1: when the filtering D-Bus proxy socket is in play, point the jailed
        # agent's DBUS_SESSION_BUS_ADDRESS at the in-jail ``<xdg>/bus`` (where the
        # mediated socket is bound just above) -- never at the host's real session bus.
        # In default mode (dbus_proxy_socket is None) no override is emitted, so the
        # host DBUS_SESSION_BUS_ADDRESS passes through unchanged.
        if dbus_proxy_socket is not None:
            argv += ["--setenv", "DBUS_SESSION_BUS_ADDRESS", "unix:path=" + os.path.join(xdg, "bus")]
    # The load-bearing barrier: repository source READ-ONLY.
    argv += ["--ro-bind", repo_root, repo_root]
    # CONTAIN C-HARDEN M-1: state/ is READ-ONLY except state/sessions/ (the hook
    # ledger state/sessions/<agent>_<sid>.ledger.jsonl + the canonical submission
    # record -- the ONLY paths a jailed agent / its in-jail PreToolUse+PostToolUse
    # hooks write under state). This denies a jailed agent writing state/control/**
    # (full_stop, decisions/<id>.json self-approval, auto_promote.allowlist) or
    # state/tasks/** (another task's spec) -- the §1b commit-gate does NOT cover
    # state/**, so before this an agent could self-approve / un-halt / queue work
    # purely via the filesystem. The trusted worker (OUTSIDE the jail) still writes
    # control/tasks/impl_progress.jsonl. (plan rev3.1 M-1 / R-CONTAIN-state/HOME)
    if os.path.exists(state_dir):
        argv += ["--ro-bind", state_dir, state_dir]
        # state/ is ro EXCEPT these two subtrees -- the only paths a jailed agent /
        # its in-jail hooks legitimately write:
        #   * state/sessions/ -- the hook ledger + canonical submission record (M-1).
        #   * state/planning/sessions/ -- the blind-draft / reconciliation JSON a jailed
        #     PLANNING spawn's PostToolUse persists; the planner READS these back
        #     (blind_draft / adversarial_review), so without this jailed planning
        #     silently yields an empty draft. (plan rev4 CH2-2 -- Phase-B precond)
        # CH2-1 (decision: ACCEPT telemetry loss): state/track_record_events.jsonl,
        # state/track_record.lock and state/hooks/shadow/ are deliberately LEFT ro --
        # their hook writes are fail-open (submit_code._emit_synthesis_event /
        # hooks_equivalence.maybe_record_shadow swallow the EROFS), so synthesis is
        # unaffected; only telemetry recording pauses during a jailed run. No
        # synthesis-path gate consumes the global track-record book, and rw-overlaying
        # it would reopen a filesystem self-influence vector (fabricated authorship
        # events skewing planner weighting) of exactly the class M-1 closed. Keeping
        # them ro holds the writable surface minimal -- the thesis of this phase.
        # Pre-created so --bind has a mountpoint; later binds overlay the state ro.
        for _rw in (
            os.path.join(state_dir, "sessions"),
            os.path.join(state_dir, "planning", "sessions"),
        ):
            try:
                os.makedirs(_rw, exist_ok=True)
            except OSError:
                pass
            if os.path.isdir(_rw):
                argv += ["--bind", _rw, _rw]
    # Per-spawn work_dir writable (outbox + inbox). Outside the repo tree.
    argv += ["--bind", work_dir, work_dir]
    argv += ["--chdir", work_dir, "--"]
    argv += list(cmd)
    return argv
