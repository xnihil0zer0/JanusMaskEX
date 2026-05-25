"""Phase 3 differential testing: cross-validate the FOUR validators that
inspect agent code submissions.

Background: Blocker #8 (B3 baseline-regen, 2026-04-19) was caused by an
ASYMMETRY between the PreToolUse hook (which correctly denied bad code) and
the PostToolUse layer (which persisted the same bytes anyway). The fix
introduced ``ensure_valid()`` as the canonical persist-time gate. This file
proves — by parametric differential — that all four validators on the same
surface produce IDENTICAL accept/reject decisions on a 50+-sample corpus.

Validators under test
---------------------
1. ``harness.ast_enforcer.validate_code(code, allow_nondeterminism=...)``
   — canonical implementation, returns full ``list[Violation]``.
2. ``harness.hooks.rpc.submit_code.validate(code, ...)``
   — thin wrapper used by the MCP server (mcp_server.py:376).
3. ``harness.hooks.rpc.submit_code.ensure_valid(code, ...)``
   — persist-time gate; raises ``AstValidationError`` on errors, returns
   warnings-only list otherwise. Used by both Claude and Gemini PostToolUse
   hooks (harness/hooks/{claude,gemini}/post_tool.py:109-112).
4. ``harness.orchestrator._validate_submission(code, agent, task)``
   — orchestrator's pre-fuzz AST gate, returns ``(valid_bool, violations)``.

Differential properties
-----------------------
For every code C (tested at both allow_nondet=False and True where meaningful):

* ``validate_code(C)`` and ``rpc.validate(C)`` return STRUCTURALLY-IDENTICAL
  violation lists (same rule/severity/line/message tuples in same order).
* ``ensure_valid(C)`` raises iff ``validate_code(C)`` contains any
  error-severity violation; the raised exception's ``violations`` attribute
  equals the canonical list.
* When ``ensure_valid(C)`` does NOT raise, its returned list equals the
  warnings-severity subset of ``validate_code(C)``.
* The orchestrator's ``_validate_submission(C, agent, task)`` returns
  ``valid==True`` iff ``ensure_valid(C)`` does not raise; the violation
  list it returns equals the canonical ``validate_code(C)`` list.

Constraint: must complete in <30s. Corpus is ~50 samples; each pair check
is O(parse) — total runtime is dominated by ast.parse calls and well under
the budget on any modern machine.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

import pytest

from harness import ast_enforcer, orchestrator
from harness.ast_enforcer import Violation, validate_code
from harness.hooks.rpc import submit_code as rpc_submit_code


# ---------------------------------------------------------------------------
# Test corpus -- ~50 samples spanning the requested categories
# ---------------------------------------------------------------------------

# Category A: 10 clean samples (no violations).
_CLEAN: list[tuple[str, str]] = [
    ("clean_add", "def add(a, b):\n    return a + b\n"),
    ("clean_mul", "def mul(a, b):\n    return a * b\n"),
    ("clean_class", "class Pt:\n    def x(self):\n        return 1\n"),
    ("clean_async", "async def fetch(x):\n    return x\n"),
    ("clean_kwonly", "def f(a, *, b=2):\n    return a + b\n"),
    ("clean_lambda_helper", "def f(xs):\n    g = lambda x: x + 1\n    return [g(x) for x in xs]\n"),
    ("clean_decorator", "def deco(f):\n    return f\n\n@deco\ndef g(x):\n    return x\n"),
    ("clean_typed", "def f(x: int) -> int:\n    return x + 1\n"),
    ("clean_unicode", "def π(x):\n    return x * 2\n"),
    ("clean_match",
     "def f(x):\n    match x:\n        case 1: return 'a'\n        case _: return 'b'\n"),
]

# Category B: 10 nondeterministic-only samples (uuid / time.time / random / datetime / os.urandom).
_NONDET: list[tuple[str, str]] = [
    ("nondet_uuid_import", "import uuid\n\ndef f():\n    return uuid.uuid4().hex\n"),
    ("nondet_random_import", "import random\n\ndef f():\n    return random.random()\n"),
    ("nondet_uuid_from", "from uuid import uuid4\n\ndef f():\n    return uuid4().hex\n"),
    ("nondet_random_from", "from random import randint\n\ndef f():\n    return randint(0, 10)\n"),
    ("nondet_time_time", "import time\n\ndef f():\n    return time.time()\n"),
    ("nondet_datetime_now",
     "import datetime\n\ndef f():\n    return datetime.now()\n"),
    ("nondet_os_urandom", "import os\n\ndef f():\n    return os.urandom(4)\n"),
    ("nondet_uuid_dotted", "import uuid.something_unlikely\n\ndef f():\n    return 1\n"),
    ("nondet_random_then_def",
     "import random\n\ndef f():\n    return 1\n\ndef g():\n    return random.choice([1, 2])\n"),
    ("nondet_combo_uuid_time",
     "import uuid\nimport time\n\ndef f():\n    return (uuid.uuid4().hex, time.time())\n"),
]

# Category C: 10 syntax-error samples.
_SYNTAX: list[tuple[str, str]] = [
    ("syntax_paren", "def broken(:\n    pass\n"),
    ("syntax_unclosed_str", "def f():\n    return 'unterminated\n"),
    ("syntax_indent", "def f():\nreturn 1\n"),
    ("syntax_extra_colon", "def f()::\n    pass\n"),
    ("syntax_random_tokens", "def f(): @@@@\n"),
    ("syntax_unbalanced_brackets", "def f():\n    return [1, 2, 3\n"),
    ("syntax_bad_import", "import\n\ndef f():\n    return 1\n"),
    ("syntax_keyword_as_name", "def class():\n    pass\n"),
    ("syntax_dangling_arrow",
     "def f() ->:\n    return 1\n"),
    ("syntax_dedent",
     "def f():\n    return 1\n  return 2\n"),
]

# Category D: 10 warnings-only samples (subprocess, side effects, recursion).
_WARNINGS: list[tuple[str, str]] = [
    ("warn_subprocess_run",
     "import subprocess\n\ndef f():\n    subprocess.run(['ls'])\n"),
    ("warn_subprocess_call",
     "import subprocess\n\ndef f():\n    subprocess.call(['ls'])\n"),
    ("warn_print", "def f(x):\n    print(x)\n    return x\n"),
    ("warn_open", "def f(p):\n    open(p)\n    return p\n"),
    ("warn_stdout_write",
     "import sys\n\ndef f(x):\n    sys.stdout.write(str(x))\n    return x\n"),
    ("warn_recursion_unbounded",
     "def f(n):\n    return f(n - 1)\n"),
    ("warn_recursion_unbounded_arith",
     "def fact(n):\n    return n * fact(n - 1)\n"),
    ("warn_print_then_recurse",
     "def f(n):\n    print(n)\n    return f(n - 1)\n"),
    ("warn_two_subprocess_no_check",
     "import subprocess\n\ndef f():\n    subprocess.run(['a'])\n    subprocess.run(['b'])\n"),
    ("warn_open_with_recursion",
     "def f(p):\n    open(p)\n    return f(p)\n"),
]

# Category E: 10 mixed (errors + warnings).
_MIXED: list[tuple[str, str]] = [
    ("mixed_uuid_print",
     "import uuid\n\ndef f():\n    print(uuid.uuid4().hex)\n    return 1\n"),
    ("mixed_time_subprocess",
     "import subprocess\nimport time\n\ndef f():\n    subprocess.run(['x'])\n    return time.time()\n"),
    ("mixed_eval_print",
     "def f(s):\n    print(s)\n    return eval(s)\n"),
    ("mixed_exec_open",
     "def f(s, p):\n    open(p)\n    exec(s)\n    return 1\n"),
    ("mixed_os_system_print",
     "import os\n\ndef f():\n    os.system('ls')\n    print('ran')\n"),
    ("mixed_bare_except_print",
     "def f():\n    try:\n        return 1\n    except:\n        pass\n"),
    ("mixed_password_subprocess",
     "import subprocess\n\ndef f():\n    password = 'hunter2'\n    subprocess.run([password])\n"),
    ("mixed_uuid_recursion",
     "import uuid\n\ndef f(n):\n    return uuid.uuid4().hex + f(n - 1)\n"),
    ("mixed_random_open",
     "import random\n\ndef f(p):\n    open(p)\n    return random.random()\n"),
    ("mixed_dunder_import_subprocess",
     "import subprocess\n\ndef f():\n    subprocess.run(['x'])\n    return __import__('os')\n"),
]

# Category F: edge cases.
_EDGE: list[tuple[str, str]] = [
    ("edge_empty", ""),
    ("edge_bom_only", "\ufeff"),
    ("edge_comment_only", "# just a comment\n# another\n"),
    ("edge_whitespace_only", "   \n\t\n   \n"),
    ("edge_unicode_bom_then_def",
     "\ufeffdef f():\n    return 1\n"),
    ("edge_module_docstring_only", "\"\"\"docstring only, no funcs.\"\"\"\n"),
    ("edge_single_pass", "pass\n"),
    ("edge_class_only_no_methods", "class A:\n    x = 1\n"),
]


CORPUS: list[tuple[str, str]] = (
    _CLEAN + _NONDET + _SYNTAX + _WARNINGS + _MIXED + _EDGE
)
assert len(CORPUS) >= 50, f"corpus too small: {len(CORPUS)}"

# Allow-nondet matrix: nondet rules only fire when allow_nondeterminism=False.
# Test both flag values for the nondet category (those samples flip
# accept/reject) plus False everywhere else (the canonical orchestrator
# default for deterministic tasks).
_NONDET_NAMES = {name for name, _ in _NONDET}


def _viol_tuples(viols: list[Violation]) -> list[tuple[str, str, int, str]]:
    """Stable, hashable shape for differential equality."""
    return [(v.rule, v.severity, v.line, v.message) for v in viols]


def _has_error(viols: list[Violation]) -> bool:
    return any(v.severity == "error" for v in viols)


def _warnings_only(viols: list[Violation]) -> list[Violation]:
    return [v for v in viols if v.severity == "warning"]


def _make_task(allow_nondet: bool) -> dict[str, Any]:
    """Mirror the orchestrator's allow_nondet derivation
    (orchestrator.py:636: ``constraints.deterministic is False``)."""
    return {"constraints": {"deterministic": not allow_nondet}}


# ---------------------------------------------------------------------------
# Pair 1: ensure_valid <-> validate_code
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,code",
    CORPUS,
    ids=[name for name, _ in CORPUS],
)
@pytest.mark.parametrize("allow_nondet", [False, True])
def test_pair1_ensure_valid_matches_validate_code(
    name: str, code: str, allow_nondet: bool
) -> None:
    """ensure_valid is a structurally-equivalent FILTER over validate_code:

    * raises iff validate_code yields any error-severity violation
    * raised exception's ``violations`` == validate_code(C)
    * non-raising return value == warnings-severity subset of validate_code(C)
    """
    canonical = validate_code(code, allow_nondeterminism=allow_nondet)
    canonical_tuples = _viol_tuples(canonical)

    if _has_error(canonical):
        with pytest.raises(rpc_submit_code.AstValidationError) as exc_info:
            rpc_submit_code.ensure_valid(code, allow_nondeterminism=allow_nondet)
        carried = _viol_tuples(exc_info.value.violations)
        assert carried == canonical_tuples, (
            f"DIFFERENTIAL DISAGREEMENT [{name}, allow_nondet={allow_nondet}]: "
            f"ensure_valid carried {carried!r} but validate_code returned "
            f"{canonical_tuples!r}"
        )
    else:
        result = rpc_submit_code.ensure_valid(
            code, allow_nondeterminism=allow_nondet
        )
        warnings_canonical = _viol_tuples(_warnings_only(canonical))
        assert _viol_tuples(result) == warnings_canonical, (
            f"DIFFERENTIAL DISAGREEMENT [{name}, allow_nondet={allow_nondet}]: "
            f"ensure_valid returned {_viol_tuples(result)!r} but warnings-"
            f"only subset of validate_code is {warnings_canonical!r}"
        )


# ---------------------------------------------------------------------------
# Pair 2: ensure_valid <-> orchestrator._validate_submission
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,code",
    CORPUS,
    ids=[name for name, _ in CORPUS],
)
@pytest.mark.parametrize("allow_nondet", [False, True])
def test_pair2_ensure_valid_matches_orchestrator(
    name: str, code: str, allow_nondet: bool
) -> None:
    """The orchestrator's pre-fuzz AST gate (the path that historically
    re-rejected bytes ensure_valid had passed in the Blocker #8 asymmetry)
    must agree with ensure_valid on the accept/reject decision and produce
    a violation list equal to the canonical validate_code output."""
    task = _make_task(allow_nondet)
    canonical = validate_code(code, allow_nondeterminism=allow_nondet)

    valid, orch_viols = orchestrator._validate_submission(code, "claude", task)

    # Decision agreement.
    ensure_raises = _has_error(canonical)
    assert valid == (not ensure_raises), (
        f"DIFFERENTIAL DISAGREEMENT [{name}, allow_nondet={allow_nondet}]: "
        f"orchestrator valid={valid} but ensure_valid "
        f"{'raises' if ensure_raises else 'passes'} on the same input"
    )

    # Violation-list shape equality with canonical.
    assert _viol_tuples(orch_viols) == _viol_tuples(canonical), (
        f"DIFFERENTIAL DISAGREEMENT [{name}, allow_nondet={allow_nondet}]: "
        f"orchestrator returned {_viol_tuples(orch_viols)!r} but canonical "
        f"validate_code returned {_viol_tuples(canonical)!r}"
    )


# ---------------------------------------------------------------------------
# Pair 3: rpc.validate (MCP server path) <-> ensure_valid / validate_code
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,code",
    CORPUS,
    ids=[name for name, _ in CORPUS],
)
@pytest.mark.parametrize("allow_nondet", [False, True])
def test_pair3_rpc_validate_matches_validate_code(
    name: str, code: str, allow_nondet: bool
) -> None:
    """``rpc_submit_code.validate`` is the entry-point used by the MCP
    server (mcp_server.py:376). It must be a pure pass-through to the
    canonical validator — same Violation tuples in the same order."""
    canonical = validate_code(code, allow_nondeterminism=allow_nondet)
    via_rpc = rpc_submit_code.validate(code, allow_nondeterminism=allow_nondet)
    assert _viol_tuples(via_rpc) == _viol_tuples(canonical), (
        f"DIFFERENTIAL DISAGREEMENT [{name}, allow_nondet={allow_nondet}]: "
        f"rpc_submit_code.validate diverges from harness.ast_enforcer."
        f"validate_code: rpc={_viol_tuples(via_rpc)!r} canonical="
        f"{_viol_tuples(canonical)!r}"
    )


@pytest.mark.parametrize(
    "name,code",
    CORPUS,
    ids=[name for name, _ in CORPUS],
)
def test_pair3b_mcp_path_decision_matches_ensure_valid(
    name: str, code: str
) -> None:
    """The MCP server's cmd_submit_code (mcp_server.py:331-396) computes the
    accept/reject decision via ``[v for v in rpc_submit_code.validate(...) if
    v.severity == 'error']``. That decision must match ensure_valid()'s
    raise/no-raise verdict on the SAME bytes — otherwise the MCP entry
    point and the post-tool persist gate could disagree on a submission,
    re-introducing a Blocker-#8-style asymmetry on the OPPOSITE side
    (MCP accepts, hook persists, orchestrator may then re-reject).
    """
    # Both validators share the default allow_nondeterminism=False of the
    # MCP path's most-common task constraint.
    via_rpc = rpc_submit_code.validate(code, allow_nondeterminism=False)
    mcp_would_reject = any(v.severity == "error" for v in via_rpc)

    canonical = validate_code(code, allow_nondeterminism=False)
    ensure_would_raise = _has_error(canonical)

    assert mcp_would_reject == ensure_would_raise, (
        f"DIFFERENTIAL DISAGREEMENT [{name}]: MCP path "
        f"{'rejects' if mcp_would_reject else 'accepts'} but persist-time "
        f"ensure_valid would {'raise' if ensure_would_raise else 'pass'} "
        f"on the same code"
    )


# ---------------------------------------------------------------------------
# Cross-validator unanimity: all four agree on the binary verdict
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,code",
    CORPUS,
    ids=[name for name, _ in CORPUS],
)
@pytest.mark.parametrize("allow_nondet", [False, True])
def test_quartet_unanimous_accept_reject(
    name: str, code: str, allow_nondet: bool
) -> None:
    """Run all four validators in parallel; all must produce the SAME binary
    accept/reject decision. Disagreement is the original Blocker #8 failure
    mode and must xfail with the offending pair surfaced."""
    task = _make_task(allow_nondet)

    canonical_viols = validate_code(code, allow_nondeterminism=allow_nondet)
    rpc_viols = rpc_submit_code.validate(
        code, allow_nondeterminism=allow_nondet
    )
    orch_valid, _ = orchestrator._validate_submission(code, "claude", task)
    try:
        rpc_submit_code.ensure_valid(
            code, allow_nondeterminism=allow_nondet
        )
        ensure_raised = False
    except rpc_submit_code.AstValidationError:
        ensure_raised = True

    canonical_rejects = _has_error(canonical_viols)
    rpc_rejects = any(v.severity == "error" for v in rpc_viols)
    orch_rejects = not orch_valid

    decisions = {
        "validate_code": canonical_rejects,
        "rpc.validate": rpc_rejects,
        "ensure_valid_raises": ensure_raised,
        "orchestrator_invalid": orch_rejects,
    }
    distinct = set(decisions.values())
    assert len(distinct) == 1, (
        f"QUARTET DISAGREEMENT [{name}, allow_nondet={allow_nondet}]: "
        f"validators disagree on accept/reject -> {decisions!r}"
    )


# ---------------------------------------------------------------------------
# Determinism / idempotence regression: repeated calls must not drift
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,code",
    # Sample one from each category; full corpus is overkill for a
    # determinism check and keeps runtime well under budget.
    [
        _CLEAN[0], _NONDET[0], _SYNTAX[0],
        _WARNINGS[0], _MIXED[0], _EDGE[0],
    ],
    ids=lambda v: v if isinstance(v, str) else "code",
)
def test_validators_are_idempotent(name: str, code: str) -> None:
    """Running each validator twice on the same bytes must produce identical
    output. Hidden state in any validator would silently rot the differential
    guarantee in long-running orchestrator processes."""
    a1 = _viol_tuples(validate_code(code))
    a2 = _viol_tuples(validate_code(code))
    assert a1 == a2, f"validate_code not idempotent on {name!r}"

    b1 = _viol_tuples(rpc_submit_code.validate(code))
    b2 = _viol_tuples(rpc_submit_code.validate(code))
    assert b1 == b2, f"rpc.validate not idempotent on {name!r}"

    task = _make_task(False)
    c1 = orchestrator._validate_submission(code, "claude", task)
    c2 = orchestrator._validate_submission(code, "claude", task)
    assert c1[0] == c2[0]
    assert _viol_tuples(c1[1]) == _viol_tuples(c2[1]), (
        f"orchestrator._validate_submission not idempotent on {name!r}"
    )
