"""Adversarial regression tests for the W76 return-type contract validator.

Context (brief_hooks_silent_canary_signals.md row 3): harness/git_integration
originally wrapped commit_accepted_output in a ThreadPoolExecutor and returned
``Future[dict]`` instead of the contract-specified ``dict``. The bypass-path
accept gate (ast_enforcer.validate_code) had no notion of return-type
conformance, so the caller-shape regression shipped silently.

W76 adds:
  - harness.diff_fuzzer.extract_return_annotation(signature_src) -> ast.expr | None
  - harness.ast_enforcer.validate_return_type(code, declared_return, func_name)
      -> list[Violation]

These tests exercise both functions directly, with no orchestrator scaffolding,
and pin the behaviour that matters for the Future-vs-dict regression and a
handful of adjacent normalisation edge cases.
"""

from __future__ import annotations

import ast
import textwrap

from harness.ast_enforcer import Violation, validate_return_type
from harness.diff_fuzzer import extract_return_annotation


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract(signature_src: str) -> ast.expr | None:
    """Small helper so the test body reads as the intent, not the plumbing."""
    return extract_return_annotation(signature_src)


# ---------------------------------------------------------------------------
# Core regression: Future vs dict (the original silent-canary bug)
# ---------------------------------------------------------------------------

def test_future_vs_dict_regression() -> None:
    """Brief promises ``-> dict``; impl returns ``concurrent.futures.Future``.

    This is the exact W64 defect: commit_accepted_output was wrapped in a
    ThreadPoolExecutor and returned Future[dict] instead of a bare dict. The
    validator must flag it as return_type_mismatch.
    """
    brief_sig = "def commit_accepted_output(round_id: str, target: str, state_dir) -> dict: ..."
    impl_src = textwrap.dedent(
        """
        import concurrent.futures

        def commit_accepted_output(round_id, target, state_dir) -> Future:
            return concurrent.futures.Future()
        """
    ).lstrip()
    declared = _extract(brief_sig)
    assert declared is not None, "brief -> dict must parse as a return annotation"

    violations = validate_return_type(impl_src, declared, "commit_accepted_output")
    assert len(violations) == 1
    assert violations[0].rule == "return_type_mismatch"


# ---------------------------------------------------------------------------
# Normaliser: typing.Dict == dict
# ---------------------------------------------------------------------------

def test_dict_alias_compatible() -> None:
    """``-> dict`` must be treated as equivalent to ``-> Dict[str, Any]``.

    The normaliser strips subscript from typing.Dict/List/Tuple/Set so the two
    forms compare equal. If this breaks, every brief that uses the bare alias
    will false-positive against correctly-typed implementations.
    """
    brief_sig = "def f(x) -> dict: ..."
    impl_src = textwrap.dedent(
        """
        from typing import Dict, Any

        def f(x) -> Dict[str, Any]:
            return {}
        """
    ).lstrip()
    declared = _extract(brief_sig)
    assert declared is not None

    violations = validate_return_type(impl_src, declared, "f")
    assert violations == [], f"expected no violations, got {violations!r}"


# ---------------------------------------------------------------------------
# Skip path: missing brief annotation is not a violation
# ---------------------------------------------------------------------------

def test_missing_brief_annotation_skips() -> None:
    """No annotation in brief → validator must not fabricate a violation."""
    brief_sig = "def f(x): ..."
    impl_src = "def f(x):\n    return x\n"
    declared = _extract(brief_sig)
    assert declared is None, "unannotated brief must yield declared=None"

    violations = validate_return_type(impl_src, declared, "f")
    assert violations == []


# ---------------------------------------------------------------------------
# Generic parameter mismatch: List[int] vs List[str]
# ---------------------------------------------------------------------------

def test_generic_param_mismatch() -> None:
    """Brief ``-> List[int]`` vs impl ``-> List[str]`` must flag mismatch.

    The normaliser collapses typing.List → list but must preserve the
    parameter, so int vs str is caught at the Subscript level.
    """
    brief_sig = "def f(x) -> List[int]: ..."
    impl_src = textwrap.dedent(
        """
        from typing import List

        def f(x) -> List[str]:
            return [str(x)]
        """
    ).lstrip()
    declared = _extract(brief_sig)
    assert declared is not None

    violations = validate_return_type(impl_src, declared, "f")
    assert len(violations) == 1
    assert violations[0].rule == "return_type_mismatch"


# ---------------------------------------------------------------------------
# PEP 563: ``from __future__ import annotations`` stringifies the return node
# ---------------------------------------------------------------------------

def test_str_annotation_resolved() -> None:
    """Under ``from __future__ import annotations`` the impl .returns node is
    ``ast.Constant(value="Future")``. The validator must unwrap the string
    form before comparing; otherwise Constant('Future') would falsely "equal"
    Constant(any string) and Future-vs-dict would slip through again.
    """
    brief_sig = "def f(x) -> dict: ..."
    impl_src = textwrap.dedent(
        """
        from __future__ import annotations

        def f(x) -> Future:
            return Future()
        """
    ).lstrip()
    declared = _extract(brief_sig)
    assert declared is not None

    violations = validate_return_type(impl_src, declared, "f")
    assert len(violations) == 1
    assert violations[0].rule == "return_type_mismatch"


# ---------------------------------------------------------------------------
# extract_return_annotation: async & empty-input edge cases
# ---------------------------------------------------------------------------

def test_extract_return_annotation_handles_async() -> None:
    """async def foo() -> int must yield the int annotation, not None."""
    src = "async def foo() -> int: ..."
    node = extract_return_annotation(src)
    assert node is not None
    assert isinstance(node, ast.Name)
    assert node.id == "int"


def test_extract_return_annotation_no_signature() -> None:
    """Empty input must return None gracefully (no SyntaxError bubble)."""
    assert extract_return_annotation("") is None


# ---------------------------------------------------------------------------
# Bonus: function-not-found is an error, not silent pass
# ---------------------------------------------------------------------------

def test_function_not_found_reports_violation() -> None:
    """If the declared function is absent from the impl, the validator must
    flag it rather than silently skip."""
    brief_sig = "def f(x) -> int: ..."
    impl_src = "def g(x) -> int:\n    return x\n"
    declared = _extract(brief_sig)
    assert declared is not None

    violations = validate_return_type(impl_src, declared, "f")
    assert len(violations) == 1
    assert violations[0].rule == "return_type_mismatch"
    assert isinstance(violations[0], Violation)
