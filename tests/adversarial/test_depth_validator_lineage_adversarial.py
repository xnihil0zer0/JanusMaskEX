"""Adversarial battery for harness.depth_validator.check_true_depth.

Plan: adversarial_test_plans/02_apply_commit_validation_fuzzing.md §D (D1-D4).
Targets parent_task/parent_task_id precedence, cycle/self-parent guard, the
depth boundary off-by-one, and the input-guard fail-closed paths.

f1a746b touched this file with a whitespace-only "fix" (no behavior change) —
these tests pin the boundary the callers actually rely on.
"""
from __future__ import annotations

import json

import pytest

from harness.depth_validator import check_true_depth


def _write_task(tasks_dir, task_id, **fields):
    fields.setdefault("task_id", task_id)
    (tasks_dir / f"{task_id}.json").write_text(json.dumps(fields))


@pytest.fixture
def tasks_dir(tmp_path):
    d = tmp_path / "tasks"
    d.mkdir()
    (d / "processed").mkdir()
    return d


# --------------------------------------------------------------------------- #
# D1 — parent_task vs parent_task_id precedence + mixed-key lineage
# --------------------------------------------------------------------------- #
class TestD1KeyPrecedence:
    def test_parent_task_preferred_over_parent_task_id(self, tasks_dir):
        # child carries BOTH; parent_task ('P_real') is preferred. P_real is a
        # root (depth 2 total). The decoy 'P_decoy' does not exist, so if it
        # were followed the walk would return False (file not found).
        _write_task(tasks_dir, "P_real")
        _write_task(tasks_dir, "child", parent_task="P_real",
                    parent_task_id="P_decoy")
        # depth: child(1) -> P_real(2). Under max_depth=3 -> True.
        assert check_true_depth("child", tasks_dir, max_depth=3) is True
        # If parent_task_id were followed instead, P_decoy is missing -> False.
        # Confirm the decoy alone fails:
        _write_task(tasks_dir, "child2", parent_task_id="P_decoy")
        assert check_true_depth("child2", tasks_dir, max_depth=3) is False

    def test_mixed_key_chain_followed_across_generations(self, tasks_dir):
        """parent uses parent_task_id, child uses parent_task — the walk must
        follow both, not silently truncate."""
        _write_task(tasks_dir, "gp")  # grandparent root
        _write_task(tasks_dir, "p", parent_task_id="gp")  # uses _id
        _write_task(tasks_dir, "c", parent_task="p")       # uses bare
        # chain c(1)->p(2)->gp(3); max_depth=3 -> True, max_depth=2 -> False
        assert check_true_depth("c", tasks_dir, max_depth=3) is True
        assert check_true_depth("c", tasks_dir, max_depth=2) is False


# --------------------------------------------------------------------------- #
# D2 — cycle and self-parent
# --------------------------------------------------------------------------- #
class TestD2Cycles:
    def test_self_parent_returns_false(self, tasks_dir):
        _write_task(tasks_dir, "selfie", parent_task="selfie")
        assert check_true_depth("selfie", tasks_dir, max_depth=10) is False

    def test_a_b_a_cycle_returns_false_no_hang(self, tasks_dir):
        _write_task(tasks_dir, "A", parent_task="B")
        _write_task(tasks_dir, "B", parent_task="A")
        assert check_true_depth("A", tasks_dir, max_depth=100) is False


# --------------------------------------------------------------------------- #
# D3 — depth boundary off-by-one
# --------------------------------------------------------------------------- #
class TestD3Boundary:
    def test_chain_of_exactly_max_depth_is_true(self, tasks_dir):
        # depth increments at top of loop; a chain of N files yields depth==N.
        # max_depth=3 chain: t1->t2->t3 (t3 root) -> depth 3 -> True.
        _write_task(tasks_dir, "t3")
        _write_task(tasks_dir, "t2", parent_task="t3")
        _write_task(tasks_dir, "t1", parent_task="t2")
        assert check_true_depth("t1", tasks_dir, max_depth=3) is True

    def test_chain_of_max_depth_plus_one_is_false(self, tasks_dir):
        _write_task(tasks_dir, "u4")
        _write_task(tasks_dir, "u3", parent_task="u4")
        _write_task(tasks_dir, "u2", parent_task="u3")
        _write_task(tasks_dir, "u1", parent_task="u2")
        # chain u1->u2->u3->u4 = depth 4 > max_depth 3 -> False
        assert check_true_depth("u1", tasks_dir, max_depth=3) is False


# --------------------------------------------------------------------------- #
# D4 — degenerate inputs fail closed
# --------------------------------------------------------------------------- #
class TestD4DegenerateInputs:
    def test_empty_string_parent_returns_false(self, tasks_dir):
        _write_task(tasks_dir, "e", parent_task="")
        # parent_task present but empty-string -> caught by isinstance/empty guard
        assert check_true_depth("e", tasks_dir, max_depth=3) is False

    def test_non_string_parent_returns_false(self, tasks_dir):
        _write_task(tasks_dir, "n", parent_task=123)
        assert check_true_depth("n", tasks_dir, max_depth=3) is False

    def test_tasks_dir_bool_returns_false(self):
        assert check_true_depth("x", True, max_depth=3) is False

    def test_empty_task_id_returns_false(self, tasks_dir):
        assert check_true_depth("", tasks_dir, max_depth=3) is False

    def test_root_task_no_parent_is_true(self, tasks_dir):
        _write_task(tasks_dir, "root")
        assert check_true_depth("root", tasks_dir, max_depth=3) is True
