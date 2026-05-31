"""Fix-detector oracle for PHASE_A2_PROMPT_FRAMING (test_authoring prompt framing).

Phase A.2 inserts ONE branch into ``harness.orchestrator.prepare_task_prompt``:

    if mtt == 'test_authoring':
        prompt += '\\nTEST-AUTHORING DISPATCH:\\n\\n...'

placed AFTER the if/elif partial-edit/multi-file manifest block and BEFORE the
optional ``if spec_summary:`` tail. For a single-file task whose
``meta_task_type`` is ``test_authoring`` (bypass_fuzzer:False), neither the
partial-edit branch (:867) nor the multi-file manifest branch (:871) fires, so
the base whole-file prompt is used; this branch reframes that base prompt as a
test-authoring dispatch — instructing the agent to author a whole pytest TEST
FILE (not a __JANUSMASK_PATCHES__ list, not a __JANUSMASK_MANIFEST__ dict),
import the module(s) under test, and be NON-VACUOUS (checked against a mutant).

GENUINE fail-then-pass detector:
  (A)/(B) FAIL on HEAD (no branch -> framing substrings absent).
  (C) passes pre- and post-fix (guards the branch against firing for other
      meta_task_types).
"""

from harness.orchestrator import prepare_task_prompt


def test_test_authoring_task_emits_dispatch_framing():
    """(A) DISCRIMINATING: a single-file test_authoring task is reframed as a
    test-authoring dispatch — RED on HEAD (branch absent)."""
    prompt = prepare_task_prompt({
        "task_id": "X",
        "meta_task_type": "test_authoring",
        "files_touched": ["tests/adversarial/test_x.py"],
    })
    assert "TEST-AUTHORING DISPATCH" in prompt
    assert "NON-VACUOUS" in prompt
    assert "pytest TEST FILE" in prompt


def test_test_authoring_prompt_instructs_whole_file_not_patches():
    """(B) The test-authoring framing explicitly forbids the patch-list channel
    — the agent must submit a whole test file, not a __JANUSMASK_PATCHES__ list.
    RED on HEAD."""
    prompt = prepare_task_prompt({
        "task_id": "X",
        "meta_task_type": "test_authoring",
        "files_touched": ["tests/adversarial/test_x.py"],
    })
    assert "DO NOT emit a __JANUSMASK_PATCHES__" in prompt


def test_non_test_authoring_task_has_no_dispatch_framing():
    """(C) CONTROL: a non-test_authoring task (here a partial-edit
    harness_self_fix) must NOT contain the test-authoring framing. Passes both
    pre- and post-fix; guards against the branch firing for other types."""
    prompt = prepare_task_prompt({
        "task_id": "Y",
        "meta_task_type": "harness_self_fix",
        "files_touched": ["harness/x.py"],
        "partial_edit": True,
    })
    assert "TEST-AUTHORING DISPATCH" not in prompt
