"""RED oracle for SessionStore.list_conversations (overseer/session_store.py).

Backs the browsable chat-session history: a deterministic summary of every
stored conversation so the WebUI can list past sessions and load one back into
the chat panel. Each summary is a plain JSON-able dict carrying the id, current
mode, turn count, and a short preview (first user turn). Order is the store's
insertion order (dict order), and the method must not mutate the store.
"""
import json

import pytest

from overseer.session_store import SessionStore


@pytest.fixture
def store(tmp_path):
    return SessionStore(store_path=tmp_path / "sessions.json")


def _seed(store, cid, mode, user_texts):
    store.create(cid, current_mode=mode, model="opus", agent_backend="claude")
    for i, t in enumerate(user_texts):
        store.append_turn(cid, {"index": i, "role": "user", "content": t})


def test_empty_store_lists_nothing(store):
    assert store.list_conversations() == []


def test_lists_one_summary_per_conversation(store):
    _seed(store, "c1", "observe", ["hello"])
    _seed(store, "c2", "brief-author", ["author a brief", "and another"])
    out = store.list_conversations()
    json.dumps(out)  # JSON-able
    assert len(out) == 2
    ids = [s["conversation_id"] for s in out]
    assert ids == ["c1", "c2"]  # insertion order preserved


def test_summary_carries_mode_turn_count_and_preview(store):
    _seed(store, "c1", "brief-author", ["author a brief please", "second"])
    s = store.list_conversations()[0]
    assert s["conversation_id"] == "c1"
    assert s["current_mode"] == "brief-author"
    assert s["turn_count"] == 2
    # preview is derived from the first user turn's content
    assert "author a brief" in s["preview"]


def test_preview_is_empty_for_a_conversation_with_no_turns(store):
    store.create("c0", current_mode="observe", model="opus", agent_backend="claude")
    s = store.list_conversations()[0]
    assert s["turn_count"] == 0
    assert s["preview"] == ""


def test_list_does_not_mutate_the_store(store):
    _seed(store, "c1", "observe", ["x"])
    before = store.get("c1")["transcript"][:]
    store.list_conversations()
    assert store.get("c1")["transcript"] == before
    # a fresh store over the same path still sees exactly the seeded data
    again = SessionStore(store_path=store._store_path)
    assert again.get("c1")["current_mode"] == "observe"
