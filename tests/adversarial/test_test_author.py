"""Operator-authored oracle for the independent test-author ROLE.

`harness/test_author.py` is dogfood-synthesized blind by the dual agents; this
file is the trusted gate (tests-as-oracle). It pins the public API and proves
the three contract points from brief_hooks_test_author_role.md:

  (a) author != implementer  — the role's session is structurally separate
      from the synthesis agents' sessions.
  (b) the non-vacuity gate REJECTS an oracle that passes the stripped stub and
      ACCEPTS one that fails the stub.
  (c) a generated oracle actually GATES a downstream synthesis — it fails the
      stub but passes the real implementation.

The role never writes the gate that judges its own synthesis run; generation is
injected via ``gen_fn`` so the role is decoupled from the live agent CLIs (the
real-agent generation is proven by the capstone dogfood, not this unit test).
"""

from __future__ import annotations

import pathlib

import pytest

import harness.test_author as ta
from harness.test_author import (
    GeneratedOracle,
    TestAuthorError,
    VacuousOracleError,
    author_oracle,
    author_session_dir,
    build_author_prompt,
    oracle_is_non_vacuous,
    run_oracle_against,
    stub_for,
)

# A tiny target module + oracles used across the contract tests.
REAL_SOURCE = (
    "def add(a, b):\n"
    "    return a + b\n"
    "\n"
    "def scale(xs, k):\n"
    "    return [x * k for x in xs]\n"
)

# A genuine oracle: exercises behaviour, so it FAILS the NotImplementedError stub.
GOOD_TEST = (
    "from calc import add, scale\n"
    "\n"
    "def test_add():\n"
    "    assert add(2, 3) == 5\n"
    "\n"
    "def test_scale():\n"
    "    assert scale([1, 2, 3], 2) == [2, 4, 6]\n"
)

# A vacuous oracle: asserts nothing about the target, so it PASSES the stub.
VACUOUS_TEST = (
    "def test_trivially_true():\n"
    "    assert True\n"
)


def test_public_api_surface():
    """import harness.test_author and reference every public symbol (Gate 3)."""
    assert isinstance(TestAuthorError, type) and issubclass(TestAuthorError, Exception)
    assert issubclass(VacuousOracleError, TestAuthorError)
    for name in (
        "GeneratedOracle",
        "author_oracle",
        "author_session_dir",
        "build_author_prompt",
        "oracle_is_non_vacuous",
        "run_oracle_against",
        "stub_for",
    ):
        assert hasattr(ta, name), f"missing public symbol: {name}"


def test_stub_for_reuses_strip_to_neuter_bodies():
    """stub_for produces a skeleton whose bodies raise NotImplementedError."""
    stub = stub_for(REAL_SOURCE)
    assert "NotImplementedError" in stub
    assert "return a + b" not in stub  # the real body is gone
    assert "def add" in stub and "def scale" in stub  # signatures kept


def test_run_oracle_against_passes_real_fails_stub():
    """The runner discriminates a correct impl from the stripped stub."""
    assert run_oracle_against(GOOD_TEST, REAL_SOURCE, "calc") is True
    assert run_oracle_against(GOOD_TEST, stub_for(REAL_SOURCE), "calc") is False


def test_non_vacuity_check():
    """A behaviour-exercising oracle is non-vacuous; a trivial one is not."""
    assert oracle_is_non_vacuous(GOOD_TEST, REAL_SOURCE, "calc") is True
    assert oracle_is_non_vacuous(VACUOUS_TEST, REAL_SOURCE, "calc") is False


def test_run_oracle_against_packaged_module():
    """C9.9: a DOTTED target name materializes a real package so a package
    module's oracle (``from pkg.mod import ...``) resolves -- otherwise the
    generated test errors on collection (ModuleNotFoundError) and poisons every
    unit's shared verification gate."""
    impl = "def clamp(value, low, high):\n    return max(low, min(value, high))\n"
    test = (
        "from geopack.fuzzy import clamp\n\n"
        "def test_clamp():\n    assert clamp(5, 0, 3) == 3\n    assert clamp(-1, 0, 3) == 0\n"
    )
    assert run_oracle_against(test, impl, "geopack.fuzzy") is True
    assert oracle_is_non_vacuous(test, impl, "geopack.fuzzy") is True


def test_author_session_is_independent_of_synthesis(tmp_path):
    """(a) author != implementer: the role's session dir is structurally
    separate from the synthesis agents' sessions (state_dir/'sessions')."""
    sd = tmp_path / "state"
    synth_sessions = sd / "sessions"
    author_dir = author_session_dir(sd, "TASK_X")
    author_dir = pathlib.Path(author_dir)
    assert "test_author" in author_dir.parts
    assert author_dir != synth_sessions
    # the author session must not live INSIDE the synthesis sessions dir
    assert synth_sessions not in author_dir.parents


def test_build_author_prompt_names_target(tmp_path):
    spec = {"description": "a pure calculator module", "module": "calc"}
    prompt = build_author_prompt("calc", spec)
    assert isinstance(prompt, str) and prompt.strip()
    assert "calc" in prompt


# B7: an oracle that is non-vacuous (fails the stub) but CONTRADICTS the real impl.
WRONG_TEST = (
    "from calc import add\n"
    "\n"
    "def test_add_wrong():\n"
    "    assert add(2, 3) == 6\n"  # real add returns 5 -> fails the real impl
)


def test_build_author_prompt_includes_reference_source(tmp_path):
    # B7a: the spec-writer sees the reference source so it can author accurate
    # tests for non-obvious behaviour.
    spec = {"description": "calc"}
    prompt = build_author_prompt("calc", spec, REAL_SOURCE)
    assert "return a + b" in prompt


def test_build_author_prompt_injects_required_unit_tokens(tmp_path):
    # B10: the exact -k tokens are injected so the author can't abbreviate a
    # multi-unit module's test names (which would make -k miss + cascade-fail).
    spec = {"description": "calc"}
    prompt = build_author_prompt(
        "calc", spec, REAL_SOURCE, unit_names=["mathlib_descriptor", "post_init"]
    )
    assert "mathlib_descriptor" in prompt
    assert "post_init" in prompt
    assert "VERBATIM" in prompt


def test_build_author_prompt_demands_test_body_isolation(tmp_path):
    # Session #39 (inflection): a side-effecting initializer (`_irregular`) was
    # authored an oracle THROUGH a sibling consumer (`pluralize`), which is a
    # NotImplementedError stub while _irregular is under reconstruction -> false
    # fail. The prompt must instruct each test body to exercise ONLY its own unit
    # and to assert on mutated module-level state directly for None-returning
    # side-effecting units.
    spec = {"description": "calc"}
    prompt = build_author_prompt("calc", spec)
    assert "ISOLATION" in prompt
    assert "module-level state" in prompt
    assert "NotImplementedError stub" in prompt


def test_author_oracle_rejects_oracle_contradicting_real_impl(tmp_path):
    # B7b: with the real-impl gate on, a non-vacuous-but-WRONG oracle is rejected
    # and regenerated; the accurate draft is returned.
    sd = tmp_path / "state"
    drafts = [WRONG_TEST, GOOD_TEST]

    def gen_fn(prompt, *, session_dir, attempt):
        return (drafts[attempt], "python -m pytest test_calc_oracle.py -q")

    result = author_oracle(
        "calc", REAL_SOURCE, {"description": "calc"}, {}, sd,
        gen_fn=gen_fn, task_id="TASK_X", max_attempts=2, real_impl_gate=True,
    )
    assert result.test_code == GOOD_TEST
    assert result.attempts == 2


def test_real_impl_gate_off_accepts_inaccurate_oracle(tmp_path):
    # The gate defaults OFF so a dep-bearing module (real impl not importable in
    # the parent interpreter) is never falsely rejected -- a non-vacuous oracle is
    # accepted on the old terms.
    sd = tmp_path / "state"

    def gen_fn(prompt, *, session_dir, attempt):
        return (WRONG_TEST, "python -m pytest test_calc_oracle.py -q")

    result = author_oracle(
        "calc", REAL_SOURCE, {"description": "calc"}, {}, sd,
        gen_fn=gen_fn, task_id="TASK_X", max_attempts=2,
    )
    assert result.test_code == WRONG_TEST


def test_author_oracle_accepts_non_vacuous(tmp_path):
    """(b)/(c) A non-vacuous generation is accepted and returned, and the role
    hands its OWN session dir to the generator (independence by construction)."""
    sd = tmp_path / "state"
    seen = {}

    def gen_fn(prompt, *, session_dir, attempt):
        seen["session_dir"] = pathlib.Path(session_dir)
        seen["prompt"] = prompt
        return (GOOD_TEST, "python -m pytest test_calc_oracle.py -q")

    result = author_oracle(
        "calc", REAL_SOURCE, {"description": "calc"}, {}, sd,
        gen_fn=gen_fn, task_id="TASK_X",
    )
    assert isinstance(result, GeneratedOracle)
    assert result.test_code == GOOD_TEST
    assert result.verification_command
    assert result.test_filename.endswith(".py")
    # the generator was invoked with the role's independent session dir
    assert "test_author" in seen["session_dir"].parts


def test_author_oracle_rejects_vacuous(tmp_path):
    """(b) The non-vacuity gate rejects an oracle that passes the stub, and the
    role raises VacuousOracleError after exhausting attempts."""
    sd = tmp_path / "state"
    calls = {"n": 0}

    def gen_fn(prompt, *, session_dir, attempt):
        calls["n"] += 1
        return (VACUOUS_TEST, "python -m pytest test_calc_oracle.py -q")

    with pytest.raises(VacuousOracleError):
        author_oracle(
            "calc", REAL_SOURCE, {"description": "calc"}, {}, sd,
            gen_fn=gen_fn, task_id="TASK_X", max_attempts=2,
        )
    assert calls["n"] == 2  # it retried before giving up


def test_author_oracle_retries_then_succeeds(tmp_path):
    """A vacuous first draft is retried; a good second draft is accepted."""
    sd = tmp_path / "state"
    drafts = [VACUOUS_TEST, GOOD_TEST]

    def gen_fn(prompt, *, session_dir, attempt):
        return (drafts[attempt], "python -m pytest test_calc_oracle.py -q")

    result = author_oracle(
        "calc", REAL_SOURCE, {"description": "calc"}, {}, sd,
        gen_fn=gen_fn, task_id="TASK_X", max_attempts=2,
    )
    assert result.test_code == GOOD_TEST
    assert result.attempts == 2


# #37: a draft that is not valid Python (the agent emitted a prose status
# message instead of a fenced code block) must be REJECTED, not accepted as
# "non-vacuous". A prose draft SyntaxErrors against the stub, which the old gate
# mis-read as "fails the stub" = non-vacuous, writing the prose verbatim as the
# oracle and breaking collection for the whole rebuild.
PROSE_DRAFT = (
    "The task is complete — the oracle has already been written and validated. "
    "The background search that just finished is no longer needed.\n"
)


def test_author_oracle_rejects_unparseable_prose_draft(tmp_path):
    sd = tmp_path / "state"
    drafts = [PROSE_DRAFT, GOOD_TEST]

    def gen_fn(prompt, *, session_dir, attempt):
        return (drafts[attempt], "python -m pytest test_calc_oracle.py -q")

    result = author_oracle(
        "calc", REAL_SOURCE, {"description": "calc"}, {}, sd,
        gen_fn=gen_fn, task_id="TASK_X", max_attempts=2,
    )
    assert result.test_code == GOOD_TEST
    assert result.attempts == 2


def test_author_oracle_all_unparseable_raises(tmp_path):
    sd = tmp_path / "state"
    calls = {"n": 0}

    def gen_fn(prompt, *, session_dir, attempt):
        calls["n"] += 1
        return (PROSE_DRAFT, "python -m pytest test_calc_oracle.py -q")

    with pytest.raises(VacuousOracleError):
        author_oracle(
            "calc", REAL_SOURCE, {"description": "calc"}, {}, sd,
            gen_fn=gen_fn, task_id="TASK_X", max_attempts=3,
        )
    assert calls["n"] == 3
