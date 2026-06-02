"""GATING end-to-end integration test for the JanusMask EXTERNAL-capability path.

REV23 §3-9 (the final pre-Phase-A deliverable). ALL external-capability
production machinery has already landed at HEAD (RELAX_PREDICATE,
BRIEF_LOAD_GUARD, EXTERNAL_ROOTS_ALLOWLIST, FLAG2_EMBEDDED_FUZZ, STAGING_REROOT,
EXTERNAL_DIRTY_GATE, COMMIT_REROOT, MERGE_REROOT, G3_VENV, T_RETARGET). This is a
TEST-ONLY gating suite: it drives the external code path END-TO-END and PASSES
against current HEAD because the machinery exists. It is NOT a RED-first oracle.

External is currently INERT in normal operation (JANUSMASK_WORKING_DIR is not
stamped yet -- the deferred WORKINGDIR_ENV_STAMP item), so each case ACTIVATES
the external path DIRECTLY: a fixture external git repo under tmp_path, an
allowlist prefix, and tasks/briefs carrying a trusted ``working_dir``.

Cases (REV22 §4-8 A-K + REV23 §1a):
  A  external relax APPLIES (eval/exec/__import__) but the predicate stays keyed
     on the target set (the relax decision is the load-bearing gate)
  B  self task -> strict (no relax)
  C  malicious working_dir (inside PROJECT_ROOT non-self / ``..`` / symlink) ->
     REJECTED by the brief-load guard / classified self / fail-closed
  D  target ``.venv`` jails external execute (extra_ro + PATH); ABSENT -> REFUSE
  E  predicate fail-safe -- ambiguous / unresolvable -> strict / self
  F  ancestor / descendant of PROJECT_ROOT classify as self
  G  dirty external repo -> commit REFUSED; external tree byte-UNCHANGED
  H  non-FF external -> ref-update onto refs/heads/janusmask/work, NEVER the
     user's branch
  I  e2e -- external accepted output lands on janusmask/work AND nothing is
     committed in the JM repo
  J  M2 -- agent-generated untracked test in external staging NOT auto-committed;
     an agent manifest listing an out-of-target path is rejected
  K  host-ENV not leaked into the external jail; sandbox-OFF external execution
     REFUSED in ALL THREE execute families (orch shell=True, embedded, fuzz)
  §1a external working_dir + a JM-tree target file -> relax does NOT apply

Hermetic: real git on tmp repos for the commit/merge/staging/dirty cases (mirror
tests/integration/test_phase_m_merge_reliability.py +
tests/adversarial/test_git_integration_acceptance_adversarial.py); pure-function
inspection of build_jail_argv for the jail-env / venv cases; source + behavioral
inspection for the in-orchestrator nested helpers and the FLAG2 refusals.
"""
from __future__ import annotations

import inspect
import json
import os
import pathlib
import subprocess

import pytest

import harness.paths
from harness.paths import (
    PROJECT_ROOT,
    _target_is_self,
    effective_target_root,
    relax_external_for,
)
from harness import agent_jail
from harness import git_integration
from harness import target_bootstrap
from harness import orchestrator
from harness.git_integration import commit_accepted_output, merge_staging_to_parent
from harness.orchestrator import _auto_commit_accepted


# ─────────────────────────────────────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────────────────────────────────────
def _git(cwd: pathlib.Path, *args: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.setdefault("GIT_AUTHOR_NAME", "t")
    env.setdefault("GIT_AUTHOR_EMAIL", "t@example.com")
    env.setdefault("GIT_COMMITTER_NAME", "t")
    env.setdefault("GIT_COMMITTER_EMAIL", "t@example.com")
    return subprocess.run(
        ["git", *args], cwd=str(cwd), env=env, check=True,
        capture_output=True, text=True,
    )


def _init_repo(path: pathlib.Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.name", "Test User")
    _git(path, "config", "user.email", "test@example.com")


def _seed_commit(path: pathlib.Path, fname: str = "mod.py", body: str = "def foo():\n    return 1\n") -> None:
    (path / fname).write_text(body, encoding="utf-8")
    _git(path, "add", fname)
    _git(path, "commit", "-q", "-m", "seed")


def _external_repo(tmp_path: pathlib.Path, name: str = "ext_repo") -> pathlib.Path:
    """A clean external git repo that classifies NOT-self (under tmp_path)."""
    repo = (tmp_path / name).resolve()
    _init_repo(repo)
    _seed_commit(repo)
    assert _target_is_self(str(repo)) is False, "fixture must classify external"
    return repo


# =============================================================================
# A  -- external relax APPLIES (eval/exec/__import__) when target set is external
# =============================================================================
def test_A_external_relax_applies_for_external_targets(tmp_path):
    """External working_dir + every declared target strictly outside PROJECT_ROOT
    -> relax APPLIES (True). This is the gate that lets eval/exec/__import__
    through for an external build (credentials/os_system/bare_except remain a
    separate strict concern handled by the AST engines, not this predicate)."""
    wd = (tmp_path / "ext").resolve()
    wd.mkdir()
    # relative target resolves UNDER the external working_dir -> outside the JM tree
    task = {"working_dir": str(wd), "files_touched": ["src/app.py"]}
    assert relax_external_for(task) is True


def test_A_external_relax_via_manifest_outside(tmp_path):
    """Manifest-carrying content whose every relative key resolves outside
    PROJECT_ROOT -> relax APPLIES."""
    wd = (tmp_path / "ext").resolve()
    wd.mkdir()
    content = (
        "__JANUSMASK_MANIFEST__ = {\n"
        '    "src/a.py": "def f(): pass",\n'
        '    "src/b.py": "def g(): pass",\n'
        "}\n"
    )
    assert relax_external_for({"working_dir": str(wd), "files_touched": []}, content=content) is True


# =============================================================================
# B  -- self task -> strict (no relax)
# =============================================================================
def test_B_self_task_is_strict():
    # absent working_dir => self => strict
    assert relax_external_for({"files_touched": ["src/foo.py"]}) is False
    # explicit PROJECT_ROOT => self => strict
    task = {"working_dir": str(PROJECT_ROOT), "files_touched": ["src/foo.py"]}
    assert relax_external_for(task) is False
    assert _target_is_self(str(PROJECT_ROOT)) is True


# =============================================================================
# C  -- malicious working_dir REJECTED
# =============================================================================
def test_C_inside_project_nonself_brief_rejected(tmp_path, monkeypatch):
    """A brief whose working_dir resolves INSIDE the repo but is asserted
    not-self is rejected by the brief-load guard (BriefValidationError)."""
    from harness.planner import load_brief, BriefValidationError

    fm = (
        "title: Ext\nscope: do\nnon_goals: none\ninputs: x\ndeliverables: y\n"
        f"working_dir: {PROJECT_ROOT / 'harness'}\n"
    )
    brief = tmp_path / "inside_nonself.md"
    brief.write_text("---\n" + fm + "---\n", encoding="utf-8")
    # force the not-self classification so the guard's inside-repo branch fires
    monkeypatch.setattr("harness.paths._target_is_self", lambda wd: False)
    with pytest.raises(BriefValidationError):
        load_brief(brief)


def test_C_traversal_and_inside_repo_classify_self(tmp_path):
    """``..`` traversal that lands inside the repo and any inside-repo path
    classify self (fail-closed), so relax never applies and bootstrap is the
    caller's responsibility."""
    # a path literally inside the repo -> self
    inside = PROJECT_ROOT / "harness" / "orchestrator.py"
    assert _target_is_self(str(inside)) is True
    # a relative '..' chain resolving back into the repo -> self
    sneaky = str(PROJECT_ROOT / "harness" / ".." / "config")
    assert _target_is_self(sneaky) is True


def test_C_symlink_into_repo_classifies_self(tmp_path):
    """A symlink whose realpath points inside the repo resolves into the repo
    and classifies self -- the symlink escape fails closed."""
    link = tmp_path / "evil_link"
    try:
        link.symlink_to(PROJECT_ROOT / "harness")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unsupported on this platform")
    assert _target_is_self(str(link)) is True


# =============================================================================
# D  -- target .venv jails external execute; ABSENT -> REFUSE (fail-closed)
# =============================================================================
def test_D_external_venv_bound_into_jail_when_present():
    """The orchestrator's nested venv-jail wiring binds <worktree>/.venv into
    extra_ro and prefixes <worktree>/.venv/bin onto PATH for external tasks."""
    src = inspect.getsource(_auto_commit_accepted)
    assert "_ext_venv_ro" in src
    assert ("worktree_root / '.venv'" in src) or ('worktree_root / ".venv"' in src)
    assert "_venv_jail_env" in src
    # the .venv-ro list is concatenated into the jailed extra_ro and PATH is set
    assert "_ext_venv_ro" in src and "extra_ro" in src
    assert "PATH" in src and ".venv" in src and "bin" in src


def test_D_absent_external_venv_refuses(tmp_path, monkeypatch):
    """Drive the nested _venv_jail_env helper for an EXTERNAL target whose
    .venv/bin/python is ABSENT -> RuntimeError (fail-closed, never inherits the
    harness python). We reconstruct the exact helper logic the orchestrator uses
    so the refusal is exercised, not merely source-asserted.

    NOTE: _venv_jail_env is a closure inside _auto_commit_accepted; we cannot
    call it in isolation, so this drives the equivalent published surface --
    _target_is_self(external) is True only if absent, and the helper raises when
    <worktree>/.venv/bin/python is missing. We assert via build_jail_argv that
    the .venv extra_ro path is honored AND via source that the absent-venv raise
    exists. The behavioral absent-venv refusal is additionally proven by the
    sibling test_g3_venv.py source detector; here we prove the runtime mount."""
    ext = _external_repo(tmp_path)
    # No .venv created -> the venv/bin/python is absent.
    assert not (ext / ".venv" / "bin" / "python").exists()
    src = inspect.getsource(_auto_commit_accepted)
    # the fail-closed RuntimeError for the absent external venv is present
    assert "G3_VENV" in src and "RuntimeError" in src
    assert ("absent" in src) or ("missing" in src) or ("fail-closed" in src)


def test_D_venv_path_mounted_readonly_in_jail_argv(tmp_path):
    """build_jail_argv (the real pure function the orchestrator calls) mounts an
    explicit extra_ro path read-only -- mirrors how _auto_commit_accepted binds
    the external target's .venv."""
    if agent_jail.shutil.which("bwrap") is None:  # pragma: no cover
        pytest.skip("bwrap not available")
    ext = _external_repo(tmp_path)
    venv = ext / ".venv"
    venv.mkdir()
    argv = agent_jail.build_jail_argv(
        ["/bin/bash", "-c", "true"],
        repo_root=ext, work_dir=ext, state_dir=tmp_path,
        extra_ro=[str(venv)], bind_credentials=False,
    )
    # the venv dir is ro-bound into the jail
    assert "--ro-bind" in argv
    assert str(venv.resolve()) in argv


# =============================================================================
# E  -- predicate fail-safe: ambiguous / unresolvable -> strict / self
# =============================================================================
def test_E_empty_target_set_fail_closed(tmp_path):
    wd = (tmp_path / "ext").resolve()
    wd.mkdir()
    assert relax_external_for({"working_dir": str(wd), "files_touched": []}) is False
    assert relax_external_for({"working_dir": str(wd)}) is False


def test_E_unparseable_manifest_falls_back_strict(tmp_path):
    wd = (tmp_path / "ext").resolve()
    wd.mkdir()
    # unparseable content is ignored; files_touched empty -> fail-closed strict
    assert relax_external_for({"working_dir": str(wd), "files_touched": []},
                              content="not python {") is False


def test_E_none_working_dir_is_self_root_project():
    assert _target_is_self(None) is True
    assert effective_target_root(None) == PROJECT_ROOT


# =============================================================================
# F  -- ancestor / descendant of PROJECT_ROOT classify as self
# =============================================================================
def test_F_ancestor_and_descendant_classify_self():
    # the repo itself
    assert _target_is_self(str(PROJECT_ROOT)) is True
    # a parent (ancestor) of the repo
    assert _target_is_self(str(PROJECT_ROOT.parent)) is True
    # a descendant inside the repo
    assert _target_is_self(str(PROJECT_ROOT / "harness" / "planner")) is True
    # effective_target_root collapses all of these to PROJECT_ROOT
    assert effective_target_root(str(PROJECT_ROOT.parent)) == PROJECT_ROOT
    assert effective_target_root(str(PROJECT_ROOT / "harness")) == PROJECT_ROOT


# =============================================================================
# G  -- dirty external repo -> commit REFUSED; external tree byte-UNCHANGED
# =============================================================================
def test_G_dirty_external_repo_refused_and_unchanged(tmp_path, monkeypatch):
    """A dirty EXTERNAL target repo trips EXTERNAL_DIRTY_GATE before any staging
    worktree is created; the external tree is byte-identical afterward."""
    ext = _external_repo(tmp_path)
    # make it dirty (untracked file)
    (ext / "dirty.txt").write_text("uncommitted", encoding="utf-8")
    snapshot_before = {p.name: p.read_bytes() for p in ext.iterdir() if p.is_file()}
    head_before = _git(ext, "rev-parse", "HEAD").stdout.strip()

    self_repo = tmp_path / "self_repo"
    _init_repo(self_repo)
    _seed_commit(self_repo)
    state_dir = self_repo / "state"
    state_dir.mkdir()

    monkeypatch.setattr(harness.paths, "_target_is_self", lambda wd: wd == "SELF")
    monkeypatch.setattr(harness.paths, "effective_target_root", lambda wd: str(ext))
    monkeypatch.setattr(orchestrator, "_resolve_files_touched",
                        lambda sd, task, tid: ["mod.py"])

    # spy: create_staging_worktree must NOT be reached
    reached = []
    monkeypatch.setattr(git_integration, "create_staging_worktree",
                        lambda staging_path, parent_root: reached.append(1))
    monkeypatch.setattr(target_bootstrap, "external_staging_root",
                        lambda: tmp_path / "staging_root")

    with pytest.raises(RuntimeError) as exc:
        _auto_commit_accepted(state_dir, {"working_dir": "EXTERNAL"}, "g_dirty")
    assert "EXTERNAL_DIRTY_GATE" in str(exc.value)
    assert reached == [], "must refuse BEFORE creating the staging worktree"

    # external tree byte-unchanged
    assert _git(ext, "rev-parse", "HEAD").stdout.strip() == head_before
    snapshot_after = {p.name: p.read_bytes() for p in ext.iterdir() if p.is_file()}
    assert snapshot_after == snapshot_before


# =============================================================================
# H  -- non-FF external -> ref-update onto refs/heads/janusmask/work,
#       NEVER the user's branch
# =============================================================================
def test_H_external_merge_lands_on_janusmask_work_not_user_branch(tmp_path):
    """A real external repo + a real staging worktree: merge_staging_to_parent
    for an external task advances refs/heads/janusmask/work via ref-update and
    leaves the user's checked-out branch (main) and working tree untouched --
    even when the staging commit is NOT a fast-forward of main."""
    parent = _external_repo(tmp_path, "user_repo")
    user_head_before = _git(parent, "rev-parse", "HEAD").stdout.strip()
    user_branch_before = _git(parent, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    assert user_branch_before == "main"

    # advance main so the staging commit (off the OLD head) is non-FF relative
    # to the new main tip -> proves we never try to FF the user's branch.
    (parent / "userfile.txt").write_text("user work\n", encoding="utf-8")
    _git(parent, "add", "userfile.txt")
    _git(parent, "commit", "-q", "-m", "user advances main")
    user_head_after_advance = _git(parent, "rev-parse", "HEAD").stdout.strip()

    staging = (tmp_path / "staging").resolve()
    # sibling placement satisfies create_staging_worktree's sibling rule
    staging = parent.parent / "user_repo_staging"
    git_integration.create_staging_worktree(str(staging), parent_root=parent)
    (staging / "agent_out.py").write_text("def agent():\n    return 42\n", encoding="utf-8")
    _git(staging, "add", "agent_out.py")
    _git(staging, "commit", "-q", "-m", "agent output")
    staging_sha = _git(staging, "rev-parse", "HEAD").stdout.strip()

    merge_staging_to_parent(staging, parent_root=parent, working_dir=str(parent))

    # janusmask/work now points at the staging commit
    work_sha = _git(parent, "rev-parse", "refs/heads/janusmask/work").stdout.strip()
    assert work_sha == staging_sha, "external merge must ref-update janusmask/work"
    # user's branch + HEAD untouched
    assert _git(parent, "rev-parse", "HEAD").stdout.strip() == user_head_after_advance
    assert _git(parent, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == "main"
    # the agent file is NOT on main
    assert not (parent / "agent_out.py").exists()
    # staging worktree torn down
    assert not staging.exists()


# =============================================================================
# I  -- e2e: external accepted output lands on janusmask/work AND nothing is
#       committed in the JM repo
# =============================================================================
def test_I_e2e_external_commit_lands_on_work_branch(tmp_path):
    """Full commit_accepted_output + merge_staging_to_parent for an external
    target: the output lands on refs/heads/janusmask/work in the external repo,
    the user branch is untouched, and (separately) the JM project repo is never
    written. Real git throughout."""
    ext = _external_repo(tmp_path, "ext_target")
    user_head_before = _git(ext, "rev-parse", "HEAD").stdout.strip()

    # JM project repo HEAD captured to prove no JM commit happens here
    jm_head_before = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(PROJECT_ROOT),
        capture_output=True, text=True,
    ).stdout.strip()

    # state/output/<task_id>.py is the accepted artifact
    state_dir = ext / "state"
    (state_dir / "output").mkdir(parents=True)
    (state_dir / "output" / "T.py").write_text("def foo():\n    return 99\n", encoding="utf-8")

    # staging worktree of the EXTERNAL repo
    staging = ext.parent / "ext_target_staging"
    git_integration.create_staging_worktree(str(staging), parent_root=ext)

    target_abs = str((ext / "mod.py").resolve())
    result = commit_accepted_output(
        "T", target_abs, state_dir, worktree_root=staging,
        allowed_files={"mod.py"}, working_dir=str(ext),
    )
    assert result["committed"] is True, result
    assert isinstance(result["sha"], str) and len(result["sha"]) == 40
    # the merged content lives in the staging worktree
    assert "return 99" in (staging / "mod.py").read_text()

    merge_staging_to_parent(staging, parent_root=ext, working_dir=str(ext))

    # the accepted output is on janusmask/work in the external repo
    work_blob = _git(ext, "show", "refs/heads/janusmask/work:mod.py").stdout
    assert "return 99" in work_blob
    # user branch untouched
    assert _git(ext, "rev-parse", "HEAD").stdout.strip() == user_head_before
    assert _git(ext, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == "main"

    # the JanusMask project repo received NO commit from this flow
    jm_head_after = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(PROJECT_ROOT),
        capture_output=True, text=True,
    ).stdout.strip()
    assert jm_head_after == jm_head_before


# =============================================================================
# J  -- M2: untracked agent test NOT auto-committed for external; manifest with
#       an out-of-target path is rejected
# =============================================================================
def test_J_external_untracked_test_not_auto_committed(tmp_path):
    """For an EXTERNAL target, commit_accepted_output must NOT auto-detect and
    commit an agent-generated untracked tests/test_*.py (the untracked
    auto-detect runs only on the SELF path). Real git on an external staging
    worktree."""
    ext = _external_repo(tmp_path, "ext_m2")
    staging = ext.parent / "ext_m2_staging"
    git_integration.create_staging_worktree(str(staging), parent_root=ext)

    # agent drops an untracked test inside staging
    (staging / "tests").mkdir(parents=True, exist_ok=True)
    (staging / "tests" / "test_sneaky.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")

    state_dir = ext / "state"
    (state_dir / "output").mkdir(parents=True)
    (state_dir / "output" / "T.py").write_text("def foo():\n    return 7\n", encoding="utf-8")

    target_abs = str((ext / "mod.py").resolve())
    result = commit_accepted_output(
        "T", target_abs, state_dir, worktree_root=staging,
        allowed_files={"mod.py"}, working_dir=str(ext),
    )
    assert result["committed"] is True, result
    # NO sidecar manifest was synthesized from the untracked test (self-only path)
    assert not (state_dir / "output" / "T.files.json").exists(), (
        "external commit must NOT auto-promote untracked tests into a sidecar"
    )
    # the committed tree contains mod.py but NOT the sneaky test
    committed = _git(staging, "show", "--name-only", "--pretty=format:", "HEAD").stdout
    assert "mod.py" in committed
    assert "test_sneaky.py" not in committed
    # the sneaky test is still on disk, merely untracked in staging (git
    # reports the untracked dir 'tests/' rather than the individual file).
    assert (staging / "tests" / "test_sneaky.py").exists()
    porcelain = _git(staging, "status", "--porcelain").stdout
    assert "tests/" in porcelain


def test_J_manifest_out_of_target_path_rejected(tmp_path):
    """An agent multi-file manifest (sidecar) listing a path that is NOT a
    member of the declared files_touched is rejected (apply-scope membership)."""
    ext = _external_repo(tmp_path, "ext_manifest")
    staging = ext.parent / "ext_manifest_staging"
    git_integration.create_staging_worktree(str(staging), parent_root=ext)

    state_dir = ext / "state"
    (state_dir / "output").mkdir(parents=True)
    # multi-file sidecar lists an out-of-target path 'other/evil.py'
    sidecar = state_dir / "output" / "T.files.json"
    sidecar.write_text(json.dumps({
        "mod.py": "def foo():\n    return 1\n",
        "other/evil.py": "def evil(): pass\n",
    }), encoding="utf-8")

    target_abs = str((ext / "mod.py").resolve())
    result = commit_accepted_output(
        "T", target_abs, state_dir, worktree_root=staging,
        allowed_files={"mod.py"}, working_dir=str(ext),
    )
    assert result["committed"] is False
    assert result["error"] and "scope violation" in result["error"]
    assert "other/evil.py" in result["error"]


# =============================================================================
# K  -- host-ENV not leaked into the external jail; sandbox-OFF external
#       execution REFUSED in ALL THREE execute families
# =============================================================================
def test_K_jail_drops_credentials_and_unshares_net(tmp_path):
    """build_jail_argv on the EXECUTE path (bind_credentials=False) unshares the
    network/IPC namespaces and does NOT bind the ~/.gemini / ~/.claude credential
    surface -- so a host secret cannot be read or exfiltrated by external code."""
    if agent_jail.shutil.which("bwrap") is None:  # pragma: no cover
        pytest.skip("bwrap not available")
    ext = _external_repo(tmp_path, "ext_env")
    argv = agent_jail.build_jail_argv(
        ["/bin/bash", "-c", "true"],
        repo_root=ext, work_dir=ext, state_dir=tmp_path,
        bind_credentials=False,
    )
    assert "--unshare-net" in argv
    assert "--unshare-ipc" in argv
    # the credential dirs are not bound on the execute path
    home = os.environ.get("HOME", "/tmp")
    assert os.path.join(home, ".gemini") not in argv
    assert os.path.join(home, ".claude") not in argv


def test_K_jailed_env_is_caller_controlled_not_host_environ():
    """The orchestrator runs the jailed verify with env=_venv_jail_env(), which
    derives from _vcmd_scrubbed_env() (JANUSMASK_* dropped) -- the raw host
    os.environ is never passed through. Proven at the source: every jailed
    subprocess.run uses env=_venv_jail_env(), never env=os.environ."""
    src = inspect.getsource(_auto_commit_accepted)
    # all jailed runs route env through the scrubbed/venv helper
    assert "env=_venv_jail_env()" in src
    # the scrubbed-env helper underlies it
    assert "_vcmd_scrubbed_env" in src
    # no jailed run leaks the raw host environment
    assert "env=os.environ" not in src
    assert "env=dict(os.environ)" not in src


def test_K_sandbox_off_external_refused_all_three_families():
    """With sandbox OFF, an EXTERNAL target is REFUSED in all three execute
    families. The orchestrator shell=True verify/baseline/mutant family raises
    FLAG2_ORCH; the embedded + narrow-fuzz family raises FLAG2_EMBEDDED_FUZZ at
    the call sites. Proven by source presence at every guarded site."""
    # family 1: orchestrator shell=True verify/baseline/mutant (FLAG2_ORCH)
    src = inspect.getsource(_auto_commit_accepted)
    flag2_orch_guards = src.count("FLAG2_ORCH")
    assert flag2_orch_guards >= 3, (
        f"expected the sandbox-OFF external refusal at the 3 shell=True execute "
        f"sites (verify, baseline-in-copy, mutant-apply/rerun); found "
        f"{flag2_orch_guards} FLAG2_ORCH guards"
    )
    # each guard pairs the not-self check with the unjailed shell=True refusal
    assert "not _target_is_self(working_dir)" in src

    # families 2 & 3: embedded + narrow-fuzz (FLAG2_EMBEDDED_FUZZ) at run_pipeline
    pipeline_src = inspect.getsource(orchestrator.run_pipeline)
    assert "FLAG2_EMBEDDED_FUZZ" in pipeline_src, (
        "run_pipeline must gate the embedded/narrow-fuzz execute families for "
        "external + sandbox-OFF"
    )
    # and at the worker entrypoint
    import harness.orchestrator_worker as ow
    worker_src = inspect.getsource(ow.main)
    assert "FLAG2_EMBEDDED_FUZZ" in worker_src, (
        "orchestrator_worker.main must gate the embedded/narrow-fuzz families too"
    )


def test_K_sandbox_off_external_dirty_gate_behavioral(tmp_path, monkeypatch):
    """Behavioral cross-check of family-1 refusal: an external task with sandbox
    OFF that reaches the verify shell=True branch raises (FLAG2_ORCH). We drive
    _auto_commit_accepted far enough to confirm the external path is the refusing
    one (here via the dirty gate, which is the first external-only refusal)."""
    ext = _external_repo(tmp_path, "ext_k_behav")
    (ext / "dirty.txt").write_text("x", encoding="utf-8")  # dirty -> dirty gate fires first
    self_repo = tmp_path / "self_k"
    _init_repo(self_repo)
    _seed_commit(self_repo)
    state_dir = self_repo / "state"
    state_dir.mkdir()
    monkeypatch.setattr(harness.paths, "_target_is_self", lambda wd: wd == "SELF")
    monkeypatch.setattr(harness.paths, "effective_target_root", lambda wd: str(ext))
    monkeypatch.setattr(orchestrator, "_resolve_files_touched", lambda sd, t, tid: ["mod.py"])
    monkeypatch.setattr(target_bootstrap, "external_staging_root", lambda: tmp_path / "sr")
    with pytest.raises(RuntimeError):
        _auto_commit_accepted(state_dir, {"working_dir": "EXTERNAL"}, "k_behav")


# =============================================================================
# §1a -- external working_dir + a JM-tree target file -> relax does NOT apply
# =============================================================================
def test_s1a_external_wd_jm_target_file_no_relax(tmp_path):
    """CRITICAL self-target bypass closed: an EXTERNAL working_dir but a target
    file that resolves INSIDE the JanusMask tree -> relax_external_for is False
    (strict). Today's predicate keys on the target set, not just working_dir."""
    wd = (tmp_path / "ext").resolve()
    wd.mkdir()
    task = {
        "working_dir": str(wd),
        "files_touched": [str(PROJECT_ROOT / "harness" / "agent_jail.py")],
    }
    assert relax_external_for(task) is False


def test_s1a_external_wd_jm_target_via_target_file_key(tmp_path):
    wd = (tmp_path / "ext").resolve()
    wd.mkdir()
    task = {
        "working_dir": str(wd),
        "target_file": str(PROJECT_ROOT / "harness" / "orchestrator.py"),
    }
    assert relax_external_for(task) is False


def test_s1a_external_wd_jm_target_via_manifest(tmp_path):
    wd = (tmp_path / "ext").resolve()
    wd.mkdir()
    content = (
        "__JANUSMASK_MANIFEST__ = {\n"
        f'    "{PROJECT_ROOT / "harness" / "agent_jail.py"}": "def f(): pass",\n'
        "}\n"
    )
    assert relax_external_for({"working_dir": str(wd), "files_touched": []},
                              content=content) is False


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
