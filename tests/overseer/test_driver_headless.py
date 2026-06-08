"""RED oracle for the overseer driver HEADLESS-argv fix (overseer/driver.py).

Context: the chat panel produced an EMPTY assistant turn ("(no output)") for
every prompt. Root cause: ``overseer.driver._build_argv`` built a claude argv
that was NOT a working headless invocation -- it omitted ``-p`` (so claude
emitted only the init event, captured the session id, but never processed the
stdin prompt) and ``--verbose`` (required with ``--output-format stream-json``
in print mode), and it handed the abstract mode-capability tokens
('read'/'search'/'write') straight to ``--tools`` space-joined, none of which is
a real claude tool name, so even a working spawn had no usable tools.

This oracle pins the FIX: a claude-backend argv must mirror the harness's
canonical spawn (harness/config.yaml agents.claude.args + orchestrator's
acceptEdits): ``-p``, ``--verbose``, real comma-joined claude tool names mapped
from the mode allowlist, ``--permission-mode acceptEdits``, and the per-mode
system prompt injected via ``--append-system-prompt``. The agy backend keeps its
prompt-on-stdin, no-model, no-claude-knobs shape.

The driver still NEVER spawns a real process here -- every seam is injected.
"""
import pytest

from overseer.driver import run_turn, AssistantTurn


CLAUDE_STREAM = [
    '{"type":"system","subtype":"init","session_id":"NEWSID"}',
    '{"type":"content_block_delta","delta":{"type":"text_delta","text":"hi"}}',
    '{"type":"result","subtype":"success","session_id":"NEWSID"}',
]


class FakeRunner:
    def __init__(self, lines):
        self.lines = lines
        self.argv = None
        self.stdin = None

    def __call__(self, argv, *, env=None, stdin=None, **kw):
        self.argv = list(argv)
        self.stdin = stdin
        return list(self.lines)


def _identity_jail(cmd, **kwargs):
    return list(cmd)


def _fake_env(*a, **k):
    return {"FAKE_ENV": "1"}


class FakeParser:
    def handle_event(self, event):
        pass


def _conversation(**over):
    base = {
        "claude_session_id": None,
        "current_mode": "brief-author",
        "model": "opus",
        "agent_backend": "claude",
        "transcript": [],
    }
    base.update(over)
    return base


def _run(conversation, text, runner, **kw):
    return run_turn(
        conversation, text,
        runner=runner, env_builder=_fake_env, jail_builder=_identity_jail,
        stream_parser=FakeParser(), **kw,
    )


# --- the FIX contract -----------------------------------------------------

def test_argv_is_headless_print_mode():
    """-p is the load-bearing fix: without it claude never processes stdin."""
    runner = FakeRunner(CLAUDE_STREAM)
    _run(_conversation(), "author a brief", runner)
    assert "-p" in runner.argv


def test_argv_carries_verbose_for_stream_json():
    runner = FakeRunner(CLAUDE_STREAM)
    _run(_conversation(), "x", runner)
    argv = runner.argv
    assert "--verbose" in argv
    assert "--output-format" in argv and "stream-json" in argv


def test_argv_maps_abstract_tools_to_real_claude_names():
    """brief-author's ('read','search','write') -> real claude tool names,
    comma-joined into a single --tools value (NOT space-joined abstract tokens)."""
    runner = FakeRunner(CLAUDE_STREAM)
    _run(_conversation(current_mode="brief-author"), "x", runner)
    argv = runner.argv
    i = argv.index("--tools")
    value = argv[i + 1]
    names = set(value.split(","))
    # mapped real names present...
    assert {"Read", "Grep", "Write"} <= names
    # ...and NO abstract leakage
    assert "read" not in names and "search" not in names and "write" not in names


def test_argv_sets_accept_edits_permission_mode():
    runner = FakeRunner(CLAUDE_STREAM)
    _run(_conversation(), "x", runner)
    argv = runner.argv
    i = argv.index("--permission-mode")
    assert argv[i + 1] == "acceptEdits"


def test_argv_injects_mode_system_prompt():
    """The per-mode procedure context must reach the agent via
    --append-system-prompt so the agent knows which mode constrains it."""
    runner = FakeRunner(CLAUDE_STREAM)
    _run(_conversation(current_mode="brief-author"), "x", runner)
    argv = runner.argv
    assert "--append-system-prompt" in argv
    i = argv.index("--append-system-prompt")
    prompt = argv[i + 1]
    assert "brief-author" in prompt


def test_observe_mode_maps_read_only_tools():
    runner = FakeRunner(CLAUDE_STREAM)
    _run(_conversation(current_mode="observe"), "x", runner)
    argv = runner.argv
    i = argv.index("--tools")
    names = set(argv[i + 1].split(","))
    assert "Read" in names           # 'read' -> Read
    assert "Write" not in names      # observe is read-only; no write capability


def test_agy_backend_keeps_stdin_and_omits_claude_knobs():
    agy_stream = ['{"type":"init","session_id":"AGY1"}',
                  '{"type":"assistant","content":"hi"}']
    runner = FakeRunner(agy_stream)
    out = _run(_conversation(agent_backend="agy", model=None), "drive me", runner)
    assert "--model" not in runner.argv
    assert "--permission-mode" not in runner.argv
    assert "--append-system-prompt" not in runner.argv
    assert runner.stdin is not None and "drive me" in runner.stdin
    assert isinstance(out, AssistantTurn)


def test_resume_and_fork_preserved():
    runner = FakeRunner(CLAUDE_STREAM)
    _run(_conversation(claude_session_id="SID0"), "x", runner)
    argv = runner.argv
    assert argv[argv.index("--resume") + 1] == "SID0"
    assert "--fork-session" not in argv

    runner2 = FakeRunner(CLAUDE_STREAM)
    conv = _conversation(transcript=[
        {"index": 0, "role": "user", "content": "a"},
        {"index": 1, "role": "assistant", "content": "b"},
    ])
    _run(conv, "redo", runner2, rewind_to_index=0)
    assert "--fork-session" in runner2.argv
