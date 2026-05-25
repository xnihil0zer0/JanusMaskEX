"""Unit coverage for HOOK-54 rollback-wiring.

Exercises the pieces that detect a rollback signal, flip ``hooks.mode``
to ``off`` in ``harness/config.yaml``, and emit a blocked-task report
under ``state/tasks/blocked/`` for human review.

Triggers (master plan §5.4): shadow divergence / canary error / drain
regression / agent permission-denied loop. This module only tests the
pipeline that consumes those triggers; trigger *detection* lives in the
equiv checker / orchestrator watchdog.
"""

from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys

import pytest

from harness import hooks_equivalence as he


# -- Fixture config factory -------------------------------------------------


SAMPLE_CONFIG = """\
# other top-level config
batch_execution:
  enabled: true

hooks:
  # HOOK-13 migration flag
  mode: "shadow"           # off | shadow | enforce
  enforce_verbs: []
  shadow_dir: "state/hooks/shadow/"
  shadow_min_clean_runs: 3
"""


def _make_config(tmp_path: pathlib.Path, mode: str = "shadow") -> pathlib.Path:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(SAMPLE_CONFIG.replace('"shadow"', f'"{mode}"'), encoding="utf-8")
    return cfg


# -- Constants / surface ---------------------------------------------------


def test_rollback_triggers_matches_master_plan():
    assert set(he.ROLLBACK_TRIGGERS) == {
        "shadow_divergence_two_consecutive",
        "canary_error_not_in_mcp",
        "drain_consensus_regression",
        "agent_permission_denied_loop",
    }


def test_rollback_triggers_is_frozen_tuple():
    assert isinstance(he.ROLLBACK_TRIGGERS, tuple)


def test_rollback_signal_path_constant():
    # Matches P5 allow-list entry verbatim so gate 1 will always permit
    # the runtime write-and-clear cycle on the signal file.
    assert he.ROLLBACK_SIGNAL_PATH == "state/hooks/rollback_signal"


# -- rollback_signal_present / read ----------------------------------------


def test_rollback_signal_present_absent(tmp_path):
    assert he.rollback_signal_present(tmp_path / "nope") is False


def test_rollback_signal_present_true(tmp_path):
    sig = tmp_path / "rollback_signal"
    sig.write_text("{}", encoding="utf-8")
    assert he.rollback_signal_present(sig) is True


def test_read_rollback_signal_structured(tmp_path):
    sig = tmp_path / "rollback_signal"
    sig.write_text(
        json.dumps(
            {
                "trigger": "shadow_divergence_two_consecutive",
                "reason": "match_rate 0.85 on sess-A",
                "detail": "two consecutive divergent runs",
            }
        ),
        encoding="utf-8",
    )
    body = he.read_rollback_signal(sig)
    assert body["trigger"] == "shadow_divergence_two_consecutive"
    assert "match_rate" in body["reason"]


def test_read_rollback_signal_plain_text_is_reason(tmp_path):
    # Non-JSON bodies degrade to {trigger: unknown, reason: <text>, detail: ""}.
    sig = tmp_path / "rollback_signal"
    sig.write_text("agent stuck in permission-denied loop", encoding="utf-8")
    body = he.read_rollback_signal(sig)
    assert body["trigger"] == "unknown"
    assert "permission-denied" in body["reason"]


def test_read_rollback_signal_missing_returns_absent(tmp_path):
    body = he.read_rollback_signal(tmp_path / "never")
    assert body == {}


def test_read_rollback_signal_invalid_json_falls_back(tmp_path):
    sig = tmp_path / "rollback_signal"
    sig.write_text("{garbage", encoding="utf-8")
    body = he.read_rollback_signal(sig)
    assert body.get("trigger") == "unknown"


# -- flip_hooks_mode_off ---------------------------------------------------


def test_flip_hooks_mode_off_from_shadow_preserves_comments(tmp_path):
    cfg = _make_config(tmp_path, mode="shadow")
    before_comment = "# HOOK-13 migration flag"
    assert before_comment in cfg.read_text()

    prior = he.flip_hooks_mode_off(cfg)

    assert prior == "shadow"
    text = cfg.read_text()
    assert re.search(r'^\s*mode:\s*"?off"?', text, re.MULTILINE)
    # Comments still present after the flip.
    assert before_comment in text
    # The other top-level block is intact.
    assert "batch_execution:" in text


def test_flip_hooks_mode_off_from_enforce(tmp_path):
    cfg = _make_config(tmp_path, mode="enforce")
    prior = he.flip_hooks_mode_off(cfg)
    assert prior == "enforce"
    assert re.search(r'^\s*mode:\s*"?off"?', cfg.read_text(), re.MULTILINE)


def test_flip_hooks_mode_off_idempotent(tmp_path):
    cfg = _make_config(tmp_path, mode="shadow")
    he.flip_hooks_mode_off(cfg)
    # Second call: already off → returns "off" but doesn't corrupt the file.
    again = he.flip_hooks_mode_off(cfg)
    assert again == "off"
    # Exactly one mode: line in the file.
    lines = [
        l for l in cfg.read_text().splitlines() if re.match(r"\s*mode:", l)
    ]
    assert len(lines) == 1


def test_flip_hooks_mode_off_preserves_enforce_verbs_and_shadow_dir(tmp_path):
    cfg = _make_config(tmp_path, mode="enforce")
    he.flip_hooks_mode_off(cfg)
    text = cfg.read_text()
    assert "enforce_verbs:" in text
    assert "shadow_dir:" in text
    assert "shadow_min_clean_runs:" in text


def test_flip_hooks_mode_off_raises_on_missing_hooks_block(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("batch_execution:\n  enabled: true\n", encoding="utf-8")
    with pytest.raises(RuntimeError):
        he.flip_hooks_mode_off(cfg)


# -- emit_rollback_blocked_report ------------------------------------------


def test_emit_rollback_blocked_report_writes_markdown(tmp_path):
    out = he.emit_rollback_blocked_report(
        trigger="shadow_divergence_two_consecutive",
        reason="match_rate < 1.0 for 2 runs",
        detail="sess-A, sess-B",
        blocked_dir=tmp_path,
        now_iso="2026-04-17T12:00:00Z",
    )
    assert out.exists()
    assert out.name.startswith("ROLLBACK-")
    body = out.read_text()
    assert "meta_task_type: harness_plumbing" in body
    assert "shadow_divergence_two_consecutive" in body
    assert "match_rate" in body


def test_emit_rollback_blocked_report_creates_dir(tmp_path):
    target = tmp_path / "new" / "blocked"
    out = he.emit_rollback_blocked_report(
        trigger="agent_permission_denied_loop",
        reason="",
        detail="",
        blocked_dir=target,
        now_iso="2026-04-17T12:00:00Z",
    )
    assert out.parent == target


def test_emit_rollback_blocked_report_unique_per_invocation(tmp_path):
    a = he.emit_rollback_blocked_report(
        trigger="drain_consensus_regression",
        reason="",
        detail="",
        blocked_dir=tmp_path,
        now_iso="2026-04-17T12:00:00Z",
    )
    b = he.emit_rollback_blocked_report(
        trigger="drain_consensus_regression",
        reason="",
        detail="",
        blocked_dir=tmp_path,
        now_iso="2026-04-17T12:00:01Z",
    )
    assert a != b
    assert a.exists() and b.exists()


def test_emit_rollback_blocked_report_unknown_trigger_rejected(tmp_path):
    with pytest.raises(ValueError):
        he.emit_rollback_blocked_report(
            trigger="made_up_reason",
            reason="",
            detail="",
            blocked_dir=tmp_path,
            now_iso="2026-04-17T12:00:00Z",
        )


# -- apply_rollback (end-to-end) -------------------------------------------


def _plant_signal(signal_path: pathlib.Path, trigger="shadow_divergence_two_consecutive") -> None:
    signal_path.parent.mkdir(parents=True, exist_ok=True)
    signal_path.write_text(
        json.dumps(
            {"trigger": trigger, "reason": "planted by test", "detail": ""}
        ),
        encoding="utf-8",
    )


def test_apply_rollback_no_signal_is_noop(tmp_path):
    cfg = _make_config(tmp_path, mode="shadow")
    outcome = he.apply_rollback(
        signal_path=tmp_path / "nope",
        config_path=cfg,
        blocked_dir=tmp_path / "blocked",
    )
    assert outcome.triggered is False
    assert cfg.read_text().count('mode: "shadow"') == 1
    # Blocked dir not created on a no-op.
    assert not (tmp_path / "blocked").exists()


def test_apply_rollback_happy_path(tmp_path):
    cfg = _make_config(tmp_path, mode="enforce")
    sig = tmp_path / "rollback_signal"
    _plant_signal(sig)
    outcome = he.apply_rollback(
        signal_path=sig,
        config_path=cfg,
        blocked_dir=tmp_path / "blocked",
        now_iso="2026-04-17T12:00:00Z",
    )
    assert outcome.triggered is True
    assert outcome.previous_mode == "enforce"
    assert re.search(r'^\s*mode:\s*"?off"?', cfg.read_text(), re.MULTILINE)
    blocked = pathlib.Path(outcome.blocked_report_path)
    assert blocked.exists()
    assert "meta_task_type: harness_plumbing" in blocked.read_text()
    # Signal file is consumed.
    assert not sig.exists()


def test_apply_rollback_twice_is_idempotent(tmp_path):
    cfg = _make_config(tmp_path, mode="shadow")
    sig = tmp_path / "rollback_signal"
    _plant_signal(sig)
    first = he.apply_rollback(
        signal_path=sig, config_path=cfg, blocked_dir=tmp_path / "blocked",
        now_iso="2026-04-17T12:00:00Z",
    )
    assert first.triggered is True
    # Second call with the signal already cleared is a no-op.
    second = he.apply_rollback(
        signal_path=sig, config_path=cfg, blocked_dir=tmp_path / "blocked",
        now_iso="2026-04-17T12:00:01Z",
    )
    assert second.triggered is False


def test_apply_rollback_preserves_trigger_reason_in_report(tmp_path):
    cfg = _make_config(tmp_path, mode="shadow")
    sig = tmp_path / "rollback_signal"
    sig.write_text(
        json.dumps(
            {
                "trigger": "canary_error_not_in_mcp",
                "reason": "Bash gate raised in hook but not in MCP",
                "detail": "sess-B round 4",
            }
        ),
        encoding="utf-8",
    )
    outcome = he.apply_rollback(
        signal_path=sig,
        config_path=cfg,
        blocked_dir=tmp_path / "blocked",
        now_iso="2026-04-17T12:00:00Z",
    )
    body = pathlib.Path(outcome.blocked_report_path).read_text()
    assert "canary_error_not_in_mcp" in body
    assert "Bash gate" in body


# -- clear_rollback_signal -------------------------------------------------


def test_clear_rollback_signal_removes_file(tmp_path):
    sig = tmp_path / "rollback_signal"
    sig.write_text("{}", encoding="utf-8")
    assert he.clear_rollback_signal(sig) is True
    assert not sig.exists()


def test_clear_rollback_signal_missing_returns_false(tmp_path):
    assert he.clear_rollback_signal(tmp_path / "never") is False


# -- CLI contract ----------------------------------------------------------


def _cli_rollback(
    cwd: pathlib.Path,
    signal_path: pathlib.Path,
    config_path: pathlib.Path,
    blocked_dir: pathlib.Path,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "harness.hooks_equivalence",
            "--rollback",
            "--signal-path",
            str(signal_path),
            "--config-path",
            str(config_path),
            "--blocked-dir",
            str(blocked_dir),
        ],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )


def test_cli_rollback_exit_zero_when_no_signal(tmp_path):
    cfg = _make_config(tmp_path, mode="shadow")
    repo_root = pathlib.Path(__file__).resolve().parents[3]
    r = _cli_rollback(
        repo_root,
        signal_path=tmp_path / "nope",
        config_path=cfg,
        blocked_dir=tmp_path / "blocked",
    )
    assert r.returncode == 0, r.stderr
    assert "no signal" in (r.stdout + r.stderr).lower() or "noop" in (r.stdout + r.stderr).lower()


def test_cli_rollback_exit_zero_when_signal_applied(tmp_path):
    cfg = _make_config(tmp_path, mode="enforce")
    sig = tmp_path / "rollback_signal"
    _plant_signal(sig)
    repo_root = pathlib.Path(__file__).resolve().parents[3]
    r = _cli_rollback(
        repo_root, signal_path=sig, config_path=cfg, blocked_dir=tmp_path / "blocked"
    )
    assert r.returncode == 0, r.stderr
    assert re.search(r'^\s*mode:\s*"?off"?', cfg.read_text(), re.MULTILINE)
    assert not sig.exists()
    blocked_files = list((tmp_path / "blocked").glob("ROLLBACK-*.md"))
    assert len(blocked_files) == 1


def test_cli_rollback_emits_structured_summary(tmp_path):
    cfg = _make_config(tmp_path, mode="shadow")
    sig = tmp_path / "rollback_signal"
    _plant_signal(sig, trigger="drain_consensus_regression")
    repo_root = pathlib.Path(__file__).resolve().parents[3]
    r = _cli_rollback(
        repo_root, signal_path=sig, config_path=cfg, blocked_dir=tmp_path / "blocked"
    )
    combined = r.stdout + r.stderr
    assert "drain_consensus_regression" in combined
    assert "shadow" in combined or "previous_mode" in combined
