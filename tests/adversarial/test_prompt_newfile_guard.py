"""Regression oracle for OWNER_HANDEDIT_PROPOSALS_2026-06-09 §4a.

BYPASS_FUZZER tasks used to receive the ``__JANUSMASK_PATCHES__`` partial-edit
dispatch even when every ``files_touched`` target was a file that does not
exist yet. Patches cannot CREATE a file (git_integration's apply path), so a
``harness_plumbing`` task creating a new single file dead-ended at
``auto_commit_failed``. The NEW-FILE GUARD must route any task whose targets
are not all present on disk to the whole-file prompt instead.
"""
import inspect

from harness.orchestrator import BYPASS_FUZZER_TYPES, prepare_task_prompt

_ABSENT = 'autocompiler/zz_newfile_guard_absent_target.py'
_PRESENT = 'harness/orchestrator.py'


def _task(files, mtt='harness_plumbing', **extra):
    t = {'task_id': 'newfile-guard-oracle', 'meta_task_type': mtt, 'files_touched': files}
    t.update(extra)
    return t


def test_precondition_harness_plumbing_bypasses_fuzzer():
    # The guard is only reachable for fuzzer-bypassed meta-types; pin the fixture.
    assert 'harness_plumbing' in BYPASS_FUZZER_TYPES


def test_new_file_bypass_fuzzer_gets_no_patches_block():
    prompt = prepare_task_prompt(_task([_ABSENT]))
    assert '__JANUSMASK_PATCHES__' not in prompt


def test_partial_edit_flag_on_new_file_gets_no_patches_block():
    prompt = prepare_task_prompt(_task([_ABSENT], mtt='cli_tooling', partial_edit=True))
    assert '__JANUSMASK_PATCHES__' not in prompt


def test_existing_file_bypass_fuzzer_still_gets_patches_block():
    prompt = prepare_task_prompt(_task([_PRESENT]))
    assert '__JANUSMASK_PATCHES__' in prompt


def test_mixed_existing_and_absent_py_targets_get_manifest_not_patches():
    # >1 file routes to the verbatim manifest regardless; the guard must not
    # resurrect patches for the multi-file shape.
    prompt = prepare_task_prompt(_task([_PRESENT, _ABSENT]))
    assert '__JANUSMASK_PATCHES__' not in prompt
    assert '__JANUSMASK_MANIFEST__' in prompt


def test_empty_files_touched_gets_no_patches_block():
    # No declared targets -> nothing provably present -> safe whole-file prompt.
    prompt = prepare_task_prompt(_task([]))
    assert '__JANUSMASK_PATCHES__' not in prompt


def test_guard_is_wired_into_prepare_task_prompt():
    src = inspect.getsource(prepare_task_prompt)
    assert '_targets_exist' in src, 'NEW-FILE GUARD (§4a) missing from prepare_task_prompt'
