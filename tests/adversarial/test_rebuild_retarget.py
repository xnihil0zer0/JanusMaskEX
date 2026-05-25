"""Regression-lock the 4 retarget invariants of the clean-room rebuild engine.

These four details are LAW (see memory feedback-rebuild-engine-retarget): when
``harness.rebuild.loop`` dispatches a unit into an OUT-OF-TREE output repo, the
worker MUST be invoked (1) by FILE PATH (not ``python -m``), (2) with cwd = the
output repo (Claude's acceptEdits write boundary), (3) with ``PYTHONPATH``
scrubbed, and (4) with all ``JANUSMASK_*`` env scrubbed. Getting any wrong cost
two keystone re-runs in session #31. We also lock ``task._k_expr``'s
snake/de-underscored/CamelCase OR so ``pytest -k`` matches ``TestIsPrime``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import harness.rebuild.loop as loop
import harness.rebuild.task as task
from harness.rebuild.target import TargetDescriptor


def _descriptor(tmp_path: Path) -> TargetDescriptor:
    return TargetDescriptor(
        name="t",
        source_root=tmp_path / "src",
        modules=["m.py"],
        test_files=[],
        output_dir=tmp_path / "out",
        stash_dir=tmp_path / "stash",
    )


def test_worker_invoked_by_file_path_not_dash_m(tmp_path):
    descriptor = _descriptor(tmp_path)
    cmd, _cwd, _env = loop.build_worker_invocation(descriptor, "RB_t_foo")
    assert "-m" not in cmd, "worker must be invoked by file path, never python -m"
    # cmd[0] is the interpreter; cmd[1] is the worker FILE.
    assert cmd[1].endswith("orchestrator_worker.py"), cmd
    assert Path(cmd[1]).is_absolute()
    assert cmd[0] == sys.executable


def test_cwd_is_output_repo(tmp_path):
    descriptor = _descriptor(tmp_path)
    _cmd, cwd, _env = loop.build_worker_invocation(descriptor, "RB_t_foo")
    assert cwd == str(descriptor.output_dir)
    assert cwd != str(loop.PARENT_ROOT)


def test_env_scrubs_pythonpath_and_janusmask(tmp_path):
    descriptor = _descriptor(tmp_path)
    dirty = {
        "PYTHONPATH": "/home/xnihil0zer0/JanusMask",
        "JANUSMASK_FOO": "1",
        "JANUSMASK_PHASE": "META",
        "PATH": "/usr/bin",
        "HOME": "/home/x",
    }
    _cmd, _cwd, env = loop.build_worker_invocation(descriptor, "RB_t_foo", env=dirty)
    assert "PYTHONPATH" not in env, "PYTHONPATH would shadow the reconstructed module"
    assert not any(k.startswith("JANUSMASK_") for k in env), "JANUSMASK_* must be scrubbed"
    # Unrelated env is preserved so the worker still runs.
    assert env["PATH"] == "/usr/bin"
    assert env["HOME"] == "/home/x"


def test_task_id_and_state_dir_target_output_repo(tmp_path):
    descriptor = _descriptor(tmp_path)
    cmd, _cwd, _env = loop.build_worker_invocation(descriptor, "RB_t_foo")
    assert "--task-id" in cmd
    assert cmd[cmd.index("--task-id") + 1] == "RB_t_foo"
    state_dir = cmd[cmd.index("--state-dir") + 1]
    assert state_dir == str(descriptor.output_dir / "state")
    config = cmd[cmd.index("--config") + 1]
    assert config == str(loop.PARENT_ROOT / "harness" / "config.yaml")


def test_k_expr_matches_function_and_camel_class_anchored():
    # #39: the -k expression ANCHORS to the author convention boundaries --
    # `test_<unit>` for functions and `Test<Camel>` for classes -- so a bare token
    # can't collide with a sibling unit's test (see the collision test below).
    expr = task._k_expr("is_prime")
    assert expr.startswith("'") and expr.endswith("'"), "must be single-quoted for the shell"
    inner = expr.strip("'")
    variants = [v.strip() for v in inner.split(" or ")]
    assert "test_is_prime_" in variants
    assert "TestIsPrime" in variants
    # the function-form variant matches a `test_is_prime_*` node id
    assert any(v in "test_m.py::test_is_prime_basic" for v in variants)


def test_k_expr_single_word_no_redundant_variants():
    expr = task._k_expr("gcd")
    inner = expr.strip("'")
    variants = [v.strip() for v in inner.split(" or ")]
    assert "test_gcd_" in variants
    assert "TestGcd" in variants
    assert "" not in variants


def test_k_expr_dunder_method_keeps_internal_underscores():
    # #37/#39: a dunder unit must yield a variant that substring-matches a test
    # named `test_post_init_*` (internal underscores preserved). The anchored
    # `test_<stripped>` form (`test_post_init`) does so.
    expr = task._k_expr("__post_init__")
    inner = expr.strip("'")
    variants = [v.strip() for v in inner.split(" or ")]
    assert "test_post_init_" in variants, variants
    node_id = "test_target_generated.py::test_post_init_resolves_paths"
    assert any(v and v in node_id for v in variants), variants


def test_k_expr_does_not_collide_with_sibling_unit_test():
    # #39 (inflection): unit `_irregular` must NOT select sibling `pluralize`'s
    # `test_pluralize_irregular_word` (which contains the bare token "irregular"
    # and exercises the still-stubbed pluralize). The anchored `test_irregular`
    # form does not substring-match that node id; the OLD bare `irregular` did.
    expr = task._k_expr("_irregular")
    variants = [v.strip() for v in expr.strip("'").split(" or ")]
    sibling = "test_inflection_generated.py::test_pluralize_irregular_word"
    own = "test_inflection_generated.py::test_irregular_inserts_rules"
    assert any(v in own for v in variants), variants
    assert not any(v in sibling for v in variants), variants


def test_k_expr_prefix_unit_does_not_select_longer_sibling():
    # #39 (inflection): `ordinal` is a PREFIX of `ordinalize`. The bare token
    # `test_ordinal` substring-matches `test_ordinalize_keeps_sign` (a sibling's
    # still-stubbed test). The trailing-underscore boundary `test_ordinal_` does
    # not, while still matching `test_ordinal_suffixes`.
    variants = [v.strip() for v in task._k_expr("ordinal").strip("'").split(" or ")]
    own = "test_inflection_generated.py::test_ordinal_suffixes"
    sibling = "test_inflection_generated.py::test_ordinalize_keeps_sign"
    assert any(v in own for v in variants), variants
    assert not any(v in sibling for v in variants), variants
