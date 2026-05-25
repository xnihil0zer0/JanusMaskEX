"""Adversarial wire-in regression tests for W76b.

W76 (commit 196e5a5) added ``harness.ast_enforcer.validate_return_type`` and
``harness.diff_fuzzer.extract_return_annotation`` but the validator was dead
code -- nothing in the orchestrator's submission gate consumed it.

W76b plumbs the brief-declared ``-> T`` signature through the public entry
point ``ast_enforcer.validate_code(..., declared_signature=...)`` so that a
return-type contract violation surfaces as a normal ``Violation`` alongside
the rest of the rule set. The Future-vs-dict regression that originally
shipped via ``harness/git_integration.py`` (brief_hooks_silent_canary_signals
row 3) would now trip the gate before the bypass-path accept.

These tests pin the wire-in at the validate_code() seam. They do NOT spin
up the orchestrator main loop (state-machine entanglement is out of scope
for a single-validator wiring change) -- end-to-end orchestration coverage
is provided by tests/adversarial/test_P5_orchestrator_stateful.py.
"""

from __future__ import annotations

import textwrap

from harness.ast_enforcer import validate_code


def _filter_return(violations):
    return [v for v in violations if v.rule == "return_type_mismatch"]


# ---------------------------------------------------------------------------
# (a) Core regression: brief -> dict, impl -> Future. Reject.
# ---------------------------------------------------------------------------

def test_brief_declared_dict_impl_returns_future_rejected() -> None:
    """The original W64 silent-canary defect: brief declared a sync ``dict``
    return but the impl shipped ``Future``. Wired through validate_code, the
    return_type_mismatch violation must surface."""
    brief_sig = "def commit_accepted_output(round_id, target, state_dir) -> dict: ..."
    impl_src = textwrap.dedent(
        """
        def commit_accepted_output(round_id, target, state_dir) -> Future:
            return Future()
        """
    ).lstrip()

    violations = validate_code(impl_src, declared_signature=brief_sig)
    rt = _filter_return(violations)
    assert len(rt) >= 1, f"expected return_type_mismatch, got: {violations}"


# ---------------------------------------------------------------------------
# (b) Conforming impl -> no return_type_mismatch.
# ---------------------------------------------------------------------------

def test_brief_declared_dict_impl_returns_dict_accepted() -> None:
    brief_sig = "def commit_accepted_output(round_id, target, state_dir) -> dict: ..."
    impl_src = textwrap.dedent(
        """
        def commit_accepted_output(round_id, target, state_dir) -> dict:
            return {}
        """
    ).lstrip()

    violations = validate_code(impl_src, declared_signature=brief_sig)
    assert _filter_return(violations) == []


# ---------------------------------------------------------------------------
# (c) Brief signature absent -> validator skipped (no return_type_mismatch).
# ---------------------------------------------------------------------------

def test_no_brief_signature_skips() -> None:
    impl_src = textwrap.dedent(
        """
        def f(x):
            return x
        """
    ).lstrip()

    # None
    violations_none = validate_code(impl_src, declared_signature=None)
    assert _filter_return(violations_none) == []

    # Empty string
    violations_empty = validate_code(impl_src, declared_signature="")
    assert _filter_return(violations_empty) == []

    # Default (kwarg omitted) -- preserves pre-W76b call-site semantics.
    violations_default = validate_code(impl_src)
    assert _filter_return(violations_default) == []


# ---------------------------------------------------------------------------
# (d) Brief names a function the impl doesn't define -> rejected.
# ---------------------------------------------------------------------------

def test_brief_function_not_found_in_impl() -> None:
    brief_sig = "def foo() -> dict: ..."
    impl_src = textwrap.dedent(
        """
        def bar() -> dict:
            return {}
        """
    ).lstrip()

    violations = validate_code(impl_src, declared_signature=brief_sig)
    rt = _filter_return(violations)
    assert len(rt) == 1
    assert "not found" in rt[0].message.lower()


# ---------------------------------------------------------------------------
# (e) async def -> async def, matching annotations -> no violation.
# ---------------------------------------------------------------------------

def test_async_impl_matches_async_brief() -> None:
    brief_sig = "async def f() -> int: ..."
    impl_src = textwrap.dedent(
        """
        async def f() -> int:
            return 1
        """
    ).lstrip()

    violations = validate_code(impl_src, declared_signature=brief_sig)
    assert _filter_return(violations) == []


# ---------------------------------------------------------------------------
# (f) PEP-563 forward-reference annotation in impl -> resolved by W76 normaliser.
# ---------------------------------------------------------------------------

def test_string_annotation_in_impl_resolved() -> None:
    """Impl declares the return type as a *string* (PEP-563). The W76
    normaliser must reparse it before comparison; the W76b wire-in must
    propagate that violation through validate_code's public surface."""
    brief_sig = "def f() -> dict: ..."
    impl_src = textwrap.dedent(
        """
        from __future__ import annotations

        def f() -> Future:
            return Future()
        """
    ).lstrip()

    violations = validate_code(impl_src, declared_signature=brief_sig)
    rt = _filter_return(violations)
    assert len(rt) == 1, f"expected exactly one return_type_mismatch, got: {violations}"
