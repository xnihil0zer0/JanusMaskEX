"""MD_SERIALIZE behavioral oracle (REV25 §3 / MD-SERIALIZE = M-D6 pt1).

A STATEFUL FuzzFailure (produced by stateful_differential_fuzz) carries
step-dict / ('error', repr) tuple / 'ok' string values in result_a/result_b
(NOT ExecutionResult), plus an action_sequence and a divergent_step_index.

On HEAD:
  * FuzzFailure declares only 5 fields; action_sequence/divergent_step_index
    are setattr-injected at orchestrator.py:817 (dynamically present only).
  * serialize_failure._result_summary dereferences result.timed_out/.success/
    .return_repr -> AttributeError on the stateful (non-ExecutionResult)
    result values -> hard crash propagating through prepare_exam_packets.

The fix:
  * promote action_sequence / divergent_step_index to real Optional fields on
    FuzzFailure (remove the setattr block);
  * make serialize_failure detect a stateful failure (action_sequence is not
    None) and summarize the action sequence + divergent step instead of
    dereferencing ExecutionResult.

RED on HEAD: constructing FuzzFailure(action_sequence=...) raises TypeError
(unexpected kwarg) AND serialize_failure on a stateful failure AttributeErrors.
"""
import pytest

from harness.diff_fuzzer import FuzzFailure
from harness.cross_examiner import serialize_failure


def _make_stateful_failure():
    # init_args + ordered (method, args) calls; diverged at step index 1.
    action_sequence = ([5], [("inc", [1]), ("inc", [1])])
    return FuzzFailure(
        input_args=[5],
        input_kwargs={},
        result_a=("error", "ValueError('a')"),
        result_b="ok",
        reason="stateful divergence at step 1",
        action_sequence=action_sequence,
        divergent_step_index=1,
    )


def test_fuzzfailure_has_real_stateful_fields():
    # field-promotion: these must be real constructor params, not setattr-injected.
    f = _make_stateful_failure()
    assert f.action_sequence is not None
    assert f.divergent_step_index == 1


def test_serialize_failure_summarizes_stateful_trace_no_crash():
    f = _make_stateful_failure()
    out = serialize_failure(f)  # must NOT raise AttributeError on HEAD's path
    # The serialized dict must surface the action sequence + divergent step,
    # NOT an ExecutionResult-style {"status": ...} summary that ignores them.
    blob = repr(out)
    assert "inc" in blob, "serialized stateful failure must include the action sequence"
    assert "1" in blob  # divergent step index surfaced somewhere
    assert out.get("reason") == "stateful divergence at step 1"


def test_stateless_failure_path_unchanged():
    from harness.sandbox import ExecutionResult
    a = ExecutionResult(success=True, return_value=42, return_repr="42")
    b = ExecutionResult(success=True, return_value=99, return_repr="99")
    f = FuzzFailure(input_args=[1], input_kwargs={}, result_a=a, result_b=b,
                    reason="return_mismatch")
    out = serialize_failure(f)
    assert out["result_a"]["status"] == "success"
    assert out["result_a"]["return_value"] == "42"
