"""Integration tests: MCP server <-> state <-> orchestrator round-trip."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from harness.mcp_server import JanusMaskServer
from harness.orchestrator import collect_submissions, get_next_task
from harness.session_namer import generate_submission_filename
from harness.state import init_state, read_state, set_phase
from harness.cross_examiner import write_feedback_files, ExamPacket


@pytest.fixture
def state_dir(tmp_path):
    for sub in ("sessions", "tasks", "tasks/processed"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    init_state(tmp_path)
    return tmp_path


@pytest.fixture
def task_in_queue(state_dir):
    task = {
        "task_id": "int-test-001",
        "specification": "Write add(a, b)",
        "constraints": {"function_signature": "def add(a: int, b: int) -> int", "deterministic": True},
    }
    (state_dir / "tasks" / "int-test-001.json").write_text(json.dumps(task))
    return task


class TestMcpStateRoundTrip:
    def test_orchestrator_task_readable_by_mcp(self, state_dir, task_in_queue, monkeypatch):
        # Post-AW10c (session #19, b3a3dca): orchestrator writes per-task
        # current_task_<task_id>.json instead of a shared current_task.json.
        # MCP server's cmd_get_task locates the spec via JANUSMASK_TASK_ID
        # env-var glob (mcp_server.py:284-290); fallback at line 296 is
        # broken under AW10c and filed as R-PROMOTE-7 for next-next-session.
        monkeypatch.setenv("JANUSMASK_TASK_ID", "int-test-001")
        task = get_next_task(state_dir)
        assert task is not None
        server = JanusMaskServer("claude", state_dir)
        result = server.cmd_get_task({})
        assert result["task_id"] == "int-test-001"

    def test_mcp_submission_readable_by_orchestrator(self, state_dir, task_in_queue):
        set_phase(state_dir, phase="synthesis")
        # Write STATE.json round
        state = read_state(state_dir)
        state["round"] = 1
        (state_dir / "STATE.json").write_text(json.dumps(state))

        get_next_task(state_dir)
        server = JanusMaskServer("claude", state_dir)
        server.cmd_get_task({})
        server.cmd_submit_code({
            "code": "def add(a: int, b: int) -> int:\n    return a + b\n",
            "session_id": "x", "agent_identity": "claude",
            "round_number": 1, "timestamp": "2026-01-01T00:00:00Z",
        })
        c, g = collect_submissions(state_dir, 1)
        assert c is not None
        assert "return a + b" in c

    def test_two_servers_no_corruption(self, state_dir, task_in_queue):
        set_phase(state_dir, phase="synthesis")
        state = read_state(state_dir)
        state["round"] = 1
        (state_dir / "STATE.json").write_text(json.dumps(state))

        get_next_task(state_dir)
        claude = JanusMaskServer("claude", state_dir)
        gemini = JanusMaskServer("gemini", state_dir)

        claude.cmd_get_task({})
        gemini.cmd_get_task({})

        claude.cmd_submit_code({
            "code": "def add(a: int, b: int) -> int:\n    return a + b\n",
            "session_id": "x", "agent_identity": "claude",
            "round_number": 1, "timestamp": "2026-01-01T00:00:00Z",
        })
        gemini.cmd_submit_code({
            "code": "def add(a: int, b: int) -> int:\n    return a + b\n",
            "session_id": "y", "agent_identity": "gemini",
            "round_number": 1, "timestamp": "2026-01-01T00:00:00Z",
        })

        c, g = collect_submissions(state_dir, 1)
        assert c is not None
        assert g is not None

    def test_phase_visible_to_mcp(self, state_dir, task_in_queue):
        set_phase(state_dir, phase="cross_examination")
        server = JanusMaskServer("claude", state_dir)
        assert server._current_phase() == "cross_examination"

    def test_ast_rejection_via_mcp(self, state_dir, task_in_queue):
        get_next_task(state_dir)
        server = JanusMaskServer("claude", state_dir)
        server.cmd_get_task({})
        result = server.cmd_submit_code({
            "code": "import random\ndef f():\n    return random.randint(1, 10)\n",
            "session_id": "x", "agent_identity": "claude",
            "round_number": 1, "timestamp": "2026-01-01T00:00:00Z",
        })
        assert result["status"] == "rejected"
        assert len(result["violations"]) > 0

    def test_feedback_round_trip(self, state_dir, task_in_queue):
        set_phase(state_dir, phase="cross_examination")
        state = read_state(state_dir)
        state["round"] = 1
        (state_dir / "STATE.json").write_text(json.dumps(state))

        # Write feedback files (simulating cross_examiner)
        cp = ExamPacket(
            agent="claude", code_under_review="def f(): return 1",
            task_specification="Write f", fuzz_failures=[],
            review_prompt="Review this code.",
        )
        gp = ExamPacket(
            agent="gemini", code_under_review="def f(): return 2",
            task_specification="Write f", fuzz_failures=[],
            review_prompt="Review that code.",
        )
        write_feedback_files(state_dir, cp, gp, round_number=1)

        get_next_task(state_dir)
        server = JanusMaskServer("claude", state_dir)
        server.cmd_get_task({})
        feedback = server.cmd_get_feedback({
            "session_id": "x", "agent_identity": "claude",
            "round_number": 1, "timestamp": "2026-01-01T00:00:00Z",
        })
        assert feedback["round"] == 1
        assert "code_under_review" in feedback

    def test_ast_accepted_persists_submission(self, state_dir, task_in_queue):
        """I-07: Code accepted by AST enforcer persists submission to
        sessions/{agent}_round{N}_{task_id}_submission.json (P0.3 contract).

        When JANUSMASK_TASK_ID is unset, mcp_server.cmd_submit_code falls
        back to task_id='default', which is what this test exercises.
        """
        set_phase(state_dir, phase="synthesis")
        state = read_state(state_dir)
        state["round"] = 1
        (state_dir / "STATE.json").write_text(json.dumps(state))

        get_next_task(state_dir)
        server = JanusMaskServer("claude", state_dir)
        server.cmd_get_task({})
        result = server.cmd_submit_code({
            "code": "def add(a: int, b: int) -> int:\n    return a + b\n",
            "session_id": "x", "agent_identity": "claude",
            "round_number": 1, "timestamp": "2026-01-01T00:00:00Z",
        })
        assert result["status"] == "accepted"
        assert result["ast_valid"] is True

        # Verify the submission file was written. Filename follows the P0.3
        # contract via generate_submission_filename. JANUSMASK_TASK_ID is not
        # set in this test, so mcp_server defaults task_id to "default".
        submission_name = generate_submission_filename(
            agent="claude", round_number=1, task_id="default"
        )
        submission_path = state_dir / "sessions" / submission_name
        assert submission_path.exists(), (
            f"Submission file not persisted at {submission_path}"
        )
        data = json.loads(submission_path.read_text())
        assert data["code"] == "def add(a: int, b: int) -> int:\n    return a + b\n"
        assert data["agent_identity"] == "claude"

    def test_nondeterminism_check_respects_task_constraints(self, state_dir, monkeypatch):
        """I-08: Nondeterminism check respects task constraints via MCP.
        A deterministic task blocks 'import random'; a non-deterministic
        task allows it.

        Post-AW10c (session #19, b3a3dca): MCP server's task-constraint
        lookup at mcp_server.py:362-369 honors JANUSMASK_TASK_ID env var
        (glob for *<task_id>.json.processing). The bare current_task.json
        fallback at line 369 is broken under AW10c -- filed as R-PROMOTE-7
        for next-next-session.
        """
        # Create a deterministic task
        det_task = {
            "task_id": "det-task",
            "specification": "Write add(a, b)",
            "constraints": {
                "function_signature": "def add(a: int, b: int) -> int",
                "deterministic": True,
            },
        }
        (state_dir / "tasks" / "det-task.json").write_text(json.dumps(det_task))
        get_next_task(state_dir)

        monkeypatch.setenv("JANUSMASK_TASK_ID", "det-task")
        server = JanusMaskServer("claude", state_dir)
        server.cmd_get_task({})
        result = server.cmd_submit_code({
            "code": "import random\ndef add(a: int, b: int) -> int:\n    return random.randint(a, b)\n",
            "session_id": "x", "agent_identity": "claude",
            "round_number": 1, "timestamp": "2026-01-01T00:00:00Z",
        })
        assert result["status"] == "rejected"
        assert any(v["rule"] == "nondeterminism" for v in result["violations"])

        # Now create a non-deterministic task
        nondet_task = {
            "task_id": "nondet-task",
            "specification": "Write shuffle(items)",
            "constraints": {
                "function_signature": "def shuffle(items: list[int]) -> list[int]",
                "deterministic": False,
            },
        }
        (state_dir / "tasks" / "nondet-task.json").write_text(json.dumps(nondet_task))
        # Mark det-task as processed
        import shutil
        (state_dir / "tasks" / "processed").mkdir(parents=True, exist_ok=True)
        shutil.move(
            str(state_dir / "tasks" / "det-task.json.processing"),
            str(state_dir / "tasks" / "processed" / "det-task.json"),
        )
        get_next_task(state_dir)

        monkeypatch.setenv("JANUSMASK_TASK_ID", "nondet-task")
        server2 = JanusMaskServer("claude", state_dir)
        server2.cmd_get_task({})
        result2 = server2.cmd_submit_code({
            "code": "import random\ndef shuffle(items: list[int]) -> list[int]:\n    result = list(items)\n    random.shuffle(result)\n    return result\n",
            "session_id": "y", "agent_identity": "claude",
            "round_number": 1, "timestamp": "2026-01-01T00:00:00Z",
        })
        assert result2["status"] == "accepted"
