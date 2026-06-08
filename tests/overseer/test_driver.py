"""RED oracle for overseer/driver.py — the per-turn interactive loop.

The driver is a DETERMINISTIC shell around injected seams (runner/env_builder/
jail_builder/stream_parser/sink). It NEVER spawns a real process in tests. It
builds the claude argv (--resume to append, --fork-session to branch a rewind,
--model, --output-format stream-json, --include-partial-messages, --tools <mode
allowlist>), wraps it via jail_builder, spawns via the injected runner, extracts
the new session_id + accumulated text + tool-use events from the stream, and
relays deltas to an injected sink. Tool allowlist comes from mode_gate
(tool-withholding). Rewind reconstructs the prefix VERBATIM and forks (constraint 8).
"""
import pytest

from overseer.driver import run_turn, AssistantTurn


# --- injected fakes -------------------------------------------------------

CLAUDE_STREAM = [
    '{"type":"system","subtype":"init","session_id":"NEWSID"}',
    '{"type":"content_block_delta","delta":{"type":"text_delta","text":"Hello "}}',
    '{"type":"content_block_delta","delta":{"type":"text_delta","text":"world"}}',
    '{"type":"content_block_start","content_block":'
    '{"type":"tool_use","id":"t1","name":"Read","input":{"file":"x"}}}',
    '{"type":"result","subtype":"success","session_id":"NEWSID"}',
]


class FakeRunner:
    """Records the spawn and replays canned stream-json NDJSON lines."""

    def __init__(self, lines):
        self.lines = lines
        self.argv = None
        self.env = None
        self.stdin = None
        self.spawned = 0

    def __call__(self, argv, *, env=None, stdin=None, **kw):
        self.spawned += 1
        self.argv = list(argv)
        self.env = env
        self.stdin = stdin
        return list(self.lines)


def _identity_jail(cmd, **kwargs):
    # record-and-passthrough so the test can inspect the inner claude argv
    _identity_jail.calls.append((list(cmd), kwargs))
    return list(cmd)


_identity_jail.calls = []


def _fake_env(*a, **k):
    return {"FAKE_ENV": "1"}


class FakeParser:
    def __init__(self):
        self.events = []

    def handle_event(self, event):
        self.events.append(event)


def _conversation(**over):
    base = {
        "claude_session_id": "SID0",
        "current_mode": "observe",
        "model": "opus",
        "agent_backend": "claude",
        "transcript": [],
    }
    base.update(over)
    return base


def _run(conversation, text, runner, **kw):
    _identity_jail.calls = []
    return run_turn(
        conversation,
        text,
        runner=runner,
        env_builder=_fake_env,
        jail_builder=_identity_jail,
        stream_parser=FakeParser(),
        **kw,
    )


# --- tests ----------------------------------------------------------------

def test_returns_assistant_turn_with_session_text_and_tools():
    runner = FakeRunner(CLAUDE_STREAM)
    out = _run(_conversation(), "hi", runner)
    assert isinstance(out, AssistantTurn)
    assert out.session_id == "NEWSID"          # captured from the init event
    assert out.text == "Hello world"           # text deltas accumulated verbatim
    assert any(tu.get("name") == "Read" for tu in out.tool_uses)


def test_only_spawns_through_the_injected_runner():
    runner = FakeRunner(CLAUDE_STREAM)
    _run(_conversation(), "hi", runner)
    assert runner.spawned == 1  # the ONLY process path is the injected seam


def test_argv_carries_stream_flags_and_model():
    runner = FakeRunner(CLAUDE_STREAM)
    _run(_conversation(model="sonnet"), "hi", runner)
    argv = runner.argv
    assert "--output-format" in argv
    assert "stream-json" in argv
    assert "--include-partial-messages" in argv
    i = argv.index("--model")
    assert argv[i + 1] == "sonnet"


def test_argv_withholds_tools_via_mode_gate_allowlist():
    # The mode allowlist is enforced, but the abstract capability tokens
    # ('read'/'search'/...) are MAPPED to real claude tool names before they
    # reach --tools (see tests/overseer/test_driver_headless.py for the full
    # mapping contract). observe is read-only, so its --tools carries no Write.
    runner = FakeRunner(CLAUDE_STREAM)
    _run(_conversation(current_mode="observe"), "hi", runner)
    argv = runner.argv
    assert "--tools" in argv
    i = argv.index("--tools")
    names = set(argv[i + 1].split(","))
    assert "Read" in names            # 'read' capability -> Read tool
    assert "Write" not in names       # observe grants no write capability


def test_append_resumes_the_existing_session():
    runner = FakeRunner(CLAUDE_STREAM)
    _run(_conversation(claude_session_id="SID0"), "hi", runner)  # rewind_to_index=None
    argv = runner.argv
    i = argv.index("--resume")
    assert argv[i + 1] == "SID0"
    assert "--fork-session" not in argv


def test_first_turn_has_no_resume():
    runner = FakeRunner(CLAUDE_STREAM)
    _run(_conversation(claude_session_id=None), "hi", runner)
    assert "--resume" not in runner.argv


def test_rewind_forks_instead_of_resuming():
    # Constraint 8: a rewind branches into a fresh session (cache-preserving),
    # never an in-place mid-edit.
    runner = FakeRunner(CLAUDE_STREAM)
    conv = _conversation(transcript=[
        {"index": 0, "role": "user", "mode": "observe", "content": "a"},
        {"index": 1, "role": "assistant", "mode": "observe", "content": "b"},
        {"index": 2, "role": "user", "mode": "observe", "content": "c"},
    ])
    _run(conv, "redo from 1", runner, rewind_to_index=1)
    assert "--fork-session" in runner.argv


def test_jail_and_env_seams_are_used():
    runner = FakeRunner(CLAUDE_STREAM)
    _run(_conversation(), "hi", runner)
    assert _identity_jail.calls, "driver must wrap the command via jail_builder"
    assert runner.env == {"FAKE_ENV": "1"}  # env came from the injected builder


def test_stream_parser_seam_receives_every_event():
    parser = FakeParser()
    runner = FakeRunner(CLAUDE_STREAM)
    _identity_jail.calls = []
    run_turn(
        _conversation(), "hi",
        runner=runner, env_builder=_fake_env, jail_builder=_identity_jail,
        stream_parser=parser,
    )
    assert len(parser.events) == len(CLAUDE_STREAM)


def test_sink_receives_streamed_deltas_for_sse_relay():
    sink_lines = []
    runner = FakeRunner(CLAUDE_STREAM)
    _identity_jail.calls = []
    run_turn(
        _conversation(), "hi",
        runner=runner, env_builder=_fake_env, jail_builder=_identity_jail,
        stream_parser=FakeParser(), sink=sink_lines.append,
    )
    assert sink_lines, "driver must write streamed deltas to the injected sink"


def test_agy_backend_uses_stdin_and_no_model_flag():
    agy_stream = ['{"type":"init","session_id":"AGY1"}',
                  '{"type":"assistant","content":"hi there"}']
    runner = FakeRunner(agy_stream)
    out = _run(_conversation(agent_backend="agy", model=None), "drive me", runner)
    assert "--model" not in runner.argv          # agy self-selects, no model knob
    assert runner.stdin is not None and "drive me" in runner.stdin
    assert isinstance(out, AssistantTurn)
