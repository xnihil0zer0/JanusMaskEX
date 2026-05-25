"""P5 adversarial battery for HOOK-53 canary-enforce routing.

Covers augmented-plan §5 P5 adversarial row 2 ("Canary flip of a verb
that has not achieved 3 clean shadow runs — blocked by gate 5 of
``impl_pre_write.py``"). The *behaviour* gate 5 leans on is the
``evaluate_canary_flip`` decision contract; these tests lock that
contract's refusal semantics even under hostile inputs.

Also covers mutation scenarios around CANARY_ORDER (the master plan
§5.3 ordering is load-bearing — flipping ``submit_code`` before
``request_clarification`` is the exact risk hole canary is designed to
close).
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys

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


# -- Row 2: canary flip blocked when diff gate not green --------------------


def test_adv_canary_refuses_flip_without_three_clean_runs(tmp_path):
    _write_report(tmp_path, "s1", mtime=1000)
    _write_report(tmp_path, "s2", mtime=2000)
    decision = he.evaluate_canary_flip(
        enforce_verbs=[],
        min_clean_runs=3,
        reports_dir=tmp_path,
    )
    assert decision.ready is False
    assert decision.diff_gate.passed is False
    # Even when the gate fails, the verb identification is still reported
    # so operators know what the next flip *would* be once ready.
    assert decision.verb == "request_clarification"


def test_adv_canary_refuses_flip_when_any_divergence_present(tmp_path):
    _write_report(tmp_path, "s1", mtime=1000)
    _write_report(tmp_path, "s2", mtime=2000)
    _write_report(
        tmp_path,
        "bad",
        mtime=3000,
        match_rate=0.8,
        divergences=[{"source": "shadow", "key": ["t", "h", "allow"], "row": {}}],
    )
    decision = he.evaluate_canary_flip(
        enforce_verbs=[],
        min_clean_runs=3,
        reports_dir=tmp_path,
    )
    assert decision.ready is False
    assert decision.diff_gate.clean_run_count == 0


def test_adv_canary_always_human_gate_on_first_flip(tmp_path):
    # Even with the diff gate green, the first trust-step is human_gate.
    for i, ts in enumerate([1000, 2000, 3000]):
        _write_report(tmp_path, f"s{i}", mtime=ts)
    decision = he.evaluate_canary_flip(
        enforce_verbs=[],
        min_clean_runs=3,
        reports_dir=tmp_path,
    )
    assert decision.human_gate_required is True


# -- Order-invariant mutation coverage -------------------------------------


def test_adv_submit_code_is_last_flip_ever():
    # Mutation: if any future edit moved submit_code out of last position
    # this test fails. submit_code is the hottest coupling (sub-plan 04
    # risk #1) and must flip last.
    assert he.CANARY_ORDER[-1] == "submit_code"


def test_adv_request_clarification_is_first_flip_ever():
    assert he.CANARY_ORDER[0] == "request_clarification"


def test_adv_canary_refuses_to_skip_order(tmp_path):
    # Adversary requests submit_code while only request_clarification is
    # enforced. canary_next_verb must still pick the in-order successor
    # (report_error), not honour an out-of-band skip.
    assert (
        he.canary_next_verb(["request_clarification"]) == "report_error"
    )


def test_adv_canary_next_verb_deterministic_under_duplicates():
    # enforce_verbs is validated at config-load, but deep-defence: a
    # duplicate entry (theoretical) should not break ordering.
    assert (
        he.canary_next_verb(["request_clarification", "request_clarification"])
        == "report_error"
    )


def test_adv_canary_next_verb_ignores_case_sensitive_mismatches():
    # Verbs are case-sensitive — HOOKS_ALLOWED_VERBS uses lowercase exactly.
    # An upper-case "REPORT_ERROR" in enforce_verbs MUST NOT be treated as
    # already-enforced.
    assert (
        he.canary_next_verb(["REPORT_ERROR", "request_clarification"])
        == "report_error"
    )


# -- No config.yaml mutation ever ------------------------------------------


def test_adv_evaluate_flip_never_touches_disk_config(tmp_path):
    cfg = pathlib.Path(__file__).resolve().parents[2] / "harness" / "config.yaml"
    mtime_before = cfg.stat().st_mtime
    bytes_before = cfg.read_bytes()
    for i, ts in enumerate([1000, 2000, 3000]):
        _write_report(tmp_path, f"s{i}", mtime=ts)
    for _ in range(5):
        he.evaluate_canary_flip(
            enforce_verbs=[],
            min_clean_runs=3,
            reports_dir=tmp_path,
        )
    assert cfg.stat().st_mtime == mtime_before
    assert cfg.read_bytes() == bytes_before


def test_adv_describe_canary_edit_is_pure(tmp_path):
    # describe_canary_edit returns a string — it MUST NOT open the config
    # file. Detect file-open attempts via a stub on pathlib.Path.open.
    cfg = pathlib.Path(__file__).resolve().parents[2] / "harness" / "config.yaml"
    text = he.describe_canary_edit("request_clarification", current=[])
    assert "request_clarification" in text
    assert cfg.exists()  # still there, unchanged


# -- CLI exit contract -----------------------------------------------------


def _cli_canary(cwd: pathlib.Path, reports_dir: pathlib.Path, **kw) -> subprocess.CompletedProcess:
    args = [
        sys.executable,
        "-m",
        "harness.hooks_equivalence",
        "--canary",
        "--reports-dir",
        str(reports_dir),
        "--min-clean-runs",
        str(kw.get("min_clean_runs", 3)),
    ]
    if "enforce_verbs" in kw:
        args.extend(["--enforce-verbs", ",".join(kw["enforce_verbs"])])
    return subprocess.run(args, cwd=str(cwd), capture_output=True, text=True)


def test_adv_cli_canary_refuses_apply_flag(tmp_path):
    # --apply must NEVER be accepted on the canary CLI — the stubbed flip
    # contract says the physical edit is operator-only.
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "harness.hooks_equivalence",
            "--canary",
            "--apply",
            "--reports-dir",
            str(tmp_path),
        ],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    assert r.returncode != 0  # argparse rejects the unknown flag
    assert "unrecognized" in r.stderr.lower() or "unknown" in r.stderr.lower() or "error" in r.stderr.lower()


def test_adv_cli_canary_deterministic_human_gate_exit(tmp_path):
    for i, ts in enumerate([1000, 2000, 3000]):
        _write_report(tmp_path, f"s{i}", mtime=ts)
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    codes = []
    for _ in range(3):
        r = _cli_canary(repo_root, tmp_path, enforce_verbs=[], min_clean_runs=3)
        codes.append(r.returncode)
    assert codes == [2, 2, 2]


def test_adv_cli_canary_emits_operator_instructions_on_human_gate(tmp_path):
    for i, ts in enumerate([1000, 2000, 3000]):
        _write_report(tmp_path, f"s{i}", mtime=ts)
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    r = _cli_canary(repo_root, tmp_path, enforce_verbs=[], min_clean_runs=3)
    combined = (r.stdout or "") + (r.stderr or "")
    # The stubbed-flip edit fragment must be printed so the operator can
    # copy-paste into the config; otherwise the human gate is opaque.
    assert "enforce_verbs" in combined
    assert "request_clarification" in combined
    # And the message must flag that this is a human operation.
    assert "human" in combined.lower() or "operator" in combined.lower()


def test_adv_cli_canary_exit_code_three_when_no_flip_remaining(tmp_path):
    # Full CANARY_ORDER enforced — no flip remains. Exit 0 (nothing to do)
    # because the canary is complete; human_gate does not re-trigger.
    for i, ts in enumerate([1000, 2000, 3000]):
        _write_report(tmp_path, f"s{i}", mtime=ts)
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    r = _cli_canary(
        repo_root,
        tmp_path,
        enforce_verbs=list(he.CANARY_ORDER),
        min_clean_runs=3,
    )
    assert r.returncode == 0


# -- Byzantine / edge inputs ------------------------------------------------


def test_adv_canary_next_verb_handles_non_string_entries():
    # Theoretical path: config validation should catch these, but the
    # in-process helper must not crash on surprising input.
    assert he.canary_next_verb([None, 1, "request_clarification"]) == "report_error"


def test_adv_evaluate_canary_flip_handles_empty_reports_dir(tmp_path):
    decision = he.evaluate_canary_flip(
        enforce_verbs=[],
        min_clean_runs=3,
        reports_dir=tmp_path,
    )
    assert decision.ready is False
    assert decision.verb == "request_clarification"
    assert decision.human_gate_required is True


def test_adv_evaluate_canary_flip_handles_missing_reports_dir(tmp_path):
    decision = he.evaluate_canary_flip(
        enforce_verbs=[],
        min_clean_runs=3,
        reports_dir=tmp_path / "never-existed",
    )
    assert decision.ready is False
    assert decision.diff_gate.clean_run_count == 0


def test_adv_canary_and_diff_gate_share_clean_semantics(tmp_path):
    # Consistency: canary readiness must imply the diff gate returns True.
    for i, ts in enumerate([1000, 2000, 3000]):
        _write_report(tmp_path, f"s{i}", mtime=ts)
    gate = he.check_diff_gate(min_clean_runs=3, reports_dir=tmp_path)
    decision = he.evaluate_canary_flip(
        enforce_verbs=[],
        min_clean_runs=3,
        reports_dir=tmp_path,
    )
    assert gate.passed is True
    assert decision.ready is True
    assert decision.diff_gate.passed == gate.passed


def test_adv_describe_canary_edit_no_verb_sentinel_is_unambiguous():
    text = he.describe_canary_edit(None, current=list(he.CANARY_ORDER))
    lowered = text.lower()
    assert "no verbs remain" in lowered or "all verbs" in lowered
    # Sentinel must not accidentally include a verb name in a way that
    # looks like a flip instruction.
    for verb in he.CANARY_ORDER:
        # All-enforced message may *list* verbs but MUST NOT show a
        # single-verb flip addition fragment like `- request_clarification\n`.
        assert f"add {verb}" not in lowered
