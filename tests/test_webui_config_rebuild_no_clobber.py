"""Source-level regression oracle for webui_config_rebuild_no_clobber.

Scans tools/webui_static/app.js as text (no JavaScript execution, no server)
to lock the configOrRebuildIsOpen() live-re-render guard in place alongside the
preserved briefEditorIsOpen() exemption. All assertions are whitespace-resilient
regex/string scans. RED on the pre-fix app.js, GREEN after the guard is added.
"""
import os
import re
import pytest

def _find_app_js():
    """Resolve tools/webui_static/app.js relative to this test file or repo root."""
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = []
    d = here
    for _ in range(8):
        candidates.append(os.path.join(d, 'tools', 'webui_static', 'app.js'))
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    candidates.append(os.path.join(os.getcwd(), 'tools', 'webui_static', 'app.js'))
    for c in candidates:
        if os.path.isfile(c):
            return c
    raise FileNotFoundError('could not locate tools/webui_static/app.js')
with open(_find_app_js(), encoding='utf-8') as _fh:
    APP_JS = _fh.read()

def _extract_function_body(src, name):
    """Return the full `function <name>(...) { ... }` text via brace matching."""
    m = re.search('function\\s+' + re.escape(name) + '\\s*\\([^)]*\\)\\s*\\{', src)
    if not m:
        return None
    depth = 0
    brace = src.index('{', m.start())
    for j in range(brace, len(src)):
        ch = src[j]
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return src[m.start():j + 1]
    return None

def _extract_live_subscriber(src):
    """Return the store.subscribers.add(...) block that drives the live re-render."""
    anchor = src.find('renderQueued = false')
    assert anchor != -1, 'could not find the renderQueued = false anchor'
    start = src.rfind('store.subscribers.add(', 0, anchor)
    assert start != -1, 'could not find the enclosing store.subscribers.add('
    brace = src.index('{', start)
    depth = 0
    for j in range(brace, len(src)):
        ch = src[j]
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return src[start:j + 1]
    raise AssertionError('could not balance the live subscriber block')

def test_configOrRebuildIsOpen_predicate_is_defined():
    assert re.search('function\\s+configOrRebuildIsOpen\\s*\\(\\s*\\)', APP_JS), 'expected a top-level `function configOrRebuildIsOpen()` predicate'

def test_configOrRebuildIsOpen_body_references_config_and_rebuild():
    body = _extract_function_body(APP_JS, 'configOrRebuildIsOpen')
    assert body is not None, 'could not extract configOrRebuildIsOpen() body'
    assert '"config"' in body or "'config'" in body, 'predicate body must reference the string "config"'
    assert '"rebuild"' in body or "'rebuild'" in body, 'predicate body must reference the string "rebuild"'

def test_subscriber_early_returns_before_renderQueued():
    block = _extract_live_subscriber(APP_JS)
    guard = re.search('if\\s*\\(\\s*configOrRebuildIsOpen\\s*\\(\\s*\\)\\s*\\)\\s*return\\s*;', block)
    assert guard, 'subscriber must call configOrRebuildIsOpen() and early-return'
    assign = block.find('renderQueued = true')
    assert assign != -1, 'subscriber must still set renderQueued = true'
    assert guard.start() < assign, 'the configOrRebuildIsOpen() guard must run BEFORE renderQueued = true'

def test_brief_editor_exemption_preserved():
    block = _extract_live_subscriber(APP_JS)
    assert re.search('if\\s*\\(\\s*briefEditorIsOpen\\s*\\(\\s*\\)\\s*\\)\\s*return\\s*;', block), 'subscriber must STILL contain `if (briefEditorIsOpen()) return;`'
    be = block.find('briefEditorIsOpen')
    cr = block.find('configOrRebuildIsOpen')
    assert be != -1 and cr != -1, 'both guards must be present in the subscriber'
    assert be < cr, 'briefEditorIsOpen() must be called before configOrRebuildIsOpen() (additive guard)'

def test_non_form_routes_still_live_update():
    block = _extract_live_subscriber(APP_JS)
    assert 'renderQueued = true' in block, 'the renderQueued = true assignment must remain so non-form routes still re-render'
    assert re.search('requestAnimationFrame\\s*\\(', block), 'the requestAnimationFrame scheduling must remain intact'
    assert 'renderRoute()' in block, 'the subscriber must still call renderRoute() inside the animation frame'