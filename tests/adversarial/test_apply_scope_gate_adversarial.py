"""Adversarial battery for the AGENT-ISOLATION §1b apply-path scoping gate.

Plan: adversarial_test_plans/02_apply_commit_validation_fuzzing.md §A (A1-A7),
§C6, §C7. Targets harness.git_integration._enforce_apply_scope /
_matches_sensitive and the three commit dispatchers
(commit_accepted_output, _commit_accepted_output_multi,
_commit_accepted_output_patches).

INVARIANTS UNDER TEST (do NOT weaken):
  INV-1 membership: never commit a rel-path outside files_touched.
  INV-2 sensitive: never write harness/**, config/**, scripts/** unless
        meta_task_type=='harness_self_fix' AND approval fired.
  INV-3 fail-closed: scope violation => committed=False, no git invoked, no
        committed on-disk write.

These tests MOCK nothing agentic; they only drive git_integration against a
tmp git repo. No agy/gemini/claude spawn.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess

import pytest

import harness.git_integration as gi


def _git(args, cwd):
    env = os.environ.copy()
    env.setdefault("GIT_AUTHOR_NAME", "t")
    env.setdefault("GIT_AUTHOR_EMAIL", "t@example.com")
    env.setdefault("GIT_COMMITTER_NAME", "t")
    env.setdefault("GIT_COMMITTER_EMAIL", "t@example.com")
    return subprocess.run(["git", *args], cwd=str(cwd), check=True,
                          capture_output=True, text=True, env=env)


@pytest.fixture
def tmp_repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / "harness").mkdir(parents=True)
    (repo / "pkg").mkdir(parents=True)
    (repo / "state" / "output").mkdir(parents=True)
    (repo / "harness" / "orchestrator.py").write_text("def gate():\n    return 1\n")
    (repo / "pkg" / "a.py").write_text("a = 1\n")
    (repo / "pkg" / "mod.py").write_text("y = 1\n")
    (repo / "pkg" / "evil.py").write_text("z = 0\n")
    _git(["init", "-q", "-b", "main"], repo)
    _git(["config", "user.email", "t@t"], repo)
    _git(["config", "user.name", "t"], repo)
    _git(["add", "-A"], repo)
    _git(["commit", "-qm", "init"], repo)
    return repo


# --------------------------------------------------------------------------- #
# A1 — membership bypass / false-lockout via path normalization
# --------------------------------------------------------------------------- #
class TestA1Normalization:
    def test_unnormalized_member_in_allowed_files_false_lockout(self, tmp_repo):
        """GAP: files_touched carrying './pkg/mod.py' does NOT match the
        resolved rel-path 'pkg/mod.py' -> a LEGITIMATE commit is rejected.

        allowed_files is compared verbatim (only \\->/ normalized), but the
        candidate rel-path is derived from a .resolve()d relative_to, so the
        './' member never matches its own resolved form.
        """
        sd = tmp_repo / "state"
        (sd / "output" / "T.files.json").write_text(json.dumps({"pkg/mod.py": "y = 2\n"}))
        # files_touched contains the SAME logical file but non-normalized.
        r = gi.commit_accepted_output(
            "T", str(tmp_repo / "pkg" / "mod.py"), sd,
            worktree_root=tmp_repo, allowed_files={"./pkg/mod.py"},
            meta_task_type=None, approval_ok=False)
        # Proven gap: the legitimate commit is wrongly rejected.
        assert r["committed"] is False, (
            "If this now commits, the normalization-asymmetry lockout was fixed")
        assert "not a member" in (r["error"] or "")

    def test_dotdot_member_in_allowed_files_false_lockout(self, tmp_repo):
        """GAP: 'pkg/../pkg/mod.py' in allowed_files fails to match resolved
        'pkg/mod.py'."""
        sd = tmp_repo / "state"
        (sd / "output" / "T2.files.json").write_text(json.dumps({"pkg/mod.py": "y = 3\n"}))
        r = gi.commit_accepted_output(
            "T2", str(tmp_repo / "pkg" / "mod.py"), sd,
            worktree_root=tmp_repo, allowed_files={"pkg/../pkg/mod.py"},
            meta_task_type=None, approval_ok=False)
        assert r["committed"] is False
        assert "not a member" in (r["error"] or "")

    def test_normalized_member_accepts(self, tmp_repo):
        """Control: a normalized member commits fine (no false negative)."""
        sd = tmp_repo / "state"
        (sd / "output" / "OK.files.json").write_text(json.dumps({"pkg/mod.py": "y = 9\n"}))
        r = gi.commit_accepted_output(
            "OK", str(tmp_repo / "pkg" / "mod.py"), sd,
            worktree_root=tmp_repo, allowed_files={"pkg/mod.py"},
            meta_task_type=None, approval_ok=False)
        assert r["committed"] is True, r


# --------------------------------------------------------------------------- #
# A2 — sensitive-glob case / separator evasion
# --------------------------------------------------------------------------- #
class TestA2SensitiveCaseEvasion:
    def test_lowercase_harness_blocked(self):
        assert gi._enforce_apply_scope(
            ["harness/x.py"], allowed_files=None, meta_task_type=None, approval_ok=False)

    def test_capital_harness_evades_gate(self):
        """GAP (proven): _matches_sensitive is case-sensitive. 'Harness/x.py'
        is NOT recognized as sensitive, so on a case-insensitive FS it writes
        the real harness/ dir while evading the protected-path gate."""
        err = gi._enforce_apply_scope(
            ["Harness/x.py"], allowed_files=None, meta_task_type=None, approval_ok=False)
        assert err is None, (
            "If non-None, the case-insensitive evasion was fixed (gate now matches Harness/)")

    def test_uppercase_harness_evades_gate(self):
        err = gi._enforce_apply_scope(
            ["HARNESS/x.py"], allowed_files=None, meta_task_type=None, approval_ok=False)
        assert err is None, "HARNESS/ should be caught if case-folding was added"

    def test_dot_slash_harness_evades_helper_directly(self):
        """GAP: a raw './harness/x.py' fed straight into the helper is NOT
        matched (prefix is 'harness/', not './harness/'). The single-file
        commit path resolves first (safe), but the helper itself is leaky."""
        err = gi._enforce_apply_scope(
            ["./harness/x.py"], allowed_files=None, meta_task_type=None, approval_ok=False)
        assert err is None, (
            "If non-None, the helper now normalizes leading './' before matching")

    def test_backslash_harness_is_normalized_and_blocked(self):
        """Control: backslashes ARE normalized to '/', so this is caught."""
        assert gi._enforce_apply_scope(
            ["harness\\x.py"], allowed_files=None, meta_task_type=None, approval_ok=False)


# --------------------------------------------------------------------------- #
# A3 — sibling-prefix false negative / bare-name edge
# --------------------------------------------------------------------------- #
class TestA3SiblingPrefix:
    @pytest.mark.parametrize("rel", [
        "harness_extra/x.py",
        "config_backup/y.yaml",
        "scripts2/z.sh",
        "pkg/harness_helper.py",
    ])
    def test_sibling_dirs_not_sensitive(self, rel):
        assert gi._enforce_apply_scope(
            [rel], allowed_files=None, meta_task_type=None, approval_ok=False) is None

    def test_bare_harness_name_is_sensitive(self):
        """A top-level file literally named 'harness' (no ext) hits the
        p == base branch and is treated as sensitive. Pin this."""
        assert gi._enforce_apply_scope(
            ["harness"], allowed_files=None, meta_task_type=None, approval_ok=False)

    def test_trailing_slash_harness_dir_sensitive(self):
        assert gi._enforce_apply_scope(
            ["harness/"], allowed_files=None, meta_task_type=None, approval_ok=False)


# --------------------------------------------------------------------------- #
# A4 — patches path sensitive write without approval (INV-3 fail-closed)
# --------------------------------------------------------------------------- #
class TestA4PatchesSensitive:
    def test_patches_harness_no_approval_no_write(self, tmp_repo):
        sd = tmp_repo / "state"
        target = tmp_repo / "harness" / "orchestrator.py"
        before = target.read_text()
        (sd / "output" / "SF.patches.json").write_text(json.dumps([
            {"file": "harness/orchestrator.py", "kind": "symbol",
             "name": "gate", "code": "def gate():\n    return 2\n"}]))
        r = gi.commit_accepted_output(
            "SF", str(target), sd, worktree_root=tmp_repo,
            allowed_files={"harness/orchestrator.py"},
            meta_task_type="harness_self_fix", approval_ok=False)
        assert r["committed"] is False
        assert "scope violation" in (r["error"] or "")
        # INV-3: scope check at gi:1090 precedes read/write -> file untouched.
        assert target.read_text() == before, "fail-closed violated: file mutated before scope reject"

    def test_patches_harness_with_approval_commits(self, tmp_repo):
        sd = tmp_repo / "state"
        target = tmp_repo / "harness" / "orchestrator.py"
        (sd / "output" / "SF2.patches.json").write_text(json.dumps([
            {"file": "harness/orchestrator.py", "kind": "symbol",
             "name": "gate", "code": "def gate():\n    return 42\n"}]))
        r = gi.commit_accepted_output(
            "SF2", str(target), sd, worktree_root=tmp_repo,
            allowed_files={"harness/orchestrator.py"},
            meta_task_type="harness_self_fix", approval_ok=True)
        assert r["committed"] is True, r
        assert "return 42" in target.read_text()


# --------------------------------------------------------------------------- #
# A5 — multi-file manifest: in-scope first, out-of-scope second (atomicity)
# --------------------------------------------------------------------------- #
class TestA5MultiAtomicity:
    def test_partial_on_disk_write_when_later_entry_fails_scope(self, tmp_repo):
        """GAP (proven): _commit_accepted_output_multi applies file-by-file and
        checks scope per rel BEFORE write, but the in-scope entry processed
        FIRST is already written to the staging worktree even though the
        function returns committed=False on the later out-of-scope entry.
        No transaction / rollback of the on-disk write."""
        sd = tmp_repo / "state"
        a_before = (tmp_repo / "pkg" / "a.py").read_text()
        # Ordered dict: in-scope pkg/a.py first, out-of-scope pkg/evil.py second.
        manifest = {"pkg/a.py": "a = 999\n", "pkg/evil.py": "z = 1\n"}
        (sd / "output" / "M.files.json").write_text(json.dumps(manifest))
        r = gi.commit_accepted_output(
            "M", str(tmp_repo / "pkg" / "a.py"), sd, worktree_root=tmp_repo,
            allowed_files={"pkg/a.py"}, meta_task_type=None, approval_ok=False)
        assert r["committed"] is False
        assert "not a member" in (r["error"] or "")
        # Document the dirty-staging leak: pkg/a.py WAS written despite reject.
        a_after = (tmp_repo / "pkg" / "a.py").read_text()
        assert a_after != a_before, (
            "If a.py is unchanged, the multi-path became transactional (gap fixed)")
        assert "a = 999" in a_after
        # But no commit was created (HEAD unchanged) — INV-3 commit-side holds.
        log = _git(["log", "--oneline"], tmp_repo).stdout
        assert log.count("\n") == 1, "a commit was created despite scope reject"


# --------------------------------------------------------------------------- #
# A6 — manifest/declared mismatch through _auto_commit_accepted (no agents)
# --------------------------------------------------------------------------- #
class TestA6DispatchMembership:
    def test_auto_commit_rejects_sidecar_listing_undeclared_file(self, tmp_repo, monkeypatch):
        """A task whose files_touched=['pkg/mod.py'] but whose .files.json
        sidecar lists pkg/evil.py -> membership rejects pkg/evil.py.

        Drives orchestrator._auto_commit_accepted with a real tmp repo. No
        agents: we monkeypatch the staging-worktree helpers to operate
        in-place on the repo so we exercise the real scope path."""
        import harness.orchestrator as orch
        sd = tmp_repo / "state"
        (sd / "output" / "AC.files.json").write_text(json.dumps({"pkg/evil.py": "z = 7\n"}))
        # Stub staging so commit happens directly in tmp_repo (no sibling worktree).
        monkeypatch.setattr(orch.git_integration, "create_staging_worktree", lambda *a, **k: None)
        monkeypatch.setattr(orch.git_integration, "remove_staging_worktree", lambda *a, **k: None)
        orig = orch.git_integration.commit_accepted_output

        def _commit_in_repo(task_id, target_abs, state_dir, *, worktree_root=None, **kw):
            # force the commit to run in the real repo, not a *_staging sibling
            return orig(task_id, target_abs, state_dir, worktree_root=tmp_repo, **kw)

        monkeypatch.setattr(orch.git_integration, "commit_accepted_output", _commit_in_repo)
        task = {"task_id": "AC", "files_touched": ["pkg/mod.py"],
                "verification_command": "true"}
        ok = orch._auto_commit_accepted(sd, task, "AC")
        assert ok is False, "membership must reject the undeclared sidecar path"


# --------------------------------------------------------------------------- #
# A7 — meta_task_type precedence: top-level vs constraints
# --------------------------------------------------------------------------- #
class TestA7MttPrecedence:
    def test_top_level_mtt_wins_over_constraints(self):
        task = {"meta_task_type": "harness_self_fix",
                "constraints": {"meta_task_type": "io_adapter"}}
        mtt = task.get("meta_task_type") or (task.get("constraints") or {}).get("meta_task_type")
        assert mtt == "harness_self_fix"

    def test_constraints_mtt_used_when_top_level_absent(self):
        task = {"constraints": {"meta_task_type": "harness_self_fix"}}
        mtt = task.get("meta_task_type") or (task.get("constraints") or {}).get("meta_task_type")
        assert mtt == "harness_self_fix"
        # And that resolved mtt authorizes a sensitive write only WITH approval.
        assert gi._enforce_apply_scope(
            ["harness/x.py"], allowed_files=None, meta_task_type=mtt, approval_ok=True) is None
        assert gi._enforce_apply_scope(
            ["harness/x.py"], allowed_files=None, meta_task_type=mtt, approval_ok=False)

    def test_non_harness_top_level_does_not_authorize_sensitive(self):
        """A non-harness_self_fix top-level mtt must NOT authorize a sensitive
        write even if approval_ok is True."""
        assert gi._enforce_apply_scope(
            ["harness/x.py"], allowed_files=None, meta_task_type="io_adapter", approval_ok=True)


# --------------------------------------------------------------------------- #
# C6 — untracked-test sidecar synthesis OVERRIDES .patches.json (memory hazard)
# --------------------------------------------------------------------------- #
class TestC6UntrackedTestPoisonsPatches:
    def test_untracked_test_converts_patches_to_multi_and_fails_membership(self, tmp_repo):
        """KNOWN cross-feature bug (MEMORY: untracked test poisons patches
        commit). A .patches.json + an untracked tests/test_*.py in the parent
        worktree causes commit_accepted_output to BUILD a .files.json manifest
        (gi:603-629) and route to _commit_accepted_output_multi (gi:633) — the
        .patches.json path (gi:636) is NEVER reached. The synthesized manifest
        includes the untracked test, which is NOT in allowed_files, so the §1b
        membership check then REJECTS the whole commit."""
        sd = tmp_repo / "state"
        # patches sidecar for an in-scope, non-sensitive target
        (sd / "output" / "P.patches.json").write_text(json.dumps([
            {"file": "pkg/mod.py", "kind": "symbol", "name": "f",
             "code": "def f():\n    return 1\n"}]))
        (tmp_repo / "pkg" / "mod.py").write_text("def f():\n    return 0\n")
        # tests/ must be a TRACKED dir so an added file shows as
        # '?? tests/test_poison.py' (not '?? tests/' for a wholly-new dir).
        (tmp_repo / "tests").mkdir(exist_ok=True)
        (tmp_repo / "tests" / "__init__.py").write_text("")
        _git(["add", "pkg/mod.py", "tests/__init__.py"], tmp_repo)
        _git(["commit", "-qm", "add f + track tests"], tmp_repo)
        # untracked test in parent worktree (state_dir.parent == tmp_repo)
        (tmp_repo / "tests" / "test_poison.py").write_text("def test_x():\n    assert True\n")
        # whole-file output so manifest synthesis has a body for the target
        (sd / "output" / "P.py").write_text("def f():\n    return 1\n")
        r = gi.commit_accepted_output(
            "P", str(tmp_repo / "pkg" / "mod.py"), sd, worktree_root=tmp_repo,
            allowed_files={"pkg/mod.py"}, meta_task_type=None, approval_ok=False)
        # The .files.json sidecar was synthesized (clobbering the patches path)
        synthesized = (sd / "output" / "P.files.json")
        assert synthesized.exists(), "untracked-test block did not synthesize a manifest"
        manifest = json.loads(synthesized.read_text())
        assert "tests/test_poison.py" in manifest, "untracked test not swept into manifest"
        # And membership now rejects the whole commit because the untracked
        # test is not a declared file.
        assert r["committed"] is False
        assert "not a member" in (r["error"] or ""), r
        assert "tests/test_poison.py" in (r["error"] or "")


# --------------------------------------------------------------------------- #
# C7 — untracked synthesis scoping: only tests/test_*.py, never sensitive
# --------------------------------------------------------------------------- #
class TestC7UntrackedScoping:
    def test_untracked_harness_and_scripts_tests_not_swept(self, tmp_repo):
        """Pin: the untracked auto-detect globs `git status --porcelain tests/`
        and fnmatch 'tests/test_*.py' — an untracked harness/test_x.py or
        scripts/test_y.py is NOT swept into the synthesized manifest."""
        sd = tmp_repo / "state"
        (tmp_repo / "scripts").mkdir(exist_ok=True)
        (tmp_repo / "harness" / "test_evil.py").write_text("def test_a():\n    pass\n")
        (tmp_repo / "scripts" / "test_evil.py").write_text("def test_b():\n    pass\n")
        # also an in-scope tests/ untracked file to make synthesis fire
        # (tests/ tracked so the added file shows as '?? tests/test_ok.py')
        (tmp_repo / "tests").mkdir(exist_ok=True)
        (tmp_repo / "tests" / "__init__.py").write_text("")
        _git(["add", "tests/__init__.py"], tmp_repo)
        _git(["commit", "-qm", "track tests"], tmp_repo)
        (tmp_repo / "tests" / "test_ok.py").write_text("def test_c():\n    pass\n")
        (sd / "output" / "S.py").write_text("y = 2\n")
        gi.commit_accepted_output(
            "S", str(tmp_repo / "pkg" / "mod.py"), sd, worktree_root=tmp_repo,
            allowed_files={"pkg/mod.py", "tests/test_ok.py"},
            meta_task_type=None, approval_ok=False)
        synthesized = sd / "output" / "S.files.json"
        if synthesized.exists():
            manifest = json.loads(synthesized.read_text())
            assert "harness/test_evil.py" not in manifest
            assert "scripts/test_evil.py" not in manifest
            assert "tests/test_ok.py" in manifest
