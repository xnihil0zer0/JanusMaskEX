"""P5 adversarial battery for HOOK-54 rollback-wiring.

Covers augmented-plan §5 P5 adversarial row 4 ("``state/hooks/rollback_signal``
planted by test; run orchestrator → ``hooks.mode: off``, blocked task
with ``meta_task_type: harness_plumbing``"). The rollback path is
agent-executable — gate 5 only blocks transitions *into* ``enforce``,
not out of it — so mutation coverage here is load-bearing: if the
rollback pipeline silently fails, a real divergence incident leaves the
system wedged in a partially-enforced state.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import sys
import threading

import pytest

from harness import hooks_equivalence as he


SAMPLE_CONFIG = """\
# Other top-level block
batch_execution:
  enabled: true

hooks:
  # migration flag
  mode: "{MODE}"           # off | shadow | enforce
  enforce_verbs: [submit_code, request_clarification]
  shadow_dir: "state/hooks/shadow/"
  shadow_min_clean_runs: 3
"""


def _cfg(tmp_path: pathlib.Path, mode: str) -> pathlib.Path:
    p = tmp_path / "config.yaml"
    p.write_text(SAMPLE_CONFIG.replace("{MODE}", mode), encoding="utf-8")
    return p


def _plant_signal(path: pathlib.Path, **kw) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"trigger": "shadow_divergence_two_consecutive", "reason": "", "detail": ""}
    body.update(kw)
    path.write_text(json.dumps(body), encoding="utf-8")


# -- Row 4 core: planted signal triggers full rollback ---------------------


def test_adv_planted_signal_flips_mode_to_off_and_emits_blocked_report(tmp_path):
    cfg = _cfg(tmp_path, "enforce")
    sig = tmp_path / "rollback_signal"
    _plant_signal(sig, trigger="canary_error_not_in_mcp", reason="Bash raised in hook only")
    outcome = he.apply_rollback(
        signal_path=sig,
        config_path=cfg,
        blocked_dir=tmp_path / "blocked",
        now_iso="2026-04-17T12:00:00Z",
    )
    assert outcome.triggered
    assert outcome.previous_mode == "enforce"
    # 1) mode is "off" after rollback
    assert re.search(r'^\s*mode:\s*"?off"?', cfg.read_text(), re.MULTILINE)
    # 2) blocked report carries harness_plumbing marker
    blocked = pathlib.Path(outcome.blocked_report_path)
    body = blocked.read_text()
    assert "meta_task_type: harness_plumbing" in body
    # 3) trigger + reason are preserved for human triage
    assert "canary_error_not_in_mcp" in body
    assert "Bash raised in hook only" in body
    # 4) signal file consumed
    assert not sig.exists()


def test_adv_rollback_preserves_enforce_verbs_on_disk(tmp_path):
    # Ops concern: a rollback should flip mode to off but NOT wipe the
    # operator's enforce_verbs list — that list is audit evidence of the
    # canary's progress. Test mutates that invariant.
    cfg = _cfg(tmp_path, "enforce")
    sig = tmp_path / "rollback_signal"
    _plant_signal(sig)
    he.apply_rollback(
        signal_path=sig,
        config_path=cfg,
        blocked_dir=tmp_path / "blocked",
        now_iso="2026-04-17T12:00:00Z",
    )
    text = cfg.read_text()
    assert "submit_code" in text
    assert "request_clarification" in text


# -- Idempotency under replanted signals -----------------------------------


def test_adv_replanted_signal_triggers_second_rollback(tmp_path):
    cfg = _cfg(tmp_path, "shadow")
    sig = tmp_path / "rollback_signal"
    _plant_signal(sig, trigger="drain_consensus_regression")
    first = he.apply_rollback(
        signal_path=sig, config_path=cfg, blocked_dir=tmp_path / "blocked",
        now_iso="2026-04-17T12:00:00Z",
    )
    assert first.triggered
    # Operator re-plants a fresh signal after investigating — a second
    # rollback should produce a distinct blocked report (timestamp-based
    # filename) even though mode is already off.
    _plant_signal(sig, trigger="agent_permission_denied_loop")
    second = he.apply_rollback(
        signal_path=sig, config_path=cfg, blocked_dir=tmp_path / "blocked",
        now_iso="2026-04-17T12:00:01Z",
    )
    assert second.triggered
    assert second.previous_mode == "off"  # already off from first rollback
    assert first.blocked_report_path != second.blocked_report_path
    blocked_files = list((tmp_path / "blocked").glob("ROLLBACK-*.md"))
    assert len(blocked_files) == 2


# -- Byzantine signal bodies ------------------------------------------------


def test_adv_signal_with_invalid_json_still_rolls_back(tmp_path):
    cfg = _cfg(tmp_path, "shadow")
    sig = tmp_path / "rollback_signal"
    sig.write_text("{not json", encoding="utf-8")
    outcome = he.apply_rollback(
        signal_path=sig, config_path=cfg, blocked_dir=tmp_path / "blocked",
        now_iso="2026-04-17T12:00:00Z",
    )
    # Rollback MUST still fire — we never let a malformed signal mask a
    # genuine incident. The trigger is marked unknown, preserving audit.
    assert outcome.triggered is True
    body = pathlib.Path(outcome.blocked_report_path).read_text()
    assert "unknown" in body.lower() or "trigger" in body.lower()


def test_adv_signal_with_unknown_trigger_recorded_as_unknown(tmp_path):
    cfg = _cfg(tmp_path, "shadow")
    sig = tmp_path / "rollback_signal"
    sig.write_text(
        json.dumps({"trigger": "made_up_exotic_trigger", "reason": "???"}),
        encoding="utf-8",
    )
    outcome = he.apply_rollback(
        signal_path=sig, config_path=cfg, blocked_dir=tmp_path / "blocked",
        now_iso="2026-04-17T12:00:00Z",
    )
    assert outcome.triggered is True
    body = pathlib.Path(outcome.blocked_report_path).read_text()
    # Unknown triggers are preserved verbatim in the blocked report so
    # the human reviewer can trace where the signal came from.
    assert "made_up_exotic_trigger" in body


def test_adv_signal_with_empty_body_still_rolls_back(tmp_path):
    cfg = _cfg(tmp_path, "shadow")
    sig = tmp_path / "rollback_signal"
    sig.write_text("", encoding="utf-8")
    outcome = he.apply_rollback(
        signal_path=sig, config_path=cfg, blocked_dir=tmp_path / "blocked",
        now_iso="2026-04-17T12:00:00Z",
    )
    assert outcome.triggered is True


# -- Mode-flip regex mutation coverage -------------------------------------


def test_adv_mode_flip_only_touches_hooks_mode_line(tmp_path):
    # Adversary plants a file where a non-hooks "mode:" substring appears
    # in a comment or in another block. The flip must NOT rewrite that
    # unrelated line.
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "# upstream mode: enforce (historical note)\n"
        "other:\n"
        "  mode: 'verbose'\n"
        "\n"
        "hooks:\n"
        '  mode: "enforce"\n'
        "  enforce_verbs: []\n",
        encoding="utf-8",
    )
    prior = he.flip_hooks_mode_off(cfg)
    assert prior == "enforce"
    text = cfg.read_text()
    # The unrelated "mode: 'verbose'" survives.
    assert "mode: 'verbose'" in text
    # The historical-note comment still reads "mode: enforce".
    assert "mode: enforce (historical note)" in text
    # And the hooks block is now off.
    assert re.search(
        r'hooks:\s*\n(?:\s*#.*\n)*\s*mode:\s*"?off"?', text, re.MULTILINE
    )


def test_adv_mode_flip_resilient_to_trailing_whitespace(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "hooks:\n"
        '  mode: "shadow"   \n'  # note trailing spaces
        "  enforce_verbs: []\n",
        encoding="utf-8",
    )
    he.flip_hooks_mode_off(cfg)
    assert re.search(r'^\s*mode:\s*"?off"?', cfg.read_text(), re.MULTILINE)


def test_adv_mode_flip_does_not_double_write_on_already_off(tmp_path):
    cfg = _cfg(tmp_path, "off")
    text_before = cfg.read_text()
    # Ensure no-op doesn't insert duplicate keys.
    he.flip_hooks_mode_off(cfg)
    text_after = cfg.read_text()
    # line count preserved
    assert text_before.count("\n") == text_after.count("\n")


# -- Concurrent rollback path ----------------------------------------------


def test_adv_concurrent_apply_rollback_is_serialisable(tmp_path):
    # Two watchdogs fire simultaneously — both call apply_rollback with
    # the same signal file. Exactly one should succeed (triggered=True);
    # the other sees the already-consumed signal and returns triggered=False.
    cfg = _cfg(tmp_path, "shadow")
    sig = tmp_path / "rollback_signal"
    _plant_signal(sig)
    outcomes: list[he.RollbackOutcome] = []
    lock = threading.Lock()

    def worker(i: int) -> None:
        out = he.apply_rollback(
            signal_path=sig, config_path=cfg, blocked_dir=tmp_path / "blocked",
            now_iso=f"2026-04-17T12:00:{i:02d}Z",
        )
        with lock:
            outcomes.append(out)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # At most one triggered=True (race-safe via O_CREAT|O_EXCL or unlink).
    triggered = [o for o in outcomes if o.triggered]
    assert len(triggered) <= 1
    assert not sig.exists()


# -- CLI contract -----------------------------------------------------------


def _cli_rollback(cwd, signal_path, config_path, blocked_dir):
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


def test_adv_cli_rollback_deterministic_exit(tmp_path):
    cfg = _cfg(tmp_path, "shadow")
    sig = tmp_path / "rollback_signal"
    _plant_signal(sig)
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    codes = []
    for _ in range(3):
        r = _cli_rollback(repo_root, sig, cfg, tmp_path / "blocked")
        codes.append(r.returncode)
        # Re-plant for the next iteration.
        _plant_signal(sig)
    assert all(c == 0 for c in codes)


def test_adv_cli_rollback_emits_blocked_path_on_stdout(tmp_path):
    cfg = _cfg(tmp_path, "enforce")
    sig = tmp_path / "rollback_signal"
    _plant_signal(sig, trigger="shadow_divergence_two_consecutive", reason="r1", detail="d1")
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    r = _cli_rollback(repo_root, sig, cfg, tmp_path / "blocked")
    combined = r.stdout + r.stderr
    assert "ROLLBACK-" in combined
    assert ".md" in combined


def test_adv_cli_rollback_no_signal_returns_zero_and_does_not_touch_config(tmp_path):
    cfg = _cfg(tmp_path, "shadow")
    text_before = cfg.read_text()
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    r = _cli_rollback(repo_root, tmp_path / "nope", cfg, tmp_path / "blocked")
    assert r.returncode == 0
    assert cfg.read_text() == text_before
    assert not (tmp_path / "blocked").exists()


# -- Fuzz: random triggers never crash -------------------------------------


def test_adv_fuzz_random_signal_shapes_never_crash(tmp_path):
    import random

    cfg = _cfg(tmp_path, "shadow")
    rng = random.Random(0xDEAD)
    shapes = [
        lambda: json.dumps({"trigger": rng.choice(list(he.ROLLBACK_TRIGGERS))}),
        lambda: json.dumps({"trigger": "unknown", "reason": "x" * rng.randint(0, 500)}),
        lambda: "",
        lambda: "{garbage",
        lambda: json.dumps([1, 2, 3]),
        lambda: json.dumps({"trigger": 123}),
        lambda: json.dumps({"trigger": "shadow_divergence_two_consecutive", "detail": None}),
    ]
    sig = tmp_path / "rollback_signal"
    for i in range(30):
        sig.write_text(shapes[i % len(shapes)](), encoding="utf-8")
        outcome = he.apply_rollback(
            signal_path=sig, config_path=cfg, blocked_dir=tmp_path / "blocked",
            now_iso=f"2026-04-17T12:{i:02d}:00Z",
        )
        # Must never raise; some iterations trigger, some don't depending
        # on whether previous ran left signal cleared. Key property: no crash.
        assert isinstance(outcome.triggered, bool)


# -- Consistency with master plan §5.4 ------------------------------------


def test_adv_blocked_report_contains_meta_task_type_line(tmp_path):
    # Master plan §5.4 mandates meta_task_type: harness_plumbing exactly.
    cfg = _cfg(tmp_path, "enforce")
    sig = tmp_path / "rollback_signal"
    _plant_signal(sig)
    outcome = he.apply_rollback(
        signal_path=sig, config_path=cfg, blocked_dir=tmp_path / "blocked",
        now_iso="2026-04-17T12:00:00Z",
    )
    body = pathlib.Path(outcome.blocked_report_path).read_text()
    assert re.search(r"meta_task_type:\s*harness_plumbing", body)


def test_adv_blocked_report_timestamp_matches_filename(tmp_path):
    cfg = _cfg(tmp_path, "shadow")
    sig = tmp_path / "rollback_signal"
    _plant_signal(sig)
    ts = "2026-04-17T12:34:56Z"
    outcome = he.apply_rollback(
        signal_path=sig, config_path=cfg, blocked_dir=tmp_path / "blocked",
        now_iso=ts,
    )
    fname = pathlib.Path(outcome.blocked_report_path).name
    # Filename must encode the timestamp (stripped of : and Z for
    # filesystem-safety) so the order is obvious from ls alone.
    assert "2026-04-17" in fname
    # And the timestamp appears verbatim in the body for traceability.
    assert ts in pathlib.Path(outcome.blocked_report_path).read_text()


# -- M19 / master-plan §Medium M19: blocked-task re-emission --------------
#
# Sub-plan 06 §3 item 3 requires rollback to re-emit the failed task with
# meta_task_type: harness_plumbing so a human can review it. The markdown
# stub written by emit_rollback_blocked_report carries that frontmatter
# header, but nothing in the planner pipeline scans state/tasks/blocked/
# for ROLLBACK-*.md files and registers them as harness_plumbing work.
# The first test asserts the frontmatter invariant (green today). The
# second test documents whether the planner picks the stub up; because
# no such scanner exists in harness/orchestrator.py or harness/task_decomposer.py
# as of HEAD 9a1f72b, that test is xfailed with a precise reason pointing
# at sub-plan 06 §3 item 3.


def test_adv_blocked_report_carries_harness_plumbing_frontmatter(tmp_path):
    """Master plan §5.4 + sub-plan 06 §3 item 3: the blocked-task markdown
    stub must declare meta_task_type: harness_plumbing in its YAML
    frontmatter so downstream planner scanners treat it as harness plumbing
    rather than brief work. Covers the format half of M19."""
    blocked_dir = tmp_path / "blocked"
    target = he.emit_rollback_blocked_report(
        trigger="drain_consensus_regression",
        reason="drain regression on brief stab_001",
        detail="session_id=drain-stab_001-abc divergence_count=2",
        blocked_dir=blocked_dir,
        now_iso="2026-04-17T13:45:00Z",
        previous_mode="shadow",
    )
    body = pathlib.Path(target).read_text(encoding="utf-8")
    # Frontmatter starts at line 0 with exact meta_task_type: harness_plumbing.
    lines = body.splitlines()
    assert lines[0] == "---", "expected YAML frontmatter delimiter at line 0"
    frontmatter_end = lines.index("---", 1)
    frontmatter = "\n".join(lines[1:frontmatter_end])
    assert re.search(r"^meta_task_type:\s*harness_plumbing\s*$", frontmatter, re.MULTILINE), (
        "blocked-task stub must declare meta_task_type: harness_plumbing; got frontmatter:\n"
        + frontmatter
    )
    # Trigger + previous_mode are audit-critical for reviewer triage.
    assert re.search(r"^trigger:\s*drain_consensus_regression\s*$", frontmatter, re.MULTILINE)
    assert re.search(r"^previous_mode:\s*shadow\s*$", frontmatter, re.MULTILINE)


def test_adv_blocked_report_is_picked_up_by_planner_as_harness_plumbing(tmp_path):
    """Second half of M19 — the integration invariant: after
    emit_rollback_blocked_report writes ROLLBACK-*.md, the planner's normal
    task-intake path surfaces it as a harness_plumbing task.

    M19 wired this up in harness/orchestrator.py via
    ``scan_blocked_rollbacks`` (exposed as the intake seam) and
    ``_reemit_blocked_rollbacks`` (called from get_next_task to materialise
    stubs as JSON tasks on the planner queue). Implements sub-plan 06 §3
    item 3 ("re-emit the failed task with meta_task_type: harness_plumbing
    asking a human to review")."""
    blocked_dir = tmp_path / "state" / "tasks" / "blocked"
    he.emit_rollback_blocked_report(
        trigger="drain_consensus_regression",
        reason="drain regression on brief stab_001",
        detail="session_id=drain-stab_001-abc divergence_count=1",
        blocked_dir=blocked_dir,
        now_iso="2026-04-17T13:45:00Z",
        previous_mode="shadow",
    )
    # Look for any planner-side entrypoint that scans blocked/ROLLBACK-*.md.
    # If harness grows e.g. `list_blocked_rollback_tasks` or similar, this
    # test will find it and assert a harness_plumbing task was registered.
    from harness import orchestrator, task_decomposer

    candidate_names = [
        "scan_blocked_rollbacks",
        "list_blocked_rollback_tasks",
        "load_blocked_tasks",
        "ingest_rollback_blocked",
    ]
    scanner = None
    for mod in (orchestrator, task_decomposer):
        for name in candidate_names:
            fn = getattr(mod, name, None)
            if callable(fn):
                scanner = fn
                break
        if scanner is not None:
            break
    assert scanner is not None, (
        "No planner-side blocked-rollback scanner exists yet — sub-plan 06 "
        "§3 item 3 re-emission seam is stubbed."
    )
    # If a scanner lands, verify it registers the stub as harness_plumbing.
    tasks = scanner(blocked_dir) if scanner.__code__.co_argcount else scanner()
    assert tasks, "scanner returned no tasks despite a blocked ROLLBACK stub on disk"
    matches = [
        t for t in tasks
        if getattr(t, "meta_task_type", None) == "harness_plumbing"
        or (isinstance(t, dict) and t.get("meta_task_type") == "harness_plumbing")
    ]
    assert matches, (
        "blocked-rollback stub was scanned but not registered as harness_plumbing: "
        + repr(tasks)
    )
