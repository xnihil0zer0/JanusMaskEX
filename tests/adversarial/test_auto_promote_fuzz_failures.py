"""B3 (AUTO_PROMOTE_FUZZ_FAILURES) oracle.

Divergent-round FuzzFailures must be folded into task['specification'] as
fail-safe, additive, idempotent, capped boundary COMMENT HINTS, re-persisted to
BOTH on-disk task files, and surfaced by prepare_task_prompt on the next round.

Pins:
  (i)   a divergent round APPENDS the generated hints to task['specification']
        AND to the persisted task file(s) on disk;
  (ii)  ADDITIVE (existing spec preserved) + IDEMPOTENT (call twice -> one append,
        via the '# JANUSMASK_PROMOTED_FUZZ_TESTS' marker) + NEVER-CRASHES
        (empty failures, odd/non-eval-able objects);
  (iii) prepare_task_prompt surfaces the promoted hints on the next round;
  (iv)  the cap (<=8 promoted) is honored; the helper returns None and never raises.

This is a genuine fix-detector: orchestrator._promote_fuzz_failures_to_tests does
not exist on the unfixed code, so every test errors until B3 adds it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import harness.orchestrator as orch

MARKER = '# JANUSMASK_PROMOTED_FUZZ_TESTS'


@dataclass
class _ER:
    """Minimal stand-in for harness.sandbox.ExecutionResult."""
    return_repr: str = ""
    return_value: Any = None


@dataclass
class _FF:
    """Minimal stand-in for harness.diff_fuzzer.FuzzFailure (duck-typed)."""
    input_args: list = field(default_factory=list)
    input_kwargs: dict = field(default_factory=dict)
    result_a: Any = None
    result_b: Any = None
    reason: str = ""


def _make_task(spec="Original spec body."):
    return {
        "task_id": "B3_ORACLE",
        "specification": spec,
        "constraints": {"function_signature": "def normalize(x: int) -> int"},
    }


def _stage(tmp_path: Path, task: dict) -> Path:
    """Write the two on-disk task files the helper must rewrite; return state_dir."""
    state_dir = tmp_path
    tasks_dir = state_dir / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    tid = task["task_id"]
    (tasks_dir / f"current_task_{tid}.json").write_text(json.dumps(task, indent=2), encoding="utf-8")
    (tasks_dir / f"{tid}.json.processing").write_text(json.dumps(task, indent=2), encoding="utf-8")
    return state_dir


def _failures():
    return [
        _FF(input_args=[0], input_kwargs={}, result_a=_ER(return_repr="0"), reason="zero boundary"),
        _FF(input_args=[-1], input_kwargs={"y": None}, result_a=_ER(return_repr="-1"), reason="negative"),
    ]


def test_promote_appends_boundary_hints_to_specification(tmp_path):
    task = _make_task()
    state_dir = _stage(tmp_path, task)
    before = task["specification"]

    rv = orch._promote_fuzz_failures_to_tests(task, _failures(), state_dir)

    assert rv is None
    spec = task["specification"]
    assert before in spec                 # additive
    assert MARKER in spec
    assert "normalize(" in spec           # target name from function_signature
    assert "result == 0" in spec          # from result_a.return_repr
    assert "result == -1" in spec
    assert "reason: zero boundary" in spec
    assert "# boundary 0:" in spec        # comment hint, not an assert
    assert "assert " not in spec


def test_promote_persists_to_both_task_files(tmp_path):
    task = _make_task()
    state_dir = _stage(tmp_path, task)
    orch._promote_fuzz_failures_to_tests(task, _failures(), state_dir)

    cur = json.loads((state_dir / "tasks" / "current_task_B3_ORACLE.json").read_text())
    proc = json.loads((state_dir / "tasks" / "B3_ORACLE.json.processing").read_text())
    assert MARKER in cur["specification"]
    assert MARKER in proc["specification"]
    assert "normalize(" in cur["specification"]
    assert "normalize(" in proc["specification"]


def test_promote_is_idempotent_via_marker(tmp_path):
    task = _make_task()
    state_dir = _stage(tmp_path, task)
    orch._promote_fuzz_failures_to_tests(task, _failures(), state_dir)
    once = task["specification"]
    orch._promote_fuzz_failures_to_tests(task, _failures(), state_dir)
    twice = task["specification"]
    assert once == twice
    assert twice.count(MARKER) == 1


def test_promote_failsafe_on_odd_objects_and_empty(tmp_path):
    # empty failures -> clean no-op, spec unchanged
    task = _make_task()
    state_dir = _stage(tmp_path, task)
    before = task["specification"]
    assert orch._promote_fuzz_failures_to_tests(task, [], state_dir) is None
    assert task["specification"] == before

    # None failures -> no-op, no raise
    assert orch._promote_fuzz_failures_to_tests(task, None, state_dir) is None

    # non-eval-able / odd objects -> still no raise, still appended as a comment hint
    class _Weird:
        def __repr__(self):
            return "<ast.FunctionDef object at 0x7fff>"

    odd = [_FF(input_args=[Path("/tmp/x"), _Weird()], input_kwargs={},
               result_a=_ER(return_repr="<obj>"), reason="odd")]
    task2 = _make_task()
    state_dir2 = _stage(tmp_path / "two", task2)
    assert orch._promote_fuzz_failures_to_tests(task2, odd, state_dir2) is None
    assert MARKER in task2["specification"]
    assert "# boundary 0:" in task2["specification"]

    # missing constraints -> placeholder name, no crash
    task3 = {"task_id": "B3_NOSIG", "specification": "s"}
    state_dir3 = _stage(tmp_path / "three", task3)
    assert orch._promote_fuzz_failures_to_tests(task3, _failures(), state_dir3) is None
    assert "target(" in task3["specification"]

    # missing on-disk files -> tolerated
    task4 = _make_task()
    bare_state = tmp_path / "bare"
    (bare_state / "tasks").mkdir(parents=True, exist_ok=True)
    assert orch._promote_fuzz_failures_to_tests(task4, _failures(), bare_state) is None
    assert MARKER in task4["specification"]


def test_prepare_task_prompt_surfaces_promoted_hints(tmp_path):
    task = _make_task()
    state_dir = _stage(tmp_path, task)
    orch._promote_fuzz_failures_to_tests(task, _failures(), state_dir)
    prompt = orch.prepare_task_prompt(task)
    assert MARKER in prompt
    assert "normalize(" in prompt
    assert "result == 0" in prompt


def test_promote_cap_honored(tmp_path):
    task = _make_task()
    state_dir = _stage(tmp_path, task)
    many = [_FF(input_args=[i], input_kwargs={}, result_a=_ER(return_repr=str(i)),
                reason=f"r{i}") for i in range(20)]
    orch._promote_fuzz_failures_to_tests(task, many, state_dir)
    spec = task["specification"]
    assert "# boundary 7:" in spec        # at most 8 (indices 0..7)
    assert "# boundary 8:" not in spec
