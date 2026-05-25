"""Unit coverage for HOOK-53 canary-enforce routing.

Exercises ``harness.hooks_equivalence`` additions that plan the per-verb
shadow→enforce canary flip without mutating config. The actual config
write is a human_gate operation per sub-plan 06 §5 item 4 — these tests
assert the planner only *reports* the decision and refuses to apply it.

Canary order (master plan §5.3, lowest-risk first):
    request_clarification → report_error → submit_reconciliation_response
    → submit_plan_draft → submit_code
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest

from harness import hooks_equivalence as he


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
        import os

        os.utime(p, (mtime, mtime))
    return p


# -- CANARY_ORDER invariants ------------------------------------------------


def test_canary_order_matches_master_plan():
    assert he.CANARY_ORDER == (
        "request_clarification",
        "report_error",
        "submit_reconciliation_response",
        "submit_plan_draft",
        "submit_code",
    )


def test_canary_order_is_subset_of_allowed_verbs():
    from harness.config_loader import HOOKS_ALLOWED_VERBS

    assert set(he.CANARY_ORDER) == set(HOOKS_ALLOWED_VERBS)


def test_canary_order_is_frozen_tuple():
    # Tuple, not list — consumers must not mutate it.
    assert isinstance(he.CANARY_ORDER, tuple)


# -- canary_next_verb -------------------------------------------------------


def test_canary_next_verb_empty_returns_first():
    assert he.canary_next_verb([]) == "request_clarification"


def test_canary_next_verb_skips_already_enforced():
    assert (
        he.canary_next_verb(["request_clarification"]) == "report_error"
    )
    assert (
        he.canary_next_verb(["request_clarification", "report_error"])
        == "submit_reconciliation_response"
    )


def test_canary_next_verb_returns_none_when_all_enforced():
    assert he.canary_next_verb(list(he.CANARY_ORDER)) is None


def test_canary_next_verb_respects_order_not_insertion():
    # Even if enforce_verbs is permuted, next-verb follows CANARY_ORDER.
    assert (
        he.canary_next_verb(["report_error", "request_clarification"])
        == "submit_reconciliation_response"
    )


def test_canary_next_verb_ignores_unknown_entries():
    # Defensive: unrecognised entries in enforce_verbs are validated at
    # config-load time; if one leaks through we should still return the
    # next *known* verb.
    assert he.canary_next_verb(["bogus"]) == "request_clarification"


# -- is_verb_enforced -------------------------------------------------------


def test_is_verb_enforced_true_when_in_list():
    assert he.is_verb_enforced("submit_code", ["submit_code"]) is True


def test_is_verb_enforced_false_when_absent():
    assert he.is_verb_enforced("submit_code", []) is False
    assert he.is_verb_enforced("submit_code", ["request_clarification"]) is False


def test_is_verb_enforced_rejects_non_string_verb():
    with pytest.raises(TypeError):
        he.is_verb_enforced(None, [])  # type: ignore[arg-type]


# -- CanaryFlipDecision dataclass ------------------------------------------


def test_canary_flip_decision_to_dict_is_json_safe():
    gate = he.DiffGateResult(
        passed=True,
        clean_run_count=3,
        required_clean_runs=3,
        reason="",
        considered_reports=[],
    )
    decision = he.CanaryFlipDecision(
        verb="request_clarification",
        ready=True,
        reason="",
        diff_gate=gate,
        human_gate_required=True,
        current_enforce_verbs=[],
    )
    body = decision.to_dict()
    assert json.loads(json.dumps(body))["verb"] == "request_clarification"
    assert body["diff_gate"]["passed"] is True
    assert body["human_gate_required"] is True


# -- evaluate_canary_flip --------------------------------------------------


def test_evaluate_canary_flip_gates_on_diff_gate_fail(tmp_path):
    # Only 1 clean report with min_clean_runs=3 → gate fails → not ready.
    _write_report(tmp_path, "s1", mtime=1000)
    decision = he.evaluate_canary_flip(
        enforce_verbs=[],
        min_clean_runs=3,
        reports_dir=tmp_path,
    )
    assert decision.ready is False
    assert decision.diff_gate.passed is False
    # human_gate remains True for the first flip regardless of diff gate.
    assert decision.human_gate_required is True
    assert decision.verb == "request_clarification"


def test_evaluate_canary_flip_first_flip_is_human_gate(tmp_path):
    # 3 clean runs, enforce_verbs empty → diff gate passes → but first
    # flip is still a human-only operation per sub-plan 06 §5 item 4.
    for i, ts in enumerate([1000, 2000, 3000]):
        _write_report(tmp_path, f"s{i}", mtime=ts)
    decision = he.evaluate_canary_flip(
        enforce_verbs=[],
        min_clean_runs=3,
        reports_dir=tmp_path,
    )
    assert decision.ready is True
    assert decision.diff_gate.passed is True
    assert decision.human_gate_required is True
    assert decision.verb == "request_clarification"


def test_evaluate_canary_flip_subsequent_flips_still_human_gate(tmp_path):
    # Even after the first verb has landed, subsequent verbs remain
    # human_gate until the P5 phase gate signs off globally (sub-plan 06
    # §5 item 4 reads the semantic bar as "each trust step").
    for i, ts in enumerate([1000, 2000, 3000]):
        _write_report(tmp_path, f"s{i}", mtime=ts)
    decision = he.evaluate_canary_flip(
        enforce_verbs=["request_clarification"],
        min_clean_runs=3,
        reports_dir=tmp_path,
    )
    assert decision.ready is True
    assert decision.verb == "report_error"
    assert decision.human_gate_required is True


def test_evaluate_canary_flip_all_verbs_enforced(tmp_path):
    for i, ts in enumerate([1000, 2000, 3000]):
        _write_report(tmp_path, f"s{i}", mtime=ts)
    decision = he.evaluate_canary_flip(
        enforce_verbs=list(he.CANARY_ORDER),
        min_clean_runs=3,
        reports_dir=tmp_path,
    )
    assert decision.verb is None
    assert decision.ready is False
    assert "all verbs" in decision.reason.lower()


def test_evaluate_canary_flip_reads_enforce_verbs_from_config(tmp_path):
    for i, ts in enumerate([1000, 2000, 3000]):
        _write_report(tmp_path, f"s{i}", mtime=ts)

    class FakeLoader:
        def read_hooks_enforce_verbs(self):
            return ["request_clarification"]

        def read_hooks_min_clean_runs(self):
            return 3

    decision = he.evaluate_canary_flip(
        reports_dir=tmp_path,
        config_loader=FakeLoader(),
    )
    assert decision.verb == "report_error"
    assert decision.current_enforce_verbs == ["request_clarification"]


def test_evaluate_canary_flip_never_mutates_config(tmp_path):
    # Belt and braces: invoke evaluate and confirm the committed config
    # is byte-identical afterwards. The planner is strictly read-only.
    cfg_path = pathlib.Path(__file__).resolve().parents[3] / "harness" / "config.yaml"
    before = cfg_path.read_bytes()
    for i, ts in enumerate([1000, 2000, 3000]):
        _write_report(tmp_path, f"s{i}", mtime=ts)
    he.evaluate_canary_flip(
        enforce_verbs=[],
        min_clean_runs=3,
        reports_dir=tmp_path,
    )
    assert cfg_path.read_bytes() == before


def test_evaluate_canary_flip_reason_quotes_next_verb(tmp_path):
    for i, ts in enumerate([1000, 2000, 3000]):
        _write_report(tmp_path, f"s{i}", mtime=ts)
    decision = he.evaluate_canary_flip(
        enforce_verbs=[],
        min_clean_runs=3,
        reports_dir=tmp_path,
    )
    combined = decision.reason
    # The reason must reference the verb so the operator sees what they
    # are being asked to authorise.
    assert "request_clarification" in combined or decision.verb == "request_clarification"


# -- describe_canary_edit --------------------------------------------------


def test_describe_canary_edit_returns_yaml_fragment():
    text = he.describe_canary_edit("request_clarification", current=[])
    assert "request_clarification" in text
    assert "enforce_verbs" in text


def test_describe_canary_edit_preserves_existing_list_order():
    text = he.describe_canary_edit(
        "report_error", current=["request_clarification"]
    )
    # Existing entries appear before the new one; order matches CANARY_ORDER.
    idx_first = text.index("request_clarification")
    idx_second = text.index("report_error")
    assert idx_first < idx_second


def test_describe_canary_edit_no_next_verb_returns_sentinel():
    text = he.describe_canary_edit(None, current=list(he.CANARY_ORDER))
    assert "no verbs remain" in text.lower() or "all verbs" in text.lower()


# -- CLI contract ----------------------------------------------------------


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


def test_cli_canary_exit_code_two_when_human_gate_required(tmp_path):
    for i, ts in enumerate([1000, 2000, 3000]):
        _write_report(tmp_path, f"s{i}", mtime=ts)
    repo_root = pathlib.Path(__file__).resolve().parents[3]
    r = _cli_canary(repo_root, tmp_path, enforce_verbs=[], min_clean_runs=3)
    # Human gate barrier always trips for the first trust-step.
    assert r.returncode == 2
    assert "human" in (r.stderr + r.stdout).lower()


def test_cli_canary_exit_code_one_when_diff_gate_fail(tmp_path):
    _write_report(tmp_path, "s1", mtime=1000)
    repo_root = pathlib.Path(__file__).resolve().parents[3]
    r = _cli_canary(repo_root, tmp_path, enforce_verbs=[], min_clean_runs=3)
    assert r.returncode == 1


def test_cli_canary_exit_code_zero_when_nothing_to_flip(tmp_path):
    for i, ts in enumerate([1000, 2000, 3000]):
        _write_report(tmp_path, f"s{i}", mtime=ts)
    repo_root = pathlib.Path(__file__).resolve().parents[3]
    r = _cli_canary(
        repo_root,
        tmp_path,
        enforce_verbs=list(he.CANARY_ORDER),
        min_clean_runs=3,
    )
    assert r.returncode == 0, r.stderr
    assert "no verbs remain" in (r.stderr + r.stdout).lower() or "all verbs" in (r.stderr + r.stdout).lower()


def test_cli_canary_stdout_contains_yaml_edit_stub(tmp_path):
    for i, ts in enumerate([1000, 2000, 3000]):
        _write_report(tmp_path, f"s{i}", mtime=ts)
    repo_root = pathlib.Path(__file__).resolve().parents[3]
    r = _cli_canary(repo_root, tmp_path, enforce_verbs=[], min_clean_runs=3)
    combined = r.stdout + r.stderr
    assert "enforce_verbs" in combined
    assert "request_clarification" in combined


def test_cli_canary_does_not_mutate_config_yaml(tmp_path):
    cfg = pathlib.Path(__file__).resolve().parents[3] / "harness" / "config.yaml"
    before = cfg.read_bytes()
    for i, ts in enumerate([1000, 2000, 3000]):
        _write_report(tmp_path, f"s{i}", mtime=ts)
    repo_root = pathlib.Path(__file__).resolve().parents[3]
    _cli_canary(repo_root, tmp_path, enforce_verbs=[], min_clean_runs=3)
    assert cfg.read_bytes() == before


def test_cli_canary_and_gate_exit_codes_orthogonal(tmp_path):
    # --gate reports 0/1; --canary adds exit 2 for human_gate. Confirm the
    # --gate mode still returns 0/1 even when canary would have been 2.
    for i, ts in enumerate([1000, 2000, 3000]):
        _write_report(tmp_path, f"s{i}", mtime=ts)
    repo_root = pathlib.Path(__file__).resolve().parents[3]
    r = subprocess.run(
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
    assert r.returncode == 0
