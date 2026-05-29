"""Adversarial battery for the partial-edit / patches sidecar apply path.

Plan: adversarial_test_plans/02_apply_commit_validation_fuzzing.md §C (C1-C5).
Targets _apply_symbol_patch, _apply_region_patch, _parse_patches, and
_commit_accepted_output_patches compose-correctness.
"""
from __future__ import annotations

import json
import os
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
    (repo / "pkg").mkdir(parents=True)
    (repo / "state" / "output").mkdir(parents=True)
    _git(["init", "-q", "-b", "main"], repo)
    _git(["config", "user.email", "t@t"], repo)
    _git(["config", "user.name", "t"], repo)
    _git(["commit", "--allow-empty", "-qm", "root"], repo)
    return repo


# --------------------------------------------------------------------------- #
# C1 — symbol patch with mismatched leaf name -> ValueError -> committed=False
# --------------------------------------------------------------------------- #
class TestC1MismatchedLeaf:
    def test_apply_symbol_patch_rejects_renamed_symbol(self):
        src = "def foo():\n    return 1\n"
        with pytest.raises(ValueError):
            gi._apply_symbol_patch(src, "foo", "def bar():\n    return 2\n")

    def test_commit_path_rejects_and_leaves_target_unmodified(self, tmp_repo):
        sd = tmp_repo / "state"
        target = tmp_repo / "pkg" / "m.py"
        target.write_text("def foo():\n    return 1\n")
        _git(["add", "pkg/m.py"], tmp_repo)
        _git(["commit", "-qm", "seed"], tmp_repo)
        before = target.read_text()
        (sd / "output" / "C1.patches.json").write_text(json.dumps([
            {"file": "pkg/m.py", "kind": "symbol", "name": "foo",
             "code": "def bar():\n    return 2\n"}]))
        r = gi.commit_accepted_output(
            "C1", str(target), sd, worktree_root=tmp_repo,
            allowed_files={"pkg/m.py"}, meta_task_type=None, approval_ok=False)
        assert r["committed"] is False
        assert "patch apply failed" in (r["error"] or "")
        assert target.read_text() == before


# --------------------------------------------------------------------------- #
# C2 — region patch with duplicate / inverted sentinels
# --------------------------------------------------------------------------- #
class TestC2RegionSentinels:
    def test_duplicate_start_sentinel_keyerror(self):
        src = ("# JANUSMASK_REGION:X\n"
               "old\n"
               "# JANUSMASK_REGION:X\n"
               "# JANUSMASK_ENDREGION:X\n")
        with pytest.raises(KeyError):
            gi._apply_region_patch(src, "X", "new\n")

    def test_end_before_start_valueerror(self):
        src = ("# JANUSMASK_ENDREGION:X\n"
               "old\n"
               "# JANUSMASK_REGION:X\n")
        with pytest.raises(ValueError):
            gi._apply_region_patch(src, "X", "new\n")


# --------------------------------------------------------------------------- #
# C3 — multiple symbol patches to one file compose with shifting offsets
# --------------------------------------------------------------------------- #
class TestC3ComposeOffsets:
    def test_two_symbol_patches_compose(self, tmp_repo):
        sd = tmp_repo / "state"
        target = tmp_repo / "pkg" / "two.py"
        # 'top' is long (above 'bottom'); shortening it shifts bottom's offsets.
        target.write_text(
            "def top():\n"
            "    a = 1\n"
            "    b = 2\n"
            "    c = 3\n"
            "    return a + b + c\n"
            "\n"
            "def bottom():\n"
            "    return 100\n")
        _git(["add", "pkg/two.py"], tmp_repo)
        _git(["commit", "-qm", "seed"], tmp_repo)
        (sd / "output" / "C3.patches.json").write_text(json.dumps([
            {"file": "pkg/two.py", "kind": "symbol", "name": "top",
             "code": "def top():\n    return 0\n"},
            {"file": "pkg/two.py", "kind": "symbol", "name": "bottom",
             "code": "def bottom():\n    return 200\n"}]))
        r = gi.commit_accepted_output(
            "C3", str(target), sd, worktree_root=tmp_repo,
            allowed_files={"pkg/two.py"}, meta_task_type=None, approval_ok=False)
        assert r["committed"] is True, r
        final = target.read_text()
        assert "return 0" in final, "first patch did not land"
        assert "return 200" in final, "second patch (post-shift) did not land"
        assert "a = 1" not in final


# --------------------------------------------------------------------------- #
# C4 — region patch on a non-.py target (language-agnostic)
# --------------------------------------------------------------------------- #
class TestC4NonPyRegion:
    def test_region_patch_on_js_target_with_hash_sentinels(self, tmp_repo):
        """The region patch is text-only (no ast.parse), so a .js target
        round-trips — BUT the sentinel token is hardcoded to the Python
        comment form '# JANUSMASK_REGION:'. A .js file must therefore embed
        '#'-prefixed sentinel lines (not '//')."""
        sd = tmp_repo / "state"
        target = tmp_repo / "pkg" / "app.js"
        target.write_text(
            "const x = 1;\n"
            "# JANUSMASK_REGION:body\n"
            "old();\n"
            "# JANUSMASK_ENDREGION:body\n"
            "const y = 2;\n")
        _git(["add", "pkg/app.js"], tmp_repo)
        _git(["commit", "-qm", "seed-js"], tmp_repo)
        (sd / "output" / "C4.patches.json").write_text(json.dumps([
            {"file": "pkg/app.js", "kind": "region", "marker": "body",
             "code": "fresh();\n"}]))
        r = gi.commit_accepted_output(
            "C4", str(target), sd, worktree_root=tmp_repo,
            allowed_files={"pkg/app.js"}, meta_task_type=None, approval_ok=False)
        assert r["committed"] is True, r
        final = target.read_text()
        assert "fresh();" in final
        assert "old();" not in final
        assert "const x = 1;" in final and "const y = 2;" in final

    def test_js_style_slashslash_sentinels_not_recognized(self):
        """GAP (documented): the 'language-agnostic' region patch only
        recognizes the Python '# JANUSMASK_REGION:' sentinel. A genuine JS
        '// JANUSMASK_REGION:body' comment is NOT matched -> KeyError (zero
        start sentinels). The language-agnostic claim is narrower than it
        reads: text-agnostic on the BODY, but Python-comment-bound on the
        SENTINEL syntax."""
        src = ("// JANUSMASK_REGION:body\n"
               "old();\n"
               "// JANUSMASK_ENDREGION:body\n")
        with pytest.raises(KeyError):
            gi._apply_region_patch(src, "body", "fresh();\n")


# --------------------------------------------------------------------------- #
# C5 — _parse_patches rejects non-string code value
# --------------------------------------------------------------------------- #
class TestC5ParsePatchesValidation:
    def test_non_string_code_returns_none(self):
        # code value is an int (ast.Constant int, not str) -> None
        code = ("__JANUSMASK_PATCHES__ = ["
                "{'file': 'a.py', 'kind': 'symbol', 'name': 'f', 'code': 1}]")
        assert gi._parse_patches(code) is None

    def test_fstring_code_returns_none(self):
        # f-string is a JoinedStr, not a Constant -> None
        code = ("__JANUSMASK_PATCHES__ = ["
                "{'file': 'a.py', 'kind': 'symbol', 'name': 'f', 'code': f'x'}]")
        assert gi._parse_patches(code) is None

    def test_concatenation_code_returns_none(self):
        # 'a' + 'b' is a BinOp, not a single Constant -> None
        code = ("__JANUSMASK_PATCHES__ = ["
                "{'file': 'a.py', 'kind': 'symbol', 'name': 'f', 'code': 'a' + 'b'}]")
        assert gi._parse_patches(code) is None

    def test_valid_symbol_patch_parses(self):
        code = ("__JANUSMASK_PATCHES__ = ["
                "{'file': 'a.py', 'kind': 'symbol', 'name': 'f', 'code': 'def f():\\n    pass\\n'}]")
        parsed = gi._parse_patches(code)
        assert parsed and parsed[0]["name"] == "f"

    def test_unknown_kind_returns_none(self):
        code = ("__JANUSMASK_PATCHES__ = ["
                "{'file': 'a.py', 'kind': 'whole', 'name': 'f', 'code': 'x'}]")
        assert gi._parse_patches(code) is None
