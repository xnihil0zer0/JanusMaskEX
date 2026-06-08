"""RED oracle for the chat_send MODE-ON-SEND fix (overseer/web_api.py).

Second half of the brief-author "(no output)" bug: even with the driver argv
fixed, the operator's selected mode never reached the conversation. The frontend
posts the mode, but ``OverseerWebApi.chat_send`` ALWAYS booted a new conversation
as ``observe`` (DEFAULT_MODE), so a "brief-author" send ran read-only ``observe``.

The fix: ``chat_send`` honours ``body['mode']`` when CREATING a conversation,
but only for a self-selectable mode -- a default-available Tier-R/W mode. An
unlock-only Tier-S mode (or an unknown name) is NOT self-selectable on boot and
falls back to ``observe`` (privileged modes still require the explicit unlock
path). Reusing an existing conversation ignores ``mode`` (mode changes flow
through ``mode_set``). Backward compatible: a send with no ``mode`` still boots
``observe``.
"""
import pytest

from overseer.session_store import SessionStore
from overseer.web_api import OverseerWebApi


@pytest.fixture
def api(tmp_path):
    return OverseerWebApi(SessionStore(store_path=tmp_path / "sessions.json"))


def test_send_with_no_mode_still_boots_observe(api):
    cid = api.chat_send({"text": "x"})["conversation_id"]
    assert api.mode_get(cid)["current_mode"] == "observe"


def test_send_with_default_available_mode_boots_into_it(api):
    out = api.chat_send({"text": "author a brief", "mode": "brief-author"})
    cid = out["conversation_id"]
    assert api.mode_get(cid)["current_mode"] == "brief-author"


def test_send_with_tier_r_mode_boots_into_it(api):
    cid = api.chat_send({"text": "x", "mode": "analyze"})["conversation_id"]
    assert api.mode_get(cid)["current_mode"] == "analyze"


def test_send_with_locked_tier_s_mode_falls_back_to_observe(api):
    # push is unlock-only; it must NOT be self-selectable on boot.
    cid = api.chat_send({"text": "x", "mode": "push"})["conversation_id"]
    assert api.mode_get(cid)["current_mode"] == "observe"


def test_send_with_unknown_mode_falls_back_to_observe(api):
    cid = api.chat_send({"text": "x", "mode": "no-such-mode"})["conversation_id"]
    assert api.mode_get(cid)["current_mode"] == "observe"


def test_reusing_a_conversation_ignores_mode(api):
    first = api.chat_send({"text": "one", "mode": "brief-author"})
    cid = first["conversation_id"]
    # a later send with a different mode does NOT silently switch the conversation
    api.chat_send({"conversation_id": cid, "text": "two", "mode": "analyze"})
    assert api.mode_get(cid)["current_mode"] == "brief-author"
    # and the user turns are still both recorded (no regression to chat_send)
    contents = [t["content"] for t in api.chat_history(cid)["turns"] if t["role"] == "user"]
    assert contents == ["one", "two"]
