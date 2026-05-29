"""Adversarial plan 01 — T8/T9: apply-scope at the multi/patches callsites.

test_agent_isolation.py covers _enforce_apply_scope units and the single-file
commit_accepted_output path. These extend coverage to the multi-file and patches
sidecar callsites (_commit_accepted_output_multi :804, _commit_accepted_output_patches
:1090) and harden _matches_sensitive / _apply_approval_granted edge cases.

  T8  — multi-file commit of a non-member rel returns committed=False + scope
        error; allowed_files=None opt-out still applies the sensitive-path gate.
  T9  — _matches_sensitive prefix-boundary (harness vs harnessextra), and
        _apply_approval_granted corrupt/missing/deny/case/non-dict handling.

No agy/claude spawned. Real tmp git repo for the commit path.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import harness.git_integration as gi
import harness.orchestrator as orch


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


@pytest.fixture
def tmp_repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / "a").mkdir(parents=True)
    (repo / "b").mkdir(parents=True)
    (repo / "state" / "output").mkdir(parents=True)
    (repo / "a" / "in.py").write_text("v = 1\n")
    (repo / "b" / "sneaky.py").write_text("w = 1\n")
    _git(["init", "-q"], repo)
    _git(["config", "user.email", "t@t"], repo)
    _git(["config", "user.name", "t"], repo)
    _git(["add", "-A"], repo)
    _git(["commit", "-qm", "init"], repo)
    return repo


# --------------------------------------------------------------------------- #
# T8 — multi-file sidecar callsite enforces membership
# --------------------------------------------------------------------------- #
def test_T8_multi_file_non_member_rejected(tmp_repo):
    sd = tmp_repo / "state"
    # manifest sidecar maps two files; allowed_files only authorizes a/in.py
    (sd / "output" / "MF.files.json").write_text(
        json.dumps({"a/in.py": "v = 2\n", "b/sneaky.py": "w = 2\n"}))
    r = gi.commit_accepted_output(
        "MF", str(tmp_repo / "a" / "in.py"), sd, worktree_root=tmp_repo,
        allowed_files={"a/in.py"}, meta_task_type=None, approval_ok=False)
    assert r["committed"] is False
    err = r.get("error") or ""
    assert "scope violation" in err and "not a member" in err, f"got {err!r}"
    # no new commit landed
    log = subprocess.run(["git", "log", "--oneline"], cwd=str(tmp_repo),
                         capture_output=True, text=True).stdout
    assert log.count("\n") == 1, "no extra commit must be created on a scope violation"


def test_T8_multi_file_all_members_commits(tmp_repo):
    sd = tmp_repo / "state"
    (sd / "output" / "MF2.files.json").write_text(
        json.dumps({"a/in.py": "v = 2\n", "b/sneaky.py": "w = 2\n"}))
    r = gi.commit_accepted_output(
        "MF2", str(tmp_repo / "a" / "in.py"), sd, worktree_root=tmp_repo,
        allowed_files={"a/in.py", "b/sneaky.py"}, meta_task_type=None, approval_ok=False)
    assert r["committed"] is True and r.get("sha")


def test_T8_allowed_none_optout_still_gates_sensitive(tmp_repo):
    """allowed_files=None disables membership but the sensitive-path gate still
    fires (documents the opt-out semantics flagged in plan §5)."""
    # rel under harness/** is sensitive; helper-level proof (no git needed):
    err = gi._enforce_apply_scope(
        ["harness/x.py"], allowed_files=None, meta_task_type="other", approval_ok=True)
    assert err and "protected path" in err
    # but a plain in-repo rel with allowed_files=None passes (the documented risk:
    # a None-passing caller can commit ANY non-sensitive in-repo rel):
    assert gi._enforce_apply_scope(
        ["pkg/anything.py"], allowed_files=None, meta_task_type=None, approval_ok=False) is None


# --------------------------------------------------------------------------- #
# T9 — _matches_sensitive boundary + _apply_approval_granted edges
# --------------------------------------------------------------------------- #
def test_T9_matches_sensitive_prefix_boundary():
    g = gi._SENSITIVE_APPLY_GLOBS
    assert gi._matches_sensitive("harness", g) is True          # bare dir
    assert gi._matches_sensitive("harness/orchestrator.py", g) is True
    assert gi._matches_sensitive("config/c.yaml", g) is True
    assert gi._matches_sensitive("scripts/run.sh", g) is True
    # NO false positive on a sibling dir that merely shares a prefix:
    assert gi._matches_sensitive("harnessextra/a.py", g) is False
    assert gi._matches_sensitive("pkg/harness_helper.py", g) is False
    assert gi._matches_sensitive("configs/other.yaml", g) is False


def test_T9_apply_approval_granted_edges(tmp_path):
    sd = tmp_path / "state"
    (sd / "control" / "decisions").mkdir(parents=True)
    f = sd / "control" / "decisions" / "T.json"

    # missing file -> closed
    assert orch._apply_approval_granted(sd, "T") is False
    # corrupt json -> closed
    f.write_text("{nope")
    assert orch._apply_approval_granted(sd, "T") is False
    # non-dict top level -> closed
    f.write_text(json.dumps(["approve"]))
    assert orch._apply_approval_granted(sd, "T") is False
    # decision deny -> closed
    f.write_text(json.dumps({"decision": "deny"}))
    assert orch._apply_approval_granted(sd, "T") is False
    # decision approve -> open
    f.write_text(json.dumps({"decision": "approve"}))
    assert orch._apply_approval_granted(sd, "T") is True
    # decision approved -> open
    f.write_text(json.dumps({"decision": "approved"}))
    assert orch._apply_approval_granted(sd, "T") is True
    # case-insensitive APPROVE -> open (lower() normalization)
    f.write_text(json.dumps({"decision": "APPROVE"}))
    assert orch._apply_approval_granted(sd, "T") is True


def test_T9_harness_path_requires_approval_at_helper():
    f = gi._enforce_apply_scope
    # harness/** without approval -> reject (3 ways)
    assert f(["harness/o.py"], allowed_files=None, meta_task_type=None, approval_ok=False)
    assert f(["harness/o.py"], allowed_files=None, meta_task_type="harness_self_fix", approval_ok=False)
    assert f(["harness/o.py"], allowed_files=None, meta_task_type="other", approval_ok=True)
    # only harness_self_fix + approval passes
    assert f(["harness/o.py"], allowed_files=None, meta_task_type="harness_self_fix", approval_ok=True) is None
