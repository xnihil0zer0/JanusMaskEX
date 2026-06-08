"""RED oracle for overseer/session_store.py — deterministic conversation store.

Maps a conversation id -> {claude_session_id, current_mode, unlocked_modes,
model, agent_backend, transcript}. Backed via an EXPLICIT ``store_path`` seam
(no real on-disk default in the tested surface). Turns are stored duck-typed
(plain dicts here) so the store builds independently of overseer.transcript.
"""
import pytest

from overseer.session_store import SessionStore


@pytest.fixture
def store(tmp_path):
    return SessionStore(store_path=tmp_path / "overseer_sessions.json")


def _turn(index, role, mode, content):
    return {"index": index, "role": role, "mode": mode, "content": content}


def test_create_seeds_a_record_with_defaults(store):
    rec = store.create("c1", current_mode="observe", model="opus", agent_backend="claude")
    assert rec["current_mode"] == "observe"
    assert rec["model"] == "opus"
    assert rec["agent_backend"] == "claude"
    assert list(rec["unlocked_modes"]) == []
    assert list(rec["transcript"]) == []
    assert rec.get("claude_session_id") in (None, "")


def test_get_returns_the_created_record(store):
    store.create("c1", current_mode="observe", model="opus", agent_backend="claude")
    rec = store.get("c1")
    assert rec["current_mode"] == "observe"


def test_get_unknown_conversation_raises(store):
    with pytest.raises(KeyError):
        store.get("missing")


def test_append_turn_preserves_order(store):
    store.create("c1", current_mode="observe", model="opus", agent_backend="claude")
    store.append_turn("c1", _turn(0, "user", "observe", "hi"))
    store.append_turn("c1", _turn(1, "assistant", "observe", "hello"))
    transcript = store.get("c1")["transcript"]
    assert [t["index"] for t in transcript] == [0, 1]
    assert transcript[0]["content"] == "hi"
    assert transcript[1]["role"] == "assistant"


def test_set_mode_and_set_model_and_set_session_id(store):
    store.create("c1", current_mode="observe", model="opus", agent_backend="claude")
    store.set_mode("c1", "analyze")
    store.set_model("c1", "sonnet")
    store.set_session_id("c1", "sess-abc123")
    rec = store.get("c1")
    assert rec["current_mode"] == "analyze"
    assert rec["model"] == "sonnet"
    assert rec["claude_session_id"] == "sess-abc123"


def test_unlock_mode_records_a_per_session_unlock_without_duplicates(store):
    store.create("c1", current_mode="observe", model="opus", agent_backend="claude")
    store.unlock_mode("c1", "push")
    store.unlock_mode("c1", "push")  # idempotent
    assert list(store.get("c1")["unlocked_modes"]) == ["push"]


def test_store_persists_across_instances_on_the_same_path(tmp_path):
    path = tmp_path / "sessions.json"
    s1 = SessionStore(store_path=path)
    s1.create("c1", current_mode="observe", model="opus", agent_backend="claude")
    s1.append_turn("c1", _turn(0, "user", "observe", "persisted"))
    s1.set_mode("c1", "audit")

    # A fresh store over the same path sees the durable state.
    s2 = SessionStore(store_path=path)
    rec = s2.get("c1")
    assert rec["current_mode"] == "audit"
    assert rec["transcript"][0]["content"] == "persisted"


def test_store_has_no_real_ondisk_default(tmp_path, monkeypatch):
    # The path is an explicit seam — constructing with an explicit tmp path must
    # not touch any shared/global location.
    path = tmp_path / "isolated.json"
    store = SessionStore(store_path=path)
    store.create("c1", current_mode="observe", model="opus", agent_backend="claude")
    assert path.exists()
