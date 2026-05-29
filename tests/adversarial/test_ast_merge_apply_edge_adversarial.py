"""Adversarial battery for harness.git_integration._ast_merge edge cases.

Plan: adversarial_test_plans/02_apply_commit_validation_fuzzing.md §B (B1-B4).
Targets _ast_merge JANUSMASK_DELETE directive, multi-alias import preservation,
the copy2 fallback data-loss surface, and the class-body recursion cap.

Does NOT duplicate test_ast_merge_regression_adversarial.py /
test_ast_merge_importfrom_additive.py — focuses on the gate-interaction and
data-loss boundaries the plan calls out.
"""
from __future__ import annotations

import ast
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
    (repo / "harness" / "git_integration.py").write_text(
        "def _enforce_apply_scope():\n    return 'GATE'\n")
    _git(["init", "-q", "-b", "main"], repo)
    _git(["config", "user.email", "t@t"], repo)
    _git(["config", "user.name", "t"], repo)
    _git(["add", "-A"], repo)
    _git(["commit", "-qm", "init"], repo)
    return repo


# --------------------------------------------------------------------------- #
# B1 — JANUSMASK_DELETE directive: works on benign target; moot on sensitive
# --------------------------------------------------------------------------- #
class TestB1DeleteDirective:
    def test_delete_directive_removes_top_level_symbol(self):
        target = "def keep():\n    return 1\n\ndef drop():\n    return 2\n"
        output = "# JANUSMASK_DELETE: keep\ndef drop():\n    return 3\n"
        merged = gi._ast_merge(output, target)
        names = {n.name for n in ast.parse(merged).body
                 if isinstance(n, ast.FunctionDef)}
        assert "keep" not in names, "JANUSMASK_DELETE failed to remove 'keep'"
        assert "drop" in names

    def test_delete_directive_cannot_remove_gate_without_approval(self, tmp_repo):
        """A JANUSMASK_DELETE targeting _enforce_apply_scope in
        harness/git_integration.py would delete the gate itself — but INV-2
        blocks the write before _ast_merge ever runs, so the directive is moot
        on a sensitive target without harness_self_fix + approval."""
        sd = tmp_repo / "state"
        (sd / "output" / "D.py").write_text(
            "# JANUSMASK_DELETE: _enforce_apply_scope\nx = 1\n")
        target = tmp_repo / "harness" / "git_integration.py"
        before = target.read_text()
        r = gi.commit_accepted_output(
            "D", str(target), sd, worktree_root=tmp_repo,
            allowed_files={"harness/git_integration.py"},
            meta_task_type=None, approval_ok=False)
        assert r["committed"] is False
        assert "scope violation" in (r["error"] or "")
        # gate symbol still present on disk
        assert "_enforce_apply_scope" in target.read_text()
        assert target.read_text() == before


# --------------------------------------------------------------------------- #
# B2 — multi-alias import preservation (G23a regression pin)
# --------------------------------------------------------------------------- #
class TestB2ImportPreservation:
    def test_subset_import_does_not_drop_sibling_alias(self):
        target = "from tools import a, b\n"
        output = "from tools import a\n"
        merged = gi._ast_merge(output, target)
        imported = set()
        for n in ast.parse(merged).body:
            if isinstance(n, ast.ImportFrom):
                imported.update(al.name for al in n.names)
        assert {"a", "b"} <= imported, f"alias 'b' was dropped: {imported}"


# --------------------------------------------------------------------------- #
# B3 — parse-failure fallback discards target-only symbols (data-loss surface)
# --------------------------------------------------------------------------- #
class TestB3CopyFallbackDataLoss:
    def test_unparseable_target_triggers_whole_file_copy_dropping_other_symbols(self, tmp_repo):
        """GAP (proven, documented): when the EXISTING target on disk is not
        parseable, _ast_merge raises and commit_accepted_output falls back to
        shutil.copy2, which whole-file-replaces — silently DISCARDING the
        target's other top-level symbols. A single-file submission can thereby
        drop unrelated code on a transient parse error.

        Scope gate still applies first, so this is bounded to non-sensitive
        in-scope targets."""
        sd = tmp_repo / "state"
        # seed a non-sensitive target that is NOT parseable but holds extra code
        broken = tmp_repo / "pkg" / "broken.py"
        broken.write_text("def survivor():\n    return 1\ndef =:  # syntax error\n")
        _git(["add", "pkg/broken.py"], tmp_repo)
        _git(["commit", "-qm", "broken"], tmp_repo)
        (sd / "output" / "B.py").write_text("def replacement():\n    return 2\n")
        r = gi.commit_accepted_output(
            "B", str(broken), sd, worktree_root=tmp_repo,
            allowed_files={"pkg/broken.py"}, meta_task_type=None, approval_ok=False)
        assert r["committed"] is True, r
        final = broken.read_text()
        # data-loss: survivor() is gone, only the verbatim output remains.
        assert "survivor" not in final, (
            "If survivor() survives, the fallback became a real merge (gap fixed)")
        assert final == "def replacement():\n    return 2\n"


# --------------------------------------------------------------------------- #
# B4 — class-body additive merge recursion cap (documented data-loss boundary)
# --------------------------------------------------------------------------- #
class TestB4RecursionCap:
    def _nested(self, levels, leaf_stmts):
        """Build `levels` nested classes; innermost class body is leaf_stmts
        (a list of single-line statements)."""
        lines = []
        for i in range(levels):
            lines.append("    " * i + f"class C{i}:")
        inner_indent = "    " * levels
        for stmt in leaf_stmts:
            lines.append(inner_indent + stmt)
        return "\n".join(lines) + "\n"

    def test_inner_attr_survives_within_cap(self):
        """At depth <=5 the additive merge preserves a target-only inner attr."""
        target = self._nested(5, ["keep = 1", "drop = 2"])
        output = self._nested(5, ["drop = 99"])
        merged = gi._ast_merge(output, target)
        assert "keep" in merged, "within-cap inner attr was dropped"
        assert "drop = 99" in merged

    def test_inner_attr_dropped_beyond_cap(self):
        """GAP (documented boundary, NOT a bug to fix): at depth 6 the merge
        falls back to wholesale agent replacement and the target-only inner
        attribute is DROPPED."""
        target = self._nested(6, ["keep = 1", "drop = 2"])
        output = self._nested(6, ["drop = 99"])
        merged = gi._ast_merge(output, target)
        # depth-6 class body is replaced wholesale -> 'keep' lost.
        assert "keep" not in merged, (
            "If 'keep' survives, the recursion cap was raised past 5")
