"""RED oracle for the chat history endpoints (overseer/web_api.py).

chat_list() exposes SessionStore.list_conversations summaries so the WebUI can
browse past sessions; chat_load(cid) returns a full conversation so a selected
session can be loaded back into the chat panel. Both are pure read paths over the
injected store -- no driver/agent/subprocess.
"""
import json

import pytest

from overseer.session_store import SessionStore
from overseer.web_api import OverseerWebApi


@pytest.fixture
def api(tmp_path):
    return OverseerWebApi(SessionStore(store_path=tmp_path / "sessions.json"))


def test_chat_list_empty(api):
    out = api.chat_list()
    json.dumps(out)
    assert out == {"conversations": []}


def test_chat_list_returns_session_summaries(api):
    a = api.chat_send({"text": "first session", "mode": "brief-author"})["conversation_id"]
    b = api.chat_send({"text": "second session"})["conversation_id"]
    out = api.chat_list()
    convs = out["conversations"]
    ids = [c["conversation_id"] for c in convs]
    assert set(ids) == {a, b}
    # each summary carries the browsable metadata
    for c in convs:
        assert "current_mode" in c and "turn_count" in c and "preview" in c


def test_chat_load_returns_full_transcript_and_mode(api):
    cid = api.chat_send({"text": "load me back", "mode": "brief-author"})["conversation_id"]
    out = api.chat_load(cid)
    json.dumps(out)
    assert out["conversation_id"] == cid
    assert out["current_mode"] == "brief-author"
    assert any(t["content"] == "load me back" and t["role"] == "user"
               for t in out["turns"])


def test_chat_load_unknown_conversation_raises(api):
    with pytest.raises(KeyError):
        api.chat_load("nope")
