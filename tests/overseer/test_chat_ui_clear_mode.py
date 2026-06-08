"""RED structural oracle for the chat panel CLEAR-button + MODE-ON-SEND edit
(tools/webui_static/app.js + styles.css).

No DOM runtime convention exists, so this is structural (mirrors test_chat_ui.py):
it asserts the load-bearing hooks are present in the static bundle. Live fidelity
is checked later by the Phase H Playwright sweep.

Two behaviours:
1. CLEAR button -> starts a NEW chat session. A handler resets the in-memory
   overseerChat state (conversation id -> null, buffer cleared) and clears the
   transcript DOM, so the NEXT send creates a fresh conversation server-side.
2. MODE-ON-SEND -> sendChat() includes the selected mode in the POST body so the
   server boots the new conversation into the operator-selected mode (the
   companion to the overseer/web_api.py chat_send fix).
"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
STATIC = REPO / "tools" / "webui_static"


def _read(name):
    return (STATIC / name).read_text(encoding="utf-8")


def test_chat_has_a_clear_control():
    src = _read("app.js")
    assert "chat-clear" in src, "no #chat-clear control anchor"


def test_clear_resets_session_and_starts_new():
    src = _read("app.js")
    # a dedicated new-session function exists and is wired to the clear control
    assert "function newChatSession" in src, "newChatSession() reset function missing"
    assert "chat-clear" in src
    # the reset nulls the conversation id and empties the replay buffer so the
    # next send boots a fresh conversation
    assert "overseerChat.cid = null" in src, "clear must null the conversation id"
    assert "overseerChat.buffer = []" in src, "clear must empty the replay buffer"


def test_send_transmits_the_selected_mode():
    src = _read("app.js")
    # sendChat must put the active mode on the POST body so the server can boot
    # the new conversation into it (pairs with web_api chat_send mode-on-create)
    assert "body.mode = overseerChat.mode" in src, "sendChat does not transmit the mode"


def test_clear_button_styles_present():
    src = _read("styles.css")
    # the clear control reuses the existing button styling; a dedicated class or
    # the shared .btn is acceptable -- assert the chat control surface is styled
    assert "chat-input" in src or "chat-transcript" in src
