"""Adversarial coverage for scripts/impl_drain_capture.py.

The wrapper bridges the CLI gap flagged in
``brief_hooks_operator_followup.md`` §3 — the orchestrator's ``main()``
does not accept ``--brief``/``--session`` and the B3 baseline
regeneration runbook needs both plus artefact-capture plumbing.

Tests exercise ONLY the dry-run path and mocked helper shapes.
Spawning a real planner or orchestrator is explicitly forbidden per the
subscription-cost guardrail (a real cycle burns the operator's 5hr
Claude rolling window + daily Gemini quota).
"""

from __future__ import annotations

import io
import json
import pathlib
import re
import subprocess
import sys
import time
from unittest import mock

import pytest


_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "impl_drain_capture.py"


sys.path.insert(0, str(_REPO_ROOT / "scripts"))
import impl_drain_capture as wrapper  # noqa: E402


# These tests drive the wrapper against the ``stab_001``/``stab_003`` drain
# briefs, whose files (``brief_stab_*.md``) are gitignored operator working-tree
# fixtures and are therefore ABSENT in a fresh clone. Rather than skip on a clean
# clone (REPL-FIXTURE: make clone-PORTABLE, not skipped), redirect the wrapper's
# brief-file lookup to a tmp-materialised stub so the dry-run plan tests run on a
# fresh clone too. The dry-run path only needs the brief file to *exist* (it
# prints the path; it never parses content — see scripts/impl_drain_capture.py
# main()/_emit_plan), so a 1-line stub is sufficient. We intercept the lookup
# regardless of whether the real fixture is present, so this also passes on the
# operator machine (it depends on neither the presence NOR absence of state).
@pytest.fixture(autouse=True)
def _portable_drain_briefs(tmp_path_factory, monkeypatch):
    brief_root = tmp_path_factory.mktemp("drain_briefs")
    for _bid in wrapper.DRAIN_BRIEFS:
        (brief_root / f"brief_{_bid}.md").write_text(
            f"# Title\nstub drain brief {_bid}\n", encoding="utf-8"
        )

    def _stub_brief_file_path(brief, repo_root=brief_root):
        return brief_root / f"brief_{brief}.md"

    monkeypatch.setattr(wrapper, "_brief_file_path", _stub_brief_file_path)
    return brief_root


# ---------------------------------------------------------------------------
# Dry-run path
# ---------------------------------------------------------------------------

def test_dry_run_prints_plan_and_exits_zero(tmp_path, capsys, monkeypatch):
    """Dry-run must print the plan and exit 0 without touching state."""
    state_dir = tmp_path / "state"
    baseline_dir = state_dir / "hooks"
    baseline_dir.mkdir(parents=True)

    rc = wrapper.main([
        "--brief", "stab_001",
        "--state-dir", str(state_dir),
        "--baseline-dir", str(baseline_dir),
        "--dry-run",
    ])
    captured = capsys.readouterr()
    assert rc == 0, f"dry-run should exit 0, got {rc}: {captured.err}"
    out = captured.out
    assert "drain-capture plan" in out
    assert "brief           : stab_001" in out
    # New flow: plan must name both subprocesses.
    assert "harness.planner.cli" in out
    assert "harness.orchestrator" in out
    assert "SIGINT" in out
    assert "capture_drain_artefacts(" in out
    assert "save_drain_baseline(" in out
    # The critical invariant: dry-run must NOT write a baseline file.
    assert not (baseline_dir / "drain_baseline_stab_001.json").exists(), (
        "dry-run must not materialise a baseline file"
    )


def test_dry_run_unknown_brief_rejects_nonzero(capsys, tmp_path):
    """stab_999 is not in DRAIN_BRIEFS — wrapper must refuse loudly."""
    with pytest.raises(SystemExit) as excinfo:
        wrapper.main([
            "--brief", "stab_999",
            "--state-dir", str(tmp_path / "state"),
            "--dry-run",
        ])
    code = excinfo.value.code
    if isinstance(code, int):
        assert code != 0
    else:
        assert "stab_999" in str(code) or "unknown brief" in str(code)


def test_dry_run_subprocess_unknown_brief_nonzero_exit(tmp_path):
    """Subprocess shape: exit code must be non-zero on unknown brief."""
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT),
         "--brief", "stab_999",
         "--state-dir", str(tmp_path / "state"),
         "--dry-run"],
        cwd=str(_REPO_ROOT), capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode != 0, (
        f"expected non-zero exit; got stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    combined = (proc.stdout + proc.stderr).lower()
    assert "stab_999" in combined or "unknown brief" in combined


def test_skip_planner_flag_shows_skipped_in_plan(tmp_path, capsys):
    """--skip-planner must annotate the plan as skipping the planner step."""
    state_dir = tmp_path / "state"
    baseline_dir = state_dir / "hooks"
    baseline_dir.mkdir(parents=True)
    rc = wrapper.main([
        "--brief", "stab_001",
        "--state-dir", str(state_dir),
        "--baseline-dir", str(baseline_dir),
        "--skip-planner",
        "--dry-run",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "SKIPPED" in out
    assert "--skip-planner" in out


# ---------------------------------------------------------------------------
# Session-id default format
# ---------------------------------------------------------------------------

def test_default_session_id_format():
    """Default: drain-<brief>-<YYYYmmddTHHMMSSZ>."""
    sid = wrapper._default_session_id("stab_001")
    m = re.match(r"^drain-stab_001-\d{8}T\d{6}Z$", sid)
    assert m is not None, f"unexpected default session id shape: {sid!r}"


def test_explicit_session_id_is_respected(tmp_path, capsys):
    """An operator-supplied --session must appear verbatim in the plan."""
    state_dir = tmp_path / "state"
    baseline_dir = state_dir / "hooks"
    baseline_dir.mkdir(parents=True)
    rc = wrapper.main([
        "--brief", "stab_003",
        "--session", "operator-picked-session",
        "--state-dir", str(state_dir),
        "--baseline-dir", str(baseline_dir),
        "--dry-run",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "operator-picked-session" in out


# ---------------------------------------------------------------------------
# Safety interlock: rollback_signal
# ---------------------------------------------------------------------------

def test_rollback_signal_reported_in_dry_run(tmp_path, capsys):
    """Dry-run must surface active interlocks so operator sees them pre-commit."""
    state_dir = tmp_path / "state"
    (state_dir / "hooks").mkdir(parents=True)
    (state_dir / "hooks" / "rollback_signal").write_text(
        "trigger=test\n", encoding="utf-8",
    )
    baseline_dir = state_dir / "hooks"

    rc = wrapper.main([
        "--brief", "stab_001",
        "--state-dir", str(state_dir),
        "--baseline-dir", str(baseline_dir),
        "--dry-run",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "SAFETY INTERLOCKS WOULD BLOCK" in out
    assert "rollback_signal present" in out


def test_rollback_interlock_detects_blocked_rollback_stub(tmp_path):
    """Stale ROLLBACK-*.md under state/tasks/blocked/ must register as blocker."""
    state_dir = tmp_path / "state"
    blocked = state_dir / "tasks" / "blocked"
    blocked.mkdir(parents=True)
    (blocked / "ROLLBACK-stub.md").write_text("stale\n", encoding="utf-8")

    blockers = wrapper._rollback_interlock_blockers(state_dir)
    assert blockers, "expected blockers for stale ROLLBACK-*.md"
    assert any("ROLLBACK" in b for b in blockers)


def test_rollback_interlock_clean_state_returns_empty(tmp_path):
    """No rollback_signal + no stale stubs = no blockers."""
    state_dir = tmp_path / "state"
    (state_dir / "hooks").mkdir(parents=True)
    (state_dir / "tasks" / "blocked").mkdir(parents=True)
    assert wrapper._rollback_interlock_blockers(state_dir) == []


# ---------------------------------------------------------------------------
# Synthetic-placeholder warning
# ---------------------------------------------------------------------------

def test_synthetic_placeholder_detected(tmp_path, capsys):
    """When existing baseline still carries __baseline_note, warn in plan."""
    state_dir = tmp_path / "state"
    baseline_dir = state_dir / "hooks"
    baseline_dir.mkdir(parents=True)
    (baseline_dir / "drain_baseline_stab_001.json").write_text(
        json.dumps({
            "__baseline_note": "synthetic empty placeholder",
            "artefacts": {"patch_stat": "", "test_count": 0, "track_events": []},
            "brief_id": "stab_001",
            "generated_at": "2026-04-18T00:00:00Z",
        }),
        encoding="utf-8",
    )

    rc = wrapper.main([
        "--brief", "stab_001",
        "--state-dir", str(state_dir),
        "--baseline-dir", str(baseline_dir),
        "--dry-run",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "synthetic placeholder" in out.lower()


def test_real_baseline_not_flagged_as_synthetic(tmp_path):
    """A baseline written by save_drain_baseline lacks __baseline_note
    (verified invariant from harness.hooks_equivalence.save_drain_baseline)."""
    from harness import hooks_equivalence as he

    baseline_dir = tmp_path / "hooks"
    baseline_dir.mkdir(parents=True)
    art = he.DrainArtefacts(patch_stat="", test_count=7, track_events=[])
    he.save_drain_baseline(
        brief_id="stab_001", artefacts=art, baseline_dir=baseline_dir,
    )
    assert wrapper._existing_baseline_is_synthetic("stab_001", baseline_dir) is False

    payload = json.loads(
        (baseline_dir / "drain_baseline_stab_001.json").read_text(encoding="utf-8")
    )
    assert "__baseline_note" not in payload


# ---------------------------------------------------------------------------
# Helper shapes — subprocess-free
# ---------------------------------------------------------------------------

def test_count_lines_missing_file_returns_zero(tmp_path):
    assert wrapper._count_lines(tmp_path / "does-not-exist") == 0


def test_count_lines_matches_actual_count(tmp_path):
    p = tmp_path / "tracks.jsonl"
    p.write_text("a\nb\nc\n", encoding="utf-8")
    assert wrapper._count_lines(p) == 3


def test_pending_task_count_counts_queued_and_inflight_work(tmp_path):
    """Count all unfinished work: queued + processing + current_task.json marker."""
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    # 2 queued (not yet claimed)
    (tasks / "t1.json").write_text("{}", encoding="utf-8")
    (tasks / "t2.json").write_text("{}", encoding="utf-8")
    # 1 in flight (claimed, renamed to .processing)
    (tasks / "t3.json.processing").write_text("{}", encoding="utf-8")
    # 1 current_task.json marker
    (tasks / "current_task.json").write_text("{}", encoding="utf-8")
    # subdirs (processed/, blocked/) must not inflate the count
    (tasks / "processed").mkdir()
    (tasks / "processed" / "old.json").write_text("{}", encoding="utf-8")
    # 2 queued + 1 processing + 1 current = 4
    assert wrapper._pending_task_count(tmp_path) == 4


def test_pending_task_count_processing_only(tmp_path):
    """In-flight synthesis with no queue — count must still be non-zero."""
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    (tasks / "DECOMPOSER-001.json.processing").write_text("{}", encoding="utf-8")
    (tasks / "current_task.json").write_text("{}", encoding="utf-8")
    assert wrapper._pending_task_count(tmp_path) == 2


def test_pending_task_count_empty_queue_returns_zero(tmp_path):
    """Orchestrator truly idle: empty queue, no processing, no current marker."""
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    assert wrapper._pending_task_count(tmp_path) == 0


def test_pending_task_count_missing_dir_returns_zero(tmp_path):
    assert wrapper._pending_task_count(tmp_path) == 0


def test_capture_tracks_delta_copies_only_new_lines(tmp_path):
    canonical = tmp_path / "track_record_events.jsonl"
    canonical.write_text("l1\nl2\nl3\nl4\nl5\n", encoding="utf-8")
    dest = tmp_path / "drain_patches" / "session.tracks.jsonl"
    wrapper._capture_tracks_delta(canonical=canonical, lines_before=2, dest=dest)
    assert dest.read_text(encoding="utf-8") == "l3\nl4\nl5\n"


def test_capture_tracks_delta_missing_canonical_writes_empty(tmp_path):
    canonical = tmp_path / "does-not-exist"
    dest = tmp_path / "drain_patches" / "session.tracks.jsonl"
    wrapper._capture_tracks_delta(canonical=canonical, lines_before=0, dest=dest)
    assert dest.exists() and dest.read_text(encoding="utf-8") == ""


def test_capture_tracks_delta_no_new_lines_writes_empty(tmp_path):
    canonical = tmp_path / "track_record_events.jsonl"
    canonical.write_text("l1\nl2\n", encoding="utf-8")
    dest = tmp_path / "drain_patches" / "session.tracks.jsonl"
    wrapper._capture_tracks_delta(canonical=canonical, lines_before=2, dest=dest)
    assert dest.read_text(encoding="utf-8") == ""


# ---------------------------------------------------------------------------
# Shutdown escalation — mocked Popen, no real signals sent
# ---------------------------------------------------------------------------

def test_shutdown_orchestrator_sigint_on_live_proc(monkeypatch):
    """A live proc receives SIGINT first; clean wait returns its rc."""
    proc = mock.Mock(spec=subprocess.Popen)
    proc.pid = 99999
    # First poll: live; then wait succeeds (returns 0).
    proc.poll.side_effect = [None, 0]
    proc.wait.return_value = 0
    proc.returncode = 0
    proc._drain_log_handles = ()

    sent_signals: list[int] = []

    def fake_killpg(pgid, sig):
        sent_signals.append(sig)

    monkeypatch.setattr(wrapper.os, "killpg", fake_killpg)
    monkeypatch.setattr(wrapper.os, "getpgid", lambda pid: pid)

    import signal as _signal
    rc = wrapper._shutdown_orchestrator(
        proc, sigint_grace=1, sigterm_grace=1,
    )
    assert rc == 0
    assert sent_signals == [_signal.SIGINT]


def test_shutdown_orchestrator_already_exited_returns_code(monkeypatch):
    """If proc already exited, no signal is sent."""
    proc = mock.Mock(spec=subprocess.Popen)
    proc.pid = 99999
    proc.poll.return_value = 0
    proc.returncode = 0
    proc._drain_log_handles = ()

    sent_signals: list[int] = []
    monkeypatch.setattr(
        wrapper.os, "killpg", lambda pgid, sig: sent_signals.append(sig),
    )
    monkeypatch.setattr(wrapper.os, "getpgid", lambda pid: pid)

    rc = wrapper._shutdown_orchestrator(proc, sigint_grace=1, sigterm_grace=1)
    assert rc == 0
    assert sent_signals == []


def test_shutdown_orchestrator_escalates_to_sigterm(monkeypatch):
    """SIGINT ignored (wait timeout) → SIGTERM follows."""
    import signal as _signal
    proc = mock.Mock(spec=subprocess.Popen)
    proc.pid = 99999
    # still live after first SIGINT wait; exits after SIGTERM wait
    proc.poll.side_effect = [None, None, 0]
    proc.wait.side_effect = [
        subprocess.TimeoutExpired(cmd="o", timeout=1),
        0,
    ]
    proc.returncode = -15
    proc._drain_log_handles = ()

    sent_signals: list[int] = []
    monkeypatch.setattr(
        wrapper.os, "killpg", lambda pgid, sig: sent_signals.append(sig),
    )
    monkeypatch.setattr(wrapper.os, "getpgid", lambda pid: pid)

    rc = wrapper._shutdown_orchestrator(proc, sigint_grace=1, sigterm_grace=1)
    assert rc == 0
    assert sent_signals == [_signal.SIGINT, _signal.SIGTERM]


# ---------------------------------------------------------------------------
# Drain wait — mocked Popen + tmp state tree, fast poll
# ---------------------------------------------------------------------------

def test_wait_for_drain_returns_idle_when_queue_stays_empty(tmp_path, monkeypatch):
    (tmp_path / "tasks").mkdir()
    proc = mock.Mock(spec=subprocess.Popen)
    proc.poll.return_value = None
    monkeypatch.setattr(wrapper.time, "sleep", lambda s: None)
    status = wrapper._wait_for_drain(
        orch_proc=proc, state_dir=tmp_path,
        poll_step=0.01, idle_confirm=0.03, timeout=5,
    )
    assert status == "idle"


def test_wait_for_drain_detects_orchestrator_exit(tmp_path, monkeypatch):
    (tmp_path / "tasks").mkdir()
    proc = mock.Mock(spec=subprocess.Popen)
    proc.poll.return_value = 1  # already exited
    monkeypatch.setattr(wrapper.time, "sleep", lambda s: None)
    status = wrapper._wait_for_drain(
        orch_proc=proc, state_dir=tmp_path,
        poll_step=0.01, idle_confirm=0.03, timeout=5,
    )
    assert status == "orchestrator_exit"


def test_wait_for_drain_timeout_when_queue_never_empties(tmp_path, monkeypatch):
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    (tasks / "t1.json").write_text("{}", encoding="utf-8")
    proc = mock.Mock(spec=subprocess.Popen)
    proc.poll.return_value = None
    # Fake monotonic so we cross the timeout quickly.
    t = iter([0.0, 0.01, 0.02, 100.0, 200.0])
    monkeypatch.setattr(wrapper.time, "monotonic", lambda: next(t))
    monkeypatch.setattr(wrapper.time, "sleep", lambda s: None)
    status = wrapper._wait_for_drain(
        orch_proc=proc, state_dir=tmp_path,
        poll_step=0.01, idle_confirm=0.03, timeout=1,
    )
    assert status == "timeout"


# ---------------------------------------------------------------------------
# Planner subprocess — subprocess.run mocked; never a real fork
# ---------------------------------------------------------------------------

def test_run_planner_passes_brief_and_config_to_cli(tmp_path, monkeypatch):
    brief_file = tmp_path / "brief_stab_001.md"
    brief_file.write_text("# Title\nstub\n", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text("synthesis: {}\n", encoding="utf-8")
    log_dir = tmp_path / "logs"

    calls: list[dict] = []

    class _FakeCompleted:
        returncode = 0

    def fake_run(cmd, **kw):
        calls.append({"cmd": cmd, "kw": kw})
        return _FakeCompleted()

    monkeypatch.setattr(wrapper.subprocess, "run", fake_run)

    wrapper._run_planner(
        brief_file=brief_file, config_path=config_path,
        repo_root=tmp_path, log_dir=log_dir, timeout=60,
    )

    assert len(calls) == 1
    cmd = calls[0]["cmd"]
    # Command must invoke harness.planner.cli with brief + --config.
    assert "-m" in cmd and "harness.planner.cli" in cmd
    assert str(brief_file) in cmd
    assert "--config" in cmd and str(config_path) in cmd
    # Log files opened for stdout/stderr.
    assert (log_dir / "planner.stdout.log").exists()
    assert (log_dir / "planner.stderr.log").exists()


def test_run_planner_nonzero_exit_raises_with_stderr_tail(tmp_path, monkeypatch):
    brief_file = tmp_path / "brief_stab_001.md"
    brief_file.write_text("# x\n", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text("\n", encoding="utf-8")
    log_dir = tmp_path / "logs"

    class _FakeCompleted:
        returncode = 2

    def fake_run(cmd, **kw):
        # Write a stderr marker the wrapper can tail.
        err_path = kw["stderr"].name if hasattr(kw["stderr"], "name") else None
        if err_path:
            pathlib.Path(err_path).write_text("planner blew up\n", encoding="utf-8")
        return _FakeCompleted()

    monkeypatch.setattr(wrapper.subprocess, "run", fake_run)
    with pytest.raises(SystemExit) as excinfo:
        wrapper._run_planner(
            brief_file=brief_file, config_path=config_path,
            repo_root=tmp_path, log_dir=log_dir, timeout=60,
        )
    msg = str(excinfo.value.code)
    assert "planner exited 2" in msg
    assert "planner blew up" in msg


def test_run_planner_timeout_raises(tmp_path, monkeypatch):
    brief_file = tmp_path / "brief_stab_001.md"
    brief_file.write_text("# x\n", encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text("\n", encoding="utf-8")
    log_dir = tmp_path / "logs"

    def fake_run(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=kw.get("timeout"))

    monkeypatch.setattr(wrapper.subprocess, "run", fake_run)
    with pytest.raises(SystemExit) as excinfo:
        wrapper._run_planner(
            brief_file=brief_file, config_path=config_path,
            repo_root=tmp_path, log_dir=log_dir, timeout=1,
        )
    assert "planner timed out" in str(excinfo.value.code)


# ---------------------------------------------------------------------------
# Spawn orchestrator — Popen mocked; verifies CLI and process-group flag
# ---------------------------------------------------------------------------

def test_spawn_orchestrator_uses_session_group_and_logs(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("\n", encoding="utf-8")
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    log_dir = tmp_path / "logs"

    captured: dict = {}

    class _FakePopen:
        def __init__(self, cmd, **kw):
            captured["cmd"] = cmd
            captured["kw"] = kw
            self.pid = 12345
            self.returncode = None

        def poll(self):
            return None

    monkeypatch.setattr(wrapper.subprocess, "Popen", _FakePopen)

    proc = wrapper._spawn_orchestrator(
        config_path=config_path, state_dir=state_dir,
        log_dir=log_dir, repo_root=tmp_path,
    )
    cmd = captured["cmd"]
    assert "-m" in cmd and "harness.orchestrator" in cmd
    assert "--config" in cmd and str(config_path) in cmd
    assert "--state-dir" in cmd and str(state_dir) in cmd
    assert "--log-dir" in cmd and str(log_dir) in cmd
    # Must use start_new_session so we have a pgroup to signal.
    assert captured["kw"].get("start_new_session") is True
    # Log-file handles were captured for later cleanup.
    assert hasattr(proc, "_drain_log_handles")
    assert len(proc._drain_log_handles) == 2
    for h in proc._drain_log_handles:
        h.close()

# ---------------------------------------------------------------------------
# Plan-shard step (merged_plan.json → state/tasks/<id>.json)
# ---------------------------------------------------------------------------

def test_shard_merged_plan_writes_per_task_files(tmp_path):
    """Each task in merged_plan["tasks"] lands at tasks_dir/<task_id>.json."""
    plan_path = tmp_path / "merged_plan.json"
    plan_path.write_text(json.dumps({
        "tasks": [
            {"task_id": "A-001", "title": "a", "meta_task_type": ""},
            {"task_id": "B-002", "title": "b", "dependencies": ["A-001"]},
        ]
    }), encoding="utf-8")
    tasks_dir = tmp_path / "tasks"
    written = wrapper._shard_merged_plan(plan_path, tasks_dir)
    assert written == ["A-001", "B-002"]
    a = json.loads((tasks_dir / "A-001.json").read_text())
    b = json.loads((tasks_dir / "B-002.json").read_text())
    assert a["task_id"] == "A-001"
    # Schema translation: dependencies -> depends_on (orchestrator reads depends_on).
    assert b["depends_on"] == ["A-001"]
    # Original field preserved for post-mortem.
    assert b["dependencies"] == ["A-001"]


def test_shard_merged_plan_missing_file_raises(tmp_path):
    with pytest.raises(SystemExit) as excinfo:
        wrapper._shard_merged_plan(tmp_path / "does-not-exist.json", tmp_path / "tasks")
    assert "did not produce a plan" in str(excinfo.value.code)


def test_shard_merged_plan_malformed_json_raises(tmp_path):
    plan_path = tmp_path / "merged_plan.json"
    plan_path.write_text("{not json", encoding="utf-8")
    with pytest.raises(SystemExit) as excinfo:
        wrapper._shard_merged_plan(plan_path, tmp_path / "tasks")
    assert "not valid JSON" in str(excinfo.value.code)


def test_shard_merged_plan_empty_tasks_array_raises(tmp_path):
    plan_path = tmp_path / "merged_plan.json"
    plan_path.write_text(json.dumps({"tasks": []}), encoding="utf-8")
    with pytest.raises(SystemExit) as excinfo:
        wrapper._shard_merged_plan(plan_path, tmp_path / "tasks")
    assert "no tasks array to shard" in str(excinfo.value.code)


def test_shard_merged_plan_skips_malformed_tasks(tmp_path):
    """Tasks without a string task_id are silently dropped, not fatal."""
    plan_path = tmp_path / "merged_plan.json"
    plan_path.write_text(json.dumps({
        "tasks": [
            {"task_id": "GOOD-1"},
            "not-a-dict",
            {"missing_task_id_field": True},
            {"task_id": 42},  # not a string
            {"task_id": "GOOD-2"},
        ]
    }), encoding="utf-8")
    written = wrapper._shard_merged_plan(plan_path, tmp_path / "tasks")
    assert written == ["GOOD-1", "GOOD-2"]


def test_shard_merged_plan_preserves_existing_depends_on(tmp_path):
    """If a task already has depends_on, don't clobber with dependencies."""
    plan_path = tmp_path / "merged_plan.json"
    plan_path.write_text(json.dumps({
        "tasks": [
            {"task_id": "T-1",
             "dependencies": ["X"],
             "depends_on": ["Y"]},
        ]
    }), encoding="utf-8")
    wrapper._shard_merged_plan(plan_path, tmp_path / "tasks")
    t1 = json.loads((tmp_path / "tasks" / "T-1.json").read_text())
    assert t1["depends_on"] == ["Y"]


def test_dry_run_plan_shows_shard_step(tmp_path, capsys):
    """The shard step must be visible in the dry-run plan."""
    state_dir = tmp_path / "state"
    baseline_dir = state_dir / "hooks"
    baseline_dir.mkdir(parents=True)
    rc = wrapper.main([
        "--brief", "stab_001",
        "--state-dir", str(state_dir),
        "--baseline-dir", str(baseline_dir),
        "--dry-run",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "[shard]" in out
    assert "merged_plan.json" in out
    assert "depends_on" in out
