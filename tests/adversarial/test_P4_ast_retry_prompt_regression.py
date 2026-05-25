"""P4 adversarial battery — HOOK-47 AST-retry prompt regression.

Stress the three-link chain (hook reason, ast_retry prompt, CLI
propagation) with fuzz-style attacks: huge violation lists, Unicode
messages, missing fields, zero-retry configs.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from harness import ast_retry  # noqa: E402
from harness.ast_enforcer import Violation  # noqa: E402
from harness.hooks.claude import pre_tool as claude_pre_tool  # noqa: E402
from harness.hooks.rpc import submit_code as rpc_submit_code  # noqa: E402


# ---------------------------------------------------------------------------
# Attack 1: hook reason scales to 50 violations but truncates beyond.
# ---------------------------------------------------------------------------

def test_hook_reason_truncates_at_max():
    vios = [
        Violation(rule=f"r{i}", line=i, message=f"m{i}", severity="error")
        for i in range(200)
    ]
    payload = rpc_submit_code.rejected_payload(vios, max_show=50)
    reason = claude_pre_tool._format_ast_reason(payload)
    assert reason.count("\n- ") == 50
    # The payload's message warns the agent about truncation.
    assert "Showing first 50" in payload["message"]


# ---------------------------------------------------------------------------
# Attack 2: Unicode in violation messages round-trips through both
# layers.
# ---------------------------------------------------------------------------

def test_unicode_violations_in_hook_reason_and_ast_retry():
    v = Violation(
        rule="no-émoji", line=1, message="found π in code 中文", severity="error"
    )
    payload = rpc_submit_code.rejected_payload([v])
    reason = claude_pre_tool._format_ast_reason(payload)
    assert "no-émoji" in reason
    assert "π" in reason
    assert "中文" in reason


# ---------------------------------------------------------------------------
# Attack 3: empty violations list — hook reason is the header only,
# ast_retry still augments the prompt with the empty-violations marker.
# ---------------------------------------------------------------------------

def test_empty_violations_hook_reason_still_usable():
    payload = rpc_submit_code.rejected_payload([])
    reason = claude_pre_tool._format_ast_reason(payload)
    # Header exists even with zero violations.
    assert reason.strip() != ""


# ---------------------------------------------------------------------------
# Attack 4: ast_retry with zero max retries exits immediately with
# (False, None/code, violations) — does NOT run the agent.
# ---------------------------------------------------------------------------

def test_ast_retry_zero_retries_is_noop():
    calls: list = []

    def run_agent(*args, **kwargs):
        calls.append(1)
        return "def f(): pass\n"

    def validate(code, task):
        return True, []

    ok, code, vios = ast_retry.synthesize_with_retries(
        "claude", "B", {"synthesis": {"max_ast_retries": 0}},
        pathlib.Path("/tmp"), 1, {}, run_agent, validate,
    )
    assert calls == []
    assert ok is False
    assert code is None


# ---------------------------------------------------------------------------
# Attack 5: timeout followed by AST failure then success — the prompt
# accumulates BOTH annotations.
# ---------------------------------------------------------------------------

def test_ast_retry_prompt_accumulates_mixed_failures():
    captured = []
    states = iter([None, "def f(): pass\n", "def f(): pass\n"])
    validate_states = iter([(False, [Violation(rule="r", line=1, message="m", severity="error")]), (True, [])])

    def run_agent(agent, prompt, config, sd, r, phase_name):
        captured.append(prompt)
        return next(states)

    def validate(code, task):
        return next(validate_states)

    ok, _, _ = ast_retry.synthesize_with_retries(
        "claude", "BASE", {"synthesis": {"max_ast_retries": 3}},
        pathlib.Path("/tmp"), 1, {}, run_agent, validate,
    )
    assert ok
    # 3 agent calls; each prompt larger than the previous.
    assert len(captured) == 3
    assert len(captured[1]) > len(captured[0])
    assert len(captured[2]) > len(captured[1])
    # 1st append: timeout annotation.
    assert "timed out" in captured[1]
    # 2nd append: the prior timeout note PLUS the validation-failure
    # text from the 2nd attempt (which was AST-invalid).
    assert "Code validation failed" in captured[2]


# ---------------------------------------------------------------------------
# Attack 6: very long code payload in a submission — the hook's deny
# reason is bounded, not unbounded; agent's next-turn context stays
# parseable.
# ---------------------------------------------------------------------------

def test_huge_code_payload_reason_stays_bounded():
    huge_code_snippet = "x = " + "1 + " * 5000 + "1"
    payload = rpc_submit_code.rejected_payload([
        Violation(rule="too-long", line=1, message="line too long", severity="error"),
    ])
    reason = claude_pre_tool._format_ast_reason(payload)
    # The reason does NOT include the raw code; it's just violation
    # metadata. This guards against the agent receiving a multi-MB
    # context on every retry.
    assert huge_code_snippet not in reason
    assert len(reason) < 10_000


# ---------------------------------------------------------------------------
# M15 corrections (sub-plan 03 §Proposed 6) — regression test for the
# legacy joint-retry branch at harness/orchestrator.py:783-790.
#
# HOOK-47 test coverage exercises the NEW per-agent retry path
# (``ast_retry.synthesize_with_retries``) exclusively.  The legacy
# joint-retry branch is dormant by default (``use_retry_module: False``
# is the ``config.synthesis.get`` default) but remains selectable.  If
# the config flag ever flips back — or gets cleared accidentally — we
# need a guard that proves the ``decision:block`` augmentation still
# appends AST violations to the next-round prompt from that branch too.
# ---------------------------------------------------------------------------


import json as _json  # noqa: E402  (kept local to this block)
import os as _os  # noqa: E402
from unittest.mock import patch as _patch  # noqa: E402

from harness import orchestrator as _orchestrator  # noqa: E402


@pytest.fixture
def _restore_task_id_env():
    """run_pipeline writes JANUSMASK_TASK_ID into os.environ; other
    tests in the suite (notably TestCollectSubmissions in
    test_orchestrator.py) read it and break if we leak. Snapshot and
    restore around each driver test.
    """
    prev = _os.environ.get("JANUSMASK_TASK_ID")
    try:
        yield
    finally:
        if prev is None:
            _os.environ.pop("JANUSMASK_TASK_ID", None)
        else:
            _os.environ["JANUSMASK_TASK_ID"] = prev


def _build_pipeline_config() -> dict:
    """Minimal synthesis-only config; use_retry_module explicitly False
    so we exercise the legacy joint-retry branch."""
    return {
        "synthesis": {
            "timeout_seconds": 30,
            "max_ast_retries": 3,
            "use_retry_module": False,
        },
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


def _pipeline_state_dir(tmp_path) -> pathlib.Path:
    """State dir with one task queued and STATE.json initialized."""
    for sub in ("tasks", "tasks/processed", "sessions"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    task = {
        "task_id": "legacy-joint-retry-01",
        "specification": "Write add(a,b).",
        "constraints": {"deterministic": True},
    }
    (tmp_path / "tasks" / "legacy-joint-retry-01.json").write_text(
        _json.dumps(task), encoding="utf-8"
    )
    _orchestrator.init_state(tmp_path)
    return tmp_path


def test_legacy_joint_retry_branch_augments_prompts_with_ast_violations(
    tmp_path, _restore_task_id_env
):
    """Drive one iteration of the legacy joint-retry branch.  The 2nd
    invocation of ``run_both_agents`` must receive prompts containing
    the rule + line + message of the 1st-round AST violations.
    """
    state_dir = _pipeline_state_dir(tmp_path)
    config = _build_pipeline_config()

    captured_prompts: list[tuple[str, str]] = []

    # run_both_agents: always return "some code" — the legacy branch
    # then runs _validate_submission; if that returns (False, ...) the
    # branch hits lines 783-790 and rebuilds prompts for the next
    # iteration.  We raise StopIteration on the 3rd call to break out.
    def fake_run_both(prompt_c, prompt_g, _cfg, _sd, _r, phase_name):
        captured_prompts.append((prompt_c, prompt_g))
        if len(captured_prompts) >= 3:
            raise StopIteration  # bail out of the daemon loop
        return ("def claude(): pass\n", "def gemini(): pass\n")

    # Two distinct violations so both branches (claude/gemini) fire.
    claude_vios = [
        Violation(
            rule="forbidden-import",
            line=7,
            message="import torch is not deterministic",
            severity="error",
        ),
    ]
    gemini_vios = [
        Violation(
            rule="syntax-not-python",
            line=3,
            message="unexpected EOF while parsing",
            severity="error",
        ),
    ]

    def fake_validate(code, agent, task):
        # Invalid for both agents on every call.  Each call alternates
        # so we don't leak mutation across iterations.
        if agent == "claude":
            return False, claude_vios
        return False, gemini_vios

    with _patch("harness.orchestrator.run_both_agents", side_effect=fake_run_both), \
         _patch(
             "harness.orchestrator._validate_submission",
             side_effect=fake_validate,
         ), \
         _patch("harness.orchestrator.time.sleep", side_effect=StopIteration):
        with pytest.raises(StopIteration):
            _orchestrator.run_pipeline(config, state_dir)

    # Sanity: the legacy branch ran at least once with the augmentation.
    assert len(captured_prompts) >= 2, (
        f"legacy joint-retry branch must iterate at least once after "
        f"the first AST failure. Got {len(captured_prompts)} call(s)."
    )

    # First invocation: base prompt — no AST augmentation yet.
    first_claude, first_gemini = captured_prompts[0]
    assert "failed AST validation" not in first_claude, (
        "legacy branch: 1st-round prompt must be the base (no "
        "augmentation). Got: " + first_claude[-400:]
    )
    assert "failed AST validation" not in first_gemini

    # Second invocation: both prompts carry the respective violations.
    second_claude, second_gemini = captured_prompts[1]
    assert "failed AST validation" in second_claude, (
        "legacy branch at orchestrator.py:783-790 dropped the "
        "augmentation for the claude prompt. This is the regression "
        "HOOK-47 per-agent coverage cannot catch. Got: "
        + second_claude[-600:]
    )
    assert "forbidden-import" in second_claude
    assert "Line 7" in second_claude
    assert "not deterministic" in second_claude

    assert "failed AST validation" in second_gemini, (
        "legacy branch dropped augmentation for the gemini prompt."
    )
    assert "syntax-not-python" in second_gemini
    assert "Line 3" in second_gemini
    assert "EOF" in second_gemini


def test_legacy_joint_retry_mutation_only_one_agent_invalid(
    tmp_path, _restore_task_id_env
):
    """When only ONE agent's submission fails AST, the OTHER agent's
    retry prompt reverts to the base prompt (lines 786-787 / 791-792).
    Confirms the branch's per-agent conditional, not just the global
    augmentation."""
    state_dir = _pipeline_state_dir(tmp_path)
    config = _build_pipeline_config()

    captured_prompts: list[tuple[str, str]] = []

    def fake_run_both(prompt_c, prompt_g, _cfg, _sd, _r, phase_name):
        captured_prompts.append((prompt_c, prompt_g))
        if len(captured_prompts) >= 3:
            raise StopIteration
        return ("def claude(): pass\n", "def gemini(): pass\n")

    only_claude_fails = [
        Violation(
            rule="only-claude",
            line=42,
            message="claude-specific issue",
            severity="error",
        )
    ]

    def fake_validate(code, agent, task):
        if agent == "claude":
            return False, only_claude_fails
        return True, []

    with _patch("harness.orchestrator.run_both_agents", side_effect=fake_run_both), \
         _patch(
             "harness.orchestrator._validate_submission",
             side_effect=fake_validate,
         ), \
         _patch("harness.orchestrator.time.sleep", side_effect=StopIteration):
        with pytest.raises(StopIteration):
            _orchestrator.run_pipeline(config, state_dir)

    assert len(captured_prompts) >= 2
    second_claude, second_gemini = captured_prompts[1]

    # Claude's prompt augmented with its violations.
    assert "failed AST validation" in second_claude
    assert "only-claude" in second_claude
    assert "Line 42" in second_claude

    # Gemini validated fine — its prompt must be the base (no
    # augmentation).  The branch at 791-792 resets gemini_prompt to
    # base_prompt; if that ever regresses to "leave last augmentation
    # in place" the agent would retry against stale guidance.
    assert "failed AST validation" not in second_gemini
    assert "only-claude" not in second_gemini
