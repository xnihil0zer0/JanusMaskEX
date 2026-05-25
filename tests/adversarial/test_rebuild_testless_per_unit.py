"""Regression-lock P1/C9.16: gen_testless authors oracles PER UNIT.

The old ensure_testless_oracles made ONE whole-module test-author call -- which
times out the live ``claude -p`` at 600s on a large module and yields
behaviour-named tests that ``pytest -k <unit>`` misses (-> whole-file cascade).
author_unit_oracles authors one SMALL prompt per unit, naming tests test_<unit>_*
so -k scopes, with the per-unit stub-must-fail non-vacuity + real-impl gates.
"""

from __future__ import annotations

import re
import time

import harness.rebuild.loop as loop
from harness.rebuild import discover

MOD = (
    "import re\n\n\n"
    "def alpha(x: int) -> int:\n    return x + 1\n\n\n"
    "def beta(s: str) -> str:\n    return re.sub(r'[a-z]', '*', s)\n"
)


def _gen_for(prompt):
    # Author a CORRECT per-unit test (fails the NotImplementedError stub,
    # passes the real impl). The prompt embeds only the unit-under-test's source.
    if "def alpha" in prompt:
        return ("from mathmod import alpha\n\n\n"
                "def test_alpha_increments():\n    assert alpha(1) == 2\n",
                "python -m pytest -q")
    return ("from mathmod import beta\n\n\n"
            "def test_beta_stars_lowercase():\n    assert beta('aB') == '*B'\n",
            "python -m pytest -q")


def test_ensure_testless_authors_per_unit(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "mathmod.py").write_text(MOD, encoding="utf-8")

    calls = []

    def counting_gen(prompt, *, session_dir, attempt):
        calls.append(prompt)
        return _gen_for(prompt)

    desc = discover.build_descriptor(
        src, output_dir=tmp_path / "out", stash_dir=tmp_path / "stash",
        modules=["mathmod.py"], test_files=[], dependencies=[], requirements_files=[],
    )
    loop.ensure_testless_oracles(desc, gen_fn=counting_gen)

    # one TA call PER UNIT (2 units), NOT one whole-module call.
    assert len(calls) == 2
    # each prompt was scoped to a SINGLE unit's source (small + fast).
    assert any("def alpha" in p and "def beta" not in p for p in calls)
    assert any("def beta" in p and "def alpha" not in p for p in calls)
    # the per-unit slice carries the module's TOP-LEVEL IMPORTS so the real-impl
    # gate (execs the slice standalone) doesn't NameError on `re` and falsely
    # reject every draft (the deps._norm_name live failure, #42).
    assert all("import re" in p for p in calls)
    # the combined oracle file has BOTH units' named tests so -k <unit> scopes.
    out_test = (tmp_path / "out" / "test_mathmod_generated.py").read_text(encoding="utf-8")
    assert "test_alpha" in out_test and "test_beta" in out_test
    # per-unit selector wired.
    assert "{unit}" in desc.unit_test_selector


def test_one_hard_unit_does_not_abort_the_module(tmp_path):
    # The live author can fail a single hard unit (3 vacuous/inaccurate drafts).
    # That must DEGRADE (skip that unit's test) -- not abort the whole module's
    # oracle authoring (the deps._dedup live failure, #42).
    src = tmp_path / "src"
    src.mkdir()
    (src / "mathmod.py").write_text(MOD, encoding="utf-8")

    def flaky_gen(prompt, *, session_dir, attempt):
        if "def alpha" in prompt:
            # vacuous: never calls alpha -> passes the NotImplementedError stub.
            return ("def test_alpha_noop():\n    assert 1 == 1\n", "python -m pytest -q")
        return _gen_for(prompt)

    desc = discover.build_descriptor(
        src, output_dir=tmp_path / "out", stash_dir=tmp_path / "stash",
        modules=["mathmod.py"], test_files=[], dependencies=[], requirements_files=[],
    )
    # must NOT raise VacuousOracleError -- the hard unit is skipped.
    loop.ensure_testless_oracles(desc, gen_fn=flaky_gen)
    out_test = (tmp_path / "out" / "test_mathmod_generated.py").read_text(encoding="utf-8")
    assert "test_beta" in out_test       # the good unit still got its oracle
    assert "test_alpha_noop" not in out_test  # the hard unit was skipped


def test_author_timeout_does_not_abort_the_module(tmp_path):
    # A single unit's live ``claude -p`` author call can TIME OUT (600s) ->
    # test_author raises TestAuthorError. That must DEGRADE (skip that unit's
    # test) exactly like VacuousOracleError -- NOT propagate out of the parallel
    # ThreadPool and crash ensure_testless_oracles -> reconstruct_all -> the whole
    # loop (which is what made the #46 P0 batch land ZERO units). The module's
    # other units still get their oracles.
    from harness import test_author

    src = tmp_path / "src"
    src.mkdir()
    (src / "mathmod.py").write_text(MOD, encoding="utf-8")

    def timeout_gen(prompt, *, session_dir, attempt):
        if "def alpha" in prompt:
            raise test_author.TestAuthorError(
                "live test-author generation failed: timed out after 600 seconds"
            )
        return _gen_for(prompt)

    desc = discover.build_descriptor(
        src, output_dir=tmp_path / "out", stash_dir=tmp_path / "stash",
        modules=["mathmod.py"], test_files=[], dependencies=[], requirements_files=[],
    )
    # must NOT raise TestAuthorError -- the timed-out unit is skipped.
    loop.ensure_testless_oracles(desc, gen_fn=timeout_gen)
    out_test = (tmp_path / "out" / "test_mathmod_generated.py").read_text(encoding="utf-8")
    assert "test_beta" in out_test       # the good unit still got its oracle
    assert "test_alpha" not in out_test  # the timed-out unit was skipped


_QMOD = "\n\n\n".join(f"def u{i}(x: int) -> int:\n    return x + {i}" for i in range(4)) + "\n"


def _slow_gen(prompt, *, session_dir, attempt):
    # simulate the ~minutes-long live claude -p author latency.
    time.sleep(0.4)
    m = re.search(r"def (u(\d))", prompt)
    u, i = m.group(1), m.group(2)
    return (f"from qmod import {u}\n\n\ndef test_{u}_adds():\n    assert {u}(0) == {i}\n",
            "python -m pytest -q")


def _qdesc(tmp_path, name):
    src = tmp_path / name
    src.mkdir()
    (src / "qmod.py").write_text(_QMOD, encoding="utf-8")
    return discover.build_descriptor(
        src, output_dir=tmp_path / f"out_{name}", stash_dir=tmp_path / f"stash_{name}",
        modules=["qmod.py"], test_files=[], dependencies=[], requirements_files=[],
    )


def test_parallel_authoring_is_faster_than_serial(tmp_path):
    # P0/C9.17: the per-unit author calls run in a ThreadPoolExecutor, so N units
    # author in ~ceil(N/workers) x latency, NOT N x. Relative timing (robust to
    # box load): parallel (4 workers, 4 units) must be meaningfully faster than
    # serial (1 worker). The ~0.4s sleep models the live ~minutes author latency.
    d1 = _qdesc(tmp_path, "serial")
    t0 = time.monotonic()
    loop.ensure_testless_oracles(d1, gen_fn=_slow_gen, config={"rebuild": {"author_workers": 1}})
    t_serial = time.monotonic() - t0

    d4 = _qdesc(tmp_path, "par")
    t0 = time.monotonic()
    loop.ensure_testless_oracles(d4, gen_fn=_slow_gen, config={"rebuild": {"author_workers": 4}})
    t_parallel = time.monotonic() - t0

    assert t_parallel < t_serial * 0.7, (t_parallel, t_serial)
    # all 4 units authored, in DETERMINISTIC source order regardless of completion.
    out = (tmp_path / "out_par" / "test_qmod_generated.py").read_text(encoding="utf-8")
    positions = [out.index(f"# ----- u{i} -----") for i in range(4)]
    assert positions == sorted(positions)
