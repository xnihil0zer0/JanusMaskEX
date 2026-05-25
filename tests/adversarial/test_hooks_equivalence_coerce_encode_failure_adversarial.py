"""W115 adversarial — hooks_equivalence._coerce silent JSON-encode failure.

Pre-fix: harness/hooks_equivalence.py drain_divergence_to_dict() defines a
nested _coerce() helper that wraps json.dumps and swallows
(TypeError, ValueError) silently, returning repr(x) as an opaque fallback.
Operators could not distinguish successful encoding from coerced fallback
when reading drain reports.

Post-fix: the except clause emits a stderr trace including type(x).__name__
and str(exc) before returning repr(x), mirroring the existing
stderr-only convention used throughout hooks_equivalence.py (L150, L228,
L268, L608, etc.). _ledger is not reachable from this module (operates at
the shadow-equivalence layer, not the ledger-event layer), so stderr-only
is the architecturally correct shape — same precedent as W109's read_events
fix inside _ledger.py itself.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

import harness.hooks_equivalence as he  # noqa: E402


class _Unserializable:
    """An object whose default-str fallback also raises."""

    def __repr__(self) -> str:
        return "<Unserializable>"

    def __str__(self) -> str:  # pragma: no cover — TypeError pathway
        raise TypeError("str() refuses too")


class _DummyDivergence:
    def __init__(self, baseline, actual):
        self.field = "test_field"
        self.baseline = baseline
        self.actual = actual
        self.detail = {}


# -- Static source pin (shape contract) -----------------------------------


class TestStaticSourcePin:
    def test_coerce_emits_stderr_trace_before_repr_fallback(self) -> None:
        src = inspect.getsource(he.drain_divergence_to_dict)
        # The except branch must contain a sys.stderr.write call before
        # returning repr(x).
        assert "sys.stderr.write" in src
        assert "_coerce JSON-encode failed" in src
        assert "type(x).__name__" in src
        assert "return repr(x)" in src
        # Order: stderr write before repr fallback in the except branch.
        stderr_pos = src.find("sys.stderr.write")
        repr_pos = src.find("return repr(x)")
        assert stderr_pos != -1 and repr_pos != -1
        assert stderr_pos < repr_pos


# -- Behavioural — non-serializable inputs go through coerce + stderr ----


class TestNonSerializableInputs:
    def test_set_baseline_emits_stderr_and_returns_repr(self, capsys) -> None:
        # set is not JSON-serializable and json.dumps default=str doesn't
        # know what to do with it without our own default → TypeError.
        # Note: json.dumps(set(), default=str) actually succeeds because
        # str(set()) is well-defined. Use a circular-ref dict instead to
        # force a real TypeError.
        circ: dict = {}
        circ["self"] = circ
        out = he.drain_divergence_to_dict(_DummyDivergence(circ, "ok"))
        # baseline got coerced to repr(x), actual passed through.
        assert isinstance(out["baseline"], str)
        assert out["actual"] == "ok"
        err = capsys.readouterr().err
        assert "[hooks_equivalence] _coerce JSON-encode failed" in err
        assert "dict" in err

    def test_unserializable_actual_emits_stderr(self, capsys) -> None:
        circ: list = []
        circ.append(circ)
        out = he.drain_divergence_to_dict(_DummyDivergence("ok", circ))
        assert out["baseline"] == "ok"
        assert isinstance(out["actual"], str)
        err = capsys.readouterr().err
        assert "[hooks_equivalence] _coerce JSON-encode failed" in err
        assert "list" in err


# -- Negative control — well-formed input → no stderr --------------------


class TestNegativeControl:
    def test_serializable_inputs_emit_no_stderr(self, capsys) -> None:
        out = he.drain_divergence_to_dict(
            _DummyDivergence({"k": 1}, [1, 2, 3])
        )
        assert out["baseline"] == {"k": 1}
        assert out["actual"] == [1, 2, 3]
        assert "_coerce JSON-encode failed" not in capsys.readouterr().err
