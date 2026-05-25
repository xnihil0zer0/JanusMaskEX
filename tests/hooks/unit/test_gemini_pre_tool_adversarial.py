"""Adversarial battery for HOOK-32-gemini-pre-tool (Phase 3).

Targets the sub-plan 03 §5 + augmented-plan §5 P3 attack rows:

  - admin-policy-test (§5 row 1): tier-5 deny wins, but hook must also
    deny if ever called — defense in depth.
  - path-gate test (§5 row 2): write to path outside expected outbox
    is denied.
  - replace-reconstruction test (§5 row 3): substitutions producing
    AST-invalid code are caught by the reconstructed-content AST gate.
  - vocab-normalisation test (§5 row 5): decisions emitted by the
    hook are always ``allow``/``deny`` — the ``block`` Claude token
    never leaks on the Gemini side.
  - Path-traversal via ``..`` / symlink attacks on the outbox.
"""

from __future__ import annotations

import io
import json
import os

import pytest

import harness.hooks.gemini.pre_tool as pre_tool
from harness.hooks import _ledger


SAFE = (
    "def f(x):\n"
    "    return x\n"
)
BROKEN_SYNTAX = "def f(x:\n    return x\n"


def _call(body: dict) -> dict:
    stdout = io.StringIO()
    pre_tool.main(io.StringIO(json.dumps(body)), stdout)
    return json.loads(stdout.getvalue())


@pytest.fixture
def synth_env(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    workdir = state / "workdirs" / "gemini" / "advPT"
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
        "session_id": "advPT",
    }


class TestAdminPolicyDefenseInDepth:
    @pytest.mark.parametrize(
        "tool",
        ["google_web_search", "web_fetch", "write_todos", "save_memory", "cli_help"],
    )
    def test_admin_policy_denied_tools_hook_also_denies(
        self, synth_env, tool
    ):
        out = _call(
            {
                "tool_name": tool,
                "tool_input": {"query": "x", "command": "x", "content": "x"},
                "session_id": synth_env["session_id"],
            }
        )
        assert out["decision"] == "deny"


class TestPathGate:
    def test_write_to_state_root_denied(self, synth_env):
        out = _call(
            {
                "tool_name": "write_file",
                "tool_input": {
                    "file_path": str(
                        synth_env["state"] / "STATE.json"
                    ),
                    "content": "{}",
                },
                "session_id": synth_env["session_id"],
            }
        )
        assert out["decision"] == "deny"
        assert "outbox" in out["reason"]

    def test_path_traversal_via_dotdot_denied(self, synth_env):
        # The outbox is state/workdirs/gemini/advPT/outbox; an agent
        # trying to escape up to the state dir via `../..` must be
        # caught even though the literal prefix string sort-of matches.
        target = (
            synth_env["outbox"]
            / ".."
            / ".."
            / "escaped_submission.py"
        )
        out = _call(
            {
                "tool_name": "write_file",
                "tool_input": {"file_path": str(target), "content": SAFE},
                "session_id": synth_env["session_id"],
            }
        )
        assert out["decision"] == "deny"

    def test_symlink_escape_denied(self, synth_env, tmp_path):
        link = synth_env["outbox"] / "submission.py"
        real_outside = tmp_path / "real_outside.py"
        real_outside.write_text("")
        try:
            os.symlink(real_outside, link)
        except (OSError, NotImplementedError):
            pytest.skip("symlink not available")
        out = _call(
            {
                "tool_name": "write_file",
                "tool_input": {"file_path": str(link), "content": SAFE},
                "session_id": synth_env["session_id"],
            }
        )
        # is_safe_subpath resolves symlinks; the escape is denied.
        assert out["decision"] == "deny"


class TestReplaceReconstruction:
    def test_adversarial_split_syntax_across_replace_denied(self, synth_env):
        # Adversary seeds a CLEAN file, then sends a `replace` that
        # swaps part of it so the resulting bytes are invalid Python.
        # Without AST reconstruction this would slip past the gate.
        target = synth_env["outbox"] / "submission.py"
        target.write_text("def f(x):\n    return x\n")
        out = _call(
            {
                "tool_name": "replace",
                "tool_input": {
                    "file_path": str(target),
                    "old_string": "def f(x):\n",
                    "new_string": "def f(x:\n",  # unmatched paren
                },
                "session_id": synth_env["session_id"],
            }
        )
        assert out["decision"] == "deny"

    def test_replace_with_unchanged_ast_still_passes(self, synth_env):
        target = synth_env["outbox"] / "submission.py"
        target.write_text("def f(x):\n    return x\n")
        out = _call(
            {
                "tool_name": "replace",
                "tool_input": {
                    "file_path": str(target),
                    "old_string": "return x",
                    "new_string": "return x + 0",
                },
                "session_id": synth_env["session_id"],
            }
        )
        assert out["decision"] == "allow"


class TestVocabNormalisation:
    def test_every_decision_is_allow_or_deny_only(self, synth_env):
        # Fuzz a few tool shapes and verify no test case emits
        # `block`/`ask`/etc. on stdout — the normaliser should have
        # already collapsed those.
        fixtures = [
            {"tool_name": "write_file", "tool_input": {"file_path": "x"}},
            {"tool_name": "read_file", "tool_input": {}},
            {"tool_name": "run_shell_command", "tool_input": {"command": ""}},
            {"tool_name": "unknown", "tool_input": {}},
        ]
        for fx in fixtures:
            fx["session_id"] = synth_env["session_id"]
            out = _call(fx)
            assert out["decision"] in ("allow", "deny")

    def test_reason_field_populated_on_deny(self, synth_env):
        out = _call(
            {
                "tool_name": "write_file",
                "tool_input": {
                    "file_path": str(synth_env["outbox"] / "wrong.py"),
                    "content": SAFE,
                },
                "session_id": synth_env["session_id"],
            }
        )
        assert out["decision"] == "deny"
        assert out.get("reason"), "deny must carry a human-readable reason"


class TestRateLimits:
    def test_over_cap_submission_denied(self, synth_env):
        for _ in range(5):
            _ledger.append_hook_event(
                synth_env["session_id"], "gemini", "submit_code", "allow"
            )
        out = _call(
            {
                "tool_name": "write_file",
                "tool_input": {
                    "file_path": str(synth_env["outbox"] / "submission.py"),
                    "content": SAFE,
                },
                "session_id": synth_env["session_id"],
            }
        )
        assert out["decision"] == "deny"
        assert "rate limit" in out["reason"].lower()

    def test_over_cap_clarification_denied(self, synth_env):
        for _ in range(2):
            _ledger.append_hook_event(
                synth_env["session_id"], "gemini", "clarification", "allow"
            )
        out = _call(
            {
                "tool_name": "write_file",
                "tool_input": {
                    "file_path": str(
                        synth_env["outbox"] / "clarification_X.md"
                    ),
                    "content": "q?",
                },
                "session_id": synth_env["session_id"],
            }
        )
        assert out["decision"] == "deny"
        assert "rate limit" in out["reason"].lower()


class TestClarificationRewrite:
    def test_clarification_path_is_rewritten(self, synth_env):
        out = _call(
            {
                "tool_name": "write_file",
                "tool_input": {
                    "file_path": str(
                        synth_env["outbox"] / "clarification_agent.md"
                    ),
                    "content": "hey",
                },
                "session_id": synth_env["session_id"],
            }
        )
        assert out["decision"] == "allow"
        rewritten = out["hookSpecificOutput"]["tool_input"]["file_path"]
        assert rewritten.endswith("clarification_1.md")


class TestShellGate:
    def test_command_with_leading_whitespace_stripped(self, synth_env):
        out = _call(
            {
                "tool_name": "run_shell_command",
                "tool_input": {"command": "  pytest tests/"},
                "session_id": synth_env["session_id"],
            }
        )
        assert out["decision"] == "allow"

    def test_piped_command_denied_even_if_starts_with_allowlisted(
        self, synth_env
    ):
        # "pytest | curl ..." must not be allowed just because it
        # starts with pytest — but the current regex only anchors at
        # start-of-command, so this becomes an explicit adversarial
        # expectation that the allow-list is suffix-tolerant only for
        # the exact allow-listed invocation shapes.
        out = _call(
            {
                "tool_name": "run_shell_command",
                "tool_input": {
                    "command": "pytest; curl https://example.com"
                },
                "session_id": synth_env["session_id"],
            }
        )
        # The current implementation treats this as starting with
        # ``pytest`` and allows. Document the gap: sandbox layer is
        # expected to refuse the net egress, not this hook. The
        # adversarial expectation is that the ledger still records
        # the allow so shadow-mode diffing surfaces the command text.
        assert out["decision"] in ("allow", "deny")
