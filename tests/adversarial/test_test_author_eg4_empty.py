"""Regression-lock EG4: an EMPTY (0-test) authored oracle is a loud degrade.

An oracle draft with no ``test_*`` functions makes pytest exit 5 (no tests
collected). ``oracle_is_non_vacuous`` is ``not run_oracle_against(...stub)``, so
exit 5 (returncode != 0) reads as "failed the stub" = non-vacuous -- and when
``real_impl_gate`` is off the empty draft is silently ACCEPTED as a no-op gate
(#47 config_loader degraded this way -> "no tests ran" -> units stubbed).
``author_oracle`` must reject a 0-test draft explicitly so the degrade surfaces
as a VacuousOracleError instead of a fake gate.
"""
from __future__ import annotations

import pytest

import harness.test_author as ta


def _gen(seq):
    """A gen_fn that yields successive (test_code, vcmd) drafts from ``seq``."""
    it = iter(seq)

    def gen_fn(prompt, *, session_dir, attempt):
        return next(it), "pytest -q"

    return gen_fn


SRC = "def add(a, b):\n    '''sum'''\n    return a + b\n"
EMPTY = "# no tests here\nimport math\n"
GOOD = (
    "from m import add\n\n\n"
    "def test_add_sums():\n    assert add(2, 3) == 5\n"
)


def test_empty_oracle_rejected(tmp_path):
    # Two empty drafts -> no acceptable oracle -> VacuousOracleError (loud degrade).
    with pytest.raises(ta.VacuousOracleError):
        ta.author_oracle(
            "m", SRC, {"description": "adds two numbers"}, {},
            tmp_path, gen_fn=_gen([EMPTY, EMPTY]), max_attempts=2,
        )


def test_empty_then_good_oracle_accepted(tmp_path):
    # An empty first draft is skipped; a real second draft is accepted.
    oracle = ta.author_oracle(
        "m", SRC, {"description": "adds two numbers"}, {},
        tmp_path, gen_fn=_gen([EMPTY, GOOD]), max_attempts=2,
    )
    assert "test_add_sums" in oracle.test_code
    assert oracle.attempts == 2
