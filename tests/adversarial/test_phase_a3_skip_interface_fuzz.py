"""Oracle for Phase A.3 — decouple interface-fuzz skipping from BYPASS_FUZZER_TYPES.

DESIGN UNDER TEST (A.3, locked):
    The differential fuzzer (``fuzz_from_task``) is currently skipped only when
    ``mtt in BYPASS_FUZZER_TYPES``. A.3 makes the run ALSO take the bypass branch
    when the ``META_TASK_POLICY`` entry for the task's meta_task_type carries
    ``skip_interface_fuzz=True``. The canonical such type is ``'test_authoring'``,
    which on HEAD has ``bypass_fuzzer=False`` (so it is NOT in BYPASS_FUZZER_TYPES)
    but ``skip_interface_fuzz=True``.

    Guard (orchestrator.run_pipeline ~:2040, orchestrator_worker.main ~:320) becomes::

        _skip_ifz = META_TASK_POLICY.get(mtt or '', {}).get('skip_interface_fuzz')
        if mtt in BYPASS_FUZZER_TYPES or _skip_ifz:
            ...                       # bypass: NO fuzz_from_task, straight to commit gate
        ...
        # inner smoke/embedded/narrow gate also gated by "and not _skip_ifz"

NET OBSERVABLE EFFECT this oracle pins:
    For meta_task_type='test_authoring' the run takes the BYPASS branch ->
    ``fuzz_from_task`` is NOT called and phase 'fuzzing' is NOT entered.

    * HEAD (no A.3): test_authoring is not in BYPASS_FUZZER_TYPES and the guard
      ignores skip_interface_fuzz, so the ELSE branch runs -> phase 'fuzzing' is
      set and ``fuzz_from_task`` IS called. The discriminating asserts FAIL.
    * After A.3: the bypass branch runs -> ``fuzz_from_task`` is NOT called and
      phase 'fuzzing' is never entered. The discriminating asserts PASS.

STRATEGY / reuse:
    Reuses the ``TestPipelineStateTransitions`` harness in tests/test_orchestrator.py
    (O-42 ``test_valid_submissions_to_fuzzing`` / O-43 ``test_equivalent_fuzz_accepted``):
    drive ``harness.orchestrator.run_pipeline`` with ``run_both_agents``,
    ``_validate_submission`` and ``fuzz_from_task`` monkeypatched, terminate the
    forever-loop by raising StopIteration from a patched ``time.sleep`` after one
    task, and observe ``set_phase`` via a tracking wrapper. The smoke/embedded/
    narrow gate functions and ``_auto_commit_accepted`` are patched so BOTH the
    HEAD (fuzz) path and the post-A.3 (bypass) path complete cleanly without
    spawning any real agents -- everything is monkeypatched/faked.

    NO real agent is spawned: run_both_agents is fully mocked.
"""

import json

import pytest
from unittest.mock import patch

from harness.orchestrator import run_pipeline, init_state
from harness.diff_fuzzer import FuzzResult
from harness.planner.taxonomies import BYPASS_FUZZER_TYPES, META_TASK_POLICY


# ── Fixtures (mirrors tests/test_orchestrator.py::TestPipelineStateTransitions) ──

@pytest.fixture
def pipeline_config():
    return {
        "synthesis": {"timeout_seconds": 30, "max_ast_retries": 3},
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
    }


@pytest.fixture
def pipeline_state_dir(tmp_path):
    for sub in ("tasks", "tasks/processed", "sessions"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    init_state(tmp_path)
    return tmp_path


def _test_authoring_task():
    """A task that exercises the skip_interface_fuzz path under A.3.

    meta_task_type='test_authoring' is, on HEAD, NOT in BYPASS_FUZZER_TYPES
    but DOES carry skip_interface_fuzz=True.
    """
    return {
        "task_id": "ta-1",
        "specification": "Author a test for foo().",
        "constraints": {"deterministic": True},
        "meta_task_type": "test_authoring",
        "verification_command": "true",
    }


def _drive_pipeline(config, state_dir, mock_fuzz):
    """Run one pipeline iteration for a test_authoring task and return
    (phases_seen, gate_calls). All side-effecting collaborators are faked."""
    phases_seen = []
    import harness.orchestrator as orch
    original_set_phase = orch.set_phase

    def tracking_set_phase(sd, *, phase):
        phases_seen.append(phase)
        return original_set_phase(sd, phase=phase)

    call_count = [0]

    def mock_get_next_task(sd):
        call_count[0] += 1
        if call_count[0] == 1:
            return _test_authoring_task()
        return None

    gate_calls = {"smoke": 0, "embedded": 0, "narrow": 0}

    def rec_smoke(*a, **k):
        gate_calls["smoke"] += 1
        return None

    def rec_embedded(*a, **k):
        gate_calls["embedded"] += 1
        return None

    def rec_narrow(*a, **k):
        gate_calls["narrow"] += 1
        return None

    with patch("harness.orchestrator.run_both_agents",
               return_value=("def f(): pass", "def g(): pass")), \
         patch("harness.orchestrator._validate_submission", return_value=(True, [])), \
         patch("harness.orchestrator.set_phase", side_effect=tracking_set_phase), \
         patch("harness.orchestrator.get_next_task", side_effect=mock_get_next_task), \
         patch("harness.orchestrator._auto_commit_accepted", return_value=True), \
         patch("harness.orchestrator.smoke_import", side_effect=rec_smoke), \
         patch("harness.orchestrator.run_embedded_tests", side_effect=rec_embedded), \
         patch("harness.orchestrator.run_narrow_fuzz", side_effect=rec_narrow), \
         patch("harness.orchestrator.time.sleep", side_effect=StopIteration):
        with pytest.raises(StopIteration):
            run_pipeline(config, state_dir)

    return phases_seen, gate_calls


# ── Preconditions (not detectors; document the HEAD taxonomy state) ──────────

def test_precondition_test_authoring_not_in_bypass_but_has_skip_flag():
    """The whole point of A.3: test_authoring is NOT bypass-eligible the old way
    but IS flagged skip_interface_fuzz. If this changes, the detector below is moot."""
    assert "test_authoring" not in BYPASS_FUZZER_TYPES, (
        "test_authoring is in BYPASS_FUZZER_TYPES -- the old guard already bypasses "
        "it, so this A.3 oracle no longer discriminates."
    )
    assert META_TASK_POLICY.get("test_authoring", {}).get("skip_interface_fuzz") is True, (
        "test_authoring must carry skip_interface_fuzz=True for A.3 to apply."
    )


# ── PRIMARY DISCRIMINATING DETECTOR (behavioural) ───────────────────────────

def test_test_authoring_does_not_enter_differential_fuzzer(
        pipeline_state_dir, pipeline_config):
    """A.3 detector: for meta_task_type='test_authoring' the run must take the
    bypass branch -- fuzz_from_task is NOT called and phase 'fuzzing' is never set.

    FAILS on HEAD (test_authoring falls through to the fuzzing branch -> fuzz IS
    called / 'fuzzing' IS entered). PASSES after A.3.
    """
    with patch("harness.orchestrator.fuzz_from_task") as mock_fuzz:
        mock_fuzz.return_value = FuzzResult(
            equivalent=True, total_inputs=100, matching_inputs=100)
        phases_seen, _ = _drive_pipeline(
            pipeline_config, pipeline_state_dir, mock_fuzz)

        # Primary behavioural assertions -- the discriminator.
        mock_fuzz.assert_not_called()
        assert "fuzzing" not in phases_seen, (
            f"test_authoring entered the 'fuzzing' phase; phases={phases_seen}"
        )

    # The task should still reach a terminal accept via the bypass commit gate.
    assert "accepted" in phases_seen, (
        f"test_authoring did not reach 'accepted' via bypass; phases={phases_seen}"
    )


# ── SECONDARY behavioural complement (smoke/embedded/narrow gate skipped) ────

def test_test_authoring_skips_smoke_embedded_narrow_gates(
        pipeline_state_dir, pipeline_config):
    """Complement to the primary detector: under A.3, skip_interface_fuzz also
    suppresses the inner smoke_import / run_embedded_tests / run_narrow_fuzz gate
    (the '... and not _skip_ifz' change), since a test-authoring submission has
    no implementation interface to smoke.

    On HEAD this also fails: test_authoring goes to the fuzzing branch which does
    not call these gate functions either, so naively this would PASS on HEAD too.
    Therefore this is explicitly NOT the sole detector -- it is asserted only as
    a coherence complement to the primary fuzz-not-called detector above. We keep
    it lenient (do not over-constrain HEAD) and only assert the gates are not run.
    """
    with patch("harness.orchestrator.fuzz_from_task") as mock_fuzz:
        mock_fuzz.return_value = FuzzResult(
            equivalent=True, total_inputs=100, matching_inputs=100)
        _, gate_calls = _drive_pipeline(
            pipeline_config, pipeline_state_dir, mock_fuzz)

    assert gate_calls["smoke"] == 0, f"smoke_import was invoked: {gate_calls}"
    assert gate_calls["embedded"] == 0, f"run_embedded_tests was invoked: {gate_calls}"
    assert gate_calls["narrow"] == 0, f"run_narrow_fuzz was invoked: {gate_calls}"


def test_worker_path_test_authoring_skips_interface_fuzz_and_embedded(
        pipeline_state_dir, monkeypatch):
    """Pins the WORKER path (orchestrator_worker.main, guard ~:319), which is the
    sibling of the orchestrator-path detectors above.

    WHY IT EXISTS:
        Audit finding V8-B — the orchestrator-path tests would go green after
        fixing only orchestrator.py while the worker guard stays broken.
        This test keeps the oracle RED until the WORKER guard in orchestrator_worker.py
        is also patched.

    SEAM:
        It drives full `orchestrator_worker.main()` spawn-free (run_both_agents mocked),
        because the guard lives inline in main() and there is no smaller public entry
        that contains it.

    MONKEYPATCH-AT-SOURCE-MODULE:
        `fuzz_from_task` and `run_embedded_tests` are imported function-locally
        inside main(), so they are patched on `harness.diff_fuzzer` and
        `harness.embedded_test_runner`, NOT on the worker module.

    EXPECTATION:
        RED-on-HEAD (worker guard ignores skip_interface_fuzz, falling through to the
        else branch where fuzz_from_task IS called) and GREEN-after-A.3 (bypass branch
        is taken, skipping both differential fuzzer and embedded test runner).
    """
    import sys
    import os
    import harness.orchestrator as orch
    import harness.orchestrator_worker as ow

    # Create worker output directory under pipeline_state_dir
    (pipeline_state_dir / "output").mkdir(parents=True, exist_ok=True)

    # Prepare the worker task definition
    task_id = "ta_worker_a3"
    task = {
        "task_id": task_id,
        "specification": "Author a test for foo().",
        "constraints": {"deterministic": True},
        "meta_task_type": "test_authoring",
        "verification_command": "true",
        "files_touched": [],
        "dependencies": [],
    }

    # Write the task description JSON
    task_file = pipeline_state_dir / "tasks" / f"{task_id}.json"
    task_file.write_text(json.dumps(task), encoding="utf-8")

    # Set up command line arguments and environment variables
    monkeypatch.setenv("JANUSMASK_AGENT_WORKROOT", str(pipeline_state_dir / "wr"))
    monkeypatch.setattr(
        sys, "argv",
        ["orchestrator_worker", "--state-dir", str(pipeline_state_dir), "--task-id", task_id]
    )

    # Load mock config
    cfg = {
        "synthesis": {
            "timeout_seconds": 600,
            "max_ast_retries": 3,
            "antigravity_mode": False,
            "use_retry_module": False,
            "active_agents": ["claude", "gemini"]
        },
        "cross_examination": {"max_rounds": 1},
        "decomposition": {"max_depth": 3},
        "fuzzing": {"float_tolerance": 1e-9}
    }
    monkeypatch.setattr(orch, "load_config", lambda *a, **k: cfg)

    # Mock agent execution and validation to avoid real runs
    monkeypatch.setattr(
        orch, "run_both_agents",
        lambda *a, **k: ("def f():\n    return 1\n", "def g():\n    return 2\n")
    )
    monkeypatch.setattr(orch, "_validate_submission", lambda *a, **k: (True, []))
    monkeypatch.setattr(orch, "_auto_commit_accepted", lambda *a, **k: True)
    monkeypatch.setattr(orch, "_save_final_output", lambda *a, **k: None)
    monkeypatch.setattr(orch, "_clear_stale_submissions", lambda *a, **k: None)

    # Mock precomputing baseline results and detect untracked tests
    monkeypatch.setattr(ow, "_precompute_baseline_test_results", lambda *a, **k: None)
    monkeypatch.setattr(ow, "_detect_and_append_untracked_tests", lambda *a, **k: None)

    # Set up mock call recorders for the fuzzer and embedded test runner
    fuzz_calls = []
    def mock_fuzz_from_task(*a, **k):
        fuzz_calls.append((a, k))
        return FuzzResult(equivalent=True, total_inputs=1, matching_inputs=1)

    embedded_calls = []
    def mock_run_embedded_tests(*a, **k):
        embedded_calls.append((a, k))
        return None

    # Patch at source modules because of local imports in orchestrator_worker.main
    monkeypatch.setattr("harness.diff_fuzzer.fuzz_from_task", mock_fuzz_from_task)
    monkeypatch.setattr("harness.embedded_test_runner.run_embedded_tests", mock_run_embedded_tests)

    # Call main() and capture the return code
    rc = ow.main()

    # The assertions: fuzzer and embedded runner must not be called, and optionally accept code 0 is returned
    assert len(fuzz_calls) == 0, f"fuzz_from_task was called {len(fuzz_calls)} times, but should be skipped"
    assert len(embedded_calls) == 0, f"run_embedded_tests was called {len(embedded_calls)} times, but should be skipped"
    assert rc == 0, f"Expected worker to return exit code 0 (accept), got {rc}"
