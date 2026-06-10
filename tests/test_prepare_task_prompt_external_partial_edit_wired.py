"""RED oracle — ``prepare_task_prompt`` must emit the PARTIAL-EDIT prompt for
EXTERNAL EDIT targets that EXIST under the task's effective target root.

Root cause under test: ``prepare_task_prompt`` resolves ``files_touched``
against ``PROJECT_DIR`` (the JanusMask repo root) when deciding whether to
offer the ``__JANUSMASK_PATCHES__`` partial-edit prompt. For an EXTERNAL task
(``working_dir`` outside the repo) an existing target lives under the external
root, NOT under ``PROJECT_DIR`` — so the existence check is False, the agent
gets the WHOLE-FILE prompt, emits a cosmetic whole-file rewrite, and the
commit path's ``whole_file_drift`` guard rejects it. The fix resolves the
candidates against ``harness.paths.effective_target_root(working_dir)``.

Contract pinned here:
  (a) EXTERNAL EDIT, target EXISTS under working_dir  -> PARTIAL-EDIT prompt
      (RED today: prompt omits it because targets resolve against PROJECT_DIR).
  (b) EXTERNAL NEW,  target ABSENT under working_dir  -> WHOLE-FILE prompt
      (NEW-FILE GUARD: patches cannot create files; passes before and after).
  (c) SELF EDIT, target EXISTS at PROJECT_DIR          -> PARTIAL-EDIT prompt
      (proves the self path is unaffected; passes before and after).

The external cases use a hermetic tmp dir (not NGv2) so the test does not
couple to any sibling checkout. ``effective_target_root`` resolves a non-self
``working_dir`` to ``Path(working_dir).resolve()``, so a tmp dir is a valid
external target root.
"""
import os

import pytest

from harness.orchestrator import prepare_task_prompt

_PARTIAL_MARKER = "PARTIAL-EDIT DISPATCH"
_PATCHES_TOKEN = "__JANUSMASK_PATCHES__"


@pytest.fixture()
def external_root(tmp_path):
    """A hermetic external (non-repo) target root holding one real .py file.

    Lives under pytest's tmp_path, which is OUTSIDE the JanusMask repo tree, so
    ``effective_target_root`` classifies the working_dir as external (non-self).
    """
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "mod.py").write_text(
        "def existing_symbol() -> int:\n    return 1\n", encoding="utf-8"
    )
    return tmp_path


def test_external_edit_existing_target_emits_partial_edit_prompt(external_root):
    """(a) EXTERNAL EDIT of an EXISTING file must offer the partial-edit prompt.

    RED today: ``_targets_exist`` is computed against PROJECT_DIR, where
    ``pkg/mod.py`` does not exist, so the whole-file prompt is emitted instead.
    """
    task = {
        "task_id": "ext-edit-existing",
        "working_dir": str(external_root),
        "files_touched": ["pkg/mod.py"],
        "meta_task_type": "validation",
        "specification": "edit an existing external symbol in place",
    }
    prompt = prepare_task_prompt(task)
    assert _PARTIAL_MARKER in prompt, (
        "external EDIT of an existing target must emit the PARTIAL-EDIT prompt; "
        "files_touched must resolve against effective_target_root(working_dir), "
        "not PROJECT_DIR"
    )
    assert _PATCHES_TOKEN in prompt


def test_external_new_absent_target_emits_whole_file_prompt(external_root):
    """(b) EXTERNAL NEW target (absent in the external root) must NOT get patches.

    NEW-FILE GUARD: partial-edit patches cannot create files, so an absent
    target must fall through to the whole-file prompt. Passes before and after
    the fix — it locks the guard.
    """
    task = {
        "task_id": "ext-new-absent",
        "working_dir": str(external_root),
        "files_touched": ["pkg/absent.py"],
        "meta_task_type": "validation",
        "specification": "create a brand new external module",
    }
    prompt = prepare_task_prompt(task)
    assert _PARTIAL_MARKER not in prompt, (
        "an absent (NEW) external target must get the whole-file prompt; "
        "patches cannot create files (NEW-FILE GUARD)"
    )


def test_self_edit_existing_target_still_emits_partial_edit_prompt():
    """(c) SELF EDIT of an existing repo file must still get the partial-edit prompt.

    Proves the fix does not regress the self path. ``working_dir=None`` ->
    effective_target_root is PROJECT_ROOT, where harness/orchestrator.py exists.
    Passes before and after the fix.
    """
    rel = os.path.join("harness", "orchestrator.py")
    task = {
        "task_id": "self-edit-existing",
        "working_dir": None,
        "files_touched": [rel],
        "meta_task_type": "validation",
        "specification": "edit a large self file in place",
    }
    prompt = prepare_task_prompt(task)
    assert _PARTIAL_MARKER in prompt
    assert _PATCHES_TOKEN in prompt
