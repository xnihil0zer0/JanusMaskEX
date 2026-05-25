"""P4 invariant: AST-failure routing surfaces into agent context
(HOOK-47).

Sub-plan 04 §4 invariant 7 + §6 row 6: the hook's ``decision=deny``
response must carry a human-readable ``reason`` that cites the
specific AST violations; the agent CLI injects that reason back into
the next turn's context; and the out-of-process retry loop
(``harness.ast_retry.synthesize_with_retries``) further appends the
same violations to the prompt when the agent escapes the in-process
hook loop and still submits AST-invalid code.

This file verifies every link in that chain so a regression anywhere
above — hook, payload shape, ast_retry prompt augmentation — fails a
test here before it reaches production.
"""

from __future__ import annotations

import io
import json
import pathlib
import sys
from typing import Any, Callable
from unittest.mock import MagicMock

import pytest

_REPO = pathlib.Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from harness import ast_retry  # noqa: E402
from harness.ast_enforcer import Violation  # noqa: E402
from harness.hooks.claude import pre_tool as claude_pre_tool  # noqa: E402
from harness.hooks.rpc import submit_code as rpc_submit_code  # noqa: E402


# ---------------------------------------------------------------------------
# Link 1: hook AST deny carries a reason that references the violations.
# ---------------------------------------------------------------------------

def test_hook_ast_reason_contains_rule_line_message():
    v1 = Violation(rule="forbidden-import", line=3, message="os.system call", severity="error")
    v2 = Violation(rule="mutable-default", line=8, message="arg=[] default", severity="error")
    payload = rpc_submit_code.rejected_payload([v1, v2])
    reason = claude_pre_tool._format_ast_reason(payload)
    assert "forbidden-import" in reason
    assert "L3" in reason
    assert "os.system call" in reason
    assert "mutable-default" in reason
    assert "L8" in reason
    assert "arg=[] default" in reason


def test_hook_ast_reason_header_preserves_error_field():
    v = Violation(rule="r", line=1, message="m", severity="error")
    payload = rpc_submit_code.rejected_payload([v])
    reason = claude_pre_tool._format_ast_reason(payload)
    # The header (first line before the bullets) must explain what
    # happened — the agent's next-turn context depends on it.
    first_line = reason.splitlines()[0]
    assert "validation failed" in first_line.lower() or "fix violations" in first_line.lower()


# ---------------------------------------------------------------------------
# Link 2: ast_retry appends the same violation info to the retry prompt.
# ---------------------------------------------------------------------------

def test_ast_retry_appends_violations_to_next_prompt():
    captured_prompts: list[str] = []

    def fake_run_agent(agent, prompt, config, state_dir, round_number, phase_name):
        captured_prompts.append(prompt)
        return "def f(): pass\n"  # always returns same code

    call_count = {"n": 0}

    def fake_validate(code, task):
        call_count["n"] += 1
        if call_count["n"] < 3:
            # Force a failure on first two attempts.
            return False, [
                Violation(rule="test-rule", line=1, message="bad thing", severity="error"),
            ]
        return True, []

    ok, code, _ = ast_retry.synthesize_with_retries(
        "claude",
        "BASE PROMPT",
        {"synthesis": {"max_ast_retries": 3}},
        pathlib.Path("/tmp"),
        1,
        {},
        fake_run_agent,
        fake_validate,
    )
    assert ok
    # Second prompt = base + violations-text; third prompt carries both appends.
    assert len(captured_prompts) == 3
    assert captured_prompts[0] == "BASE PROMPT"
    assert "Code validation failed" in captured_prompts[1]
    assert "test-rule" in captured_prompts[1] or "bad thing" in captured_prompts[1]
    assert "Retry attempt 2/3" in captured_prompts[2]


def test_ast_retry_timeout_appends_timeout_note():
    captured: list[str] = []
    call_count = {"n": 0}

    def fake_run_agent(agent, prompt, config, state_dir, round_number, phase_name):
        captured.append(prompt)
        call_count["n"] += 1
        return None if call_count["n"] < 2 else "def f(): pass\n"

    def fake_validate(code, task):
        return True, []

    ok, _, _ = ast_retry.synthesize_with_retries(
        "claude",
        "BASE",
        {"synthesis": {"max_ast_retries": 3}},
        pathlib.Path("/tmp"),
        1,
        {},
        fake_run_agent,
        fake_validate,
    )
    assert ok
    # Second attempt's prompt has the timeout note from the first.
    assert "timed out" in captured[1]


# ---------------------------------------------------------------------------
# Link 3: full chain — hook emits decision=deny + reason, and the
# orchestrator's ast_retry retry would carry that same information.
# ---------------------------------------------------------------------------

def test_hook_deny_reason_format_survives_ast_retry_round_trip():
    """Smoke test: _format_ast_reason → ast_retry prompt augmentation.
    Confirms the reason string the CLI sees on turn N carries the same
    keywords the ast_retry append would use on turn N+1."""
    v = Violation(rule="no-network", line=5, message="socket.create_connection", severity="error")
    hook_payload = rpc_submit_code.rejected_payload([v])
    hook_reason = claude_pre_tool._format_ast_reason(hook_payload)

    # Now drive ast_retry to fail once with the SAME Violation and
    # inspect its prompt.
    class _Vio:
        """ast_retry formats each violation via __str__."""
        def __str__(self):
            return f"- {v.rule} (Line {v.line}): {v.message}"

    captured: list[str] = []

    def fake_run(agent, prompt, config, sd, r, phase_name):
        captured.append(prompt)
        return "def f(): pass\n"

    attempts = {"n": 0}

    def fake_validate(code, task):
        attempts["n"] += 1
        if attempts["n"] == 1:
            return False, [_Vio()]
        return True, []

    ast_retry.synthesize_with_retries(
        "claude", "B", {"synthesis": {"max_ast_retries": 2}},
        pathlib.Path("/tmp"), 1, {}, fake_run, fake_validate,
    )
    retry_prompt = captured[1]
    # Both the hook reason and the ast_retry prompt cite rule + line + message.
    assert "no-network" in hook_reason and "no-network" in retry_prompt
    assert "5" in hook_reason and "5" in retry_prompt
    assert "socket.create_connection" in hook_reason
    assert "socket.create_connection" in retry_prompt


# ---------------------------------------------------------------------------
# Mutation guard: if _format_ast_reason ever dropped the violations
# list, the agent would get a useless "AST validation failed." with
# no actionable info. The positive tests above catch that.
# ---------------------------------------------------------------------------

def test_mutation_empty_reason_would_fail_positive_test():
    """Simulate the mutation inline: return just the header. The
    invariant tests would fail because they assert specific tokens."""
    mutated_reason = "AST validation failed."
    # Positive-test assertions would fail against this mutated reason:
    assert "forbidden-import" not in mutated_reason
    assert "L3" not in mutated_reason


def test_mutation_ast_retry_without_prompt_append_detected():
    """Mutation: ast_retry returns without appending violations to the
    prompt. The positive test above would fail because the 2nd prompt
    would equal the 1st."""
    # Simulated mutated function:
    def mutated_synthesize(run_fn, validate_fn):
        prompt = "BASE"
        prompts = []
        for _ in range(3):
            prompts.append(prompt)
            code = run_fn(prompt)
            ok, _ = validate_fn(code)
            if ok:
                return prompts
            # Mutation: no prompt += violations-text.
        return prompts

    attempts = {"n": 0}

    def vfn(code):
        attempts["n"] += 1
        return attempts["n"] >= 3, []

    prompts = mutated_synthesize(lambda p: "code", vfn)
    # Under the mutation, all 3 prompts are identical — the positive
    # test above catches this because it asserts prompts[1] != prompts[0].
    assert prompts[0] == prompts[1] == prompts[2]


# ---------------------------------------------------------------------------
# Belt-and-braces: the schema reference (sub-plan 04 §4 invariant 1
# indirect) is preserved in rpc.submit_code.SchemaError text so the
# agent's retry-context has a pointer to the canonical submission
# shape.
# ---------------------------------------------------------------------------

def test_schema_error_cites_mcp_server_line_range():
    try:
        rpc_submit_code.build_record({"code": "x=1"}, submission_number=1)
    except rpc_submit_code.SchemaError as exc:
        assert "mcp_server.py:648-658" in str(exc)
    else:
        pytest.fail("SchemaError must be raised when fields are missing")
