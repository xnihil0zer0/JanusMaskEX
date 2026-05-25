"""Pin META-AST-IO-ADAPTER carve-out: io_adapter and logging_observability
meta_task_types are exempt from the AST validator's nondeterminism check
(time.time, datetime.now, os.urandom).

Mirrors the W113-pattern: tests pin both the positive carve-out behavior and
a negative-control proving other meta_task_types remain strict.
"""
import inspect
import textwrap

import pytest

from harness import orchestrator
from harness.ast_enforcer import validate_code


_NONDET_SAMPLE = textwrap.dedent(
    """
    import time
    def heartbeat():
        return time.time()
    """
)


def _make_task(meta_task_type, deterministic=None):
    task = {
        "task_id": "T",
        "meta_task_type": meta_task_type,
        "files_touched": ["foo.py"],
    }
    if deterministic is not None:
        task["constraints"] = {"deterministic": deterministic}
    return task


@pytest.mark.parametrize("mtt", ["io_adapter", "logging_observability"])
def test_carveout_meta_task_types_allow_time_time(mtt):
    task = _make_task(mtt)
    valid, violations = orchestrator._validate_submission(_NONDET_SAMPLE, "claude", task)
    assert valid, f"{mtt} should bypass nondeterminism check; got violations={violations!r}"
    assert not any(v.severity == "error" and v.rule == "nondeterminism" for v in violations), (
        f"unexpected nondeterminism error for {mtt}: {violations!r}"
    )


@pytest.mark.parametrize("mtt", ["docs_writing", "synthesis", None])
def test_carveout_does_not_apply_to_other_meta_task_types(mtt):
    task = _make_task(mtt) if mtt is not None else {"task_id": "T"}
    valid, violations = orchestrator._validate_submission(_NONDET_SAMPLE, "claude", task)
    assert not valid, f"{mtt} should still trigger nondeterminism rejection; violations={violations!r}"
    assert any(v.rule == "nondeterminism" and v.severity == "error" for v in violations), (
        f"expected nondeterminism error for {mtt}, got {violations!r}"
    )


def test_explicit_constraints_deterministic_false_still_works():
    """Pre-existing escape hatch via constraints.deterministic=False unchanged."""
    task = {"task_id": "T", "meta_task_type": "test_unit", "constraints": {"deterministic": False}}
    valid, _ = orchestrator._validate_submission(_NONDET_SAMPLE, "claude", task)
    assert valid


def test_constraints_meta_task_type_fallback_path_honored():
    """The carve-out falls back to constraints.meta_task_type when top-level absent."""
    task = {"task_id": "T", "constraints": {"meta_task_type": "io_adapter"}}
    valid, _ = orchestrator._validate_submission(_NONDET_SAMPLE, "claude", task)
    assert valid


def test_static_source_pin_carveout_present_in_validate_submission():
    """Static-source pin: ensure the meta_task_type carve-out remains in the
    function and is gated correctly. Catches accidental removal.
    """
    src = inspect.getsource(orchestrator._validate_submission)
    assert "meta_task_type" in src, "carve-out reference removed"
    assert "io_adapter" in src, "io_adapter carve-out removed"
    assert "logging_observability" in src, "logging_observability carve-out removed"
    # Ordering: carve-out must come AFTER the constraints.deterministic check
    # so explicit operator opt-in still wins.
    det_idx = src.index("deterministic")
    carve_idx = src.index("io_adapter")
    assert det_idx < carve_idx, "carve-out must come after deterministic check"


def test_validate_code_directly_unchanged_still_strict():
    """Direct calls to validate_code (no task context) remain strict — only
    the orchestrator wrapper applies the carve-out. Pins ast_enforcer.py
    behavior is not regressed.
    """
    violations = validate_code(_NONDET_SAMPLE, allow_nondeterminism=False)
    assert any(v.rule == "nondeterminism" and v.severity == "error" for v in violations)


def test_static_source_pin_carveout_present_in_hooks():
    """Pin META-AST-IO-ADAPTER-HOOKS: the same carve-out lives at all 3
    hook-layer enforcement sites that wrap rpc_submit_code validation.

    Without these, the orchestrator wrapper would relax but the hook would
    still deny gemini's write_file with 'Tool execution blocked: Fix
    violations' — exactly the second-order failure that hit D1 re-dispatch.
    """
    from harness.hooks import _decide_common
    from harness.hooks.claude import post_tool as claude_post_tool
    from harness.hooks.gemini import post_tool as gemini_post_tool

    for module, name in [
        (_decide_common, "decide_submission"),
        (claude_post_tool, "_persist_submission"),
        (gemini_post_tool, "_persist_submission"),
    ]:
        src = inspect.getsource(getattr(module, name))
        assert "meta_task_type" in src, f"{module.__name__}.{name} missing meta_task_type carve-out"
        assert "io_adapter" in src, f"{module.__name__}.{name} missing io_adapter carve-out"
        assert "logging_observability" in src, (
            f"{module.__name__}.{name} missing logging_observability carve-out"
        )
        det_idx = src.index("deterministic")
        carve_idx = src.index("io_adapter")
        assert det_idx < carve_idx, (
            f"{module.__name__}.{name} carve-out must come after deterministic check "
            "so explicit operator opt-in still wins"
        )
