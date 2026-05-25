"""Tests for harness.rebuild.job: the daemon-drivable rebuild JOB lifecycle.

A job bundles a TargetDescriptor + an initialized output repo (skeleton + git +
stash) + per-unit task specs + an allowlist opt-in, persisted under
state/control/rebuild/jobs/<id>.json so the autowork daemon's rebuild-watcher
can supervise a resumable `harness.rebuild.loop` run to completion.
"""

from __future__ import annotations

import json
from pathlib import Path

import harness.rebuild.job as job
from harness.rebuild.target import TargetDescriptor

_REPO = Path(__file__).resolve().parent.parent.parent


def test_public_surface():
    assert callable(job.create_job)
    assert callable(job.list_jobs)
    assert callable(job.load_job)
    assert callable(job.job_status)
    assert callable(job.build_loop_command)
    assert callable(job.add_to_allowlist)
    assert callable(job.job_slug)
    assert callable(job.main)


def _state(tmp_path) -> Path:
    sd = tmp_path / "state"
    (sd / "control" / "autowork").mkdir(parents=True)
    (sd / "control" / "autowork" / "auto_promote.allowlist").write_text(
        "# allowlist\n", encoding="utf-8"
    )
    return sd


def test_create_job_mathlib(tmp_path):
    sd = _state(tmp_path)
    j = job.create_job(
        input_dir=_REPO / "samples" / "mathlib",
        output_dir=tmp_path / "out",
        state_dir=sd,
        stash_dir=tmp_path / "stash",
        repo_root=tmp_path,  # brief written here, not the real repo root
    )
    assert j["status"] == "pending"
    assert j["name"] == "mathlib"
    assert "mathlib.py:gcd" in j["units"]
    # output repo initialized: skeleton + git + stub bodies
    out = tmp_path / "out"
    assert (out / "mathlib.py").exists()
    assert (out / ".git").exists()
    # job + descriptor persisted
    jobs = job.list_jobs(sd)
    assert len(jobs) == 1 and jobs[0]["job_id"] == j["job_id"]
    assert Path(j["descriptor_path"]).exists()
    # slug allowlisted (the Begin-button safety opt-in)
    allow = (sd / "control" / "autowork" / "auto_promote.allowlist").read_text(encoding="utf-8")
    assert j["job_id"] in allow
    # per-unit task specs queued in the OUTPUT repo
    task_files = list((out / "state" / "tasks").glob("RB_mathlib_*.json"))
    assert len(task_files) == 3


def test_job_status_tracks_remaining(tmp_path):
    sd = _state(tmp_path)
    j = job.create_job(
        input_dir=_REPO / "samples" / "mathlib",
        output_dir=tmp_path / "out",
        state_dir=sd,
        stash_dir=tmp_path / "stash",
        repo_root=tmp_path,
    )
    st = job.job_status(sd, j["job_id"])
    assert set(st["remaining"]) == {"mathlib.py:gcd", "mathlib.py:is_prime", "mathlib.py:fib"}
    assert st["done"] == []
    assert st["complete"] is False
    # make gcd real -> status reflects it
    out_mod = tmp_path / "out" / "mathlib.py"
    real = (_REPO / "samples" / "mathlib" / "mathlib.py").read_text(encoding="utf-8")
    out_mod.write_text(real, encoding="utf-8")
    st2 = job.job_status(sd, j["job_id"])
    assert st2["complete"] is True
    assert st2["remaining"] == []


def test_build_loop_command_is_resumable_and_retargeted(tmp_path):
    sd = _state(tmp_path)
    j = job.create_job(
        input_dir=_REPO / "samples" / "mathlib",
        output_dir=tmp_path / "out",
        state_dir=sd,
        stash_dir=tmp_path / "stash",
        repo_root=tmp_path,
    )
    cmd = job.build_loop_command(j)
    assert "--resume" in cmd
    # loop runs in the PARENT (needs import harness) -> launched via -m, NOT by
    # file path. The file-path/retarget law applies to the output-repo worker the
    # loop spawns (build_worker_invocation), not to the loop launcher itself.
    assert "-m" in cmd and "harness.rebuild.loop" in cmd
    assert str(tmp_path / "out") in cmd
    assert job.parent_root() == str(Path(job.__file__).resolve().parents[2])


def test_n_units_counts_class_methods(tmp_path):
    # B8: _all_unit_qualnames must harvest with include_methods=True so a per-method
    # unit (e.g. a dataclass __post_init__, which the loop reconstructs as its own
    # unit) is counted in n_units instead of being silently omitted from the total.
    src = (
        "from dataclasses import dataclass\n\n\n"
        "@dataclass\n"
        "class Box:\n"
        "    raw: str\n"
        '    norm: str = ""\n'
        "    def __post_init__(self):\n"
        "        self.norm = self.raw.strip().lower()\n"
    )
    (tmp_path / "box.py").write_text(src, encoding="utf-8")
    desc = TargetDescriptor(
        name="box",
        source_root=tmp_path,
        modules=["box.py"],
        test_files=[],
        output_dir=tmp_path / "out",
        stash_dir=tmp_path / "stash",
        unit_test_selector="test_box.py -k {unit}",
    )
    qns = job._all_unit_qualnames(desc)
    assert "box.py:Box.__post_init__" in qns, f"per-method units must count: {qns}"


def test_add_to_allowlist_idempotent(tmp_path):
    sd = _state(tmp_path)
    job.add_to_allowlist(sd, "rebuild_demo")
    job.add_to_allowlist(sd, "rebuild_demo")
    allow = (sd / "control" / "autowork" / "auto_promote.allowlist").read_text(encoding="utf-8")
    assert allow.count("rebuild_demo") == 1
