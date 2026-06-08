"""RED oracle pinning overseer/driver.run_turn to the REAL claude stream shapes.

The live ``claude -p --output-format stream-json --include-partial-messages``
output does NOT emit bare top-level ``content_block_delta`` events. The partial
message deltas/blocks are NESTED under a ``stream_event`` envelope, the complete
message arrives as an ``assistant`` event (``message.content`` = list of blocks),
and a terminal ``result`` event carries the authoritative answer + session id.
The old fixture fed bare top-level deltas, so the unit test stayed GREEN against a
fiction while the live chat panel returned "(no output)" (text == "").

Source-of-truth rule pinned here: the terminal ``assistant`` text (then the
``result`` text) is preferred over the accumulated ``stream_event`` deltas, so a
parser that misses some deltas still returns the complete message; deltas alone
suffice when no terminal text exists; the agy bare-``assistant`` (top-level string
``content``) shape keeps working. See the captured evidence at
_autowork_archive/overseer_no_output_evidence/real_claude_stream_sample.jsonl.
"""
import pytest

from overseer.driver import run_turn, AssistantTurn


# --- injected fakes -------------------------------------------------------

class FakeRunner:
    def __init__(self, lines):
        self.lines = lines

    def __call__(self, argv, *, env=None, stdin=None, **kw):
        return list(self.lines)


def _jail(cmd, **kw):
    return list(cmd)


def _env(*a, **k):
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


def _run(lines, conversation=None, **kw):
    return run_turn(
        conversation or _conversation(),
        kw.pop("text", "hi"),
        runner=FakeRunner(lines),
        env_builder=_env,
        jail_builder=_jail,
        stream_parser=FakeParser(),
        **kw,
    )


INIT = '{"type":"system","subtype":"init","session_id":"NEWSID"}'


# --- text recovery from each of the three real sources --------------------

def test_text_recovered_from_stream_event_wrapped_text_delta():
    # The ONLY text source is the stream_event-nested text_delta stream
    # (no terminal assistant/result event present).
    lines = [
        INIT,
        '{"type":"stream_event","event":{"type":"content_block_delta","index":0,'
        '"delta":{"type":"text_delta","text":"HEL"}}}',
        '{"type":"stream_event","event":{"type":"content_block_delta","index":0,'
        '"delta":{"type":"text_delta","text":"LO"}}}',
    ]
    out = _run(lines)
    assert isinstance(out, AssistantTurn)
    assert out.text == "HELLO"
    assert out.session_id == "NEWSID"


def test_text_recovered_from_assistant_event_when_no_deltas():
    # No stream_event deltas at all — only the complete assistant message,
    # whose content is a LIST of blocks (claude shape).
    lines = [
        INIT,
        '{"type":"assistant","message":{"role":"assistant","content":'
        '[{"type":"text","text":"HELLO"}]}}',
    ]
    out = _run(lines)
    assert out.text == "HELLO"


def test_text_recovered_from_result_event_as_last_resort():
    # Neither deltas nor an assistant event — only the terminal result.
    lines = [
        INIT,
        '{"type":"result","subtype":"success","is_error":false,'
        '"result":"HELLO","session_id":"NEWSID"}',
    ]
    out = _run(lines)
    assert out.text == "HELLO"


def test_terminal_assistant_text_preferred_over_partial_deltas():
    # Single source of truth: when both partial deltas AND a complete assistant
    # message exist, the complete message wins (a parser that dropped a delta
    # still returns the whole answer — no double-counting / truncation).
    lines = [
        INIT,
        '{"type":"stream_event","event":{"type":"content_block_delta","index":0,'
        '"delta":{"type":"text_delta","text":"HEL"}}}',  # missing the tail delta
        '{"type":"assistant","message":{"role":"assistant","content":'
        '[{"type":"text","text":"HELLO"}]}}',
        '{"type":"result","subtype":"success","is_error":false,'
        '"result":"HELLO","session_id":"NEWSID"}',
    ]
    out = _run(lines)
    assert out.text == "HELLO"


# --- tool_use collection from the nested envelope -------------------------

def test_tool_use_collected_from_stream_event_content_block_start():
    lines = [
        INIT,
        '{"type":"stream_event","event":{"type":"content_block_start","index":0,'
        '"content_block":{"type":"tool_use","id":"t1","name":"Read",'
        '"input":{"file":"x"}}}}',
    ]
    out = _run(lines)
    assert any(tu.get("name") == "Read" for tu in out.tool_uses)


# --- the live sink still relays nested deltas -----------------------------

def test_sink_relays_stream_event_wrapped_deltas():
    sink_chunks = []
    lines = [
        INIT,
        '{"type":"stream_event","event":{"type":"content_block_delta","index":0,'
        '"delta":{"type":"text_delta","text":"HEL"}}}',
        '{"type":"stream_event","event":{"type":"content_block_delta","index":0,'
        '"delta":{"type":"text_delta","text":"LO"}}}',
    ]
    _run(lines, sink=sink_chunks.append)
    assert "".join(sink_chunks) == "HELLO"


# --- agy bare-assistant shape must NOT regress ----------------------------

def test_agy_bare_assistant_string_content_still_works():
    # agy emits a complete assistant event whose `content` is a bare STRING at
    # the TOP level (no `message` wrapper, no block list). Keep it working.
    lines = [
        '{"type":"init","session_id":"AGY1"}',
        '{"type":"assistant","content":"hi there"}',
    ]
    out = _run(lines, _conversation(agent_backend="agy", model=None))
    assert out.session_id == "AGY1"
    assert out.text == "hi there"


# --- session id still captured from init ----------------------------------

def test_session_id_captured_from_init_event():
    out = _run([INIT])
    assert out.session_id == "NEWSID"


# --- the full real-evidence sample folds to the answer --------------------

def test_real_evidence_sample_folds_to_answer():
    import os
    path = os.path.join(
        os.path.dirname(__file__), "..", "..",
        "_autowork_archive", "overseer_no_output_evidence",
        "real_claude_stream_sample.jsonl",
    )
    if not os.path.exists(path):
        pytest.skip("captured evidence sample not present")
    with open(path) as fh:
        lines = [ln for ln in fh.read().splitlines() if ln.strip()]
    out = _run(lines)
    assert out.text == "HELLO"
    assert out.session_id == "28097c97-d0eb-428f-b068-1f64e0dc8355"
