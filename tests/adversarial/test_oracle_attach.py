"""Contract for the planner stage that attaches a generated oracle.

Proves the planner-side integration of the independent test-author role:
- a test-less task gets a generated, non-vacuous verification_command;
- a task that already has one is left untouched;
- self-modification of harness/ is left for operator review (guard intact).
"""

from __future__ import annotations

import pytest

import harness.planner.oracle_attach as oa
from harness.planner.oracle_attach import attach_oracle, task_needs_oracle
from harness.test_author import VacuousOracleError

REAL_SOURCE = "def add(a, b):\n    return a + b\n"
GOOD_TEST = "from calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n"
VACUOUS_TEST = "def test_t():\n    assert True\n"


def _gen(test_code):
    def gen_fn(prompt, *, session_dir, attempt):
        return (test_code, "python -m pytest test_calc_oracle.py -q")
    return gen_fn


def test_module_api():
    assert hasattr(oa, "attach_oracle") and hasattr(oa, "task_needs_oracle")


def test_task_needs_oracle():
    assert task_needs_oracle({"task_id": "T"}) is True
    assert task_needs_oracle({"verification_command": "  "}) is True
    assert task_needs_oracle({"verification_command": "pytest -q"}) is False


def test_attach_to_testless_task(tmp_path):
    task = {"task_id": "T", "files_touched": ["calc.py"], "specification": "calc"}
    out = attach_oracle(
        task, REAL_SOURCE, "calc", {}, tmp_path / "state", gen_fn=_gen(GOOD_TEST)
    )
    assert out["verification_command"]
    assert out["generated_oracle"]["test_code"] == GOOD_TEST
    assert out["generated_oracle"]["test_filename"].endswith(".py")


def test_existing_vcmd_untouched(tmp_path):
    task = {"task_id": "T", "verification_command": "pytest -q", "files_touched": ["calc.py"]}
    out = attach_oracle(
        task, REAL_SOURCE, "calc", {}, tmp_path / "state", gen_fn=_gen(GOOD_TEST)
    )
    assert out["verification_command"] == "pytest -q"
    assert "generated_oracle" not in out


def test_self_modification_left_for_operator(tmp_path):
    task = {"task_id": "T", "files_touched": ["harness/foo.py"]}
    out = attach_oracle(
        task, REAL_SOURCE, "foo", {}, tmp_path / "state", gen_fn=_gen(GOOD_TEST)
    )
    # guard: no oracle attached for a self-modification target
    assert task_needs_oracle(out) is True
    assert "generated_oracle" not in out
    # explicit opt-in lifts the guard
    out2 = attach_oracle(
        dict(task), REAL_SOURCE, "foo", {}, tmp_path / "state",
        gen_fn=_gen(GOOD_TEST), allow_self_modification=True,
    )
    assert out2["verification_command"]


def test_vacuous_oracle_propagates(tmp_path):
    task = {"task_id": "T", "files_touched": ["calc.py"]}
    with pytest.raises(VacuousOracleError):
        attach_oracle(
            task, REAL_SOURCE, "calc", {}, tmp_path / "state",
            gen_fn=_gen(VACUOUS_TEST), max_attempts=2,
        )
