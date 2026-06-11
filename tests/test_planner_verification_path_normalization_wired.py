"""RED oracle: the planner deterministically canonicalizes a REVERSED external
oracle verification path (``ngv2/tests/test_x_wired.py`` -> ``tests/ngv2/test_x_wired.py``).

THE BUG (observed repeatedly across NGv2 epics): when the JM planner decomposes
an external (NobleGreedv2, working_dir=/home/xnihil0zer0/NobleGreedv2) multi-leaf
brief, a blind draft sometimes emits a leaf's ``verification_command`` with the
test path REVERSED -- ``pytest ngv2/tests/test_<x>_wired.py`` -- when the real
oracle lives at ``tests/ngv2/test_<x>_wired.py`` (repo-root ``tests/`` package,
``ngv2`` subdir). reconciliation/normalization does NOT repair the order, so the
reversed token survives into the staged task. pytest then exits 4 ("file or
directory not found" / "no tests ran") -> verification_failed -> auto_commit_failed,
blocking the leaf. The instability is which draft token wins reconciliation: some
leaves got the correct ``tests/ngv2/...`` form, others the reversed one, with no
deterministic backstop to canonicalize either way.

THE CONTRACT (the durable, deterministic fix this oracle pins): a new pure pass
``_canonicalize_oracle_paths(plan, repo_root)`` in ``harness.planner.plan_normalizer``,
threaded into ``normalize_plan`` BEFORE the oracle-file-resolving passes
(``_sanitize_impl_verification_commands`` / ``_force_smoke_gated_leaf_impl`` /
``_inject_oracle_sources``), rewrites every ``.py`` token in a task's
``verification_command`` that does NOT resolve under ``repo_root`` but whose
``<pkg>/tests/...`` <-> ``tests/<pkg>/...`` swap DOES resolve to an existing file.

Properties asserted:
  * REVERSED external token is repaired to the on-disk ``tests/<pkg>/...`` form.
  * an already-correct ``tests/ngv2/...`` command is left unchanged (idempotent).
  * a SELF/JM ``tests/test_bar.py`` command is left unchanged (no spurious swap).

RED today: ``_canonicalize_oracle_paths`` does not exist (ImportError) and
``normalize_plan`` does not repair the reversed path.
"""
from __future__ import annotations

import pathlib

import pytest


def _write(root: pathlib.Path, rel: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("def test_placeholder():\n    assert True\n", encoding="utf-8")


def _vc(plan, task_id):
    for t in plan["tasks"]:
        if t.get("task_id") == task_id:
            return t.get("verification_command")
    raise AssertionError("task %r not in plan" % (task_id,))


def _ext_leaf(task_id, vcmd):
    return {
        "task_id": task_id,
        "title": task_id,
        "meta_task_type": "orchestration",
        "priority": "high",
        "dependencies": [],
        "files_touched": ["ngv2/%s.py" % task_id],
        "acceptance_criteria": [],
        "spec_author": None,
        "estimated_complexity": "m",
        "verification_command": vcmd,
        "spec": {"objective": "build ngv2/%s.py" % task_id,
                 "implementation_notes": ""},
    }


# ---------------------------------------------------------------------------
# 1. The helper exists and is importable (ImportError => RED).
# ---------------------------------------------------------------------------

def test_canonicalize_oracle_paths_is_importable():
    from harness.planner.plan_normalizer import _canonicalize_oracle_paths  # noqa: F401


# ---------------------------------------------------------------------------
# 2. Direct helper: reversed external token is repaired to the on-disk form.
# ---------------------------------------------------------------------------

def test_reversed_external_path_is_repaired(tmp_path):
    from harness.planner.plan_normalizer import _canonicalize_oracle_paths
    _write(tmp_path, "tests/ngv2/test_foo_wired.py")  # the REAL on-disk location
    plan = {"tasks": [_ext_leaf(
        "foo", "pytest ngv2/tests/test_foo_wired.py")]}
    out = _canonicalize_oracle_paths(plan, repo_root=tmp_path)
    assert _vc(out, "foo") == "pytest tests/ngv2/test_foo_wired.py"


def test_reversed_external_path_repaired_preserves_other_tokens(tmp_path):
    from harness.planner.plan_normalizer import _canonicalize_oracle_paths
    _write(tmp_path, "tests/ngv2/test_bar_wired.py")
    plan = {"tasks": [_ext_leaf(
        "bar", "python -m pytest ngv2/tests/test_bar_wired.py -q")]}
    out = _canonicalize_oracle_paths(plan, repo_root=tmp_path)
    assert _vc(out, "bar") == "python -m pytest tests/ngv2/test_bar_wired.py -q"


# ---------------------------------------------------------------------------
# 3. Idempotent on an already-correct external command.
# ---------------------------------------------------------------------------

def test_correct_external_path_is_unchanged(tmp_path):
    from harness.planner.plan_normalizer import _canonicalize_oracle_paths
    _write(tmp_path, "tests/ngv2/test_foo_wired.py")
    correct = "pytest tests/ngv2/test_foo_wired.py"
    plan = {"tasks": [_ext_leaf("foo", correct)]}
    out = _canonicalize_oracle_paths(plan, repo_root=tmp_path)
    assert _vc(out, "foo") == correct
    # second application is a strict no-op (idempotent)
    out2 = _canonicalize_oracle_paths(out, repo_root=tmp_path)
    assert _vc(out2, "foo") == correct


# ---------------------------------------------------------------------------
# 4. SELF/JM command is left untouched (no spurious swap).
# ---------------------------------------------------------------------------

def test_self_jm_path_is_unchanged(tmp_path):
    from harness.planner.plan_normalizer import _canonicalize_oracle_paths
    _write(tmp_path, "tests/test_bar.py")
    self_cmd = "pytest tests/test_bar.py"
    plan = {"tasks": [{
        "task_id": "selffix",
        "meta_task_type": "harness_self_fix",
        "files_touched": ["harness/foo.py"],
        "dependencies": [],
        "verification_command": self_cmd,
        "spec": {"objective": "x", "implementation_notes": ""},
    }]}
    out = _canonicalize_oracle_paths(plan, repo_root=tmp_path)
    assert _vc(out, "selffix") == self_cmd


def test_unresolvable_token_left_unchanged(tmp_path):
    """A token that resolves NEITHER as-is NOR swapped is left alone (no I/O
    guess), so a genuinely-missing oracle is not silently rewritten."""
    from harness.planner.plan_normalizer import _canonicalize_oracle_paths
    missing = "pytest ngv2/tests/test_missing_wired.py"
    plan = {"tasks": [_ext_leaf("missing", missing)]}
    out = _canonicalize_oracle_paths(plan, repo_root=tmp_path)
    assert _vc(out, "missing") == missing


# ---------------------------------------------------------------------------
# 5. Wired through the public normalize_plan entry point.
# ---------------------------------------------------------------------------

def test_normalize_plan_repairs_reversed_external_path(tmp_path):
    from harness.planner.plan_normalizer import normalize_plan
    _write(tmp_path, "tests/ngv2/test_foo_wired.py")
    plan = {"tasks": [_ext_leaf(
        "foo", "pytest ngv2/tests/test_foo_wired.py")]}
    out = normalize_plan(plan, repo_root=tmp_path)
    assert _vc(out, "foo") == "pytest tests/ngv2/test_foo_wired.py"


def test_normalize_plan_repo_root_none_is_noop(tmp_path):
    """With repo_root=None there is no filesystem to resolve against, so the
    reversed command must be left exactly as-is (pure, no I/O)."""
    from harness.planner.plan_normalizer import normalize_plan
    reversed_cmd = "pytest ngv2/tests/test_foo_wired.py"
    plan = {"tasks": [_ext_leaf("foo", reversed_cmd)]}
    out = normalize_plan(plan, repo_root=None)
    assert _vc(out, "foo") == reversed_cmd


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-x", "-q"]))
