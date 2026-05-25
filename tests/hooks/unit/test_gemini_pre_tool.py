"""Unit tests for harness.hooks.gemini.pre_tool (HOOK-32 / P3).

Gate 3 partner for harness.hooks.gemini.pre_tool: the full dotted path
is imported below so the post-write gate recognises this file as its
test partner.
"""

from __future__ import annotations

import io
import json

import pytest

import harness.hooks.gemini.pre_tool as pre_tool
from harness.hooks import _ledger
from harness.hooks.gemini import pre_tool as pt_mod


SAFE_SUBMISSION_CODE = (
    "def solve(data):\n"
    "    total = 0\n"
    "    for item in data:\n"
    "        total += item\n"
    "    return total\n"
)
AST_INVALID_CODE = "def broken(:\n    pass\n"


@pytest.fixture
def synth_workdir(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    workdir = state / "workdirs" / "gemini" / "sessPT"
    (workdir / "inbox").mkdir(parents=True)
    (workdir / "outbox").mkdir(parents=True)
    (workdir / "inbox" / "task.json").write_text(
        json.dumps({"task_id": "T", "synthesis_target_type": "function"})
    )
    (state / "STATE.json").write_text(
        json.dumps({"round": 1, "phase": "synthesis", "task_id": "T"})
    )
    monkeypatch.setenv("JANUSMASK_STATE_DIR", str(state))
    monkeypatch.setenv("JANUSMASK_WORK_DIR", str(workdir))
    monkeypatch.setenv("JANUSMASK_AGENT", "gemini")
    monkeypatch.setenv("JANUSMASK_MODE", "synthesis")
    return {
        "state": state,
        "workdir": workdir,
        "outbox": workdir / "outbox",
        "session_id": "sessPT",
    }


def _call(stdin_body: dict, *, monkeypatch=None):
    stdout = io.StringIO()
    pre_tool.main(io.StringIO(json.dumps(stdin_body)), stdout)
    return json.loads(stdout.getvalue())


class TestAllowedToolsSet:
    def test_rejects_unknown_tool(self, synth_workdir):
        out = _call(
            {
                "tool_name": "not_a_real_tool",
                "tool_input": {},
                "session_id": synth_workdir["session_id"],
            }
        )
        assert out["decision"] == "deny"
        assert "not_a_real_tool" in out["reason"]

    def test_tools_disallowed_even_if_admin_policy_would_allow(
        self, synth_workdir
    ):
        # Defence in depth: admin-policy denies google_web_search at
        # tier 5, but if for any reason a policy regression ever let
        # it through, the hook must still deny.
        out = _call(
            {
                "tool_name": "google_web_search",
                "tool_input": {"query": "janusmask"},
                "session_id": synth_workdir["session_id"],
            }
        )
        assert out["decision"] == "deny"


class TestReadLike:
    def test_read_file_inside_workdir_allowed(self, synth_workdir):
        target = synth_workdir["workdir"] / "inbox" / "task.json"
        out = _call(
            {
                "tool_name": "read_file",
                "tool_input": {"absolute_path": str(target)},
                "session_id": synth_workdir["session_id"],
            }
        )
        assert out["decision"] == "allow"

    def test_read_file_via_file_path_key_also_allowed(self, synth_workdir):
        # Gemini's read_file uses `absolute_path`; `file_path` is the Claude
        # naming convention. Accept both to survive minor schema churn.
        target = synth_workdir["workdir"] / "inbox" / "task.json"
        out = _call(
            {
                "tool_name": "read_file",
                "tool_input": {"file_path": str(target)},
                "session_id": synth_workdir["session_id"],
            }
        )
        assert out["decision"] == "allow"

    def test_read_outside_allowed_roots_denied(self, synth_workdir, tmp_path):
        stranger = tmp_path / "stranger.txt"
        stranger.write_text("nope")
        out = _call(
            {
                "tool_name": "read_file",
                "tool_input": {"absolute_path": str(stranger)},
                "session_id": synth_workdir["session_id"],
            }
        )
        assert out["decision"] == "deny"
        assert "allowed roots" in out["reason"]

    def test_glob_without_path_allowed(self, synth_workdir):
        out = _call(
            {
                "tool_name": "glob",
                "tool_input": {"pattern": "**/*.py"},
                "session_id": synth_workdir["session_id"],
            }
        )
        assert out["decision"] == "allow"

    def test_list_directory_under_workdir_allowed(self, synth_workdir):
        out = _call(
            {
                "tool_name": "list_directory",
                "tool_input": {"path": str(synth_workdir["workdir"])},
                "session_id": synth_workdir["session_id"],
            }
        )
        assert out["decision"] == "allow"


class TestRunShellCommand:
    def test_allowlisted_pytest_command(self, synth_workdir):
        out = _call(
            {
                "tool_name": "run_shell_command",
                "tool_input": {"command": "pytest tests/ -q"},
                "session_id": synth_workdir["session_id"],
            }
        )
        assert out["decision"] == "allow"

    def test_allowlisted_python_module_run(self, synth_workdir):
        out = _call(
            {
                "tool_name": "run_shell_command",
                "tool_input": {"command": "python3 -m pytest tests/foo.py"},
                "session_id": synth_workdir["session_id"],
            }
        )
        assert out["decision"] == "allow"

    def test_non_allowlisted_shell_denied(self, synth_workdir):
        out = _call(
            {
                "tool_name": "run_shell_command",
                "tool_input": {"command": "curl https://example.com"},
                "session_id": synth_workdir["session_id"],
            }
        )
        assert out["decision"] == "deny"
        assert "shell command not in allow-list" in out["reason"].lower() or \
               "not allow" in out["reason"].lower()

    def test_empty_command_denied(self, synth_workdir):
        out = _call(
            {
                "tool_name": "run_shell_command",
                "tool_input": {"command": ""},
                "session_id": synth_workdir["session_id"],
            }
        )
        assert out["decision"] == "deny"


class TestWriteFileSubmission:
    def test_clean_submission_allowed(self, synth_workdir):
        out = _call(
            {
                "tool_name": "write_file",
                "tool_input": {
                    "file_path": str(synth_workdir["outbox"] / "submission.py"),
                    "content": SAFE_SUBMISSION_CODE,
                },
                "session_id": synth_workdir["session_id"],
            }
        )
        assert out["decision"] == "allow"

    def test_ast_invalid_submission_denied(self, synth_workdir):
        out = _call(
            {
                "tool_name": "write_file",
                "tool_input": {
                    "file_path": str(synth_workdir["outbox"] / "submission.py"),
                    "content": AST_INVALID_CODE,
                },
                "session_id": synth_workdir["session_id"],
            }
        )
        assert out["decision"] == "deny"
        assert "Fix violations and resubmit" in out["reason"]

    def test_write_outside_outbox_denied(self, synth_workdir):
        out = _call(
            {
                "tool_name": "write_file",
                "tool_input": {
                    "file_path": str(synth_workdir["state"] / "evil.py"),
                    "content": SAFE_SUBMISSION_CODE,
                },
                "session_id": synth_workdir["session_id"],
            }
        )
        assert out["decision"] == "deny"
        assert "outbox" in out["reason"]

    def test_rate_limit_sixth_submission_denied(self, synth_workdir):
        for _ in range(5):
            _ledger.append_hook_event(
                synth_workdir["session_id"], "gemini", "submit_code", "allow"
            )
        out = _call(
            {
                "tool_name": "write_file",
                "tool_input": {
                    "file_path": str(synth_workdir["outbox"] / "submission.py"),
                    "content": SAFE_SUBMISSION_CODE,
                },
                "session_id": synth_workdir["session_id"],
            }
        )
        assert out["decision"] == "deny"
        assert "rate limit" in out["reason"].lower()

    def test_error_md_allowed_in_any_mode(self, synth_workdir):
        out = _call(
            {
                "tool_name": "write_file",
                "tool_input": {
                    "file_path": str(synth_workdir["outbox"] / "error.md"),
                    "content": "oops",
                },
                "session_id": synth_workdir["session_id"],
            }
        )
        assert out["decision"] == "allow"


class TestReplaceReconstruction:
    """`replace` must reconstruct the post-write file and AST-validate it
    (sub-plan 03 §5 row 3). Otherwise an agent could slip invalid code
    past the gate by splitting the bad bytes across old_string/new_string."""

    def test_replace_producing_valid_code_allowed(self, synth_workdir):
        # Seed the outbox submission with a placeholder body.
        target = synth_workdir["outbox"] / "submission.py"
        target.write_text("def solve(data):\n    return 0\n")
        out = _call(
            {
                "tool_name": "replace",
                "tool_input": {
                    "file_path": str(target),
                    "old_string": "    return 0\n",
                    "new_string": "    return sum(data)\n",
                },
                "session_id": synth_workdir["session_id"],
            }
        )
        assert out["decision"] == "allow"

    def test_replace_producing_syntax_error_denied(self, synth_workdir):
        target = synth_workdir["outbox"] / "submission.py"
        target.write_text("def solve(data):\n    return 0\n")
        out = _call(
            {
                "tool_name": "replace",
                "tool_input": {
                    "file_path": str(target),
                    "old_string": "    return 0\n",
                    # A hanging colon turns the file into invalid Python
                    # only after the substitution is applied.
                    "new_string": "    return 0:\n",
                },
                "session_id": synth_workdir["session_id"],
            }
        )
        assert out["decision"] == "deny"

    def test_replace_on_missing_file_uses_empty_base(self, synth_workdir):
        target = synth_workdir["outbox"] / "submission.py"  # not yet written
        out = _call(
            {
                "tool_name": "replace",
                "tool_input": {
                    "file_path": str(target),
                    "old_string": "",
                    "new_string": SAFE_SUBMISSION_CODE,
                },
                "session_id": synth_workdir["session_id"],
            }
        )
        assert out["decision"] == "allow"


class TestModeGating:
    def test_synthesis_cannot_write_plan_draft(self, synth_workdir):
        out = _call(
            {
                "tool_name": "write_file",
                "tool_input": {
                    "file_path": str(
                        synth_workdir["outbox"] / "plan_draft.json"
                    ),
                    "content": json.dumps({"a": 1}),
                },
                "session_id": synth_workdir["session_id"],
            }
        )
        assert out["decision"] == "deny"
        assert "mode=" in out["reason"]

    def test_planning_allows_plan_draft(self, tmp_path, monkeypatch):
        state = tmp_path / "state"
        state.mkdir()
        workdir = state / "workdirs" / "gemini" / "pl"
        (workdir / "inbox").mkdir(parents=True)
        (workdir / "outbox").mkdir(parents=True)
        (workdir / "inbox" / "brief.json").write_text(json.dumps({"t": 1}))
        (state / "STATE.json").write_text(
            json.dumps({"round": 1, "phase": "planning"})
        )
        monkeypatch.setenv("JANUSMASK_STATE_DIR", str(state))
        monkeypatch.setenv("JANUSMASK_WORK_DIR", str(workdir))
        monkeypatch.setenv("JANUSMASK_AGENT", "gemini")
        monkeypatch.setenv("JANUSMASK_MODE", "planning")
        stdout = io.StringIO()
        pre_tool.main(
            io.StringIO(
                json.dumps(
                    {
                        "tool_name": "write_file",
                        "tool_input": {
                            "file_path": str(workdir / "outbox" / "plan_draft.json"),
                            "content": json.dumps(
                                {"plan_version": "v1", "tasks": []}
                            ),
                        },
                        "session_id": "pl",
                    }
                )
            ),
            stdout,
        )
        out = json.loads(stdout.getvalue())
        assert out["decision"] == "allow"


class TestMalformedInputs:
    def test_empty_stdin_denied(self, synth_workdir):
        stdout = io.StringIO()
        pre_tool.main(io.StringIO(""), stdout)
        out = json.loads(stdout.getvalue())
        # Empty stdin has no tool_name → deny.
        assert out["decision"] == "deny"

    def test_non_json_stdin_denied(self, synth_workdir):
        stdout = io.StringIO()
        pre_tool.main(io.StringIO("{broken"), stdout)
        out = json.loads(stdout.getvalue())
        assert out["decision"] == "deny"
        assert "Malformed" in out["reason"] or "malformed" in out["reason"]
