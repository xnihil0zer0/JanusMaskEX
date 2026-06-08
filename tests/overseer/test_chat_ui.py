"""RED oracle for the tools/webui_static/ frontend EDIT leaf (frontend).

No DOM-runtime test convention exists in this repo, so this is a STRUCTURAL
oracle: it asserts the load-bearing hooks the chat panel must add are present in
the static assets. Live behavior/fidelity is verified later by the Phase H
Playwright sweep — this just guarantees the contract the sweep depends on.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
STATIC = REPO / "tools" / "webui_static"


def _read(name):
    return (STATIC / name).read_text(encoding="utf-8")


def test_app_js_adds_chat_is_open_guard():
    src = _read("app.js")
    assert "function chatIsOpen" in src, "chatIsOpen() predicate missing"
    # Wired into the same SSE re-render skip path as briefEditorIsOpen so a tick
    # never clobbers the chat input/transcript.
    assert "if (chatIsOpen()) return;" in src, "chatIsOpen() not in the skip guard"


def test_app_js_registers_the_chat_page():
    src = _read("app.js")
    assert ("pages.chat" in src) or ("pages['chat']" in src), "no pages.chat route"


def test_app_js_has_persistent_transcript_and_input_anchors():
    src = _read("app.js")
    # Self-managed, append-only DOM anchors (not re-rendered each tick).
    assert "chat-transcript" in src
    assert "chat-input" in src
    assert "chat-resend" in src  # the resend-transcript control


def test_index_html_has_the_chat_nav_link():
    src = _read("index.html")
    assert "#/chat" in src, "no #/chat nav link"


def test_styles_css_has_single_source_per_mode_color_map():
    src = _read("styles.css")
    # Tier-grouped hue ramp as CSS custom properties — one source of truth.
    for var in ("--mode-tier-r", "--mode-tier-w", "--mode-tier-s"):
        assert var in src, f"missing per-mode color variable {var}"
