"""Adversarial regression bar for AW10 — per-task current_task path (R-PARALLEL-1).

Background: ``harness/orchestrator_worker.py:94`` writes the task spec to a
SHARED ``state/tasks/current_task.json``. The agent prompt at
``harness/orchestrator.py:670`` directs both Claude and Gemini to read from
that single path. When two workers dispatch in parallel on dissimilar tasks
(the autowork daemon's primary use case), the later writer CLOBBERS the
earlier task's spec — both agents read the wrong spec, both submit the wrong
code, and one or both rounds rolls back via verification failure.

AGENT-ISOLATION §3.5 supersedes the original AW10 mechanism. The race is now
closed by a STRONGER guarantee: the prompt directs both agents to read the spec
from ``{WORK_DIR}/inbox/task.json`` — a per-SPAWN staged copy — and spawn_agent
resolves ``{WORK_DIR}`` to a unique, outside-the-repo workdir per spawn (its
slug embeds task_id + a uuid). So two parallel workers can never read or clobber
a shared spec: each reads its own staged inbox copy. These tests pin the new
contract:

1. ``prepare_task_prompt`` points agents at ``{WORK_DIR}/inbox/task.json`` and
   never at the shared ``{STATE_DIR}/tasks/current_task.json`` race surface.
2. Per-spawn ``{WORK_DIR}`` uniqueness (the actual isolation) is verified at the
   spawn layer — see tests/adversarial/test_P4_planner_flow_attacks.py
   ::test_outbox_path_is_per_agent and tests/adversarial/test_agent_isolation.py.
"""
from __future__ import annotations

import pytest


def test_prompt_template_points_at_per_spawn_inbox() -> None:
    """The prompt must read the spec from the per-spawn staged inbox copy."""
    from harness.orchestrator import prepare_task_prompt

    prompt = prepare_task_prompt(
        {"task_id": "PROMPT_TID_XYZ", "specification": "demo task"}
    )

    assert "{WORK_DIR}/inbox/task.json" in prompt, (
        "AGENT-ISOLATION §3.5: prepare_task_prompt must direct agents to the "
        f"per-spawn staged spec {{WORK_DIR}}/inbox/task.json. Prompt head: {prompt[:600]!r}"
    )
    # The shared (race-prone) current_task path must NOT leak into the prompt.
    assert "{STATE_DIR}/tasks/current_task.json" not in prompt
    assert "{STATE_DIR}/tasks/current_task_" not in prompt


def test_prompt_template_is_spawn_isolated_not_state_shared() -> None:
    """Prompts for dissimilar tasks must both route through the per-spawn inbox,
    never a shared {STATE_DIR} spec path — isolation moved to {WORK_DIR}."""
    from harness.orchestrator import prepare_task_prompt

    prompt_a = prepare_task_prompt({"task_id": "TASK_AAA", "specification": "A"})
    prompt_b = prepare_task_prompt({"task_id": "TASK_BBB", "specification": "B"})

    for p in (prompt_a, prompt_b):
        assert "{WORK_DIR}/inbox/task.json" in p, (
            f"prompt must read spec from per-spawn inbox: {p[:600]!r}"
        )
        # No shared, task-id-free state spec path that two workers could clobber.
        assert "{STATE_DIR}/tasks/current_task" not in p, (
            f"shared current_task path leaked into prompt: {p[:600]!r}"
        )
