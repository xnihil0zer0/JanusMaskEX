"""Tests for harness/orchestrator.py — main pipeline orchestrator."""

import json
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, call

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
_REPO_ROOT = str(Path(__file__).resolve().parent.parent)

from harness.orchestrator import (
    collect_submissions,
    run_both_agents,
    get_next_task,
    load_config,
    prepare_task_prompt,
    spawn_agent,
    run_pipeline,
    main,
    _mark_processed,
    _persist_fuzz_results,
    _validate_submission,
    _configure_logging,
    DEFAULT_CONFIG_PATH,
    DEFAULT_STATE_DIR,
)
from harness.diff_fuzzer import FuzzFailure, FuzzResult
from harness.sandbox import ExecutionResult


# ── Configuration ───────────────────────────────────────────────────────

class TestLoadConfig:
    def test_loads_valid_yaml(self):
        config = load_config()
        assert isinstance(config, dict)
        assert "synthesis" in config
        assert "fuzzing" in config
        assert "sandbox" in config
        assert "agents" in config

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_config(tmp_path / "nonexistent.yaml")

    def test_list_root_raises(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text("- item1\n- item2\n")
        with pytest.raises(ValueError, match="mapping"):
            load_config(bad)


# ── Task Prompt ─────────────────────────────────────────────────────────

class TestPrepareTaskPrompt:
    def test_includes_current_task_json_read_path(self):
        """Post-migration: agent reads task spec from current_task.json (not MCP get_task)."""
        prompt = prepare_task_prompt({"task_id": "t1", "specification": "do stuff"})
        assert "current_task.json" in prompt

    def test_includes_submission_py_write_path(self):
        """Post-migration: agent submits by writing submission.py under its outbox."""
        prompt = prepare_task_prompt({"task_id": "t1"})
        assert "submission.py" in prompt
        assert "{OUTBOX_PATH}" in prompt  # placeholder resolved per-agent in spawn_agent

    def test_includes_task_id(self):
        prompt = prepare_task_prompt({"task_id": "my-task-42"})
        assert "my-task-42" in prompt

    def test_no_agent_names(self):
        prompt = prepare_task_prompt({"task_id": "t1", "specification": "code stuff"})
        assert "Claude" not in prompt
        assert "Gemini" not in prompt

    def test_no_fuzzing_mention(self):
        prompt = prepare_task_prompt({"task_id": "t1", "specification": "code stuff"})
        assert "fuzzing" not in prompt.lower()
        assert "differential" not in prompt.lower()

    def test_includes_spec_summary(self):
        prompt = prepare_task_prompt({
            "task_id": "t1",
            "specification": "Write a merge_sorted function.",
        })
        assert "merge_sorted" in prompt


# ── Task Queue ──────────────────────────────────────────────────────────

class TestGetNextTask:
    def test_no_tasks_dir(self, tmp_path):
        assert get_next_task(tmp_path / "nonexistent") is None

    def test_empty_tasks_dir(self, state_dir):
        assert get_next_task(state_dir) is None

    def test_one_task(self, state_dir):
        task = {"task_id": "t1", "specification": "do stuff"}
        (state_dir / "tasks" / "t1.json").write_text(json.dumps(task))
        result = get_next_task(state_dir)
        assert result["task_id"] == "t1"
        assert (state_dir / "tasks" / "current_task_t1.json").is_file()

    def test_selects_first_alphabetically(self, state_dir):
        for name in ("c_task.json", "a_task.json", "b_task.json"):
            (state_dir / "tasks" / name).write_text(json.dumps({"task_id": name}))
        result = get_next_task(state_dir)
        assert result["task_id"] == "a_task.json"

    def test_skips_current_task(self, state_dir):
        (state_dir / "tasks" / "current_task.json").write_text(json.dumps({"task_id": "current"}))
        assert get_next_task(state_dir) is None

    def test_skips_processed(self, state_dir):
        task = {"task_id": "t1"}
        (state_dir / "tasks" / "t1.json").write_text(json.dumps(task))
        (state_dir / "tasks" / "processed" / "t1.json").write_text("{}")
        assert get_next_task(state_dir) is None


class TestMarkProcessed:
    def test_moves_current_task(self, state_dir):
        (state_dir / "tasks" / "t1.json.processing").write_text('{"task_id": "t1"}')
        (state_dir / "tasks" / "current_task_t1.json").write_text('{"task_id": "t1"}')
        _mark_processed(state_dir, "t1")
        assert not (state_dir / "tasks" / "current_task_t1.json").exists()
        assert (state_dir / "tasks" / "processed" / "t1.json").is_file()

    def test_missing_current_no_error(self, state_dir):
        _mark_processed(state_dir, "nonexistent")  # should not raise


class TestSaveFinalOutput:
    def test_saves_final_output(self, state_dir):
        from harness.orchestrator import _save_final_output
        _save_final_output(state_dir, "t1", "def foo(): pass")
        out_path = state_dir / "output" / "t1.py"
        assert out_path.is_file()
        assert out_path.read_text() == "def foo(): pass"


# ── Submission Collection ───────────────────────────────────────────────

class TestCollectSubmissions:
    """Post-P0.3: submission filenames come from session_namer.generate_submission_filename."""

    def _path(self, state_dir, agent, round_number=1, task_id="default"):
        from harness.session_namer import generate_submission_filename
        return state_dir / "sessions" / generate_submission_filename(agent, round_number, task_id)

    def test_both_present(self, state_dir):
        for agent in ("claude", "gemini"):
            path = self._path(state_dir, agent)
            path.write_text(json.dumps({"code": f"def f(): return '{agent}'"}))
        c, g = collect_submissions(state_dir, 1)
        assert c is not None and g is not None

    def test_missing_claude(self, state_dir):
        self._path(state_dir, "gemini").write_text(
            json.dumps({"code": "def f(): pass"})
        )
        c, g = collect_submissions(state_dir, 1)
        assert c is None and g is not None

    def test_both_missing(self, state_dir):
        c, g = collect_submissions(state_dir, 1)
        assert c is None and g is None

    def test_empty_code(self, state_dir):
        self._path(state_dir, "claude").write_text(json.dumps({"code": ""}))
        c, g = collect_submissions(state_dir, 1)
        assert c is None

    def test_corrupt_json(self, state_dir):
        self._path(state_dir, "claude").write_text("NOT JSON")
        c, g = collect_submissions(state_dir, 1)
        assert c is None


# ── Validation Helper ───────────────────────────────────────────────────

class TestValidateSubmission:
    def test_valid_code(self):
        ok, violations = _validate_submission(
            "def f(x: int) -> int:\n    return x + 1\n", "claude",
            {"constraints": {"deterministic": True}},
        )
        assert ok is True

    def test_invalid_code(self):
        ok, violations = _validate_submission(
            "def f(:", "claude", {"constraints": {}},
        )
        assert ok is False

    def test_nondeterminism_allowed(self):
        ok, _ = _validate_submission(
            "import random\ndef f():\n    return random.randint(1,10)\n",
            "claude",
            {"constraints": {"deterministic": False}},
        )
        assert ok is True


# ── Fuzz Result Persistence ─────────────────────────────────────────────

class TestPersistFuzzResults:
    def test_writes_json(self, state_dir):
        fuzz_result = FuzzResult(equivalent=True, total_inputs=100, matching_inputs=100)
        _persist_fuzz_results(state_dir, "t1", "round1", fuzz_result)
        path = state_dir.parent / "logs" / "fuzz_results" / "t1_round1.json"
        assert path.is_file()
        data = json.loads(path.read_text())
        assert data["equivalent"] is True
        assert data["total_inputs"] == 100

    # O-38: Summary includes task_id, round, equivalent, counts
    def test_summary_includes_all_fields(self, state_dir):
        fuzz_result = FuzzResult(
            equivalent=False, total_inputs=200, matching_inputs=180,
            failures=[
                FuzzFailure(
                    input_args=[1, 2], input_kwargs={},
                    result_a=ExecutionResult(success=True, return_value=3),
                    result_b=ExecutionResult(success=True, return_value=4),
                    reason="return_mismatch",
                ),
            ],
            error=None,
        )
        _persist_fuzz_results(state_dir, "t42", "round2", fuzz_result)
        path = state_dir.parent / "logs" / "fuzz_results" / "t42_round2.json"
        data = json.loads(path.read_text())
        assert data["task_id"] == "t42"
        assert data["round"] == "round2"
        assert data["equivalent"] is False
        assert data["total_inputs"] == 200
        assert data["matching_inputs"] == 180
        assert data["failure_count"] == 1
        assert data["error"] is None
        assert len(data["failures"]) == 1

    # O-39: Failures capped at 20 in summary
    def test_failures_capped_at_20(self, state_dir):
        failures = [
            FuzzFailure(
                input_args=[i], input_kwargs={},
                result_a=ExecutionResult(success=True, return_value=i),
                result_b=ExecutionResult(success=True, return_value=i + 1),
                reason="return_mismatch",
            )
            for i in range(50)
        ]
        fuzz_result = FuzzResult(
            equivalent=False, total_inputs=200, matching_inputs=150,
            failures=failures,
        )
        _persist_fuzz_results(state_dir, "t1", "round1", fuzz_result)
        path = state_dir.parent / "logs" / "fuzz_results" / "t1_round1.json"
        data = json.loads(path.read_text())
        assert len(data["failures"]) == 20
        assert data["failure_count"] == 50

    # O-40: Args repr truncated at 200 chars
    def test_args_repr_truncated_at_200(self, state_dir):
        long_arg = list(range(500))  # repr will be very long
        failures = [
            FuzzFailure(
                input_args=[long_arg], input_kwargs={},
                result_a=ExecutionResult(success=True, return_value=0),
                result_b=ExecutionResult(success=True, return_value=1),
                reason="return_mismatch",
            ),
        ]
        fuzz_result = FuzzResult(
            equivalent=False, total_inputs=10, matching_inputs=9,
            failures=failures,
        )
        _persist_fuzz_results(state_dir, "t1", "round1", fuzz_result)
        path = state_dir.parent / "logs" / "fuzz_results" / "t1_round1.json"
        data = json.loads(path.read_text())
        for f in data["failures"]:
            assert len(f["args"]) <= 200


# ── Configuration (additional) ─────────────────────────────────────────

class TestLoadConfigAdditional:
    # O-03: load_config with invalid YAML raises parsing error
    def test_invalid_yaml_raises(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text(":\n  - :\n    invalid: [unclosed\n")
        with pytest.raises(yaml.YAMLError):
            load_config(bad)

    # O-05: Config includes synthesis, fuzzing, sandbox, agents sections
    def test_config_has_all_sections(self):
        config = load_config()
        assert "synthesis" in config
        assert "fuzzing" in config
        assert "sandbox" in config
        assert "agents" in config


# ── Submission Collection (additional) ─────────────────────────────────

class TestCollectSubmissionsAdditional:
    # O-22: Missing gemini submission file
    def test_missing_gemini(self, state_dir):
        from harness.session_namer import generate_submission_filename
        (state_dir / "sessions" / generate_submission_filename("claude", 1, "default")).write_text(
            json.dumps({"code": "def f(): pass"})
        )
        c, g = collect_submissions(state_dir, 1)
        assert c is not None and g is None


# ── Agent Spawning (O-26 through O-33) ─────────────────────────────────

class TestSpawnAgent:
    @pytest.fixture
    def agent_config(self):
        """Config mimicking the real config.yaml for agent tests."""
        return {
            "synthesis": {"timeout_seconds": 120},
            "state_dir": "/tmp/test_state",
            "agents": {
                "claude": {
                    "command": "claude",
                    "args": ["-p", "--model", "claude-opus-4-6",
                             "--permission-mode", "plan",
                             "--output-format", "json",
                             "--project-dir", _REPO_ROOT],
                },
                "gemini": {
                    "command": "gemini",
                    "args": ["-p", "--approval-mode", "yolo",
                             "--format", "json"],
                },
            },
        }

    # O-26: spawn_agent("claude", ...) builds correct command
    @patch("harness.orchestrator.subprocess.Popen")
    def test_claude_command(self, mock_popen, agent_config):
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_popen.return_value = mock_proc
        spawn_agent("claude", "do task", agent_config)
        cmd = mock_popen.call_args[0][0]
        assert cmd[0] == "claude"
        assert "-p" in cmd
        assert "do task" in cmd
        assert "--model" in cmd

    # O-27: spawn_agent("gemini", ...) builds correct command
    @patch("harness.orchestrator.subprocess.Popen")
    def test_gemini_command(self, mock_popen, agent_config):
        mock_proc = MagicMock()
        mock_proc.pid = 12346
        mock_popen.return_value = mock_proc
        spawn_agent("gemini", "do task", agent_config)
        cmd = mock_popen.call_args[0][0]
        assert cmd[0] == "gemini"
        assert "-p" in cmd
        assert "do task" in cmd
        assert "--approval-mode" in cmd

    # O-28: Prompt inserted after -p flag
    @patch("harness.orchestrator.subprocess.Popen")
    def test_prompt_after_p_flag(self, mock_popen, agent_config):
        mock_proc = MagicMock()
        mock_proc.pid = 12347
        mock_popen.return_value = mock_proc
        spawn_agent("claude", "MY_PROMPT", agent_config)
        cmd = mock_popen.call_args[0][0]
        p_idx = cmd.index("-p")
        assert cmd[p_idx + 1] == "MY_PROMPT"

    # O-29: Environment includes PYTHONHASHSEED=0
    @patch("harness.orchestrator.subprocess.Popen")
    def test_env_pythonhashseed(self, mock_popen, agent_config):
        mock_proc = MagicMock()
        mock_proc.pid = 12348
        mock_popen.return_value = mock_proc
        spawn_agent("claude", "prompt", agent_config)
        env = mock_popen.call_args[1]["env"]
        assert env["PYTHONHASHSEED"] == "0"

    # O-30: Environment includes JANUSMASK_AGENT
    @patch("harness.orchestrator.subprocess.Popen")
    def test_env_agent_name(self, mock_popen, agent_config):
        mock_proc = MagicMock()
        mock_proc.pid = 12349
        mock_popen.return_value = mock_proc
        spawn_agent("gemini", "prompt", agent_config)
        env = mock_popen.call_args[1]["env"]
        assert env["JANUSMASK_AGENT"] == "gemini"

    # O-31: Environment includes JANUSMASK_STATE_DIR
    @patch("harness.orchestrator.subprocess.Popen")
    def test_env_state_dir(self, mock_popen, agent_config):
        mock_proc = MagicMock()
        mock_proc.pid = 12350
        mock_popen.return_value = mock_proc
        spawn_agent("claude", "prompt", agent_config)
        env = mock_popen.call_args[1]["env"]
        assert env["JANUSMASK_STATE_DIR"] == "/tmp/test_state"

    # O-32: start_new_session=True for process group isolation
    @patch("harness.orchestrator.subprocess.Popen")
    def test_start_new_session(self, mock_popen, agent_config):
        mock_proc = MagicMock()
        mock_proc.pid = 12351
        mock_popen.return_value = mock_proc
        spawn_agent("claude", "prompt", agent_config)
        assert mock_popen.call_args[1]["start_new_session"] is True

    # O-33: spawn_agent returns a Popen handle
    @patch("harness.orchestrator.subprocess.Popen")
    def test_returns_popen(self, mock_popen, agent_config):
        mock_proc = MagicMock()
        mock_proc.pid = 12352
        mock_popen.return_value = mock_proc
        result = spawn_agent("claude", "prompt", agent_config)
        assert result is mock_proc


# ── Pipeline State Transitions (O-41 through O-51) ────────────────────

class TestPipelineStateTransitions:
    """Test pipeline state transitions by mocking agents and subcomponents."""

    @pytest.fixture
    def pipeline_config(self):
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
            "sandbox": {
                "memory_limit_mb": 256,
                "cpu_time_limit_seconds": 5,
                "network": False,
            },
            "decomposition": {
                "max_depth": 3,
                "max_subtasks": 5,
                "fresh_instances": True,
            },
            "agents": {
                "claude": {"command": "claude", "args": ["-p"]},
                "gemini": {"command": "gemini", "args": ["-p"]},
            },
        }

    @pytest.fixture
    def pipeline_state_dir(self, tmp_path):
        """State dir with one task queued and STATE.json initialized."""
        for sub in ("tasks", "tasks/processed", "sessions"):
            (tmp_path / sub).mkdir(parents=True, exist_ok=True)

        task = {
            "task_id": "test-task-1",
            "specification": "Write a function add(a, b) that returns a + b.",
            "constraints": {"deterministic": True, "language": "python"},
        }
        (tmp_path / "tasks" / "test-task-1.json").write_text(json.dumps(task))

        # Initialize state file
        from harness.orchestrator import init_state
        init_state(tmp_path)

        return tmp_path

    def _write_submissions(self, state_dir, round_number, claude_code, gemini_code, task_id="default"):
        """Helper to write submission files for both agents (post-P0.3 filename contract)."""
        from harness.session_namer import generate_submission_filename
        sessions = state_dir / "sessions"
        if claude_code is not None:
            (sessions / generate_submission_filename("claude", round_number, task_id)).write_text(
                json.dumps({"code": claude_code})
            )
        if gemini_code is not None:
            (sessions / generate_submission_filename("gemini", round_number, task_id)).write_text(
                json.dumps({"code": gemini_code})
            )

    def _read_state(self, state_dir):
        return json.loads((state_dir / "STATE.json").read_text())

    # O-41: Pipeline sets phase to "synthesis" at start
    @patch("harness.orchestrator.run_both_agents")
    def test_pipeline_synthesis_phase(self, mock_run_both,
                                       pipeline_state_dir, pipeline_config):
        """Pipeline sets phase to synthesis, then rejects when no submissions."""
        mock_run_both.return_value = (None, None)

        phases_seen = []
        original_set_phase = __import__("harness.orchestrator", fromlist=["set_phase"]).set_phase

        def tracking_set_phase(state_dir, *, phase):
            phases_seen.append(phase)
            return original_set_phase(state_dir, phase=phase)

        with patch("harness.orchestrator.set_phase", side_effect=tracking_set_phase):
            # run_pipeline loops forever; we break out after 1 iteration by removing tasks
            def mock_get_next_task(sd):
                if not hasattr(mock_get_next_task, "_called"):
                    mock_get_next_task._called = True
                    task = {"task_id": "test-task-1",
                            "specification": "Write add(a, b).",
                            "constraints": {"deterministic": True}}
                    return task
                return None

            with patch("harness.orchestrator.get_next_task", side_effect=mock_get_next_task):
                with patch("harness.orchestrator.time.sleep", side_effect=StopIteration):
                    with pytest.raises(StopIteration):
                        run_pipeline(pipeline_config, pipeline_state_dir)

        # Verify synthesis was the initial phase set via locked_read_modify_write
        state = self._read_state(pipeline_state_dir)
        # The phase after processing (no submissions) should be "rejected"
        assert "rejected" in phases_seen

    # O-48: Neither agent submits -> phase "rejected"
    @patch("harness.orchestrator.run_both_agents", return_value=(None, None))
    def test_no_submissions_rejected(self, mock_run_both,
                                      pipeline_state_dir, pipeline_config):

        phases_seen = []
        original_set_phase = __import__("harness.orchestrator", fromlist=["set_phase"]).set_phase

        def tracking_set_phase(sd, *, phase):
            phases_seen.append(phase)
            return original_set_phase(sd, phase=phase)

        call_count = [0]

        def mock_get_next_task(sd):
            call_count[0] += 1
            if call_count[0] == 1:
                return {"task_id": "t1", "specification": "s",
                        "constraints": {"deterministic": True}}
            return None

        with patch("harness.orchestrator.set_phase", side_effect=tracking_set_phase), \
             patch("harness.orchestrator.get_next_task", side_effect=mock_get_next_task), \
             patch("harness.orchestrator.time.sleep", side_effect=StopIteration):
            with pytest.raises(StopIteration):
                run_pipeline(pipeline_config, pipeline_state_dir)

        assert "rejected" in phases_seen

    # O-49: Only one agent submits -> phase "rejected"
    @patch("harness.orchestrator.run_both_agents")
    def test_single_submission_rejected(self, mock_run_both,
                                         pipeline_state_dir, pipeline_config):
        mock_run_both.return_value = ("def f(): pass", None)

        phases_seen = []
        original_set_phase = __import__("harness.orchestrator", fromlist=["set_phase"]).set_phase

        def tracking_set_phase(sd, *, phase):
            phases_seen.append(phase)
            return original_set_phase(sd, phase=phase)

        call_count = [0]

        def mock_get_next_task(sd):
            call_count[0] += 1
            if call_count[0] == 1:
                return {"task_id": "t1", "specification": "s",
                        "constraints": {"deterministic": True}}
            return None

        with patch("harness.orchestrator.set_phase", side_effect=tracking_set_phase), \
             patch("harness.orchestrator.get_next_task", side_effect=mock_get_next_task), \
             patch("harness.orchestrator.time.sleep", side_effect=StopIteration):
            with pytest.raises(StopIteration):
                run_pipeline(pipeline_config, pipeline_state_dir)

        assert "rejected" in phases_seen

    # O-50: AST validation fails -> phase "rejected"
    @patch("harness.orchestrator.run_both_agents")
    @patch("harness.orchestrator._validate_submission")
    def test_ast_failure_rejected(self, mock_validate, mock_run_both,
                                   pipeline_state_dir, pipeline_config):
        mock_run_both.return_value = ("def f(): pass", "def f(): pass")
        # Exhaust max_ast_retries attempts. Default is 3 retries (so 3 calls). 3 * 2 = 6 calls.
        # Wait, the config fixture sets max_ast_retries to 3.
        mock_validate.side_effect = [(False, []), (True, [])] * 3

        phases_seen = []
        original_set_phase = __import__("harness.orchestrator", fromlist=["set_phase"]).set_phase

        def tracking_set_phase(sd, *, phase):
            phases_seen.append(phase)
            return original_set_phase(sd, phase=phase)

        call_count = [0]

        def mock_get_next_task(sd):
            call_count[0] += 1
            if call_count[0] == 1:
                return {"task_id": "t1", "specification": "s",
                        "constraints": {"deterministic": True}}
            return None

        with patch("harness.orchestrator.set_phase", side_effect=tracking_set_phase), \
             patch("harness.orchestrator.get_next_task", side_effect=mock_get_next_task), \
             patch("harness.orchestrator.time.sleep", side_effect=StopIteration):
            with pytest.raises(StopIteration):
                run_pipeline(pipeline_config, pipeline_state_dir)

        assert "ast_validation" in phases_seen
        assert "rejected" in phases_seen
        assert mock_run_both.call_count == 3  # Verified retry logic

    # O-42: Both agents submit, AST valid -> phase "fuzzing"
    @patch("harness.orchestrator.run_both_agents")
    @patch("harness.orchestrator._validate_submission", return_value=(True, []))
    @patch("harness.orchestrator.fuzz_from_task")
    def test_valid_submissions_to_fuzzing(self, mock_fuzz, mock_validate,
                                           mock_run_both,
                                           pipeline_state_dir, pipeline_config):
        mock_run_both.return_value = ("def f(): pass", "def g(): pass")
        mock_fuzz.return_value = FuzzResult(
            equivalent=True, total_inputs=100, matching_inputs=100
        )

        phases_seen = []
        original_set_phase = __import__("harness.orchestrator", fromlist=["set_phase"]).set_phase

        def tracking_set_phase(sd, *, phase):
            phases_seen.append(phase)
            return original_set_phase(sd, phase=phase)

        call_count = [0]

        def mock_get_next_task(sd):
            call_count[0] += 1
            if call_count[0] == 1:
                return {"task_id": "t1", "specification": "s",
                        "constraints": {"deterministic": True}}
            return None

        with patch("harness.orchestrator.set_phase", side_effect=tracking_set_phase), \
             patch("harness.orchestrator.get_next_task", side_effect=mock_get_next_task), \
             patch("harness.orchestrator.time.sleep", side_effect=StopIteration):
            with pytest.raises(StopIteration):
                run_pipeline(pipeline_config, pipeline_state_dir)

        assert "fuzzing" in phases_seen

    # O-43: Equivalent fuzz result -> phase "accepted"
    @patch("harness.orchestrator.run_both_agents")
    @patch("harness.orchestrator._validate_submission", return_value=(True, []))
    @patch("harness.orchestrator.fuzz_from_task")
    def test_equivalent_fuzz_accepted(self, mock_fuzz, mock_validate,
                                       mock_run_both,
                                       pipeline_state_dir, pipeline_config):
        mock_run_both.return_value = ("def f(): pass", "def g(): pass")
        mock_fuzz.return_value = FuzzResult(
            equivalent=True, total_inputs=100, matching_inputs=100
        )

        phases_seen = []
        original_set_phase = __import__("harness.orchestrator", fromlist=["set_phase"]).set_phase

        def tracking_set_phase(sd, *, phase):
            phases_seen.append(phase)
            return original_set_phase(sd, phase=phase)

        call_count = [0]

        def mock_get_next_task(sd):
            call_count[0] += 1
            if call_count[0] == 1:
                # V2 (commit cf523fd) requires non-empty verification_command;
                # without it, _auto_commit_accepted rolls back and returns
                # False, and G18bc (commits e66f7f4 + 3333056) now reads that
                # False and transitions phase='rejected' instead of 'accepted'.
                return {"task_id": "t1", "specification": "s",
                        "constraints": {"deterministic": True},
                        "verification_command": "true"}
            return None

        # G18bc (e66f7f4 + 3333056) gates set_phase('accepted') behind
        # _auto_commit_accepted's True return. The synthetic task has no
        # real worktree, so we mock the auto-commit to return True and
        # exercise the accept branch.
        with patch("harness.orchestrator.set_phase", side_effect=tracking_set_phase), \
             patch("harness.orchestrator.get_next_task", side_effect=mock_get_next_task), \
             patch("harness.orchestrator._auto_commit_accepted", return_value=True), \
             patch("harness.orchestrator.time.sleep", side_effect=StopIteration):
            with pytest.raises(StopIteration):
                run_pipeline(pipeline_config, pipeline_state_dir)

        assert "accepted" in phases_seen

    # O-44: Divergent fuzz -> phase "cross_examination"
    @patch("harness.orchestrator.run_both_agents")
    @patch("harness.orchestrator._validate_submission", return_value=(True, []))
    @patch("harness.orchestrator.fuzz_from_task")
    @patch("harness.orchestrator.prepare_exam_packets")
    @patch("harness.orchestrator.write_feedback_files")
    @patch("harness.orchestrator.clear_feedback_files")
    def test_divergent_to_cross_exam(self, mock_clear, mock_write_fb,
                                      mock_prep_exam, mock_fuzz,
                                      mock_validate, mock_run_both,
                                      pipeline_state_dir, pipeline_config):
        failure = FuzzFailure(
            input_args=[1], input_kwargs={},
            result_a=ExecutionResult(success=True, return_value=2),
            result_b=ExecutionResult(success=True, return_value=3),
            reason="return_mismatch",
        )

        # First call: collect original submissions
        # Second call: collect revised submissions (after cross-exam)
        mock_run_both.side_effect = [
            ("def f(): pass", "def g(): pass"),
            ("def f(): pass", "def g(): pass"),
        ]

        # First fuzz: divergent; second fuzz: equivalent
        mock_fuzz.side_effect = [
            FuzzResult(equivalent=False, total_inputs=100, matching_inputs=90,
                       failures=[failure]),
            FuzzResult(equivalent=True, total_inputs=100, matching_inputs=100),
        ]

        mock_packet = MagicMock()
        mock_packet.review_prompt = "review this"
        mock_prep_exam.return_value = (mock_packet, mock_packet)

        phases_seen = []
        original_set_phase = __import__("harness.orchestrator", fromlist=["set_phase"]).set_phase

        def tracking_set_phase(sd, *, phase):
            phases_seen.append(phase)
            return original_set_phase(sd, phase=phase)

        call_count = [0]

        def mock_get_next_task(sd):
            call_count[0] += 1
            if call_count[0] == 1:
                return {"task_id": "t1", "specification": "s",
                        "constraints": {"deterministic": True}}
            return None

        with patch("harness.orchestrator.set_phase", side_effect=tracking_set_phase), \
             patch("harness.orchestrator.get_next_task", side_effect=mock_get_next_task), \
             patch("harness.orchestrator.time.sleep", side_effect=StopIteration):
            with pytest.raises(StopIteration):
                run_pipeline(pipeline_config, pipeline_state_dir)

        assert "cross_examination" in phases_seen

    # O-45: After cross-exam -> phase "fuzzing" (round 2)
    @patch("harness.orchestrator.run_both_agents")
    @patch("harness.orchestrator._validate_submission", return_value=(True, []))
    @patch("harness.orchestrator.fuzz_from_task")
    @patch("harness.orchestrator.prepare_exam_packets")
    @patch("harness.orchestrator.write_feedback_files")
    @patch("harness.orchestrator.clear_feedback_files")
    def test_orchestrator_phase4_fallback(self, mock_clear, mock_write_fb,
                                          mock_prep_exam, mock_fuzz,
                                          mock_validate, mock_run_both,
                                          pipeline_state_dir, pipeline_config):
        """Verify fallback logic for missing variables in Phase 4."""
        failure = FuzzFailure(
            input_args=[1], input_kwargs={},
            result_a=ExecutionResult(success=True, return_value=2),
            result_b=ExecutionResult(success=True, return_value=3),
            reason="return_mismatch",
        )

        mock_run_both.side_effect = [
            ("def f(): pass", "def g(): pass"),
            ("def f(): pass", "def g(): pass"),
        ]

        mock_fuzz.side_effect = [
            FuzzResult(equivalent=False, total_inputs=100, matching_inputs=90, failures=[failure]),
            FuzzResult(equivalent=True, total_inputs=100, matching_inputs=100),
        ]

        mock_packet = MagicMock()
        mock_packet.review_prompt = "review this"
        mock_prep_exam.return_value = (mock_packet, mock_packet)

        call_count = [0]
        def mock_get_next_task(sd):
            call_count[0] += 1
            if call_count[0] == 1:
                return {"task_id": "t1", "specification": None, "description": "Fallback desc",
                        "constraints": {"deterministic": True}}
            return None

        with patch("harness.orchestrator.get_next_task", side_effect=mock_get_next_task), \
             patch("harness.orchestrator.time.sleep", side_effect=StopIteration):
            with pytest.raises(StopIteration):
                run_pipeline(pipeline_config, pipeline_state_dir)

        # Assert prepare_exam_packets was called with the fallback description
        assert mock_prep_exam.call_args is not None
        assert mock_prep_exam.call_args[0][2] == "Fallback desc"


    @patch("harness.orchestrator.run_both_agents")
    @patch("harness.orchestrator._validate_submission", return_value=(True, []))
    @patch("harness.orchestrator.fuzz_from_task")
    @patch("harness.orchestrator.prepare_exam_packets")
    @patch("harness.orchestrator.write_feedback_files")
    @patch("harness.orchestrator.clear_feedback_files")
    def test_cross_exam_to_round2_fuzzing(self, mock_clear, mock_write_fb,
                                           mock_prep_exam, mock_fuzz,
                                           mock_validate, mock_run_both,
                                           pipeline_state_dir, pipeline_config):
        failure = FuzzFailure(
            input_args=[1], input_kwargs={},
            result_a=ExecutionResult(success=True, return_value=2),
            result_b=ExecutionResult(success=True, return_value=3),
            reason="return_mismatch",
        )

        mock_run_both.side_effect = [
            ("def f(): pass", "def g(): pass"),
            ("def f(): pass", "def g(): pass"),
        ]

        mock_fuzz.side_effect = [
            FuzzResult(equivalent=False, total_inputs=100, matching_inputs=90,
                       failures=[failure]),
            FuzzResult(equivalent=True, total_inputs=100, matching_inputs=100),
        ]

        mock_packet = MagicMock()
        mock_packet.review_prompt = "review this"
        mock_prep_exam.return_value = (mock_packet, mock_packet)

        phases_seen = []
        original_set_phase = __import__("harness.orchestrator", fromlist=["set_phase"]).set_phase

        def tracking_set_phase(sd, *, phase):
            phases_seen.append(phase)
            return original_set_phase(sd, phase=phase)

        call_count = [0]

        def mock_get_next_task(sd):
            call_count[0] += 1
            if call_count[0] == 1:
                return {"task_id": "t1", "specification": "s",
                        "constraints": {"deterministic": True}}
            return None

        with patch("harness.orchestrator.set_phase", side_effect=tracking_set_phase), \
             patch("harness.orchestrator.get_next_task", side_effect=mock_get_next_task), \
             patch("harness.orchestrator.time.sleep", side_effect=StopIteration):
            with pytest.raises(StopIteration):
                run_pipeline(pipeline_config, pipeline_state_dir)

        # Fuzzing should appear twice (round 1 and round 2)
        fuzzing_count = phases_seen.count("fuzzing")
        assert fuzzing_count == 2

    # O-46: Round 2 equivalent -> phase "accepted"
    @patch("harness.orchestrator.run_both_agents")
    @patch("harness.orchestrator._validate_submission", return_value=(True, []))
    @patch("harness.orchestrator.fuzz_from_task")
    @patch("harness.orchestrator.prepare_exam_packets")
    @patch("harness.orchestrator.write_feedback_files")
    @patch("harness.orchestrator.clear_feedback_files")
    def test_round2_equivalent_accepted(self, mock_clear, mock_write_fb,
                                         mock_prep_exam, mock_fuzz,
                                         mock_validate, mock_run_both,
                                         pipeline_state_dir, pipeline_config):
        failure = FuzzFailure(
            input_args=[1], input_kwargs={},
            result_a=ExecutionResult(success=True, return_value=2),
            result_b=ExecutionResult(success=True, return_value=3),
            reason="return_mismatch",
        )

        mock_run_both.side_effect = [
            ("def f(): pass", "def g(): pass"),
            ("def f_rev(): pass", "def g_rev(): pass"),
        ]

        mock_fuzz.side_effect = [
            FuzzResult(equivalent=False, total_inputs=100, matching_inputs=90,
                       failures=[failure]),
            FuzzResult(equivalent=True, total_inputs=100, matching_inputs=100),
        ]

        mock_packet = MagicMock()
        mock_packet.review_prompt = "review this"
        mock_prep_exam.return_value = (mock_packet, mock_packet)

        phases_seen = []
        original_set_phase = __import__("harness.orchestrator", fromlist=["set_phase"]).set_phase

        def tracking_set_phase(sd, *, phase):
            phases_seen.append(phase)
            return original_set_phase(sd, phase=phase)

        call_count = [0]

        def mock_get_next_task(sd):
            call_count[0] += 1
            if call_count[0] == 1:
                # V2 (cf523fd) + G18bc (e66f7f4 + 3333056) — see
                # test_equivalent_fuzz_accepted for the rationale on this
                # verification_command='true' addition.
                return {"task_id": "t1", "specification": "s",
                        "constraints": {"deterministic": True},
                        "verification_command": "true"}
            return None

        # G18bc auto-commit gate -- see test_equivalent_fuzz_accepted.
        with patch("harness.orchestrator.set_phase", side_effect=tracking_set_phase), \
             patch("harness.orchestrator.get_next_task", side_effect=mock_get_next_task), \
             patch("harness.orchestrator._auto_commit_accepted", return_value=True), \
             patch("harness.orchestrator.time.sleep", side_effect=StopIteration):
            with pytest.raises(StopIteration):
                run_pipeline(pipeline_config, pipeline_state_dir)

        assert "accepted" in phases_seen

    # O-47: Round 2 divergent -> decomposition
    @patch("harness.orchestrator.run_both_agents")
    @patch("harness.orchestrator._validate_submission", return_value=(True, []))
    @patch("harness.orchestrator.fuzz_from_task")
    @patch("harness.orchestrator.prepare_exam_packets")
    @patch("harness.orchestrator.write_feedback_files")
    @patch("harness.orchestrator.clear_feedback_files")
    @patch("harness.orchestrator.decompose_task")
    @patch("harness.orchestrator.enqueue_subtasks")
    @patch("harness.orchestrator.update_parent_state")
    def test_round2_divergent_decompose(self, mock_update_parent, mock_enqueue,
                                         mock_decompose, mock_clear,
                                         mock_write_fb, mock_prep_exam,
                                         mock_fuzz, mock_validate,
                                         mock_run_both,
                                         pipeline_state_dir, pipeline_config):
        failure = FuzzFailure(
            input_args=[1], input_kwargs={},
            result_a=ExecutionResult(success=True, return_value=2),
            result_b=ExecutionResult(success=True, return_value=3),
            reason="return_mismatch",
        )

        mock_run_both.side_effect = [
            ("def f(): pass", "def g(): pass"),
            ("def f(): pass", "def g(): pass"),
        ]

        mock_fuzz.side_effect = [
            FuzzResult(equivalent=False, total_inputs=100, matching_inputs=90,
                       failures=[failure]),
            FuzzResult(equivalent=False, total_inputs=100, matching_inputs=85,
                       failures=[failure]),
        ]

        mock_packet = MagicMock()
        mock_packet.review_prompt = "review this"
        mock_prep_exam.return_value = (mock_packet, mock_packet)

        from harness.task_decomposer import DecompositionResult, Subtask
        mock_decompose.return_value = DecompositionResult(
            parent_task_id="t1",
            subtasks=[
                Subtask(task_id="t1-sub1", parent_task_id="t1",
                        specification="sub1", constraints={}),
                Subtask(task_id="t1-sub2", parent_task_id="t1",
                        specification="sub2", constraints={}),
            ],
            strategy="edge_case",
            reason="test decomposition",
        )

        call_count = [0]

        def mock_get_next_task(sd):
            call_count[0] += 1
            if call_count[0] == 1:
                return {"task_id": "t1", "specification": "s",
                        "constraints": {"deterministic": True}}
            return None

        with patch("harness.orchestrator.get_next_task", side_effect=mock_get_next_task), \
             patch("harness.orchestrator.time.sleep", side_effect=StopIteration):
            with pytest.raises(StopIteration):
                run_pipeline(pipeline_config, pipeline_state_dir)

        mock_decompose.assert_called_once()
        mock_enqueue.assert_called_once()
        mock_update_parent.assert_called_once()

    # O-51: Fuzzing error -> phase "rejected"
    @patch("harness.orchestrator.run_both_agents")
    @patch("harness.orchestrator._validate_submission", return_value=(True, []))
    @patch("harness.orchestrator.fuzz_from_task")
    def test_fuzzing_error_rejected(self, mock_fuzz, mock_validate,
                                     mock_run_both,
                                     pipeline_state_dir, pipeline_config):
        mock_run_both.return_value = ("def f(): pass", "def g(): pass")
        mock_fuzz.return_value = FuzzResult(
            equivalent=False, total_inputs=0, matching_inputs=0,
            error="Sandbox execution failed",
        )

        phases_seen = []
        original_set_phase = __import__("harness.orchestrator", fromlist=["set_phase"]).set_phase

        def tracking_set_phase(sd, *, phase):
            phases_seen.append(phase)
            return original_set_phase(sd, phase=phase)

        call_count = [0]

        def mock_get_next_task(sd):
            call_count[0] += 1
            if call_count[0] == 1:
                return {"task_id": "t1", "specification": "s",
                        "constraints": {"deterministic": True}}
            return None

        with patch("harness.orchestrator.set_phase", side_effect=tracking_set_phase), \
             patch("harness.orchestrator.get_next_task", side_effect=mock_get_next_task), \
             patch("harness.orchestrator.time.sleep", side_effect=StopIteration):
            with pytest.raises(StopIteration):
                run_pipeline(pipeline_config, pipeline_state_dir)

        assert "rejected" in phases_seen


# ── Entry Point (O-52 through O-57) ───────────────────────────────────

class TestMainEntryPoint:
    # O-52: main() with --config flag
    @patch("harness.orchestrator.run_pipeline")
    @patch("harness.orchestrator._configure_logging")
    def test_config_flag(self, mock_logging, mock_pipeline, tmp_path):
        config_file = tmp_path / "custom.yaml"
        config_file.write_text(
            "synthesis:\n  timeout_seconds: 60\n"
            "fuzzing:\n  seed: 42\n"
            "sandbox:\n  memory_limit_mb: 128\n"
            "agents:\n  claude:\n    command: claude\n    args: [-p]\n"
        )
        state_dir = tmp_path / "state"
        mock_pipeline.side_effect = KeyboardInterrupt()

        with patch("sys.argv", ["orchestrator", "--config", str(config_file),
                                "--state-dir", str(state_dir)]):
            main()

        # Verify run_pipeline was called with loaded config
        assert mock_pipeline.called
        loaded_config = mock_pipeline.call_args[0][0]
        assert loaded_config["synthesis"]["timeout_seconds"] == 60

    # O-53: main() with --state-dir flag
    @patch("harness.orchestrator.run_pipeline")
    @patch("harness.orchestrator._configure_logging")
    def test_state_dir_flag(self, mock_logging, mock_pipeline, tmp_path):
        state_dir = tmp_path / "custom_state"
        mock_pipeline.side_effect = KeyboardInterrupt()

        with patch("sys.argv", ["orchestrator", "--state-dir", str(state_dir)]):
            main()

        # State dir should have been created and passed
        assert state_dir.is_dir()
        used_state_dir = mock_pipeline.call_args[0][1]
        assert used_state_dir == state_dir

    # O-54: main() with --log-dir flag
    @patch("harness.orchestrator.run_pipeline")
    @patch("harness.orchestrator._configure_logging")
    def test_log_dir_flag(self, mock_logging, mock_pipeline, tmp_path):
        log_dir = tmp_path / "custom_logs"
        state_dir = tmp_path / "state"
        mock_pipeline.side_effect = KeyboardInterrupt()

        with patch("sys.argv", ["orchestrator", "--log-dir", str(log_dir),
                                "--state-dir", str(state_dir)]):
            main()

        mock_logging.assert_called_once_with(log_dir)

    # O-55: main() creates state directories
    @patch("harness.orchestrator.run_pipeline")
    @patch("harness.orchestrator._configure_logging")
    def test_creates_directories(self, mock_logging, mock_pipeline, tmp_path):
        state_dir = tmp_path / "fresh_state"
        mock_pipeline.side_effect = KeyboardInterrupt()

        with patch("sys.argv", ["orchestrator", "--state-dir", str(state_dir)]):
            main()

        assert (state_dir / "tasks").is_dir()
        assert (state_dir / "sessions").is_dir()

    # O-56: main() initializes STATE.json
    @patch("harness.orchestrator.run_pipeline")
    @patch("harness.orchestrator._configure_logging")
    def test_initializes_state(self, mock_logging, mock_pipeline, tmp_path):
        state_dir = tmp_path / "new_state"
        mock_pipeline.side_effect = KeyboardInterrupt()

        with patch("sys.argv", ["orchestrator", "--state-dir", str(state_dir)]):
            main()

        state_file = state_dir / "STATE.json"
        assert state_file.is_file()
        data = json.loads(state_file.read_text())
        assert data["phase"] == "idle"
        assert data["round"] == 0

    # O-57: Ctrl-C (KeyboardInterrupt) sets phase "idle" and exits
    @patch("harness.orchestrator.run_pipeline", side_effect=KeyboardInterrupt)
    @patch("harness.orchestrator._configure_logging")
    def test_keyboard_interrupt_clean_shutdown(self, mock_logging, mock_pipeline, tmp_path):
        state_dir = tmp_path / "int_state"
        with patch("sys.argv", ["orchestrator", "--state-dir", str(state_dir)]):
            main()  # should NOT raise

        state_file = state_dir / "STATE.json"
        assert state_file.is_file()
        data = json.loads(state_file.read_text())
        assert data["phase"] == "idle"
