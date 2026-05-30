"""CONTAIN C2 — bwrap jail wraps agent spawns with the repo read-only.

Asserts the argv shape (repo ro-bind, work_dir + state rw-bind, cmd after --),
the config gate, fail-closed behaviour when bwrap is absent, and -- when a real
bwrap is present -- that a write to a ro-bound path is actually denied by the
kernel.
"""
from __future__ import annotations

import shutil
import subprocess

import pytest

import harness.agent_jail as aj


def _pairs(argv, flag):
    """All (src, dst) pairs following occurrences of ``flag`` in argv."""
    out = []
    for i, tok in enumerate(argv):
        if tok == flag and i + 2 < len(argv):
            out.append((argv[i + 1], argv[i + 2]))
    return out


def test_sandbox_enabled_gate():
    assert aj.sandbox_enabled({"agent_sandbox": {"bwrap": True}}) is True
    assert aj.sandbox_enabled({"agent_sandbox": {"bwrap": False}}) is False
    assert aj.sandbox_enabled({}) is False
    assert aj.sandbox_enabled(None) is False


def test_argv_repo_readonly_workdir_writable(tmp_path, monkeypatch):
    monkeypatch.setattr(aj.shutil, "which", lambda _x: "/usr/bin/bwrap")
    repo = tmp_path / "repo"
    state = repo / "state"
    work = tmp_path / "wr" / "claude" / "sess"
    home = tmp_path / "home"
    for d in (repo, state, work, home):
        d.mkdir(parents=True, exist_ok=True)

    argv = aj.build_jail_argv(
        ["/agent/bin", "-p", "do-it"],
        repo_root=repo, work_dir=work, state_dir=state, home=home,
    )

    assert argv[0] == "/usr/bin/bwrap"
    # Repo is read-only, NOT read-write.
    ro = _pairs(argv, "--ro-bind")
    rw = _pairs(argv, "--bind")
    assert (str(repo), str(repo)) in ro, "repo must be ro-bind"
    assert (str(repo), str(repo)) not in rw, "repo must NOT be writable"
    # CONTAIN C-HARDEN M-1: state/ is READ-ONLY; only state/sessions/ is writable.
    sessions = state / "sessions"
    assert (str(state), str(state)) in ro, "state root must be ro-bind (C-HARDEN M-1)"
    assert (str(state), str(state)) not in rw, "state root must NOT be rw (M-1)"
    assert (str(sessions), str(sessions)) in rw, "state/sessions must be rw (ledger + submission)"
    # work_dir is writable.
    assert (str(work), str(work)) in rw, "work_dir must be rw-bind"
    # No namespace unsharing: --unshare-all/--unshare-pid both break agy's OAuth
    # (cred read / token refresh). The mount-ns binds alone enforce repo-RO. chdir work_dir.
    assert "--unshare-all" not in argv, "must not --unshare-all (breaks agy OAuth cred read)"
    assert "--unshare-pid" not in argv, "must not --unshare-pid (breaks agy OAuth token refresh)"
    assert argv[argv.index("--chdir") + 1] == str(work)
    # The agent command is appended verbatim after the bwrap '--' terminator.
    dd = len(argv) - 1 - argv[::-1].index("--")
    assert argv[dd + 1:] == ["/agent/bin", "-p", "do-it"]


def test_fail_closed_when_bwrap_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(aj.shutil, "which", lambda _x: None)
    with pytest.raises(FileNotFoundError):
        aj.build_jail_argv(["x"], repo_root=tmp_path, work_dir=tmp_path,
                           state_dir=tmp_path)


@pytest.mark.skipif(shutil.which("bwrap") is None, reason="bwrap not installed")
def test_real_bwrap_denies_write_to_ro_repo(tmp_path):
    """A tiny real bwrap run: a write to the ro-bound repo must fail; a write to
    the rw-bound work_dir must succeed."""
    repo = tmp_path / "repo"
    state = repo / "state"
    work = tmp_path / "work"
    for d in (repo, state, work):
        d.mkdir(parents=True, exist_ok=True)
    (repo / "guarded.py").write_text("original\n")

    # Attempt to overwrite a ro-bound repo file -> must be denied.
    argv = aj.build_jail_argv(
        ["/bin/sh", "-c", f"echo tampered > {repo}/guarded.py"],
        repo_root=repo, work_dir=work, state_dir=state, home=tmp_path,
    )
    r = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    assert r.returncode != 0, "write to ro-bound repo must fail"
    assert (repo / "guarded.py").read_text() == "original\n", "repo file untouched"

    # A write to the rw-bound work_dir must succeed.
    argv_ok = aj.build_jail_argv(
        ["/bin/sh", "-c", f"echo ok > {work}/out.txt"],
        repo_root=repo, work_dir=work, state_dir=state, home=tmp_path,
    )
    r2 = subprocess.run(argv_ok, capture_output=True, text=True, timeout=30)
    assert r2.returncode == 0, f"write to work_dir must succeed: {r2.stderr}"
    assert (work / "out.txt").read_text().strip() == "ok"


@pytest.mark.skipif(shutil.which("bwrap") is None, reason="bwrap not installed")
def test_real_bwrap_M1_state_control_readonly_sessions_writable(tmp_path):
    """C-HARDEN M-1: under the jail, state/control/** (full_stop, allowlist,
    decisions self-approval) is READ-ONLY, but state/sessions/ (the hook ledger +
    canonical submission) is writable -- the only legitimate state write surface."""
    repo = tmp_path / "repo"
    state = repo / "state"
    control = state / "control" / "autowork"
    sessions = state / "sessions"
    work = tmp_path / "work"
    for d in (repo, control, sessions, work):
        d.mkdir(parents=True, exist_ok=True)
    (control / "full_stop").write_text("halted\n")

    # (i) overwrite state/control/.../full_stop (un-halt) -> DENIED
    argv = aj.build_jail_argv(
        ["/bin/sh", "-c", f"echo '' > {control}/full_stop"],
        repo_root=repo, work_dir=work, state_dir=state, home=tmp_path / "home",
    )
    r = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    assert r.returncode != 0, "un-halting full_stop must be denied (M-1)"
    assert (control / "full_stop").read_text() == "halted\n", "full_stop untouched"

    # (ii) append the FORBIDDEN EX_fix to auto_promote.allowlist -> DENIED
    argv2 = aj.build_jail_argv(
        ["/bin/sh", "-c", f"echo EX_fix >> {control}/auto_promote.allowlist"],
        repo_root=repo, work_dir=work, state_dir=state, home=tmp_path / "home",
    )
    r2 = subprocess.run(argv2, capture_output=True, text=True, timeout=30)
    assert r2.returncode != 0, "appending auto_promote.allowlist must be denied (M-1)"
    assert not (control / "auto_promote.allowlist").exists()

    # (iii) write the hook ledger under state/sessions/ -> ALLOWED
    argv3 = aj.build_jail_argv(
        ["/bin/sh", "-c", f"echo row > {sessions}/claude_x.ledger.jsonl"],
        repo_root=repo, work_dir=work, state_dir=state, home=tmp_path / "home",
    )
    r3 = subprocess.run(argv3, capture_output=True, text=True, timeout=30)
    assert r3.returncode == 0, f"write to state/sessions must succeed: {r3.stderr}"
    assert (sessions / "claude_x.ledger.jsonl").read_text().strip() == "row"


@pytest.mark.skipif(shutil.which("bwrap") is None, reason="bwrap not installed")
def test_real_bwrap_M2_claude_memory_readonly_rest_writable(tmp_path):
    """C-HARDEN M-2: under the jail, ~/.claude/projects/*/memory is READ-ONLY (an
    agent cannot poison the session-memory that steers future Claude runs), while
    the rest of ~/.claude stays writable (claude-code session/project state)."""
    repo = tmp_path / "repo"
    state = repo / "state"
    home = tmp_path / "home"
    proj = home / ".claude" / "projects" / "proj1"
    mem = proj / "memory"
    work = tmp_path / "work"
    for d in (repo, state, mem, work):
        d.mkdir(parents=True, exist_ok=True)
    (mem / "MEMORY.md").write_text("trusted\n")

    # (i) poison ~/.claude/.../memory/MEMORY.md -> DENIED
    argv = aj.build_jail_argv(
        ["/bin/sh", "-c", f"echo poison > {mem}/MEMORY.md"],
        repo_root=repo, work_dir=work, state_dir=state, home=home,
    )
    r = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    assert r.returncode != 0, "write to ~/.claude/.../memory must be denied (M-2)"
    assert (mem / "MEMORY.md").read_text() == "trusted\n", "memory untouched"

    # (ii) write a sibling under the SAME project dir (non-memory) -> ALLOWED
    argv2 = aj.build_jail_argv(
        ["/bin/sh", "-c", f"echo ok > {proj}/session.json"],
        repo_root=repo, work_dir=work, state_dir=state, home=home,
    )
    r2 = subprocess.run(argv2, capture_output=True, text=True, timeout=30)
    assert r2.returncode == 0, f"write to ~/.claude (non-memory) must succeed: {r2.stderr}"
    assert (proj / "session.json").read_text().strip() == "ok"


@pytest.mark.skipif(shutil.which("bwrap") is None, reason="bwrap not installed")
def test_real_bwrap_M2_unbound_home_subdir_denied(tmp_path):
    """C-HARDEN M-2: a HOME subdir that is NOT one of {.nvm,.gemini,.claude} is
    not bound at all -- e.g. the <repo>_agentwork residue or ~/.bashrc. A write to
    an unbound home path must fail (no mount exists)."""
    repo = tmp_path / "repo"
    state = repo / "state"
    home = tmp_path / "home"
    for d in (repo, state, home, tmp_path / "work"):
        d.mkdir(parents=True, exist_ok=True)
    work = tmp_path / "work"
    (home / ".bashrc").write_text("export X=1\n")
    argv = aj.build_jail_argv(
        ["/bin/sh", "-c", f"echo evil >> {home}/.bashrc"],
        repo_root=repo, work_dir=work, state_dir=state, home=home,
    )
    r = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    assert r.returncode != 0, "write to an unbound HOME path must fail (M-2)"
    assert (home / ".bashrc").read_text() == "export X=1\n"


def test_argv_planning_sessions_writable(tmp_path, monkeypatch):
    """C-HARDEN-2 CH2-2: state/planning/sessions/ joins state/sessions/ in the rw
    set; the state root and the state/planning root stay read-only."""
    monkeypatch.setattr(aj.shutil, "which", lambda _x: "/usr/bin/bwrap")
    repo = tmp_path / "repo"
    state = repo / "state"
    work = tmp_path / "wr" / "claude" / "sess"
    home = tmp_path / "home"
    for d in (repo, state, work, home):
        d.mkdir(parents=True, exist_ok=True)
    argv = aj.build_jail_argv(
        ["/agent/bin", "-p", "x"],
        repo_root=repo, work_dir=work, state_dir=state, home=home,
    )
    ro = _pairs(argv, "--ro-bind")
    rw = _pairs(argv, "--bind")
    sessions = state / "sessions"
    psessions = state / "planning" / "sessions"
    assert (str(sessions), str(sessions)) in rw, "state/sessions still rw (M-1)"
    assert (str(psessions), str(psessions)) in rw, "state/planning/sessions must be rw (CH2-2)"
    assert (str(state / "planning"), str(state / "planning")) not in rw, "planning root not rw"
    assert (str(state), str(state)) in ro, "state root ro"


@pytest.mark.skipif(shutil.which("bwrap") is None, reason="bwrap not installed")
def test_real_bwrap_CH2_3_global_cli_config_readonly(tmp_path):
    """C-HARDEN-2 CH2-3: ~/.claude/settings*.json, skills, plugins and
    ~/.gemini/GEMINI.md, config are ro-overlaid -- overwriting any of them would run
    operator-side code on the NEXT interactive session (stronger than the memory
    poisoning M-2 closed). The rest of ~/.claude stays writable."""
    repo = tmp_path / "repo"
    state = repo / "state"
    home = tmp_path / "home"
    claude = home / ".claude"
    gemini = home / ".gemini"
    skills = claude / "skills"
    plugins = claude / "plugins"
    gconfig = gemini / "config"
    work = tmp_path / "work"
    for d in (repo, state, skills, plugins, gconfig, work):
        d.mkdir(parents=True, exist_ok=True)
    (claude / "settings.json").write_text('{"hooks": {}}\n')
    (claude / "settings.local.json").write_text('{"local": true}\n')
    (skills / "s.md").write_text("trusted skill\n")
    (plugins / "p.json").write_text("{}\n")
    (gemini / "GEMINI.md").write_text("trusted gemini md\n")
    (gconfig / "settings.json").write_text("{}\n")

    for target, sh in (
        (claude / "settings.json", f"echo evil > {claude}/settings.json"),
        (claude / "settings.local.json", f"echo evil > {claude}/settings.local.json"),
        (skills / "s.md", f"echo evil > {skills}/s.md"),
        (plugins / "p.json", f"echo evil > {plugins}/p.json"),
        (gemini / "GEMINI.md", f"echo evil > {gemini}/GEMINI.md"),
        (gconfig / "settings.json", f"echo evil > {gconfig}/settings.json"),
    ):
        before = target.read_text()
        argv = aj.build_jail_argv(
            ["/bin/sh", "-c", sh],
            repo_root=repo, work_dir=work, state_dir=state, home=home,
        )
        r = subprocess.run(argv, capture_output=True, text=True, timeout=30)
        assert r.returncode != 0, f"overwriting {target} must be denied (CH2-3)"
        assert target.read_text() == before, f"{target} untouched"

    # A benign write elsewhere under ~/.claude (session/todo state) is ALLOWED.
    argv_ok = aj.build_jail_argv(
        ["/bin/sh", "-c", f"echo ok > {claude}/todos.json"],
        repo_root=repo, work_dir=work, state_dir=state, home=home,
    )
    r2 = subprocess.run(argv_ok, capture_output=True, text=True, timeout=30)
    assert r2.returncode == 0, f"benign ~/.claude write must succeed: {r2.stderr}"
    assert (claude / "todos.json").read_text().strip() == "ok"


@pytest.mark.skipif(shutil.which("bwrap") is None, reason="bwrap not installed")
def test_real_bwrap_CH2_2_planning_sessions_writable(tmp_path):
    """C-HARDEN-2 CH2-2: state/planning/sessions/ is writable (a jailed planning
    spawn persists its blind-draft / reconciliation there for the planner to read
    back), while the rest of state/planning/ stays read-only."""
    repo = tmp_path / "repo"
    state = repo / "state"
    planning = state / "planning"
    psessions = planning / "sessions"
    work = tmp_path / "work"
    for d in (repo, psessions, work):
        d.mkdir(parents=True, exist_ok=True)
    (planning / "policy.json").write_text("trusted\n")

    # (i) write under state/planning/ but NOT sessions/ -> DENIED (planning root ro)
    argv = aj.build_jail_argv(
        ["/bin/sh", "-c", f"echo evil > {planning}/policy.json"],
        repo_root=repo, work_dir=work, state_dir=state, home=tmp_path / "home",
    )
    r = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    assert r.returncode != 0, "write to state/planning root must be denied (CH2-2)"
    assert (planning / "policy.json").read_text() == "trusted\n"

    # (ii) write the canonical draft under state/planning/sessions/ -> ALLOWED
    argv2 = aj.build_jail_argv(
        ["/bin/sh", "-c", f"echo '{{}}' > {psessions}/claude_draft.json"],
        repo_root=repo, work_dir=work, state_dir=state, home=tmp_path / "home",
    )
    r2 = subprocess.run(argv2, capture_output=True, text=True, timeout=30)
    assert r2.returncode == 0, f"write to state/planning/sessions must succeed: {r2.stderr}"
    assert (psessions / "claude_draft.json").exists()


@pytest.mark.skipif(shutil.which("bwrap") is None, reason="bwrap not installed")
def test_real_bwrap_CH2_1_track_record_telemetry_denied(tmp_path):
    """C-HARDEN-2 CH2-1 (accepted telemetry loss, guarded): the global track-record
    book + the shadow-hook log stay READ-ONLY under the jail. Their hook writes are
    fail-open, so only telemetry pauses; a writable book would reopen a fabricated-
    event self-influence vector. This pins the decision against accidental
    re-widening."""
    repo = tmp_path / "repo"
    state = repo / "state"
    shadow = state / "hooks" / "shadow"
    work = tmp_path / "work"
    for d in (repo, shadow, work):
        d.mkdir(parents=True, exist_ok=True)
    (state / "track_record_events.jsonl").write_text("")
    for target, sh in (
        (state / "track_record_events.jsonl",
         f"echo '{{}}' >> {state}/track_record_events.jsonl"),
        (shadow / "s.jsonl", f"echo '{{}}' > {shadow}/s.jsonl"),
    ):
        argv = aj.build_jail_argv(
            ["/bin/sh", "-c", sh],
            repo_root=repo, work_dir=work, state_dir=state, home=tmp_path / "home",
        )
        r = subprocess.run(argv, capture_output=True, text=True, timeout=30)
        assert r.returncode != 0, f"telemetry write to {target} must be denied (CH2-1)"


@pytest.mark.skipif(shutil.which("bwrap") is None, reason="bwrap not installed")
def test_real_bwrap_claude_json_readable_but_readonly(tmp_path):
    """claude-jail-fix: $HOME/.claude.json (claude-code's PRIMARY config -- a HOME-root
    file the ~/.claude subdir bind misses) is bound READ-ONLY. It must be READABLE so
    the jailed claude can start (without it claude aborts "configuration file not found"
    -- the gap that broke every prior jailed claude probe), but NOT writable (the
    operator's project list + account state must not be poisoned)."""
    repo = tmp_path / "repo"
    state = repo / "state"
    home = tmp_path / "home"
    work = tmp_path / "work"
    for d in (repo, state, home, work):
        d.mkdir(parents=True, exist_ok=True)
    (home / ".claude.json").write_text('{"trusted": true}\n')

    # (i) readable inside the jail (claude must be able to load it)
    argv_r = aj.build_jail_argv(
        ["/bin/sh", "-c", f"cat {home}/.claude.json"],
        repo_root=repo, work_dir=work, state_dir=state, home=home,
    )
    r = subprocess.run(argv_r, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0 and "trusted" in r.stdout, (
        f"~/.claude.json must be readable inside the jail: {r.stderr}"
    )

    # (ii) writing it is DENIED (ro-bind -- no operator-config poisoning)
    argv_w = aj.build_jail_argv(
        ["/bin/sh", "-c", f"echo poison > {home}/.claude.json"],
        repo_root=repo, work_dir=work, state_dir=state, home=home,
    )
    r2 = subprocess.run(argv_w, capture_output=True, text=True, timeout=30)
    assert r2.returncode != 0, "writing ~/.claude.json must be denied (ro-bind)"
    assert (home / ".claude.json").read_text() == '{"trusted": true}\n'
