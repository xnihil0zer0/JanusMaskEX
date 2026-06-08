"""RED oracle for overseer/web_api.py — the JSON handler layer.

OverseerWebApi operates on an injected session_store (+ driver/actions seams).
Every method returns a plain JSON-able dict. Mode-set refuses an unlock-required
target unless unlocked and reverts to the fallback; mode-unlock records a
per-session unlock; chat_resend exposes the cache-friendly replay/rewind.
"""
import json

import pytest

from overseer.session_store import SessionStore
from overseer.web_api import OverseerWebApi


@pytest.fixture
def api(tmp_path):
    store = SessionStore(store_path=tmp_path / "sessions.json")
    return OverseerWebApi(store)


def _jsonable(obj):
    json.dumps(obj)  # raises TypeError if not JSON-serializable
    return True


def test_chat_send_creates_conversation_and_appends_user_turn(api):
    out = api.chat_send({"text": "hello overseer"})
    assert _jsonable(out)
    assert out["conversation_id"]
    assert isinstance(out["job_id"], str) and out["job_id"]
    hist = api.chat_history(out["conversation_id"])
    assert any(t["content"] == "hello overseer" and t["role"] == "user"
               for t in hist["turns"])


def test_chat_send_reuses_an_existing_conversation(api):
    first = api.chat_send({"text": "one"})
    cid = first["conversation_id"]
    again = api.chat_send({"conversation_id": cid, "text": "two"})
    assert again["conversation_id"] == cid
    hist = api.chat_history(cid)
    contents = [t["content"] for t in hist["turns"] if t["role"] == "user"]
    assert contents == ["one", "two"]


def test_mode_get_lists_available_modes_excluding_locked_tier_s(api):
    cid = api.chat_send({"text": "x"})["conversation_id"]
    info = api.mode_get(cid)
    assert _jsonable(info)
    assert info["current_mode"] == "observe"  # default boot mode
    assert "push" not in info["available_modes"]      # Tier-S locked by default
    assert "observe" in info["available_modes"]


def test_mode_set_to_tier_r_succeeds_and_persists(api):
    cid = api.chat_send({"text": "x"})["conversation_id"]
    out = api.mode_set(cid, "analyze")
    assert out["ok"] is True
    assert out["current_mode"] == "analyze"
    assert api.mode_get(cid)["current_mode"] == "analyze"


def test_mode_set_to_locked_tier_s_is_rejected_and_reverts(api):
    cid = api.chat_send({"text": "x"})["conversation_id"]
    out = api.mode_set(cid, "push")  # Tier-S, not unlocked
    assert out["ok"] is False
    # The conversation must NOT be left in the privileged mode.
    assert api.mode_get(cid)["current_mode"] != "push"


def test_unlock_then_set_tier_s_succeeds(api):
    cid = api.chat_send({"text": "x"})["conversation_id"]
    unlocked = api.mode_unlock(cid, "push")
    assert unlocked["ok"] is True
    assert "push" in unlocked["unlocked_modes"]
    out = api.mode_set(cid, "push")
    assert out["ok"] is True
    assert api.mode_get(cid)["current_mode"] == "push"


def test_model_list_exposes_claude_tiers_and_agy_without_pick(api):
    out = api.model_list()
    assert _jsonable(out)
    assert out["claude"] == ["opus", "sonnet", "haiku"]
    assert list(out["agy"]) == []


def test_chat_resend_whole_transcript_returns_a_job(api):
    cid = api.chat_send({"text": "x"})["conversation_id"]
    out = api.chat_resend(cid)
    assert _jsonable(out)
    assert out["conversation_id"] == cid
    assert out["job_id"]
    assert out.get("rewind_to_index") is None  # whole-transcript resend


def test_chat_resend_with_rewind_index_marks_a_branch(api):
    cid = api.chat_send({"text": "x"})["conversation_id"]
    out = api.chat_resend(cid, rewind_to_index=0)
    assert out["rewind_to_index"] == 0


def test_handlers_reject_unknown_conversation(api):
    with pytest.raises(KeyError):
        api.chat_history("nope")
