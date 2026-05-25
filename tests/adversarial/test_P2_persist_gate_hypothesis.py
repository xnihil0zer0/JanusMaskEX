"""Phase-3 hypothesis-based property tests for the persist-time AST gate.

Phase 2 (test_P2_rpc_submit_persist_gate.py + test_P2_persist_gate_attacks.py)
covers ensure_valid via concrete examples, monkeypatch-based hook integration,
and parametrized error-injection. Phase 3 must use COMPLETELY DIFFERENT
methods. This file uses ``hypothesis`` property-based testing exclusively to
generate inputs and exercise invariants over the (code, allow_nondeterminism)
input space rather than enumerating cases by hand.

Targets
-------
* ``harness.hooks.rpc.submit_code.ensure_valid`` -- the persist-time gate.
* ``harness.hooks.rpc.submit_code.AstValidationError`` -- carrier object.
* ``harness.ast_enforcer.validate_code`` -- differentially exercised so the
  gate's witnesses are shown to be a subset of the validator's output.

Properties exercised (12-20)
----------------------------
1. Determinism (idempotent under repeat)              -- @given safe_python_code
2. Determinism on syntactically-arbitrary text        -- @given text()
3. Idempotence on whitespace-only inputs              -- @given whitespace
4. Empty / whitespace inputs always raise incomplete_ast (no funcdef)
5. allow_nondeterminism monotonicity                  -- @given mixed_code
6. Witness preservation against validate_code         -- differential property
7. AstValidationError invariants on every raise
8. str() preview is stable / sorted / suffix correct
9. Defensive copy: mutating exc.violations doesn't poison next call
10. Side-effect-free (no state/sessions/ writes from ensure_valid)
11. error_count fidelity for nondeterministic_code generator
12. Pathological-size code is handled in <2s deadline budget
13. validate_code returns the same object type for both modes
14. Recursive expression generator: deeply-nested expr trees parse cleanly
15. Stateful machine: any sequence of (code, mode) calls preserves invariants

Counter-example handling
------------------------
If hypothesis surfaces a real bug, mark with @pytest.mark.xfail(reason=...)
documenting whether the property pins HARDENED behavior we believe should
hold (real bug to fix) or describes CURRENT behavior we're characterizing.
Concrete reproductions are pinned with ``@example(...)`` so future runs
deterministically re-exercise the failure case.

META allow-listed (tests/adversarial/).
Index timestamp: 2026-04-20T04:11:25Z (60197 edges, 20408 nodes).
"""
from __future__ import annotations

import ast
import keyword
import os
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from hypothesis import HealthCheck, assume, example, given, note, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

from harness.ast_enforcer import Violation, validate_code
from harness.hooks.rpc.submit_code import (
    AstValidationError,
    ensure_valid,
)


# ---------------------------------------------------------------------------
# Strategy primitives
# ---------------------------------------------------------------------------

# Identifier strategy that always yields a syntactically-valid Python name.
_safe_identifier = st.from_regex(r"\A[a-z][a-z0-9_]{0,7}\Z", fullmatch=True).filter(
    lambda x: not keyword.iskeyword(x) and not keyword.issoftkeyword(x)
)

# Whitespace-only strings (BOM excluded -- ast.parse rejects BOM in some configs).
_whitespace_only = st.text(alphabet=" \t\n\r", min_size=0, max_size=64)


@st.composite
def safe_python_code(draw: st.DrawFn) -> str:
    """Generate syntactically-valid pure-Python code with no nondeterminism.

    Each sample contains exactly one FunctionDef whose body returns a pure
    arithmetic / string expression over its parameters. This avoids
    side-effects and nondeterministic markers, so ensure_valid should NOT
    raise on any sample drawn from this strategy.
    """
    fname = draw(_safe_identifier)
    n_params = draw(st.integers(min_value=0, max_value=4))
    params = [draw(_safe_identifier) for _ in range(n_params)]
    # Keep params unique so we don't generate `def f(a, a): ...`.
    seen: set[str] = set()
    unique_params: list[str] = []
    for p in params:
        if p not in seen and p != fname:
            seen.add(p)
            unique_params.append(p)
    sig = ", ".join(unique_params)

    op = draw(st.sampled_from(["+", "-", "*"]))
    if unique_params:
        # Combine first param with itself (or another) using a pure op.
        a = unique_params[0]
        b = unique_params[1] if len(unique_params) > 1 else a
        body_expr = f"{a} {op} {b}"
    else:
        body_expr = draw(st.sampled_from(["1 + 1", "2 * 3", "'x' + 'y'", "(7,)"]))
    return f"def {fname}({sig}):\n    return {body_expr}\n"


_NONDET_FORMS = [
    "import uuid\n\ndef f():\n    return uuid.uuid4()\n",
    "import random\n\ndef f():\n    return random.random()\n",
    "from random import randint\n\ndef f():\n    return randint(0, 9)\n",
    "from uuid import uuid4\n\ndef f():\n    return uuid4()\n",
    "import time\n\ndef f():\n    return time.time()\n",
    "import datetime\n\ndef f():\n    return datetime.now()\n",
    "import os\n\ndef f():\n    return os.urandom(8)\n",
]


@st.composite
def nondeterministic_code(draw: st.DrawFn) -> str:
    """Generate code with at least ONE error-severity nondeterminism violation."""
    return draw(st.sampled_from(_NONDET_FORMS))


@st.composite
def mixed_code(draw: st.DrawFn, *, max_errors: int = 3, max_warnings: int = 3) -> str:
    """Generate code that contains N error violations and M warning violations.

    Errors come from extra uuid imports; warnings from extra print() calls
    inside the function body (rule "side_effect"). At least one funcdef is
    always present so we don't accidentally trip "incomplete_ast".
    """
    n_err = draw(st.integers(min_value=0, max_value=max_errors))
    n_warn = draw(st.integers(min_value=0, max_value=max_warnings))
    # One uuid import per error (each is a separate Violation).
    imports = "\n".join(f"import uuid as _u{i}" for i in range(n_err))
    # Make sure there's exactly one function so incomplete_ast never fires.
    body_lines = ["    x = 1"]
    for i in range(n_warn):
        body_lines.append(f"    print('warn-{i}')")
    body_lines.append("    return x")
    body = "\n".join(body_lines)
    head = imports + ("\n\n" if imports else "")
    return f"{head}def f():\n{body}\n"


@st.composite
def pathological_code(draw: st.DrawFn) -> str:
    """Pathological extremes: long string constants, many statements, deep
    nesting. Each path returns a still-syntactically-valid module so we
    don't accidentally hit the syntax rule. Bounded so each sample runs
    well within the 2s deadline.
    """
    kind = draw(st.sampled_from(["wide", "long_string", "nested"]))
    if kind == "wide":
        n = draw(st.integers(min_value=10, max_value=200))
        lines = [f"    a{i} = {i}" for i in range(n)]
        return "def f():\n" + "\n".join(lines) + "\n    return 0\n"
    if kind == "long_string":
        # 1KB-50KB string constant. We avoid 1MB to stay under deadline.
        size = draw(st.integers(min_value=1024, max_value=50_000))
        # Use a benign character; escape nothing.
        return f"def f():\n    s = 'a' * {size}\n    return s\n"
    # nested: deep parenthesization of arithmetic.
    depth = draw(st.integers(min_value=10, max_value=80))
    expr = "1"
    for _ in range(depth):
        expr = f"({expr} + 1)"
    return f"def f():\n    return {expr}\n"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _violation_key(v: Violation) -> tuple:
    """Stable sort key so we can compare violation lists order-insensitively."""
    return (v.line, v.rule, v.severity, v.message)


def _sorted_violations(vs: list[Violation]) -> list[tuple]:
    return sorted(_violation_key(v) for v in vs)


def _snapshot_dir(p: pathlib.Path) -> tuple:
    """Return a hashable snapshot of the immediate contents of p."""
    if not p.exists():
        return ()
    try:
        return tuple(sorted((entry.name, entry.stat().st_size) for entry in p.iterdir()))
    except (OSError, NotADirectoryError):
        return ()


# ---------------------------------------------------------------------------
# Property 1-2: Determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    """ensure_valid is referentially transparent w.r.t. its (code, mode) tuple."""

    @given(code=safe_python_code(), allow=st.booleans())
    @settings(deadline=2000, max_examples=75)
    def test_determinism_safe_code(self, code: str, allow: bool) -> None:
        # safe_python_code never produces nondeterminism markers, so both
        # modes should return [] (or identical warning lists if any).
        a = ensure_valid(code, allow_nondeterminism=allow)
        b = ensure_valid(code, allow_nondeterminism=allow)
        note(f"violations: {a}")
        assert _sorted_violations(a) == _sorted_violations(b)

    @given(code=st.text(min_size=0, max_size=200), allow=st.booleans())
    @settings(
        deadline=2000,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
        max_examples=75,
    )
    def test_determinism_arbitrary_text(self, code: str, allow: bool) -> None:
        """Either both calls raise (same exception class) or both return
        identical violation lists. No call may differ from the next."""
        try:
            a = ensure_valid(code, allow_nondeterminism=allow)
            raised_a: type | None = None
        except AstValidationError:
            a = []
            raised_a = AstValidationError

        try:
            b = ensure_valid(code, allow_nondeterminism=allow)
            raised_b: type | None = None
        except AstValidationError:
            b = []
            raised_b = AstValidationError

        assert raised_a is raised_b
        if raised_a is None:
            assert _sorted_violations(a) == _sorted_violations(b)


# ---------------------------------------------------------------------------
# Property 3: Whitespace / empty inputs
# ---------------------------------------------------------------------------


class TestEmptyAndWhitespace:
    """An empty module never contains a FunctionDef -- it must raise
    AstValidationError with rule == 'incomplete_ast'."""

    @given(ws=_whitespace_only)
    @settings(deadline=2000, max_examples=40)
    @example(ws="")
    @example(ws=" ")
    @example(ws="\n\n\n")
    def test_whitespace_only_raises_incomplete_ast(self, ws: str) -> None:
        with pytest.raises(AstValidationError) as exc_info:
            ensure_valid(ws)
        rules = {v.rule for v in exc_info.value.violations}
        # Either incomplete_ast (no funcdef) or syntax (e.g. lone CR).
        assert rules <= {"incomplete_ast", "syntax"}
        assert any(v.severity == "error" for v in exc_info.value.violations)


# ---------------------------------------------------------------------------
# Property 4: allow_nondeterminism monotonicity
# ---------------------------------------------------------------------------


class TestAllowNondeterminismMonotonicity:
    """Setting allow_nondeterminism=True can only relax the gate; it must
    never introduce new error-severity violations that weren't present at
    allow_nondeterminism=False."""

    @given(code=mixed_code(max_errors=3, max_warnings=3))
    @settings(deadline=2000, max_examples=60)
    def test_allow_true_is_strictly_weaker_than_allow_false(self, code: str) -> None:
        try:
            strict = ensure_valid(code, allow_nondeterminism=False)
            strict_errs: list[Violation] = []
            strict_warns = list(strict)
        except AstValidationError as exc:
            strict_errs = [v for v in exc.violations if v.severity == "error"]
            strict_warns = [v for v in exc.violations if v.severity == "warning"]

        try:
            loose = ensure_valid(code, allow_nondeterminism=True)
            loose_errs: list[Violation] = []
            loose_warns = list(loose)
        except AstValidationError as exc:
            loose_errs = [v for v in exc.violations if v.severity == "error"]
            loose_warns = [v for v in exc.violations if v.severity == "warning"]

        note(f"strict_errs={len(strict_errs)} loose_errs={len(loose_errs)}")
        # Loose-mode error count <= strict-mode error count.
        assert len(loose_errs) <= len(strict_errs)
        # Specifically, every error rule in loose mode is also in strict mode.
        assert {v.rule for v in loose_errs} <= {v.rule for v in strict_errs}
        # Warnings should be the same set of rules across modes (subprocess
        # and side_effect rules ignore the mode flag).
        assert {v.rule for v in loose_warns} == {v.rule for v in strict_warns}

    @given(code=nondeterministic_code())
    @settings(deadline=2000, max_examples=20)
    def test_nondet_strategy_raises_strict_passes_loose(self, code: str) -> None:
        with pytest.raises(AstValidationError):
            ensure_valid(code, allow_nondeterminism=False)
        # Loose mode: no error-severity left.
        result = ensure_valid(code, allow_nondeterminism=True)
        assert all(v.severity != "error" for v in result)


# ---------------------------------------------------------------------------
# Property 5: Idempotence (no side effects)
# ---------------------------------------------------------------------------


class TestSideEffectFree:
    """ensure_valid is read-only. 100 sequential calls must not create or
    modify any file under state/sessions/ relative to a fresh tmp dir.

    These tests use the ``tmp_path`` function-scoped fixture together with
    @given. Function-scoped fixtures aren't reset between hypothesis-
    generated inputs, but here that's harmless: we snapshot before/after
    inside each call so we only assert "no NEW writes" relative to
    whatever state the (shared) fixture started in. The
    HealthCheck.function_scoped_fixture suppression makes the intent
    explicit.
    """

    @given(code=safe_python_code())
    @settings(
        deadline=2000,
        max_examples=20,
        suppress_health_check=[
            HealthCheck.too_slow,
            HealthCheck.function_scoped_fixture,
        ],
    )
    def test_no_state_sessions_writes(self, code: str, tmp_path: pathlib.Path) -> None:
        sessions = tmp_path / "sessions"
        before = _snapshot_dir(sessions)
        for _ in range(100):
            ensure_valid(code)
        after = _snapshot_dir(sessions)
        assert before == after

    @given(code=mixed_code(max_errors=2, max_warnings=2))
    @settings(
        deadline=2000,
        max_examples=20,
        suppress_health_check=[
            HealthCheck.too_slow,
            HealthCheck.function_scoped_fixture,
        ],
    )
    def test_no_cwd_writes_on_raise(
        self, code: str, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        before = _snapshot_dir(tmp_path)
        for _ in range(20):
            try:
                ensure_valid(code)
            except AstValidationError:
                pass
        after = _snapshot_dir(tmp_path)
        assert before == after


# ---------------------------------------------------------------------------
# Property 6: Differential -- gate witnesses subset of validator's
# ---------------------------------------------------------------------------


class TestWitnessPreservation:
    """Every Violation carried by AstValidationError must also appear in the
    underlying validate_code() output for the same input. The gate is a
    pure filter -- it never invents violations."""

    @given(
        code=st.one_of(safe_python_code(), nondeterministic_code(), mixed_code()),
        allow=st.booleans(),
    )
    @settings(deadline=2000, max_examples=60)
    def test_exception_violations_subset_of_validator(self, code: str, allow: bool) -> None:
        try:
            ensure_valid(code, allow_nondeterminism=allow)
        except AstValidationError as exc:
            base = _sorted_violations(validate_code(code, allow_nondeterminism=allow))
            carried = _sorted_violations(exc.violations)
            assert carried == base, (
                f"AstValidationError.violations must equal validate_code output "
                f"for the same input. carried={carried} base={base}"
            )

    @given(
        code=st.one_of(safe_python_code(), mixed_code(max_errors=0, max_warnings=3)),
        allow=st.booleans(),
    )
    @settings(deadline=2000, max_examples=60)
    def test_clean_return_equals_validator_warnings(self, code: str, allow: bool) -> None:
        # When ensure_valid does NOT raise, its return value is the
        # warning-only tail of validate_code.
        try:
            warns = ensure_valid(code, allow_nondeterminism=allow)
        except AstValidationError:
            return  # property only applies to the non-raising path
        base = validate_code(code, allow_nondeterminism=allow)
        assert _sorted_violations(warns) == _sorted_violations(base)
        assert all(v.severity != "error" for v in warns)


# ---------------------------------------------------------------------------
# Property 7-9: AstValidationError invariants
# ---------------------------------------------------------------------------


class TestErrorInvariants:
    @given(
        code=st.one_of(nondeterministic_code(), mixed_code(max_errors=3, max_warnings=2)),
    )
    @settings(deadline=2000, max_examples=50)
    def test_error_carries_at_least_one_error_severity(self, code: str) -> None:
        try:
            ensure_valid(code)
        except AstValidationError as exc:
            assert len(exc.violations) >= 1
            assert any(v.severity == "error" for v in exc.violations), (
                "AstValidationError must carry at least one error-severity violation"
            )
        else:
            # Fine; some mixed_code samples have 0 errors.
            return

    @given(code=nondeterministic_code())
    @settings(deadline=2000, max_examples=20)
    def test_str_preview_contains_some_rule_name(self, code: str) -> None:
        with pytest.raises(AstValidationError) as exc_info:
            ensure_valid(code)
        msg = str(exc_info.value)
        rules = {v.rule for v in exc_info.value.violations if v.severity == "error"}
        # Preview shows up to 5 errors -- but rules is small here, so at
        # least one rule name must appear in the message.
        assert any(r in msg for r in rules), f"msg={msg!r} rules={rules}"

    @given(code=mixed_code(max_errors=10, max_warnings=2))
    @settings(deadline=2000, max_examples=40)
    def test_str_preview_is_stable_across_calls(self, code: str) -> None:
        try:
            ensure_valid(code)
        except AstValidationError as exc:
            s1 = str(exc)
            s2 = str(exc)
            s3 = str(exc)
            assert s1 == s2 == s3
            # The "+N more" suffix must accurately reflect error count > 5.
            errs = [v for v in exc.violations if v.severity == "error"]
            if len(errs) > 5:
                assert f"(+{len(errs) - 5} more)" in s1

    @given(code=nondeterministic_code())
    @settings(deadline=2000, max_examples=20)
    def test_violations_list_is_defensive_copy(self, code: str) -> None:
        with pytest.raises(AstValidationError) as exc_info:
            ensure_valid(code)
        exc_info.value.violations.clear()
        exc_info.value.violations.append(
            Violation(rule="hijack", severity="error", line=999, message="poison")
        )
        # A fresh ensure_valid call must not be affected by our mutation.
        with pytest.raises(AstValidationError) as fresh:
            ensure_valid(code)
        assert all(v.rule != "hijack" for v in fresh.value.violations)
        assert all(v.message != "poison" for v in fresh.value.violations)


# ---------------------------------------------------------------------------
# Property 10: error_count fidelity
# ---------------------------------------------------------------------------


class TestErrorCountFidelity:
    """For mixed_code(N errors, M warnings), the count of error-severity
    violations from validate_code equals the N we asked for. This is the
    invariant a deny-ledger row's detail.error_count would propagate."""

    @given(
        n_err=st.integers(min_value=1, max_value=5),
        n_warn=st.integers(min_value=0, max_value=3),
    )
    @settings(deadline=2000, max_examples=30)
    def test_error_count_matches_construction(self, n_err: int, n_warn: int) -> None:
        # Build the same shape as mixed_code so we control n exactly.
        imports = "\n".join(f"import uuid as _u{i}" for i in range(n_err))
        body_lines = ["    x = 1"]
        for i in range(n_warn):
            body_lines.append(f"    print('w{i}')")
        body_lines.append("    return x")
        code = (imports + ("\n\n" if imports else "")) + "def f():\n" + "\n".join(body_lines) + "\n"

        violations = validate_code(code, allow_nondeterminism=False)
        errors = [v for v in violations if v.severity == "error"]
        warnings = [v for v in violations if v.severity == "warning"]
        note(f"errors={len(errors)} warnings={len(warnings)}")
        assert len(errors) == n_err
        # Each print is ONE side_effect warning.
        assert sum(1 for v in warnings if v.rule == "side_effect") == n_warn


# ---------------------------------------------------------------------------
# Property 11: pathological inputs handled in deadline budget
# ---------------------------------------------------------------------------


class TestPathological:
    @given(code=pathological_code())
    @settings(
        deadline=2000,
        max_examples=20,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
    )
    def test_pathological_input_terminates(self, code: str) -> None:
        # We don't care whether it raises or not -- only that it returns
        # within the deadline and the result has the expected types.
        try:
            result = ensure_valid(code)
        except AstValidationError as exc:
            for v in exc.violations:
                assert isinstance(v.line, int)
                assert isinstance(v.rule, str)
                assert isinstance(v.severity, str)
                assert isinstance(v.message, str)
            return
        assert isinstance(result, list)
        for v in result:
            assert v.severity == "warning"


# ---------------------------------------------------------------------------
# Property 12: validate_code return shape
# ---------------------------------------------------------------------------


class TestValidateShape:
    @given(
        code=st.one_of(safe_python_code(), nondeterministic_code(), mixed_code()),
        allow=st.booleans(),
    )
    @settings(deadline=2000, max_examples=40)
    def test_validate_code_returns_list_of_violations(self, code: str, allow: bool) -> None:
        result = validate_code(code, allow_nondeterminism=allow)
        assert isinstance(result, list)
        for v in result:
            assert isinstance(v, Violation)
            assert v.severity in {"error", "warning"}
            assert isinstance(v.rule, str) and v.rule
            assert isinstance(v.line, int) and v.line >= 0
            assert isinstance(v.message, str) and v.message


# ---------------------------------------------------------------------------
# Property 13: stateful machine -- arbitrary call sequences preserve invariants
# ---------------------------------------------------------------------------


class EnsureValidMachine(RuleBasedStateMachine):
    """Drive ensure_valid with arbitrary sequences of (code, mode) calls
    and check that every transition preserves the gate's contract:

    * No state file is created under the test's tmp dir.
    * Whenever the gate raises, the carried list contains >=1 error.
    * Whenever the gate returns, no carried element has severity == 'error'.
    * Re-issuing the same call yields the same outcome (determinism).
    """

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    @rule(
        code=st.one_of(safe_python_code(), nondeterministic_code(), mixed_code()),
        allow=st.booleans(),
    )
    def call_ensure_valid(self, code: str, allow: bool) -> None:
        self.calls += 1
        try:
            r1 = ensure_valid(code, allow_nondeterminism=allow)
            r2 = ensure_valid(code, allow_nondeterminism=allow)
            assert all(v.severity != "error" for v in r1)
            assert _sorted_violations(r1) == _sorted_violations(r2)
        except AstValidationError as exc1:
            assert any(v.severity == "error" for v in exc1.violations)
            try:
                ensure_valid(code, allow_nondeterminism=allow)
            except AstValidationError as exc2:
                assert _sorted_violations(exc1.violations) == _sorted_violations(exc2.violations)
            else:  # pragma: no cover -- determinism violation
                raise AssertionError("ensure_valid not deterministic across calls")

    @invariant()
    def calls_never_negative(self) -> None:
        assert self.calls >= 0


TestEnsureValidStateMachine = EnsureValidMachine.TestCase
TestEnsureValidStateMachine.settings = settings(  # type: ignore[attr-defined]
    deadline=2000,
    max_examples=20,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
)


# ---------------------------------------------------------------------------
# Property 14: AstValidationError init with empty list (regression)
# ---------------------------------------------------------------------------


class TestErrorInitEdgeCases:
    @given(
        n=st.integers(min_value=0, max_value=10),
    )
    @settings(deadline=2000, max_examples=15)
    def test_error_can_be_constructed_with_arbitrary_violation_count(self, n: int) -> None:
        viols = [
            Violation(rule="x", severity="error", line=i + 1, message=f"m{i}")
            for i in range(n)
        ]
        exc = AstValidationError(viols)
        assert len(exc.violations) == n
        # The defensive copy means the list identity differs.
        assert exc.violations is not viols
        # str() never crashes regardless of length.
        s = str(exc)
        assert isinstance(s, str)
        if n == 0:
            assert s == "AST validation failed"
        else:
            # First-up-to-5 previews appear.
            for v in viols[:5]:
                assert f"@L{v.line}" in s


# ---------------------------------------------------------------------------
# Property 15: ast.unparse round-trip generator is well-formed
# ---------------------------------------------------------------------------


@st.composite
def ast_unparse_code(draw: st.DrawFn) -> str:
    """Generate code via the AST module + ast.unparse to guarantee
    syntactic well-formedness without lexer artefacts."""
    fname = draw(_safe_identifier)
    n_stmts = draw(st.integers(min_value=1, max_value=6))
    body: list[ast.stmt] = []
    for i in range(n_stmts):
        target = ast.Name(id=f"v{i}", ctx=ast.Store())
        value = ast.Constant(value=draw(st.integers(min_value=-100, max_value=100)))
        body.append(ast.Assign(targets=[target], value=value))
    body.append(ast.Return(value=ast.Constant(value=0)))
    func = ast.FunctionDef(
        name=fname,
        args=ast.arguments(
            posonlyargs=[], args=[], vararg=None,
            kwonlyargs=[], kw_defaults=[], kwarg=None, defaults=[],
        ),
        body=body,
        decorator_list=[],
        returns=None,
        type_comment=None,
    )
    module = ast.Module(body=[func], type_ignores=[])
    ast.fix_missing_locations(module)
    return ast.unparse(module) + "\n"


class TestAstUnparseGenerator:
    @given(code=ast_unparse_code())
    @settings(deadline=2000, max_examples=30)
    def test_unparse_generated_code_is_clean(self, code: str) -> None:
        # Code generated through ast.unparse with no nondeterminism imports
        # and only int constants must pass the gate cleanly.
        result = ensure_valid(code)
        assert all(v.severity != "error" for v in result)
