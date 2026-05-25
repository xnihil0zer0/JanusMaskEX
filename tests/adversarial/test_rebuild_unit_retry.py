"""B5: reconstruct_unit retries a stochastic differential miss (bounded, test-gated).

A single failed worker dispatch must not be terminal for a non-oversized unit --
the oversized driver already retries; this proves the normal path does too. The
stub is restored between attempts so a retry starts from a clean body.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import harness.rebuild.harvest as _harvest
import harness.rebuild.loop as _loop
from harness.rebuild.target import TargetDescriptor

_REAL = "def add(a: int, b: int) -> int:\n    return a + b\n"
_STUB = "def add(a: int, b: int) -> int:\n    raise NotImplementedError\n"


def _setup(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "calc.py").write_text(_STUB, encoding="utf-8")
    stash = tmp_path / "stash"
    stash.mkdir()
    (stash / "calc.py").write_text(_REAL, encoding="utf-8")
    desc = TargetDescriptor(
        name="calc",
        source_root=tmp_path,
        modules=["calc.py"],
        test_files=[],
        output_dir=out,
        stash_dir=stash,
        unit_test_selector="",
    )
    unit = _harvest.harvest_module("calc.py", _REAL)[0]
    stash_map = {"calc.py": str(stash / "calc.py")}
    return out, desc, unit, stash_map


def test_retry_lands_on_second_attempt(tmp_path, monkeypatch):
    out, desc, unit, stash_map = _setup(tmp_path)
    monkeypatch.setattr(_loop, "build_worker_invocation", lambda d, t: (["true"], str(out), {}))
    monkeypatch.setattr(_loop, "_run_unit_tests", lambda d, u: {"returncode": 0, "stdout_tail": ""})
    calls = {"n": 0}

    def fake_run(cmd, *a, **k):
        if cmd and cmd[0] == "git":  # the internal _git rev-parse -- no repo here
            return SimpleNamespace(stdout="", stderr="", returncode=1)
        calls["n"] += 1
        if calls["n"] == 1:
            # attempt 1: a stochastic miss -- leave the stub, report failure.
            assert _loop.has_notimplemented(out / "calc.py", "add"), "stub must be restored before each attempt"
            return SimpleNamespace(stdout='{"outcome": "rejected", "reason": "auto_commit_failed_r1"}', stderr="", returncode=1)
        # attempt 2: the worker lands the real body.
        (out / "calc.py").write_text(_REAL, encoding="utf-8")
        return SimpleNamespace(stdout='{"outcome": "accepted"}', stderr="", returncode=0)

    monkeypatch.setattr(_loop.subprocess, "run", fake_run)
    res = _loop.reconstruct_unit(desc, unit, "calc.py", stash_map)
    assert res["body_landed"] is True
    assert res["attempts"] == 2
    assert res["tests_passed"] is True
    assert calls["n"] == 2
    assert not _loop.has_notimplemented(out / "calc.py", "add")


def test_retry_gives_up_after_max_attempts(tmp_path, monkeypatch):
    out, desc, unit, stash_map = _setup(tmp_path)
    monkeypatch.setattr(_loop, "build_worker_invocation", lambda d, t: (["true"], str(out), {}))
    monkeypatch.setattr(_loop, "_run_unit_tests", lambda d, u: {"returncode": 0, "stdout_tail": ""})
    calls = {"n": 0}

    def fake_run(cmd, *a, **k):
        if cmd and cmd[0] == "git":
            return SimpleNamespace(stdout="", stderr="", returncode=1)
        calls["n"] += 1
        return SimpleNamespace(stdout='{"outcome": "rejected", "reason": "miss"}', stderr="", returncode=1)

    monkeypatch.setattr(_loop.subprocess, "run", fake_run)
    res = _loop.reconstruct_unit(desc, unit, "calc.py", stash_map, max_attempts=3)
    assert res["body_landed"] is False
    assert res["attempts"] == 3
    assert calls["n"] == 3
    # stub restored after the final miss.
    assert _loop.has_notimplemented(out / "calc.py", "add")
