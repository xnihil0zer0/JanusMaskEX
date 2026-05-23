# ----- synthesize_with_retries -----
"""Verification oracle for harness.ast_retry.synthesize_with_retries."""
from pathlib import Path

import pytest

from harness.ast_retry import synthesize_with_retries


def test_synthesize_with_retries_success_first_attempt():
    """Valid code on the first try returns (True, code, []) with one agent call."""
    calls = []

    def run_agent(agent_name, prompt, config, state_dir, round_number, phase_name):
        calls.append(prompt)
        return "valid code"

    def validate(code, task):
        return True, []

    success, code, violations = synthesize_with_retries(
        "agent", "base", {}, Path("/tmp"), 1, {"t": 1}, run_agent, validate
    )

    assert success is True
    assert code == "valid code"
    assert violations == []
    assert len(calls) == 1


def test_synthesize_with_retries_passes_correct_args_to_run_agent():
    """The agent is invoked with the documented positional args and phase_name='synthesis'."""
    captured = {}

    def run_agent(agent_name, prompt, config, state_dir, round_number, phase_name):
        captured["agent_name"] = agent_name
        captured["prompt"] = prompt
        captured["config"] = config
        captured["state_dir"] = state_dir
        captured["round_number"] = round_number
        captured["phase_name"] = phase_name
        return "code"

    def validate(code, task):
        return True, []

    cfg = {"synthesis": {"max_ast_retries": 3}}
    sd = Path("/some/dir")
    synthesize_with_retries("myagent", "myprompt", cfg, sd, 5, {"task": "x"}, run_agent, validate)

    assert captured["agent_name"] == "myagent"
    assert captured["prompt"] == "myprompt"
    assert captured["config"] is cfg
    assert captured["state_dir"] == sd
    assert captured["round_number"] == 5
    assert captured["phase_name"] == "synthesis"


def test_synthesize_with_retries_validate_receives_code_and_task():
    """validate_code_func is handed the agent's code and the original task."""
    captured = {}

    def run_agent(agent_name, prompt, config, state_dir, round_number, phase_name):
        return "thecode"

    def validate(code, task):
        captured["code"] = code
        captured["task"] = task
        return True, []

    mytask = {"name": "demo"}
    synthesize_with_retries("a", "p", {}, Path("/tmp"), 0, mytask, run_agent, validate)

    assert captured["code"] == "thecode"
    assert captured["task"] is mytask


def test_synthesize_with_retries_success_after_validation_failure():
    """A first invalid attempt is retried; the retry prompt carries the violations and base prompt."""
    prompts = []
    codes = ["bad", "good"]
    call = {"n": 0}

    def run_agent(agent_name, prompt, config, state_dir, round_number, phase_name):
        prompts.append(prompt)
        c = codes[call["n"]]
        call["n"] += 1
        return c

    def validate(code, task):
        if code == "good":
            return True, []
        return False, ["E1: bad thing"]

    success, code, violations = synthesize_with_retries(
        "a", "BASE", {}, Path("/tmp"), 0, {}, run_agent, validate
    )

    assert success is True
    assert code == "good"
    assert violations == []
    assert len(prompts) == 2
    assert prompts[0] == "BASE"
    assert prompts[1].startswith("BASE")
    assert "[Retry attempt 1/3]" in prompts[1]
    assert "Code validation failed with the following issues:" in prompts[1]
    assert "- E1: bad thing" in prompts[1]
    assert "Please fix these issues and regenerate the code." in prompts[1]


def test_synthesize_with_retries_exhausts_retries_returns_false():
    """When validation never passes, returns (False, last_code, last_violations) after max attempts."""
    prompts = []

    def run_agent(agent_name, prompt, config, state_dir, round_number, phase_name):
        prompts.append(prompt)
        return "bad code"

    def validate(code, task):
        return False, ["v"]

    success, code, violations = synthesize_with_retries(
        "a", "BASE", {"synthesis": {"max_ast_retries": 3}}, Path("/tmp"), 0, {}, run_agent, validate
    )

    assert success is False
    assert code == "bad code"
    assert violations == ["v"]
    assert len(prompts) == 3


def test_synthesize_with_retries_respects_max_ast_retries_config():
    """A configured max_ast_retries of 1 limits the loop to a single attempt."""
    count = {"n": 0}

    def run_agent(agent_name, prompt, config, state_dir, round_number, phase_name):
        count["n"] += 1
        return "bad"

    def validate(code, task):
        return False, ["x"]

    success, code, violations = synthesize_with_retries(
        "a", "p", {"synthesis": {"max_ast_retries": 1}}, Path("/tmp"), 0, {}, run_agent, validate
    )

    assert success is False
    assert count["n"] == 1


def test_synthesize_with_retries_defaults_max_retries_to_three():
    """With no synthesis config, the loop defaults to three attempts."""
    count = {"n": 0}

    def run_agent(agent_name, prompt, config, state_dir, round_number, phase_name):
        count["n"] += 1
        return "bad"

    def validate(code, task):
        return False, []

    success, code, violations = synthesize_with_retries(
        "a", "p", {}, Path("/tmp"), 0, {}, run_agent, validate
    )

    assert success is False
    assert count["n"] == 3


def test_synthesize_with_retries_timeout_appends_message_and_continues():
    """A None result (timeout) appends a timeout note to the prompt and retries."""
    prompts = []
    seq = [None, "good"]
    call = {"n": 0}

    def run_agent(agent_name, prompt, config, state_dir, round_number, phase_name):
        prompts.append(prompt)
        r = seq[call["n"]]
        call["n"] += 1
        return r

    def validate(code, task):
        return True, []

    success, code, violations = synthesize_with_retries(
        "a", "BASE", {}, Path("/tmp"), 0, {}, run_agent, validate
    )

    assert success is True
    assert code == "good"
    assert len(prompts) == 2
    assert prompts[0] == "BASE"
    assert "[Retry attempt 1/3]" in prompts[1]
    assert "Previous attempt timed out." in prompts[1]


def test_synthesize_with_retries_all_timeouts_returns_none_code():
    """If every attempt times out, returns (False, None, []) and never validates."""
    count = {"n": 0}

    def run_agent(agent_name, prompt, config, state_dir, round_number, phase_name):
        count["n"] += 1
        return None

    def validate(code, task):
        raise AssertionError("validate must not be called when code is None")

    success, code, violations = synthesize_with_retries(
        "a", "p", {}, Path("/tmp"), 0, {}, run_agent, validate
    )

    assert success is False
    assert code is None
    assert violations == []
    assert count["n"] == 3


def test_synthesize_with_retries_returns_last_violations_on_failure():
    """The returned violations come from the final validation attempt, not earlier ones."""
    call = {"n": 0}
    violations_seq = [["first"], ["second"], ["third"]]

    def run_agent(agent_name, prompt, config, state_dir, round_number, phase_name):
        return "code"

    def validate(code, task):
        v = violations_seq[call["n"]]
        call["n"] += 1
        return False, v

    success, code, violations = synthesize_with_retries(
        "a", "p", {}, Path("/tmp"), 0, {}, run_agent, validate
    )

    assert success is False
    assert violations == ["third"]


def test_synthesize_with_retries_accumulates_violations_in_prompt():
    """Each failed attempt appends its numbered violations, so later prompts contain all prior notes."""
    prompts = []
    call = {"n": 0}
    violations_seq = [["A"], ["B"], ["C"]]

    def run_agent(agent_name, prompt, config, state_dir, round_number, phase_name):
        prompts.append(prompt)
        return "code"

    def validate(code, task):
        v = violations_seq[call["n"]]
        call["n"] += 1
        return False, v

    synthesize_with_retries("a", "BASE", {}, Path("/tmp"), 0, {}, run_agent, validate)

    assert len(prompts) == 3
    assert prompts[0] == "BASE"
    assert "[Retry attempt 1/3]" in prompts[1]
    assert "- A" in prompts[1]
    assert "[Retry attempt 1/3]" in prompts[2]
    assert "[Retry attempt 2/3]" in prompts[2]
    assert "- A" in prompts[2]
    assert "- B" in prompts[2]
