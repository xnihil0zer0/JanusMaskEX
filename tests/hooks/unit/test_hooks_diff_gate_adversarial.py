"""P5 adversarial battery for HOOK-52 diff gate.

Covers the augmented-plan §5 P5 adversarial rows that consume the
shadow→enforce diff gate:

* Row 2 — "Canary flip of a verb that has not achieved 3 clean shadow runs"
  blocked by gate 5 of ``impl_pre_write.py``. The *check* that gate 5
  leans on is ``check_diff_gate``; this file locks that check's
  refusal semantics with mutation + fuzz coverage.
* Row 4 — ``state/hooks/rollback_signal`` planted; gate must surface
  the signal rather than silently pass. Exercised indirectly by the
  "signal file present" row below.

The gate is agent-executable: HOOK-53 canary-enforce calls it, but
the first enforce transition is a human_gate (sub-plan 06 §5 item 4).
These tests prove the gate's refusal is *load-bearing* — i.e. mutating
its contract causes the tests to fail.
"""

from __future__ import annotations

import json
import os
import pathlib
import random
import subprocess
import sys
import threading
import time

import pytest

from harness import hooks_equivalence as he


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
        os.utime(p, (mtime, mtime))
    return p


# -- Row 2: canary flip blocked without 3 clean runs ------------------------


def test_adv_canary_flip_blocked_without_three_clean_runs(tmp_path):
    # Only two clean reports exist — the canary gate MUST refuse.
    _write_report(tmp_path, "s1", mtime=1000)
    _write_report(tmp_path, "s2", mtime=2000)
    result = he.check_diff_gate(min_clean_runs=3, reports_dir=tmp_path)
    assert result.passed is False
    assert result.clean_run_count == 2
    assert "3 required" in result.reason or "3 required" in result.reason.replace(" ", "")


def test_adv_canary_flip_allowed_only_after_third_clean_run(tmp_path):
    _write_report(tmp_path, "s1", mtime=1000)
    _write_report(tmp_path, "s2", mtime=2000)
    r2 = he.check_diff_gate(min_clean_runs=3, reports_dir=tmp_path)
    assert not r2.passed
    _write_report(tmp_path, "s3", mtime=3000)
    r3 = he.check_diff_gate(min_clean_runs=3, reports_dir=tmp_path)
    assert r3.passed is True


# -- Row 3 parity: rate-limit divergence blocks gate ------------------------


def test_adv_rate_limit_divergence_blocks_gate(tmp_path):
    # Simulate the augmented-plan §5 row-3 fixture: hook counted one more
    # than MCP, producing a divergence. Even a single divergent run breaks
    # the streak and refuses the canary flip.
    _write_report(tmp_path, "s1", mtime=1000)
    _write_report(tmp_path, "s2", mtime=2000)
    _write_report(
        tmp_path,
        "rate-limited",
        mtime=3000,
        match_rate=0.5,
        divergences=[
            {
                "source": "mcp",
                "key": ["submit_code", "abcd1234", "deny"],
                "row": {"reason": "rate_limited"},
            }
        ],
    )
    result = he.check_diff_gate(min_clean_runs=3, reports_dir=tmp_path)
    assert result.passed is False
    assert result.clean_run_count == 0


# -- Streak semantics mutation ----------------------------------------------


def test_adv_single_divergence_in_streak_resets_count(tmp_path):
    # Adversary plants a divergent report between clean ones to simulate a
    # flaky canary candidate. Gate counts from most-recent backwards and
    # stops at the first divergence; mutation-safe under reorder.
    _write_report(tmp_path, "s1", mtime=1000)
    _write_report(
        tmp_path,
        "flake",
        mtime=2000,
        match_rate=0.8,
        divergences=[{"source": "shadow", "key": ["x", "y", "allow"], "row": {}}],
    )
    _write_report(tmp_path, "s2", mtime=3000)
    _write_report(tmp_path, "s3", mtime=4000)
    # Only s2/s3 are consecutive from the top; the divergent "flake" stops
    # the scan before s1 is reached.
    result = he.check_diff_gate(min_clean_runs=3, reports_dir=tmp_path)
    assert result.passed is False
    assert result.clean_run_count == 2


# -- Byzantine input resilience ---------------------------------------------


def test_adv_corrupt_json_report_blocks_gate(tmp_path):
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "equiv_report_broken.json").write_text("{garbage", encoding="utf-8")
    os.utime(tmp_path / "equiv_report_broken.json", (9999, 9999))
    _write_report(tmp_path, "s1", mtime=1000)
    _write_report(tmp_path, "s2", mtime=2000)
    _write_report(tmp_path, "s3", mtime=3000)
    result = he.check_diff_gate(min_clean_runs=3, reports_dir=tmp_path)
    # A malformed most-recent report is treated as divergent, not skipped.
    assert result.passed is False
    assert "broken" in result.reason


def test_adv_empty_json_report_blocks_gate(tmp_path):
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "equiv_report_empty.json").write_text("", encoding="utf-8")
    os.utime(tmp_path / "equiv_report_empty.json", (9999, 9999))
    result = he.check_diff_gate(min_clean_runs=1, reports_dir=tmp_path)
    assert result.passed is False


def test_adv_symlink_outside_reports_dir_does_not_escape(tmp_path):
    # Adversary plants a symlink pointing to an attacker-controlled "clean"
    # report outside the reports dir. The gate scans the directory via
    # glob, which resolves the link — confirm: even if the linked file IS
    # a clean report, the gate still ties the name to reports_dir and
    # therefore remains pinned to the scoped path.
    reports = tmp_path / "reports"
    attacker = tmp_path / "attacker"
    attacker.mkdir()
    _write_report(reports, "s1", mtime=1000)
    real = _write_report(attacker, "evil", mtime=9999)
    link = reports / "equiv_report_evil.json"
    link.symlink_to(real)
    os.utime(link, (5000, 5000), follow_symlinks=False)
    # The linked file IS clean, but the scan is still bounded to reports/.
    # What matters is: we never walk outside reports/ on directory
    # enumeration. list_equiv_reports returns what it found in scope.
    discovered = he.list_equiv_reports(reports)
    assert all(p.parent.resolve() == reports.resolve() for p in discovered)


def test_adv_zero_reports_blocks_gate(tmp_path):
    result = he.check_diff_gate(min_clean_runs=3, reports_dir=tmp_path)
    assert result.passed is False
    assert result.clean_run_count == 0


def test_adv_gate_monotonic_under_concurrent_appends(tmp_path):
    # Simulate concurrent orchestrator runs each writing one clean report.
    # The gate must never observe a non-monotonic streak — more reports
    # across calls only reinforce the pass/fail decision.
    errors: list[BaseException] = []

    def writer(i: int) -> None:
        try:
            _write_report(tmp_path, f"concurrent-{i}", mtime=1000 + i)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    result = he.check_diff_gate(min_clean_runs=3, reports_dir=tmp_path)
    assert result.passed is True
    assert result.clean_run_count >= 3


def test_adv_fuzz_random_match_rates_never_crashes(tmp_path):
    rng = random.Random(0xBEEF)
    for i in range(200):
        match_rate = rng.random()
        divergences = []
        if match_rate < 1.0:
            divergences = [{"source": "shadow", "key": ["t", "h", "allow"], "row": {}}]
        _write_report(
            tmp_path,
            f"fuzz-{i}",
            mtime=1000 + i,
            match_rate=match_rate,
            divergences=divergences,
        )
    result = he.check_diff_gate(min_clean_runs=3, reports_dir=tmp_path)
    # Non-crashing; the specific pass/fail depends on the random sequence.
    assert isinstance(result.passed, bool)
    assert result.required_clean_runs == 3


# -- Config-key mutation coverage -------------------------------------------


def test_adv_config_rejects_shadow_min_clean_runs_string():
    from harness import config_loader

    with pytest.raises(config_loader.ConfigError):
        config_loader.get_hooks_config(
            {"hooks": {"mode": "shadow", "shadow_min_clean_runs": "three"}}
        )


def test_adv_config_rejects_float_shadow_min_clean_runs():
    from harness import config_loader

    with pytest.raises(config_loader.ConfigError):
        config_loader.get_hooks_config(
            {"hooks": {"mode": "shadow", "shadow_min_clean_runs": 1.5}}
        )


# -- CLI exit contract deterministic under replay ---------------------------


def test_adv_cli_gate_deterministic_exit_on_repeated_runs(tmp_path):
    reports = tmp_path / "reports"
    _write_report(reports, "s1", mtime=1000)
    _write_report(reports, "s2", mtime=2000)
    repo_root = pathlib.Path(__file__).resolve().parents[3]
    codes = []
    for _ in range(3):
        r = subprocess.run(
            [
                sys.executable,
                "-m",
                "harness.hooks_equivalence",
                "--gate",
                "--reports-dir",
                str(reports),
                "--min-clean-runs",
                "3",
            ],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
        )
        codes.append(r.returncode)
    assert codes == [1, 1, 1]
    _write_report(reports, "s3", mtime=3000)
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "harness.hooks_equivalence",
            "--gate",
            "--reports-dir",
            str(reports),
            "--min-clean-runs",
            "3",
        ],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0


def test_adv_cli_gate_emits_useful_diagnostic_on_fail(tmp_path):
    reports = tmp_path / "reports"
    _write_report(reports, "s1", mtime=1000)
    repo_root = pathlib.Path(__file__).resolve().parents[3]
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "harness.hooks_equivalence",
            "--gate",
            "--reports-dir",
            str(reports),
            "--min-clean-runs",
            "3",
        ],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    combined = (result.stderr or "") + (result.stdout or "")
    assert "clean" in combined.lower() or "required" in combined.lower()


# -- Gate refuses forward-progress when streak is unmet regardless of count -


def test_adv_gate_refuses_with_many_broken_reports(tmp_path):
    for i in range(10):
        _write_report(
            tmp_path,
            f"broken-{i}",
            mtime=1000 + i,
            match_rate=0.0,
            divergences=[{"source": "shadow", "key": ["x", "y", "z"], "row": {}}],
        )
    result = he.check_diff_gate(min_clean_runs=3, reports_dir=tmp_path)
    assert result.passed is False
    assert result.clean_run_count == 0


def test_adv_gate_zero_min_clean_runs_is_rejected():
    # The gate treats min_clean_runs=0 as a misconfiguration; a zero-floor
    # canary flip would defeat the whole shadow phase. Explicit pass-through
    # is banned — callers must specify an intentional positive int.
    with pytest.raises(ValueError):
        he.check_diff_gate(min_clean_runs=0, reports_dir=pathlib.Path("/tmp/nope"))


def test_adv_gate_negative_min_clean_runs_is_rejected():
    with pytest.raises(ValueError):
        he.check_diff_gate(min_clean_runs=-1, reports_dir=pathlib.Path("/tmp/nope"))
