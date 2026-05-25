"""Unit coverage for the HOOK-52 shadow->enforce diff gate.

Exercises the pieces that read ``state/hooks/equiv_report_<session>.json``
artefacts emitted by HOOK-51 and decide whether the shadow phase has
accumulated enough consecutive clean runs to justify a canary enforce
flip. Config surface: ``hooks.shadow_min_clean_runs`` (int>=1, default 3).

The gate is consumed by HOOK-53 canary-enforce tasks and by the P5
phase gate script; the first ``mode: enforce`` flip is a human_gate
operation (sub-plan 06 §5 item 4) — the gate only *permits* the flip,
it does not execute it.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import time

import pytest

from harness import hooks_equivalence as he
from harness import config_loader


# -- Fixtures ---------------------------------------------------------------


def _write_report(
    reports_dir: pathlib.Path,
    session_id: str,
    *,
    match_rate: float = 1.0,
    divergences: list[dict] | None = None,
    mtime: float | None = None,
) -> pathlib.Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    p = reports_dir / f"equiv_report_{session_id}.json"
    body = {
        "session_id": session_id,
        "match_rate": match_rate,
        "divergences": divergences or [],
        "shadow_count": 1,
        "mcp_count": 1,
        "shadow_source": "",
        "mcp_source": "",
        "generated_at": "2026-04-17T00:00:00Z",
    }
    p.write_text(json.dumps(body), encoding="utf-8")
    if mtime is not None:
        # Ordering by mtime is load-bearing; tests assert this explicitly.
        import os

        os.utime(p, (mtime, mtime))
    return p


# -- list_equiv_reports -----------------------------------------------------


def test_list_equiv_reports_orders_by_mtime_desc(tmp_path):
    _write_report(tmp_path, "oldest", mtime=1000)
    _write_report(tmp_path, "mid", mtime=2000)
    _write_report(tmp_path, "newest", mtime=3000)
    reports = he.list_equiv_reports(tmp_path)
    names = [p.name for p in reports]
    assert names == [
        "equiv_report_newest.json",
        "equiv_report_mid.json",
        "equiv_report_oldest.json",
    ]


def test_list_equiv_reports_missing_dir_returns_empty(tmp_path):
    assert he.list_equiv_reports(tmp_path / "nope") == []


def test_list_equiv_reports_ignores_non_report_json(tmp_path):
    tmp_path.mkdir(exist_ok=True)
    _write_report(tmp_path, "s1", mtime=1000)
    (tmp_path / "other.json").write_text("{}", encoding="utf-8")
    (tmp_path / "equiv_report_ignored.txt").write_text("x", encoding="utf-8")
    names = [p.name for p in he.list_equiv_reports(tmp_path)]
    assert names == ["equiv_report_s1.json"]


# -- check_diff_gate core semantics ----------------------------------------


def test_gate_passes_with_three_clean_reports(tmp_path):
    for i, ts in enumerate([1000, 2000, 3000]):
        _write_report(tmp_path, f"s{i}", mtime=ts)
    result = he.check_diff_gate(min_clean_runs=3, reports_dir=tmp_path)
    assert result.passed is True
    assert result.clean_run_count == 3
    assert result.required_clean_runs == 3


def test_gate_fails_with_two_clean_reports(tmp_path):
    _write_report(tmp_path, "s1", mtime=1000)
    _write_report(tmp_path, "s2", mtime=2000)
    result = he.check_diff_gate(min_clean_runs=3, reports_dir=tmp_path)
    assert result.passed is False
    assert result.clean_run_count == 2
    assert result.required_clean_runs == 3
    assert "2 clean" in result.reason


def test_gate_fails_on_most_recent_divergence(tmp_path):
    _write_report(tmp_path, "s1", mtime=1000)
    _write_report(tmp_path, "s2", mtime=2000)
    _write_report(tmp_path, "s3", mtime=3000)
    _write_report(
        tmp_path,
        "bad",
        mtime=4000,
        match_rate=0.5,
        divergences=[{"source": "shadow", "key": ["t", "h", "allow"], "row": {}}],
    )
    result = he.check_diff_gate(min_clean_runs=3, reports_dir=tmp_path)
    assert result.passed is False
    assert result.clean_run_count == 0
    assert "bad" in result.reason


def test_gate_breaks_streak_on_intermediate_divergence(tmp_path):
    _write_report(tmp_path, "s1", mtime=1000)
    _write_report(
        tmp_path,
        "bad",
        mtime=2000,
        match_rate=0.99,
        divergences=[{"source": "mcp", "key": ["t", "h", "deny"], "row": {}}],
    )
    _write_report(tmp_path, "s2", mtime=3000)
    _write_report(tmp_path, "s3", mtime=4000)
    # Only the two most-recent clean runs count; the divergent run breaks
    # the streak before a third clean report can accumulate.
    result = he.check_diff_gate(min_clean_runs=3, reports_dir=tmp_path)
    assert result.passed is False
    assert result.clean_run_count == 2
    assert "bad" in result.reason


def test_gate_reports_considered_paths(tmp_path):
    p1 = _write_report(tmp_path, "s1", mtime=1000)
    p2 = _write_report(tmp_path, "s2", mtime=2000)
    result = he.check_diff_gate(min_clean_runs=5, reports_dir=tmp_path)
    considered = {pathlib.Path(s).name for s in result.considered_reports}
    assert considered == {p1.name, p2.name}


def test_gate_match_rate_less_than_one_is_not_clean(tmp_path):
    _write_report(tmp_path, "s1", mtime=1000, match_rate=0.9999)
    result = he.check_diff_gate(min_clean_runs=1, reports_dir=tmp_path)
    assert result.passed is False


def test_gate_divergences_present_with_match_rate_one_is_not_clean(tmp_path):
    # Belt and braces: a malformed report that claims match_rate=1.0 but
    # carries divergences is treated as dirty — trust the list, not the float.
    _write_report(
        tmp_path,
        "s1",
        mtime=1000,
        match_rate=1.0,
        divergences=[{"source": "shadow", "key": ["x", "y", "allow"], "row": {}}],
    )
    result = he.check_diff_gate(min_clean_runs=1, reports_dir=tmp_path)
    assert result.passed is False


def test_gate_match_rate_one_with_empty_divergences_is_clean(tmp_path):
    _write_report(tmp_path, "s1", mtime=1000)
    result = he.check_diff_gate(min_clean_runs=1, reports_dir=tmp_path)
    assert result.passed is True
    assert result.clean_run_count == 1


def test_gate_handles_missing_reports_dir(tmp_path):
    result = he.check_diff_gate(min_clean_runs=3, reports_dir=tmp_path / "nope")
    assert result.passed is False
    assert result.clean_run_count == 0


def test_gate_handles_malformed_json_report(tmp_path):
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "equiv_report_broken.json").write_text("{not json", encoding="utf-8")
    result = he.check_diff_gate(min_clean_runs=1, reports_dir=tmp_path)
    assert result.passed is False
    assert "broken" in result.reason


def test_gate_counts_only_consecutive_runs_from_most_recent(tmp_path):
    # Four clean reports but we only ask for 2 — gate should short-circuit
    # as soon as the required count is met (considered_reports reflects that).
    for i, ts in enumerate([1000, 2000, 3000, 4000]):
        _write_report(tmp_path, f"s{i}", mtime=ts)
    result = he.check_diff_gate(min_clean_runs=2, reports_dir=tmp_path)
    assert result.passed is True
    assert result.clean_run_count == 2
    assert len(result.considered_reports) == 2


# -- hooks.shadow_min_clean_runs config plumbing ---------------------------


def test_hooks_config_accepts_shadow_min_clean_runs():
    cfg = config_loader.get_hooks_config(
        {"hooks": {"mode": "shadow", "shadow_min_clean_runs": 5}}
    )
    assert cfg.shadow_min_clean_runs == 5


def test_hooks_config_defaults_shadow_min_clean_runs_to_three():
    cfg = config_loader.get_hooks_config({"hooks": {"mode": "shadow"}})
    assert cfg.shadow_min_clean_runs == 3


def test_hooks_config_rejects_non_int_shadow_min_clean_runs():
    with pytest.raises(config_loader.ConfigError):
        config_loader.get_hooks_config(
            {"hooks": {"mode": "shadow", "shadow_min_clean_runs": "3"}}
        )


def test_hooks_config_rejects_bool_shadow_min_clean_runs():
    with pytest.raises(config_loader.ConfigError):
        config_loader.get_hooks_config(
            {"hooks": {"mode": "shadow", "shadow_min_clean_runs": True}}
        )


def test_hooks_config_rejects_negative_shadow_min_clean_runs():
    with pytest.raises(config_loader.ConfigError):
        config_loader.get_hooks_config(
            {"hooks": {"mode": "shadow", "shadow_min_clean_runs": -1}}
        )


def test_hooks_config_rejects_zero_shadow_min_clean_runs():
    with pytest.raises(config_loader.ConfigError):
        config_loader.get_hooks_config(
            {"hooks": {"mode": "shadow", "shadow_min_clean_runs": 0}}
        )


def test_config_yaml_declares_shadow_min_clean_runs():
    import yaml

    cfg = yaml.safe_load(
        (pathlib.Path(__file__).resolve().parents[3] / "harness" / "config.yaml").read_text()
    )
    assert cfg["hooks"]["shadow_min_clean_runs"] == 3


def test_gate_reads_shadow_min_clean_runs_from_config(tmp_path):
    for i, ts in enumerate([1000, 2000]):
        _write_report(tmp_path, f"s{i}", mtime=ts)

    class FakeLoader:
        def read_hooks_min_clean_runs(self):
            return 2

    result = he.check_diff_gate(reports_dir=tmp_path, config_loader=FakeLoader())
    assert result.passed is True
    assert result.required_clean_runs == 2


def test_gate_defaults_to_three_when_config_missing(tmp_path):
    for i, ts in enumerate([1000, 2000]):
        _write_report(tmp_path, f"s{i}", mtime=ts)

    class BrokenLoader:
        def read_hooks_min_clean_runs(self):
            raise RuntimeError("bad config")

    result = he.check_diff_gate(reports_dir=tmp_path, config_loader=BrokenLoader())
    assert result.required_clean_runs == 3
    assert result.passed is False


# -- CLI contract ----------------------------------------------------------


def _cli_gate(cwd: pathlib.Path, reports_dir: pathlib.Path, min_clean_runs: int = 3) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "harness.hooks_equivalence",
            "--gate",
            "--reports-dir",
            str(reports_dir),
            "--min-clean-runs",
            str(min_clean_runs),
        ],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )


def test_cli_gate_exits_zero_when_passed(tmp_path):
    reports = tmp_path / "reports"
    for i, ts in enumerate([1000, 2000, 3000]):
        _write_report(reports, f"s{i}", mtime=ts)
    repo_root = pathlib.Path(__file__).resolve().parents[3]
    result = _cli_gate(repo_root, reports, min_clean_runs=3)
    assert result.returncode == 0, result.stderr


def test_cli_gate_exits_one_when_failed(tmp_path):
    reports = tmp_path / "reports"
    _write_report(reports, "s1", mtime=1000)
    repo_root = pathlib.Path(__file__).resolve().parents[3]
    result = _cli_gate(repo_root, reports, min_clean_runs=3)
    assert result.returncode == 1


def test_cli_gate_does_not_require_session_id(tmp_path):
    # The --gate flag re-routes CLI semantics; session_id must be optional.
    repo_root = pathlib.Path(__file__).resolve().parents[3]
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "harness.hooks_equivalence",
            "--gate",
            "--reports-dir",
            str(tmp_path),
            "--min-clean-runs",
            "3",
        ],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "clean" in result.stderr.lower() or "run" in result.stderr.lower()


def test_cli_session_mode_unaffected_by_gate_addition(tmp_path):
    # Back-compat: the positional session_id path still runs the comparator.
    shadow = tmp_path / "shadow"
    shadow.mkdir()
    (shadow / "sess-A.jsonl").write_text("", encoding="utf-8")
    audit = tmp_path / "state"
    (audit / "sessions").mkdir(parents=True)
    out_dir = tmp_path / "reports"
    repo_root = pathlib.Path(__file__).resolve().parents[3]
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "harness.hooks_equivalence",
            "sess-A",
            "--shadow-dir",
            str(shadow),
            "--audit-root",
            str(audit),
            "--output-dir",
            str(out_dir),
        ],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    # Clean empty run (zero events both sides) exits 0 per HOOK-51 contract.
    assert result.returncode == 0
    assert (out_dir / "equiv_report_sess-A.json").exists()
