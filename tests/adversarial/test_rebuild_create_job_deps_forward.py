"""Regression-lock: create_job forwards explicit dependencies/requirements_files.

build_descriptor accepts dependencies=/requirements_files= (to skip the deps SCAN
so a SLICE rebuild can run standalone), but create_job dropped them -> a stdlib-only
module sliced out of a dep-bearing repo would still provision a spurious .venv from
the REPO's requirements. create_job now forwards both (R2/#42).
"""

from __future__ import annotations

from pathlib import Path

import harness.rebuild.job as job

_REPO = Path(__file__).resolve().parent.parent.parent


def _state(tmp_path) -> Path:
    sd = tmp_path / "state"
    (sd / "control" / "autowork").mkdir(parents=True)
    (sd / "control" / "autowork" / "auto_promote.allowlist").write_text("# allowlist\n", encoding="utf-8")
    return sd


def test_create_job_explicit_empty_deps_overrides_scan(tmp_path):
    # An input dir that WOULD scan a dependency (requirements.txt names one).
    src = tmp_path / "src"
    src.mkdir()
    (src / "mod.py").write_text("def f(x: int) -> int:\n    return x + 1\n", encoding="utf-8")
    (src / "requirements.txt").write_text("some-third-party-pkg==1.0\n", encoding="utf-8")
    sd = _state(tmp_path)
    j = job.create_job(
        input_dir=src,
        output_dir=tmp_path / "out",
        state_dir=sd,
        stash_dir=tmp_path / "stash",
        modules=["mod.py"],
        test_files=[],
        dependencies=[],          # explicit override -> skip the scan
        requirements_files=[],
        repo_root=tmp_path,
    )
    # Before the fix create_job dropped the kwarg and build_descriptor re-SCANNED
    # requirements.txt -> dependencies==['some-third-party-pkg==1.0'] -> a spurious
    # .venv provision. The forward makes the explicit [] win (standalone slice).
    assert j["descriptor"]["dependencies"] == []
    assert j["descriptor"]["requirements_files"] == []
