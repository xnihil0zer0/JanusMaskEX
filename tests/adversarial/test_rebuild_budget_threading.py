"""B4 (session #37) contract: a unit-byte-budget threads from job creation to
the autonomous loop subprocess.

Before this fix loop.main always called reconstruct_all without config=, so the
daemon/loop path was hard-pinned to the 4000-char default and could never
exercise the oversized decompose->reconstruct->recompose driver. The budget now
flows: create_job(unit_byte_budget=N) -> job['unit_byte_budget'] ->
build_loop_command(--unit-byte-budget N) -> loop.main builds
config={'rebuild':{'unit_byte_budget':N}} -> reconstruct_all(config=) ->
unit_exceeds_byte_budget / _budget_from_config.
"""
from __future__ import annotations

from pathlib import Path

import harness.rebuild.job as job
import harness.rebuild.loop as loop

_REPO = Path(__file__).resolve().parent.parent.parent


def _state(tmp_path) -> Path:
    sd = tmp_path / "state"
    (sd / "control" / "autowork").mkdir(parents=True)
    (sd / "control" / "autowork" / "auto_promote.allowlist").write_text("# allowlist\n", encoding="utf-8")
    return sd


def _make_job(tmp_path, **kw):
    return job.create_job(
        input_dir=_REPO / "samples" / "mathlib",
        output_dir=tmp_path / "out",
        state_dir=_state(tmp_path),
        stash_dir=tmp_path / "stash",
        repo_root=tmp_path,
        **kw,
    )


class _FakeUnit:
    def __init__(self, name, cls=None):
        self.name = name
        self.cls = cls


def test_create_job_persists_budget(tmp_path):
    j = _make_job(tmp_path, unit_byte_budget=250)
    assert j["unit_byte_budget"] == 250


def test_create_job_default_budget_is_none(tmp_path):
    j = _make_job(tmp_path)
    assert j.get("unit_byte_budget") is None


def test_build_loop_command_emits_budget_flag(tmp_path):
    j = _make_job(tmp_path, unit_byte_budget=250)
    cmd = job.build_loop_command(j)
    assert "--unit-byte-budget" in cmd
    assert cmd[cmd.index("--unit-byte-budget") + 1] == "250"


def test_build_loop_command_omits_flag_when_unset(tmp_path):
    j = _make_job(tmp_path)
    cmd = job.build_loop_command(j)
    assert "--unit-byte-budget" not in cmd


def test_config_shape_from_main_is_honored_by_budget_helpers():
    # the exact config dict loop.main constructs from --unit-byte-budget
    config = {"rebuild": {"unit_byte_budget": 250}}
    assert loop._budget_from_config(config) == 250
    big = "def f():\n    " + "x = 1\n    " * 200 + "return x\n"
    assert loop.unit_exceeds_byte_budget(big, _FakeUnit("f"), config) is True
    assert loop.unit_exceeds_byte_budget(big, _FakeUnit("f"), {"rebuild": {"unit_byte_budget": 100000}}) is False
