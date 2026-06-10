"""RED oracle: route non-Python / multi-file bypass-fuzzer edits to the
VERBATIM ``__JANUSMASK_MANIFEST__`` whole-file path instead of the Python-only
``__JANUSMASK_PATCHES__`` symbol-patch path.

Root cause (HANDOFF_multifile_nonpython_edits.md §1): in
``harness.orchestrator.prepare_task_prompt`` the ``mtt in BYPASS_FUZZER_TYPES``
guard is checked FIRST and is true for every safe edit type
(``harness_plumbing``, ``harness_self_fix`` ...). So a non-Python (``.js`` /
``.css`` / ``.yaml``) or multi-file edit leaf is forced into the PARTIAL-EDIT
dispatch (branch A), whose applier ``_apply_symbol_patch`` is pure ``ast.parse``
and CANNOT apply a non-Python file -> ``ast.parse`` raises -> rollback -> the
structural oracle fails. The verbatim whole-file apply already exists
(``git_integration._apply_file_to_target`` non-``.py`` arm writes verbatim); the
bug is purely DISPATCH ROUTING.

Fix: a module-level predicate ``_requires_verbatim_manifest(files_touched)`` ->
True when the leaf touches > 1 file OR any non-``.py`` target. ``prepare_task_prompt``
must route those leaves to the ``__JANUSMASK_MANIFEST__`` branch even when
``mtt in BYPASS_FUZZER_TYPES``; a single ``.py`` edit STILL uses the patches path.

Tests 1-2 FAIL on HEAD (RED -> the routing bug) and pass after the fix. Tests
3-6 are regression / guardrail invariants that must hold both before and after.
"""
from __future__ import annotations

import json
import subprocess

import pathlib

import pytest

from harness import git_integration
from harness.orchestrator import prepare_task_prompt, _save_final_output


# Markers that uniquely identify which dispatch block the prompt emitted.
_MANIFEST_TOKEN = "__JANUSMASK_MANIFEST__"
_MANIFEST_HEADER = "MULTI-FILE DISPATCH"
_PATCHES_HEADER = "PARTIAL-EDIT DISPATCH"


def _git(args, cwd):
    subprocess.run(
        ["git"] + args, cwd=str(cwd), check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )


# ---------------------------------------------------------------------------
# 1. multi-file non-Python bypass leaf -> MANIFEST dispatch (RED on HEAD)
# ---------------------------------------------------------------------------
def test_prepare_prompt_multifile_nonpy_routes_to_manifest():
    task = {
        "task_id": "t-frontend",
        "meta_task_type": "harness_plumbing",  # in BYPASS_FUZZER_TYPES
        "files_touched": [
            "tools/webui_static/app.js",
            "tools/webui_static/styles.css",
        ],
    }
    prompt = prepare_task_prompt(task)
    assert _MANIFEST_TOKEN in prompt and _MANIFEST_HEADER in prompt, (
        "multi-file non-Python bypass leaf must get the __JANUSMASK_MANIFEST__ "
        "(verbatim whole-file) dispatch"
    )
    assert _PATCHES_HEADER not in prompt, (
        "multi-file non-Python bypass leaf was forced into the PARTIAL-EDIT "
        "(Python-only symbol-patch) dispatch -- that path cannot apply .js/.css"
    )


# ---------------------------------------------------------------------------
# 2. single non-Python bypass leaf -> MANIFEST dispatch (RED on HEAD)
# ---------------------------------------------------------------------------
def test_prepare_prompt_single_nonpy_routes_to_manifest():
    task = {
        "task_id": "t-config",
        "meta_task_type": "harness_self_fix",  # in BYPASS_FUZZER_TYPES
        "files_touched": ["harness/config.yaml"],
    }
    prompt = prepare_task_prompt(task)
    assert _MANIFEST_TOKEN in prompt, (
        "single non-Python bypass leaf (config.yaml) must get the verbatim "
        "__JANUSMASK_MANIFEST__ dispatch, not the symbol-patch dispatch"
    )
    assert _PATCHES_HEADER not in prompt, (
        "single non-Python bypass leaf was forced into the PARTIAL-EDIT "
        "(ast.parse) dispatch -- ast.parse on YAML raises -> rollback"
    )


# ---------------------------------------------------------------------------
# 3. REGRESSION: single .py bypass leaf STILL uses the patches path
# ---------------------------------------------------------------------------
def test_prepare_prompt_single_py_still_uses_patches():
    task = {
        "task_id": "t-webui-control",
        "meta_task_type": "harness_plumbing",
        "files_touched": ["tools/webui_control.py"],
    }
    prompt = prepare_task_prompt(task)
    assert _PATCHES_HEADER in prompt, (
        "single .py bypass leaf must keep using the working __JANUSMASK_PATCHES__ "
        "symbol-patch dispatch (webui_control proved it works)"
    )
    assert _MANIFEST_TOKEN not in prompt, (
        "single .py bypass leaf must NOT be re-routed to the manifest dispatch"
    )


# ---------------------------------------------------------------------------
# 4. GUARDRAIL: _save_final_output for a manifest writes .files.json (not .patches)
# ---------------------------------------------------------------------------
def test_save_final_output_manifest_writes_files_sidecar(tmp_path):
    state_dir = tmp_path / "state"
    (state_dir / "output").mkdir(parents=True)
    task_id = "t-save-manifest"
    code = (
        "__JANUSMASK_MANIFEST__ = {\n"
        "    'a.js': r'''console.log(1);\n''',\n"
        "    'b.css': r''':root { color: red; }\n''',\n"
        "}\n"
    )
    _save_final_output(state_dir, task_id, code)
    files_sidecar = state_dir / "output" / f"{task_id}.files.json"
    patches_sidecar = state_dir / "output" / f"{task_id}.patches.json"
    assert files_sidecar.exists(), "manifest submission must emit a .files.json sidecar"
    assert not patches_sidecar.exists(), "manifest submission must NOT emit a .patches.json sidecar"
    saved = json.loads(files_sidecar.read_text(encoding="utf-8"))
    assert saved == {"a.js": "console.log(1);\n", "b.css": ":root { color: red; }\n"}


# ---------------------------------------------------------------------------
# 5. END-TO-END: a manifest commit lands non-Python files VERBATIM (one commit)
# ---------------------------------------------------------------------------
def test_commit_manifest_lands_nonpy_files_verbatim(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(["init", "-q"], root)
    _git(["config", "user.email", "nonpy@test"], root)
    _git(["config", "user.name", "nonpy"], root)
    app = root / "app.js"
    styles = root / "styles.css"
    app.write_text("// OLD\n", encoding="utf-8")
    styles.write_text("/* OLD */\n", encoding="utf-8")
    _git(["add", "-A"], root)
    _git(["commit", "-q", "-m", "init"], root)
    head_before = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(root),
        check=True, stdout=subprocess.PIPE,
    ).stdout.decode().strip()

    state_dir = root / "state"
    out_dir = state_dir / "output"
    out_dir.mkdir(parents=True)
    task_id = "t-commit-manifest"
    new_app = "function chatIsOpen() { return false; }\n// NEW\n"
    new_styles = ":root { --mode-tier-r: #0f0; }\n"
    manifest = {"app.js": new_app, "styles.css": new_styles}
    (out_dir / f"{task_id}.files.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )

    result = git_integration.commit_accepted_output(
        task_id,
        str(app),
        state_dir,
        worktree_root=root,
        meta_task_type="harness_plumbing",
        approval_ok=True,
        working_dir=None,  # SELF
    )

    assert result.get("committed") is True, (
        "manifest commit failed: " + repr(result.get("error"))
    )
    # files landed byte-equal to the manifest values (verbatim, no AST mangling)
    assert app.read_text(encoding="utf-8") == new_app
    assert styles.read_text(encoding="utf-8") == new_styles
    # exactly one new commit
    head_after = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(root),
        check=True, stdout=subprocess.PIPE,
    ).stdout.decode().strip()
    assert head_after != head_before
    parent = subprocess.run(
        ["git", "rev-parse", "HEAD~1"], cwd=str(root),
        check=True, stdout=subprocess.PIPE,
    ).stdout.decode().strip()
    assert parent == head_before, "manifest commit must add exactly one commit"


# ---------------------------------------------------------------------------
# 6. NEGATIVE CONTROL: a symbol patch targeting a .js file fails LOUD
# ---------------------------------------------------------------------------
def test_symbol_patch_on_js_is_rejected_nonsilent():
    js_source = "function boot() {\n  return 1;\n}\n"
    new_block = "function boot() {\n  return 2;\n}\n"
    with pytest.raises((SyntaxError, ValueError, KeyError)):
        git_integration._apply_symbol_patch(js_source, "boot", new_block)
