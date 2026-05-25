"""M17 coverage: CLI argparse wiring for --output-drain-dir and --baseline-dir.

Sub-plan 04 §Proposed 5 + master-plan M17: no test exercises the two drain
flags through the subprocess CLI. Python-level paths are covered in
tests/hooks/unit/test_hooks_drain.py; these tests close the gap by running
python -m harness.hooks_equivalence via subprocess and asserting the
drain_report_*.json file lands in the expected location.

Two shapes:

1. --output-drain-dir override: report lands in the explicit dir,
   not under state/hooks/.
2. Default path (no --output-drain-dir): B2 says the report should default
   to <project>/state/hooks/drain_report_*.json. The corrections edit to
   harness/hooks_equivalence.py is blocked by the META-phase write gate, so
   the default-path test is marked xfail(strict=False) with a precise reason
   citing sub-plan 04 phase5 §Proposed 2 / master-plan B2. Once the default
   lands it flips to xpassed.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys

import pytest

from harness import hooks_equivalence as he


_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


_B2_XFAIL_REASON = (
    "Sub-plan 04 phase5 §Proposed 2 / master-plan B2: "
    "harness/hooks_equivalence.py:1631-1640 _maybe_emit_drain_report "
    "short-circuits when output_dir is None -- no report file is written "
    "anywhere, including under <project>/state/hooks/. The META-phase "
    "write gate blocks the corrections edit (file lives in the P5 "
    "allow-list only). Test flips green once the default path lands."
)


def _baseline_art(**overrides):
    base = dict(
        patch_stat=(
            " harness/orchestrator.py | 6 +++---\n"
            " 1 file changed, 3 insertions(+), 3 deletions(-)"
        ),
        test_count=776,
        track_events=[
            {"ts": "2026-04-18T00:00:00Z", "event": "start", "task_id": "STAB-001"},
            {"ts": "2026-04-18T00:00:02Z", "event": "test_pass", "task_id": "STAB-001"},
        ],
    )
    base.update(overrides)
    return he.DrainArtefacts(**base)


def _stage_baseline_and_actual(tmp_path: pathlib.Path, brief: str = "stab_001"):
    """Create state/hooks/drain_baseline_<brief>.json + actual.json under tmp_path.
    Returns (baseline_dir, actual_path). The actual artefacts diverge from the
    baseline in test_count so the drain run exits 1 and we get a report file."""
    baseline_dir = tmp_path / "state" / "hooks"
    baseline_dir.mkdir(parents=True)
    baseline_art = _baseline_art()
    he.save_drain_baseline(
        brief_id=brief, artefacts=baseline_art, baseline_dir=baseline_dir,
    )
    actual_art = _baseline_art(test_count=1)  # divergence on test_count
    actual_path = tmp_path / "actual.json"
    actual_path.write_text(
        json.dumps(he.drain_artefacts_to_dict(actual_art)), encoding="utf-8",
    )
    return baseline_dir, actual_path


def _run_cli(args, tmp_path: pathlib.Path):
    env = dict(os.environ)
    env["JANUSMASK_PROJECT_DIR"] = str(tmp_path)
    return subprocess.run(
        [sys.executable, "-m", "harness.hooks_equivalence", *args],
        env=env, cwd=str(_REPO_ROOT),
        capture_output=True, text=True,
    )


# -- --output-drain-dir override lands the report in the explicit dir -------


def test_cli_drain_writes_report_to_explicit_output_drain_dir(tmp_path):
    _stage_baseline_and_actual(tmp_path)
    out_dir = tmp_path / "custom_reports"
    proc = _run_cli(
        [
            "--drain", "stab_001",
            "--actual-path", str(tmp_path / "actual.json"),
            "--output-drain-dir", str(out_dir),
        ],
        tmp_path=tmp_path,
    )
    assert proc.returncode == 1, proc.stderr  # divergence expected
    reports = list(out_dir.glob("drain_report_*.json"))
    assert reports, (
        "expected drain_report_*.json under explicit --output-drain-dir "
        + str(out_dir) + "; dir contents: "
        + repr(list(out_dir.iterdir()) if out_dir.exists() else "<missing>")
    )
    data = json.loads(reports[0].read_text(encoding="utf-8"))
    assert data["brief_id"] == "stab_001"
    assert data["clean"] is False


def test_cli_drain_baseline_dir_override_reads_from_explicit_dir(tmp_path):
    """--baseline-dir should override the default state/hooks lookup.
    Stage the baseline under a non-default dir and point --baseline-dir at
    it; the comparator must find + compare against that baseline, not fail
    with 'no baseline found'."""
    custom_baseline_dir = tmp_path / "alt_baselines"
    custom_baseline_dir.mkdir()
    baseline_art = _baseline_art()
    he.save_drain_baseline(
        brief_id="stab_001",
        artefacts=baseline_art,
        baseline_dir=custom_baseline_dir,
    )
    actual_path = tmp_path / "actual.json"
    actual_path.write_text(
        json.dumps(he.drain_artefacts_to_dict(baseline_art)), encoding="utf-8",
    )
    proc = _run_cli(
        [
            "--drain", "stab_001",
            "--actual-path", str(actual_path),
            "--baseline-dir", str(custom_baseline_dir),
        ],
        tmp_path=tmp_path,
    )
    # Clean compare -> exit 0. If --baseline-dir were ignored we would hit
    # "no baseline found" and exit 1 / stderr would mention baseline missing.
    assert proc.returncode == 0, (
        "drain should be clean when --baseline-dir points at a staged "
        "baseline. stdout=" + proc.stdout + " stderr=" + proc.stderr
    )


# -- Default --output-drain-dir (None) should land under state/hooks/ -------


def test_cli_drain_default_output_dir_writes_under_state_hooks(tmp_path):
    """Brief: reports land at <project>/state/hooks/drain_report_*.json by
    default. _maybe_emit_drain_report now defaults to <project>/state/hooks
    when output_dir is None (B2 edit landed)."""
    baseline_dir, actual_path = _stage_baseline_and_actual(tmp_path)
    proc = _run_cli(
        [
            "--drain", "stab_001",
            "--actual-path", str(actual_path),
            # note: no --output-drain-dir
        ],
        tmp_path=tmp_path,
    )
    assert proc.returncode == 1, proc.stderr
    # B2 target: default output-drain-dir is <project>/state/hooks/
    reports = list(baseline_dir.glob("drain_report_*.json"))
    assert reports, (
        "expected default drain_report_*.json under " + str(baseline_dir)
        + "; dir contents: " + repr(list(baseline_dir.iterdir()))
    )
