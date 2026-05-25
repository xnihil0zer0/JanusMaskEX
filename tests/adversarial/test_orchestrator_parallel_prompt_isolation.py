"""Adversarial regression bar for AW10 — per-task current_task path (R-PARALLEL-1).

Background: ``harness/orchestrator_worker.py:94`` writes the task spec to a
SHARED ``state/tasks/current_task.json``. The agent prompt at
``harness/orchestrator.py:670`` directs both Claude and Gemini to read from
that single path. When two workers dispatch in parallel on dissimilar tasks
(the autowork daemon's primary use case), the later writer CLOBBERS the
earlier task's spec — both agents read the wrong spec, both submit the wrong
code, and one or both rounds rolls back via verification failure.

This test pins two contracts AW10 is required to satisfy:

1. ``harness.orchestrator.prepare_task_prompt`` interpolates the task_id
   into the per-task spec path so each worker's agent sees a distinct path.
2. Two distinct task_ids produce two distinct embedded current_task path
   strings in the resulting prompts — the race surface is gone at the
   prompt-template level.

Pattern mirrors session #14 G27/G28 and session #17 AW9c: META commit lands
the test with ``xfail(strict=False, reason=...)``. AW10's
verification_command runs pytest with ``--runxfail`` so the markers are
bypassed at gate time; the post-AW10 META commit drops the markers and the
tests pass naturally.
"""
from __future__ import annotations

import re

import pytest


def test_prompt_template_interpolates_task_id() -> None:
    """Each agent's prompt must reference a per-task current_task path."""
    from harness.orchestrator import prepare_task_prompt

    prompt = prepare_task_prompt(
        {"task_id": "PROMPT_TID_XYZ", "specification": "demo task"}
    )

    assert "current_task_PROMPT_TID_XYZ.json" in prompt, (
        "AW10 contract: prepare_task_prompt must embed the per-task spec path "
        f"current_task_<task_id>.json. Prompt head was: {prompt[:600]!r}"
    )
    assert "{STATE_DIR}/tasks/current_task.json" not in prompt, (
        "AW10 contract: the shared current_task.json path must NOT appear in "
        f"the prompt. Prompt head was: {prompt[:600]!r}"
    )


def test_parallel_workers_write_distinct_specs() -> None:
    """Two parallel workers on dissimilar tasks must see distinct spec paths."""
    from harness.orchestrator import prepare_task_prompt

    prompt_a = prepare_task_prompt({"task_id": "TASK_AAA", "specification": "A"})
    prompt_b = prepare_task_prompt({"task_id": "TASK_BBB", "specification": "B"})

    path_re = re.compile(r"\{STATE_DIR\}/tasks/current_task[^\s`]*\.json")
    paths_a = set(path_re.findall(prompt_a))
    paths_b = set(path_re.findall(prompt_b))

    assert paths_a, f"no current_task path found in prompt_a: {prompt_a[:600]!r}"
    assert paths_b, f"no current_task path found in prompt_b: {prompt_b[:600]!r}"

    assert any("TASK_AAA" in p for p in paths_a), (
        f"TASK_AAA missing from prompt_a paths: {paths_a}"
    )
    assert any("TASK_BBB" in p for p in paths_b), (
        f"TASK_BBB missing from prompt_b paths: {paths_b}"
    )

    assert paths_a != paths_b, (
        "AW10 contract: parallel workers on dissimilar tasks must see distinct "
        f"current_task paths in their prompts. Got identical: {paths_a}"
    )
