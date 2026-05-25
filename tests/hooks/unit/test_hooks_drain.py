"""HOOK-55 drain-e2e unit tests.

Covers the drain-runner primitives added to harness/hooks_equivalence.py:

* DrainArtefacts / DrainBaseline / DrainReport dataclasses.
* capture_drain_artefacts: reads the patch file, counts collected tests,
  loads a tracks .jsonl — never mutates source.
* save_drain_baseline / load_drain_baseline: round-trip JSON persistence
  under state/hooks/drain_baseline_<brief>.json.
* compare_drain_artefacts: exact compare for patch_stat / test_count plus a
  multiset diff for track_events (order-insensitive, per sub-plan 06 §2 L3).
* run_drain_cycle: accepts an injectable cycle_runner callable so unit tests
  never spawn real Claude/Gemini.
* fire_drain_rollback: writes state/hooks/rollback_signal with
  trigger=drain_consensus_regression and dispatches apply_rollback (HOOK-54).
* CLI --drain mode: exit 0 clean, exit 1 regression; fires rollback inline
  when --emit-rollback is set so operators do not duplicate flip logic.

The drain never touches run_consensus_patch.py or state/tracks/ — tests
supply baselines + actuals through the injectable boundary.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest

from harness import hooks_equivalence as he


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


def _baseline_artefacts(**overrides):
    base = dict(
        patch_stat=" harness/orchestrator.py | 6 +++---\n 1 file changed, 3 insertions(+), 3 deletions(-)",
        test_count=776,
        track_events=[
            {"ts": "2026-04-18T00:00:00Z", "event": "start", "task_id": "STAB-001"},
            {"ts": "2026-04-18T00:00:01Z", "event": "write", "task_id": "STAB-001"},
            {"ts": "2026-04-18T00:00:02Z", "event": "test_pass", "task_id": "STAB-001"},
        ],
    )
    base.update(overrides)
    return he.DrainArtefacts(**base)


@pytest.fixture
def baseline(tmp_path):
    art = _baseline_artefacts()
    baseline_dir = tmp_path / "hooks"
    baseline_dir.mkdir()
    path = he.save_drain_baseline(
        brief_id="stab_001",
        artefacts=art,
        baseline_dir=baseline_dir,
    )
    return path, art, baseline_dir


# ---------------------------------------------------------------------------
# contract: constants + dataclasses
# ---------------------------------------------------------------------------


def test_drain_briefs_includes_regression_triad():
    assert he.DRAIN_BRIEFS == ("stab_001", "stab_003", "stab_005")


def test_drain_baseline_dir_constant_under_state_hooks():
    assert he.DRAIN_BASELINE_DIR.endswith("hooks")
    assert "state" in he.DRAIN_BASELINE_DIR


def test_drain_artefacts_dataclass_is_json_serialisable():
    art = _baseline_artefacts()
    payload = he.drain_artefacts_to_dict(art)
    round_trip = json.loads(json.dumps(payload))
    assert round_trip["patch_stat"] == art.patch_stat
    assert round_trip["test_count"] == art.test_count
    assert round_trip["track_events"] == art.track_events


def test_drain_report_to_dict_has_clean_and_divergences():
    art = _baseline_artefacts()
    actual = _baseline_artefacts()
    report = he.run_drain_cycle(
        brief_id="stab_001",
        cycle_runner=lambda _brief: actual,
        baseline=he.DrainBaseline(brief_id="stab_001", artefacts=art),
    )
    data = report.to_dict()
    assert data["clean"] is True
    assert data["divergences"] == []
    assert data["brief_id"] == "stab_001"


# ---------------------------------------------------------------------------
# capture_drain_artefacts
# ---------------------------------------------------------------------------


def test_capture_drain_artefacts_reads_patch_stat_and_tracks(tmp_path):
    patch = tmp_path / "patch.diff"
    patch.write_text(
        "diff --git a/harness/orchestrator.py b/harness/orchestrator.py\n"
        "index 111..222 100644\n"
        "--- a/harness/orchestrator.py\n"
        "+++ b/harness/orchestrator.py\n"
        "@@ -1,3 +1,3 @@\n"
        "-old\n"
        "+new\n"
        " unchanged\n"
        " context\n",
        encoding="utf-8",
    )
    tracks = tmp_path / "tracks.jsonl"
    rows = [
        {"ts": "2026-04-18T00:00:00Z", "event": "start"},
        {"ts": "2026-04-18T00:00:01Z", "event": "test_pass"},
    ]
    tracks.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    art = he.capture_drain_artefacts(
        patch_path=patch, test_count=123, tracks_path=tracks
    )
    assert art.test_count == 123
    assert art.track_events == rows
    # patch_stat should be a non-empty string summarising the diff
    assert art.patch_stat
    assert "harness/orchestrator.py" in art.patch_stat


def test_capture_drain_artefacts_empty_tracks_is_empty_list(tmp_path):
    patch = tmp_path / "patch.diff"
    patch.write_text("", encoding="utf-8")
    tracks = tmp_path / "tracks.jsonl"
    tracks.write_text("", encoding="utf-8")
    art = he.capture_drain_artefacts(
        patch_path=patch, test_count=0, tracks_path=tracks
    )
    assert art.patch_stat == ""
    assert art.test_count == 0
    assert art.track_events == []


def test_capture_drain_artefacts_skips_malformed_track_rows(tmp_path):
    patch = tmp_path / "patch.diff"
    patch.write_text("", encoding="utf-8")
    tracks = tmp_path / "tracks.jsonl"
    tracks.write_text(
        '{"event":"ok"}\n'
        "not-json\n"
        '{"event":"ok2"}\n',
        encoding="utf-8",
    )
    art = he.capture_drain_artefacts(
        patch_path=patch, test_count=0, tracks_path=tracks
    )
    assert {r["event"] for r in art.track_events} == {"ok", "ok2"}


def test_capture_drain_artefacts_rejects_negative_test_count(tmp_path):
    patch = tmp_path / "patch.diff"
    patch.write_text("", encoding="utf-8")
    tracks = tmp_path / "tracks.jsonl"
    tracks.write_text("", encoding="utf-8")
    with pytest.raises(ValueError):
        he.capture_drain_artefacts(
            patch_path=patch, test_count=-1, tracks_path=tracks
        )


def test_capture_drain_artefacts_missing_patch_file_is_empty_stat(tmp_path):
    tracks = tmp_path / "tracks.jsonl"
    tracks.write_text("", encoding="utf-8")
    art = he.capture_drain_artefacts(
        patch_path=tmp_path / "nope.diff", test_count=0, tracks_path=tracks
    )
    assert art.patch_stat == ""
    assert art.track_events == []


# ---------------------------------------------------------------------------
# baseline persistence
# ---------------------------------------------------------------------------


def test_save_and_load_drain_baseline_round_trip(baseline):
    path, art, baseline_dir = baseline
    assert path.exists()
    loaded = he.load_drain_baseline(brief_id="stab_001", baseline_dir=baseline_dir)
    assert loaded is not None
    assert loaded.brief_id == "stab_001"
    assert loaded.artefacts.patch_stat == art.patch_stat
    assert loaded.artefacts.test_count == art.test_count
    assert loaded.artefacts.track_events == art.track_events


def test_load_drain_baseline_missing_returns_none(tmp_path):
    assert he.load_drain_baseline(brief_id="stab_999", baseline_dir=tmp_path) is None


def test_load_drain_baseline_malformed_json_returns_none(tmp_path):
    target = tmp_path / "drain_baseline_stab_001.json"
    target.write_text("{not json", encoding="utf-8")
    assert he.load_drain_baseline(brief_id="stab_001", baseline_dir=tmp_path) is None


def test_save_drain_baseline_rejects_unknown_brief(tmp_path):
    with pytest.raises(ValueError):
        he.save_drain_baseline(
            brief_id="stab_999",
            artefacts=_baseline_artefacts(),
            baseline_dir=tmp_path,
        )


def test_save_drain_baseline_creates_parent_dir(tmp_path):
    nested = tmp_path / "a" / "b"
    path = he.save_drain_baseline(
        brief_id="stab_003",
        artefacts=_baseline_artefacts(),
        baseline_dir=nested,
    )
    assert path.exists()
    assert path.parent == nested


# ---------------------------------------------------------------------------
# compare_drain_artefacts — multiset + exact
# ---------------------------------------------------------------------------


def test_compare_clean_when_identical():
    a = _baseline_artefacts()
    b = _baseline_artefacts()
    divs = he.compare_drain_artefacts(a, b)
    assert divs == []


def test_compare_detects_patch_stat_delta():
    a = _baseline_artefacts()
    b = _baseline_artefacts(patch_stat="different content")
    divs = he.compare_drain_artefacts(a, b)
    assert any(d.field == "patch_stat" for d in divs)


def test_compare_detects_test_count_delta():
    a = _baseline_artefacts()
    b = _baseline_artefacts(test_count=775)
    divs = he.compare_drain_artefacts(a, b)
    assert any(d.field == "test_count" for d in divs)


def test_compare_track_events_is_order_insensitive():
    a = _baseline_artefacts()
    rev = list(reversed(a.track_events))
    b = _baseline_artefacts(track_events=rev)
    divs = he.compare_drain_artefacts(a, b)
    assert divs == []


def test_compare_detects_extra_track_event():
    a = _baseline_artefacts()
    extra = list(a.track_events) + [
        {"ts": "2026-04-18T00:00:03Z", "event": "extra", "task_id": "STAB-001"}
    ]
    b = _baseline_artefacts(track_events=extra)
    divs = he.compare_drain_artefacts(a, b)
    assert [d.field for d in divs] == ["track_events"]
    assert "extra" in divs[0].detail or "actual_only" in divs[0].detail


def test_compare_detects_missing_track_event():
    a = _baseline_artefacts()
    trimmed = a.track_events[:-1]
    b = _baseline_artefacts(track_events=trimmed)
    divs = he.compare_drain_artefacts(a, b)
    assert [d.field for d in divs] == ["track_events"]


def test_compare_returns_all_divergent_fields_together():
    a = _baseline_artefacts()
    b = _baseline_artefacts(
        patch_stat="other", test_count=999, track_events=[]
    )
    fields = {d.field for d in he.compare_drain_artefacts(a, b)}
    assert fields == {"patch_stat", "test_count", "track_events"}


def test_compare_divergence_has_deterministic_structure():
    a = _baseline_artefacts()
    b = _baseline_artefacts(patch_stat="other")
    divs = he.compare_drain_artefacts(a, b)
    assert divs
    for d in divs:
        assert isinstance(d.field, str)
        assert isinstance(d.detail, str)
        assert d.baseline is not None or d.baseline == ""
        # serialisable
        json.dumps(he.drain_divergence_to_dict(d))


# ---------------------------------------------------------------------------
# run_drain_cycle
# ---------------------------------------------------------------------------


def test_run_drain_cycle_clean_when_cycle_matches_baseline(baseline):
    _path, art, _dir = baseline
    report = he.run_drain_cycle(
        brief_id="stab_001",
        cycle_runner=lambda _b: _baseline_artefacts(),
        baseline=he.DrainBaseline(brief_id="stab_001", artefacts=art),
    )
    assert report.clean is True
    assert report.divergences == []
    assert report.brief_id == "stab_001"


def test_run_drain_cycle_regression_when_test_count_drops(baseline):
    _path, art, _dir = baseline
    report = he.run_drain_cycle(
        brief_id="stab_001",
        cycle_runner=lambda _b: _baseline_artefacts(test_count=775),
        baseline=he.DrainBaseline(brief_id="stab_001", artefacts=art),
    )
    assert report.clean is False
    assert any(d.field == "test_count" for d in report.divergences)


def test_run_drain_cycle_passes_brief_id_to_runner(baseline):
    _path, art, _dir = baseline
    seen = []

    def runner(brief_id):
        seen.append(brief_id)
        return _baseline_artefacts()

    he.run_drain_cycle(
        brief_id="stab_001",
        cycle_runner=runner,
        baseline=he.DrainBaseline(brief_id="stab_001", artefacts=art),
    )
    assert seen == ["stab_001"]


def test_run_drain_cycle_raises_when_baseline_mismatches_brief(baseline):
    _path, art, _dir = baseline
    with pytest.raises(ValueError):
        he.run_drain_cycle(
            brief_id="stab_003",
            cycle_runner=lambda _b: _baseline_artefacts(),
            baseline=he.DrainBaseline(brief_id="stab_001", artefacts=art),
        )


def test_run_drain_cycle_loads_baseline_from_disk_when_omitted(baseline):
    _path, art, baseline_dir = baseline
    report = he.run_drain_cycle(
        brief_id="stab_001",
        cycle_runner=lambda _b: _baseline_artefacts(),
        baseline_dir=baseline_dir,
    )
    assert report.clean is True


def test_run_drain_cycle_missing_baseline_is_regression(tmp_path):
    report = he.run_drain_cycle(
        brief_id="stab_001",
        cycle_runner=lambda _b: _baseline_artefacts(),
        baseline_dir=tmp_path,
    )
    assert report.clean is False
    assert any(d.field == "baseline" for d in report.divergences)


def test_run_drain_cycle_rejects_unknown_brief(tmp_path):
    with pytest.raises(ValueError):
        he.run_drain_cycle(
            brief_id="not_a_real_brief",
            cycle_runner=lambda _b: _baseline_artefacts(),
            baseline_dir=tmp_path,
        )


def test_run_drain_cycle_cycle_runner_exception_surfaces_as_regression(baseline):
    _path, art, _dir = baseline

    def bad_runner(_brief):
        raise RuntimeError("agent blew up")

    report = he.run_drain_cycle(
        brief_id="stab_001",
        cycle_runner=bad_runner,
        baseline=he.DrainBaseline(brief_id="stab_001", artefacts=art),
    )
    assert report.clean is False
    assert any(d.field == "cycle_runner" for d in report.divergences)


def test_run_drain_cycle_emits_report_file_when_output_dir(tmp_path, baseline):
    _path, art, _dir = baseline
    out_dir = tmp_path / "drain_reports"
    report = he.run_drain_cycle(
        brief_id="stab_001",
        cycle_runner=lambda _b: _baseline_artefacts(test_count=9),
        baseline=he.DrainBaseline(brief_id="stab_001", artefacts=art),
        output_dir=out_dir,
    )
    emitted = list(out_dir.glob("drain_report_*.json"))
    assert emitted, "expected drain_report_* file"
    data = json.loads(emitted[0].read_text(encoding="utf-8"))
    assert data["brief_id"] == "stab_001"
    assert data["clean"] is False


# ---------------------------------------------------------------------------
# fire_drain_rollback — reuses apply_rollback
# ---------------------------------------------------------------------------


def test_fire_drain_rollback_no_op_when_report_clean(tmp_path):
    signal_path = tmp_path / "rollback_signal"
    report = he.DrainReport(
        session_id="drain-1",
        brief_id="stab_001",
        clean=True,
        divergences=[],
        generated_at="2026-04-18T00:00:00Z",
    )
    fired = he.fire_drain_rollback(report, signal_path=signal_path)
    assert fired is False
    assert not signal_path.exists()


def test_fire_drain_rollback_writes_signal_on_regression(tmp_path):
    signal_path = tmp_path / "rollback_signal"
    div = he.DrainDivergence(
        field="test_count", baseline=776, actual=500, detail="regression"
    )
    report = he.DrainReport(
        session_id="drain-1",
        brief_id="stab_001",
        clean=False,
        divergences=[div],
        generated_at="2026-04-18T00:00:00Z",
    )
    fired = he.fire_drain_rollback(report, signal_path=signal_path)
    assert fired is True
    body = json.loads(signal_path.read_text(encoding="utf-8"))
    assert body["trigger"] == "drain_consensus_regression"
    assert "stab_001" in body.get("reason", "") + body.get("detail", "")


def test_fire_drain_rollback_and_apply_rollback_complete_end_to_end(tmp_path):
    signal_path = tmp_path / "rollback_signal"
    config = tmp_path / "config.yaml"
    config.write_text(
        "hooks:\n"
        "  mode: shadow\n"
        "  enforce_verbs: []\n"
        "other:\n"
        "  foo: bar\n",
        encoding="utf-8",
    )
    div = he.DrainDivergence(
        field="patch_stat", baseline="a", actual="b", detail="patch drift"
    )
    report = he.DrainReport(
        session_id="drain-1",
        brief_id="stab_003",
        clean=False,
        divergences=[div],
        generated_at="2026-04-18T00:00:00Z",
    )
    he.fire_drain_rollback(report, signal_path=signal_path)
    outcome = he.apply_rollback(
        signal_path=signal_path,
        config_path=config,
        blocked_dir=tmp_path / "blocked",
    )
    assert outcome.triggered is True
    assert outcome.previous_mode == "shadow"
    after = config.read_text(encoding="utf-8")
    import re as _re
    assert _re.search(r'^\s*mode:\s*"?off"?', after, _re.MULTILINE)


def test_fire_drain_rollback_does_not_mutate_signal_when_already_present(tmp_path):
    """Second drain regression must not overwrite an unconsumed signal so the
    original trigger reason is preserved. Callers should rely on apply_rollback
    to consume before re-firing."""
    signal_path = tmp_path / "rollback_signal"
    signal_path.write_text(
        json.dumps({"trigger": "shadow_divergence_two_consecutive", "reason": "first"}),
        encoding="utf-8",
    )
    div = he.DrainDivergence(
        field="test_count", baseline=1, actual=0, detail="x"
    )
    report = he.DrainReport(
        session_id="drain-1",
        brief_id="stab_001",
        clean=False,
        divergences=[div],
        generated_at="2026-04-18T00:00:00Z",
    )
    fired = he.fire_drain_rollback(report, signal_path=signal_path)
    assert fired is False
    body = json.loads(signal_path.read_text(encoding="utf-8"))
    assert body["trigger"] == "shadow_divergence_two_consecutive"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]


def _run_cli(*argv, tmp_path=None):
    cmd = [sys.executable, "-m", "harness.hooks_equivalence", *argv]
    import os as _os
    env = dict(_os.environ)
    if tmp_path is not None:
        env["JANUSMASK_PROJECT_DIR"] = str(tmp_path)
    proc = subprocess.run(
        cmd, capture_output=True, text=True, env=env, cwd=str(_REPO_ROOT)
    )
    return proc


def test_cli_drain_requires_brief_id(tmp_path):
    proc = _run_cli("--drain", tmp_path=tmp_path)
    assert proc.returncode != 0


def test_cli_drain_rejects_unknown_brief(tmp_path):
    proc = _run_cli("--drain", "stab_999", tmp_path=tmp_path)
    assert proc.returncode != 0


def test_cli_drain_exit_zero_when_clean(tmp_path):
    baseline_dir = tmp_path / "state" / "hooks"
    baseline_dir.mkdir(parents=True)
    art = _baseline_artefacts()
    he.save_drain_baseline(
        brief_id="stab_001", artefacts=art, baseline_dir=baseline_dir
    )
    actual_path = tmp_path / "actual.json"
    actual_path.write_text(
        json.dumps(he.drain_artefacts_to_dict(art)), encoding="utf-8"
    )
    proc = _run_cli(
        "--drain", "stab_001", "--actual-path", str(actual_path), tmp_path=tmp_path
    )
    assert proc.returncode == 0, proc.stderr


def test_cli_drain_exit_one_on_regression(tmp_path):
    baseline_dir = tmp_path / "state" / "hooks"
    baseline_dir.mkdir(parents=True)
    art = _baseline_artefacts()
    he.save_drain_baseline(
        brief_id="stab_001", artefacts=art, baseline_dir=baseline_dir
    )
    actual_art = _baseline_artefacts(test_count=1)
    actual_path = tmp_path / "actual.json"
    actual_path.write_text(
        json.dumps(he.drain_artefacts_to_dict(actual_art)), encoding="utf-8"
    )
    proc = _run_cli(
        "--drain", "stab_001", "--actual-path", str(actual_path), tmp_path=tmp_path
    )
    assert proc.returncode == 1
    assert "divergen" in (proc.stderr + proc.stdout).lower()


def test_cli_drain_emit_rollback_writes_signal(tmp_path):
    baseline_dir = tmp_path / "state" / "hooks"
    baseline_dir.mkdir(parents=True)
    art = _baseline_artefacts()
    he.save_drain_baseline(
        brief_id="stab_001", artefacts=art, baseline_dir=baseline_dir
    )
    actual_art = _baseline_artefacts(test_count=1)
    actual_path = tmp_path / "actual.json"
    actual_path.write_text(
        json.dumps(he.drain_artefacts_to_dict(actual_art)), encoding="utf-8"
    )
    proc = _run_cli(
        "--drain",
        "stab_001",
        "--actual-path",
        str(actual_path),
        "--emit-rollback",
        tmp_path=tmp_path,
    )
    assert proc.returncode == 1
    signal = tmp_path / "state" / "hooks" / "rollback_signal"
    assert signal.exists()
    body = json.loads(signal.read_text(encoding="utf-8"))
    assert body["trigger"] == "drain_consensus_regression"


def test_cli_gate_mode_unaffected_by_drain_addition(tmp_path):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    proc = _run_cli(
        "--gate", "--reports-dir", str(reports_dir), tmp_path=tmp_path
    )
    assert proc.returncode == 1


def test_cli_rollback_mode_unaffected_by_drain_addition(tmp_path):
    # Point at tmp_path so any existing state/hooks/rollback_signal does not bleed in.
    proc = _run_cli(
        "--rollback",
        "--signal-path",
        str(tmp_path / "absent_rollback_signal"),
        "--config-path",
        str(tmp_path / "absent_config.yaml"),
        tmp_path=tmp_path,
    )
    assert proc.returncode == 0
