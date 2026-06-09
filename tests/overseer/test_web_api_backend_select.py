"""Wiring oracle for overseer/web_api.py backend selection.

The full claude-tmux backend chain (overseer/tmux_*.py) is built and wired into
turn_runner.run_chat_turn, which dispatches to it purely on
``rec['agent_backend'] == 'claude-tmux'`` (turn_runner.py:307). But web_api.chat_send
HARD-CODES ``agent_backend='claude'`` on conversation creation, so the backend is
never selectable and the entire tmux subsystem is dead code in production.

This oracle pins the missing wire: a requested ``backend`` must be honored (and an
unknown one must fail safe to ``claude``), and the literal web_api persists must be
byte-for-byte the literal the live dispatch branch checks — so an orphan cannot
silently reappear.
"""
import inspect

from overseer.session_store import SessionStore
from overseer.web_api import OverseerWebApi


def _api(tmp_path):
    store = SessionStore(store_path=tmp_path / "sessions.json")
    return OverseerWebApi(store), store


def _backend_of(store, cid):
    return store.get(cid).get("agent_backend")


def test_requested_claude_tmux_backend_is_persisted(tmp_path):
    api, store = _api(tmp_path)
    out = api.chat_send({"text": "hi", "backend": "claude-tmux"})
    assert _backend_of(store, out["conversation_id"]) == "claude-tmux"


def test_unknown_backend_falls_back_to_claude(tmp_path):
    api, store = _api(tmp_path)
    cid = api.chat_send({"text": "hi", "backend": "bogus"})["conversation_id"]
    assert _backend_of(store, cid) == "claude"


def test_no_backend_defaults_to_claude(tmp_path):
    api, store = _api(tmp_path)
    cid = api.chat_send({"text": "hi"})["conversation_id"]
    assert _backend_of(store, cid) == "claude"


def test_existing_conversation_ignores_requested_backend(tmp_path):
    api, store = _api(tmp_path)
    cid = api.chat_send({"text": "one", "backend": "claude-tmux"})["conversation_id"]
    api.chat_send({"conversation_id": cid, "text": "two", "backend": "claude"})
    # Reuse path must not rewrite the stored backend.
    assert _backend_of(store, cid) == "claude-tmux"


def test_dispatch_reads_the_same_field_web_api_writes(tmp_path):
    # Anti-orphan guard: the live dispatch still keys on the exact field/literal.
    src = inspect.getsource(__import__("overseer.turn_runner", fromlist=["run_chat_turn"]).run_chat_turn)
    assert "agent_backend" in src and "claude-tmux" in src
    api, store = _api(tmp_path)
    cid = api.chat_send({"text": "hi", "backend": "claude-tmux"})["conversation_id"]
    assert store.get(cid).get("agent_backend") == "claude-tmux"
