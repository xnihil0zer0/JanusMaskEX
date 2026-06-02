"""FLAG2_EMBEDDED_FUZZ oracle (REV23 §C6) — fail-closed gate on the two OTHER
execute families (embedded-test-runner + narrow-fuzz) that still run an external
candidate UNJAILED when ``agent_sandbox`` is OFF.

Final repo path: tests/adversarial/test_flag2_embedded_fuzz.py

THREAT: FLAG2 fail-closed is done for the orchestrator shell=True verify family
(``_auto_commit_accepted``, FLAG2_ORCH @09693d4) but NOT for the embedded and
narrow-fuzz gates inside the bypass-fuzzer branch. With G2 relax already allowing
external eval/exec, the moment an external task runs, its JM-synthesized candidate
string is executed by ``run_embedded_tests`` / ``run_narrow_fuzz`` UNJAILED on the
host whenever sandbox is disabled.

FIX (gate at the CALL SITES, NOT inside the runners — §C6): before EACH of the
four call sites (orchestrator.run_pipeline ~:2554/:2563 and
orchestrator_worker.main ~:333/:342) add, mirroring the FLAG2_ORCH idiom::

    working_dir = task.get('working_dir')                 # at top of fn
    from harness import agent_jail                         # lazy, in-body
    from harness.paths import _target_is_self              # lazy, in-body
    ...
    if not _target_is_self(working_dir) and not agent_jail.sandbox_enabled(config):
        raise RuntimeError("FLAG2_EMBEDDED_FUZZ (REV23 §C6): refusing to run "
                           "<embedded tests|narrow-fuzz> UNJAILED ...")

REFUSAL OBSERVABILITY:
  * run_pipeline: the per-task loop body is ``try: ... finally:`` (no except), so a
    RuntimeError raised at the gate propagates OUT of run_pipeline -> caught here by
    ``pytest.raises(RuntimeError)`` AND no runner spy was invoked.
  * orchestrator_worker.main: the loop body is wrapped by ``except Exception`` which
    turns a raised RuntimeError into ``exit_code = 2`` / outcome 'error' -> observed
    via the return code AND no runner spy was invoked.

NON-VACUOUS / fail-closed:
  * RED on HEAD: no guard -> external + sandbox-OFF reaches the runner (orch: runs to
    the commit/accept path; worker: returns 0 accept) -> the discriminating asserts FAIL.
  * Negative controls: self (working_dir=None -> _target_is_self(None)==True) + sandbox
    OFF is NOT refused (runner IS called); external + sandbox ON is NOT refused (jailed).

Driving idiom mirrors tests/adversarial/test_phase_a3_skip_interface_fuzz.py: drive
run_pipeline / orchestrator_worker.main spawn-free, every collaborator faked. mtt is
'validation' (in BYPASS_FUZZER_TYPES, NOT in SKIP_SMOKE_GATE_TYPES, no
skip_interface_fuzz) so the inner smoke/embedded/narrow gate is actually reached.

Patch-target notes:
  * run_embedded_tests / run_narrow_fuzz are MODULE-LEVEL imports in orchestrator.py
    -> patch on ``harness.orchestrator``.
  * In orchestrator_worker.main they are imported FUNCTION-LOCALLY -> patch at the
    source modules ``harness.embedded_test_runner`` / ``harness.narrow_fuzz``.
"""
import json
import sys

import pytest
from unittest.mock import patch

import harness.orchestrator as orch
import harness.orchestrator_worker as ow
from harness.paths import _target_is_self


class _StopLoop(Exception):
    """Sentinel to break run_pipeline's ``while True`` after one task WITHOUT
    relying on StopIteration (which Python 3.13 re-wraps as a spurious RuntimeError
    when it escapes a generator frame, muddying the refusal signal)."""


@pytest.fixture
def pipeline_config():
    return {
        "synthesis": {
            "timeout_seconds": 30,
            "max_ast_retries": 3,
            "antigravity_mode": False,
            "use_retry_module": False,
            "active_agents": ["claude", "gemini"],
        },
        "fuzzing": {
            "engine": "hypothesis",
            "function_level_inputs": 50,
            "program_level_inputs": 20,
            "timeout_per_input_ms": 2000,
            "float_tolerance": 1e-9,
            "seed": 42,
        },
        "sandbox": {"memory_limit_mb": 256, "cpu_time_limit_seconds": 5, "network": False},
        "decomposition": {"max_depth": 3, "max_subtasks": 5, "fresh_instances": True},
        "agents": {
            "claude": {"command": "claude", "args": ["-p"]},
            "gemini": {"command": "gemini", "args": ["-p"]},
        },
        "agent_sandbox": {"bwrap": False},
    }


@pytest.fixture
def pipeline_state_dir(tmp_path):
    for sub in ("tasks", "tasks/processed", "sessions"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    orch.init_state(tmp_path)
    return tmp_path


def _make_task(working_dir):
    task = {
        "task_id": "flag2_embedded_fuzz_task",
        "specification": "Run verification and tests",
        "constraints": {"deterministic": True},
        # 'validation' is bypass-eligible (BYPASS_FUZZER_TYPES) and NOT in
        # SKIP_SMOKE_GATE_TYPES and carries no skip_interface_fuzz -> the inner
        # smoke -> embedded -> narrow gate is the path under test.
        "meta_task_type": "validation",
        "verification_command": "pytest tests/test_dummy.py",
        "files_touched": [],
        "dependencies": [],
    }
    if working_dir is not None:
        task["working_dir"] = working_dir
    return task


def _worker_cfg(*, bwrap):
    return {
        "synthesis": {
            "timeout_seconds": 600,
            "max_ast_retries": 3,
            "antigravity_mode": False,
            "use_retry_module": False,
            "active_agents": ["claude", "gemini"],
        },
        "cross_examination": {"max_rounds": 1},
        "decomposition": {"max_depth": 3},
        "fuzzing": {"float_tolerance": 1e-9},
        "agent_sandbox": {"bwrap": bwrap},
    }


# ── Precondition (documents the taxonomy state; not a detector) ──────────────

def test_precondition_external_is_classified_not_self(tmp_path):
    external = tmp_path / "totally_outside_repo"
    external.mkdir()
    assert _target_is_self(str(external)) is False, (
        "fixture working_dir must classify EXTERNAL for the oracle to be non-vacuous"
    )
    assert _target_is_self(None) is True


# ── ORCHESTRATOR PATH (harness/orchestrator.py::run_pipeline) ────────────────

def _drive_run_pipeline(config, state_dir, task):
    """Drive one bypass-branch iteration of run_pipeline spawn-free.

    Returns (raised_runtimeerror_or_None, embedded_calls, narrow_calls).
    time.sleep raises _StopLoop to terminate after the single task is processed
    (if the task path ever reaches the loop tail without being refused)."""
    call_count = [0]

    def mock_get_next_task(sd):
        call_count[0] += 1
        return task if call_count[0] == 1 else None

    embedded_calls, narrow_calls = [], []

    def mock_embedded(*a, **k):
        embedded_calls.append(a)
        return None

    def mock_narrow(*a, **k):
        narrow_calls.append(a)
        return None

    raised = None
    with patch("harness.orchestrator.run_both_agents",
               return_value=("def f(): pass", "def g(): pass")), \
         patch("harness.orchestrator._validate_submission", return_value=(True, [])), \
         patch("harness.orchestrator.get_next_task", side_effect=mock_get_next_task), \
         patch("harness.orchestrator._auto_commit_accepted", return_value=True), \
         patch("harness.orchestrator.smoke_import", return_value=None), \
         patch("harness.orchestrator.run_embedded_tests", side_effect=mock_embedded), \
         patch("harness.orchestrator.run_narrow_fuzz", side_effect=mock_narrow), \
         patch("harness.orchestrator.control_gate.await_decision", return_value="accept"), \
         patch("harness.orchestrator.time.sleep", side_effect=_StopLoop):
        try:
            orch.run_pipeline(config, state_dir)
        except _StopLoop:
            # loop completed one full (non-refused) iteration and looped back
            pass
        except RuntimeError as exc:
            raised = exc

    return raised, embedded_calls, narrow_calls


def test_orch_external_sandbox_off_refuses(pipeline_state_dir, pipeline_config, tmp_path):
    """RED on HEAD, GREEN after fix. External target + sandbox OFF -> run_pipeline
    MUST raise the FLAG2_EMBEDDED_FUZZ refusal and MUST NOT invoke the runners."""
    ext = tmp_path / "external_target_repo"
    ext.mkdir()
    assert _target_is_self(str(ext)) is False
    pipeline_config["agent_sandbox"] = {"bwrap": False}

    raised, embedded_calls, narrow_calls = _drive_run_pipeline(
        pipeline_config, pipeline_state_dir, _make_task(str(ext)))

    assert raised is not None, (
        "external target + sandbox-OFF MUST raise (fail-closed); on HEAD the missing "
        "gate lets the candidate reach the unjailed embedded/narrow runner. "
        f"embedded_calls={embedded_calls!r} narrow_calls={narrow_calls!r}"
    )
    assert "FLAG2_EMBEDDED_FUZZ" in str(raised) or "refus" in str(raised).lower(), (
        f"refusal RuntimeError must be the FLAG2_EMBEDDED_FUZZ gate, got: {raised!r}"
    )
    assert embedded_calls == [] and narrow_calls == [], (
        "NO embedded/narrow runner may execute the external candidate when sandbox is "
        f"off. embedded={embedded_calls!r} narrow={narrow_calls!r}"
    )


def test_orch_self_sandbox_off_not_refused(pipeline_state_dir, pipeline_config):
    """Negative control / inert-for-self: working_dir absent -> _target_is_self(None)
    == True -> gate is a no-op -> embedded + narrow runners ARE invoked (then the loop
    tail terminates via _StopLoop)."""
    pipeline_config["agent_sandbox"] = {"bwrap": False}
    raised, embedded_calls, narrow_calls = _drive_run_pipeline(
        pipeline_config, pipeline_state_dir, _make_task(None))

    assert raised is None, f"self path must NOT be refused; got: {raised!r}"
    assert len(embedded_calls) == 1, f"self embedded gate not reached: {embedded_calls!r}"
    assert len(narrow_calls) == 1, f"self narrow gate not reached: {narrow_calls!r}"


def test_orch_external_sandbox_on_not_refused(pipeline_state_dir, pipeline_config, tmp_path):
    """Negative control: external target but sandbox ON -> NOT refused (runs jailed),
    runners ARE invoked."""
    ext = tmp_path / "external_target_repo"
    ext.mkdir()
    pipeline_config["agent_sandbox"] = {"bwrap": True}
    raised, embedded_calls, narrow_calls = _drive_run_pipeline(
        pipeline_config, pipeline_state_dir, _make_task(str(ext)))

    assert raised is None, f"sandbox-ON external must NOT be refused; got: {raised!r}"
    assert len(embedded_calls) == 1, f"sandbox-ON embedded gate not reached: {embedded_calls!r}"
    assert len(narrow_calls) == 1, f"sandbox-ON narrow gate not reached: {narrow_calls!r}"


# ── WORKER PATH (harness/orchestrator_worker.py::main) ───────────────────────

def _drive_worker(state_dir, task, *, bwrap, monkeypatch):
    """Drive orchestrator_worker.main() spawn-free for one task.

    Returns (return_code, embedded_calls, narrow_calls). The worker's broad
    ``except Exception`` converts a gate RuntimeError into exit_code 2."""
    task_id = task["task_id"]
    (state_dir / "tasks" / f"{task_id}.json").write_text(json.dumps(task), encoding="utf-8")

    monkeypatch.setenv("JANUSMASK_AGENT_WORKROOT", str(state_dir / "wr"))
    monkeypatch.setattr(
        sys, "argv",
        ["orchestrator_worker", "--state-dir", str(state_dir), "--task-id", task_id],
    )
    monkeypatch.setattr(orch, "load_config", lambda *a, **k: _worker_cfg(bwrap=bwrap))
    monkeypatch.setattr(orch, "run_both_agents",
                        lambda *a, **k: ("def f():\n    return 1\n", "def g():\n    return 2\n"))
    monkeypatch.setattr(orch, "_validate_submission", lambda *a, **k: (True, []))
    monkeypatch.setattr(orch, "_auto_commit_accepted", lambda *a, **k: True)
    monkeypatch.setattr(orch, "_save_final_output", lambda *a, **k: None)
    monkeypatch.setattr(orch, "_clear_stale_submissions", lambda *a, **k: None)
    monkeypatch.setattr(orch, "smoke_import", lambda *a, **k: None)
    monkeypatch.setattr(ow, "_precompute_baseline_test_results", lambda *a, **k: None)
    monkeypatch.setattr(ow, "_detect_and_append_untracked_tests", lambda *a, **k: None)

    embedded_calls, narrow_calls = [], []

    def mock_embedded(*a, **k):
        embedded_calls.append(a)
        return None

    def mock_narrow(*a, **k):
        narrow_calls.append(a)
        return None

    monkeypatch.setattr("harness.embedded_test_runner.run_embedded_tests", mock_embedded)
    monkeypatch.setattr("harness.narrow_fuzz.run_narrow_fuzz", mock_narrow)

    rc = ow.main()
    return rc, embedded_calls, narrow_calls


def test_worker_external_sandbox_off_refuses(pipeline_state_dir, tmp_path, monkeypatch):
    """RED on HEAD, GREEN after fix. Worker + external + sandbox OFF -> the gate raises,
    the broad except returns exit_code 2, and NO runner executes the candidate."""
    ext = tmp_path / "external_target_repo"
    ext.mkdir()
    assert _target_is_self(str(ext)) is False

    task = _make_task(str(ext))
    task["task_id"] = "flag2_worker_external"
    rc, embedded_calls, narrow_calls = _drive_worker(
        pipeline_state_dir, task, bwrap=False, monkeypatch=monkeypatch)

    assert rc == 2, (
        "worker external + sandbox-OFF MUST fail closed (exit 2 via the gate refusal); "
        f"on HEAD it accepts (rc=0). embedded={embedded_calls!r} narrow={narrow_calls!r}"
    )
    assert embedded_calls == [] and narrow_calls == [], (
        f"no runner may execute the external candidate. embedded={embedded_calls!r} narrow={narrow_calls!r}"
    )


def test_worker_self_sandbox_off_not_refused(pipeline_state_dir, monkeypatch):
    """Negative control: worker + self + sandbox OFF -> accepted (rc 0), runners invoked."""
    task = _make_task(None)
    task["task_id"] = "flag2_worker_self"
    rc, embedded_calls, narrow_calls = _drive_worker(
        pipeline_state_dir, task, bwrap=False, monkeypatch=monkeypatch)

    assert rc == 0, f"self worker path must accept (rc 0); got rc={rc}"
    assert len(embedded_calls) == 1, f"self embedded gate not reached: {embedded_calls!r}"
    assert len(narrow_calls) == 1, f"self narrow gate not reached: {narrow_calls!r}"
