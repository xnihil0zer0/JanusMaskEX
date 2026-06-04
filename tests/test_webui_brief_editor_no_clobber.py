"""Source-level regression oracle for T1_guard_brief_editor_no_clobber.

Statically scans tools/webui_static/app.js as text (the JS is never executed)
to pin the brief-editor live-re-render guard in place. Must be RED against the
pre-fix app.js and GREEN against the post-fix app.js.
"""
import pathlib
import re
import pytest
APP_JS = pathlib.Path(__file__).resolve().parents[1] / 'tools' / 'webui_static' / 'app.js'
_RAF_RE = re.compile('requestAnimationFrame\\(\\s*\\(\\)\\s*=>\\s*\\{\\s*renderQueued\\s*=\\s*false;\\s*renderRoute\\(\\)\\s*;?\\s*\\}\\s*\\)')

def _src() -> str:
    return APP_JS.read_text(encoding='utf-8')

def _live_rerender_block(src: str) -> str:
    """Return the source slice from the live re-render subscriber's
    store.subscribers.add(...) up to and including its requestAnimationFrame
    machinery."""
    raf = _RAF_RE.search(src)
    assert raf, 'live re-render requestAnimationFrame machinery not found in app.js'
    start = src.rfind('store.subscribers.add', 0, raf.start())
    assert start != -1, 'store.subscribers.add(...) for the live re-render subscriber not found'
    return src[start:raf.end()]

def test_brief_editor_is_open_predicate_defined():
    src = _src()
    assert re.search('function\\s+briefEditorIsOpen\\s*\\(\\s*\\)', src), 'expected a top-level `function briefEditorIsOpen()` definition in app.js'

def test_live_rerender_subscriber_guards_editor_route():
    block = _live_rerender_block(_src())
    pred = re.search('briefEditorIsOpen\\s*\\(\\s*\\)', block)
    assert pred, 'briefEditorIsOpen() guard call missing from the live re-render subscriber'
    set_true = re.search('renderQueued\\s*=\\s*true', block)
    assert set_true, 'renderQueued = true assignment missing from the live re-render subscriber'
    assert pred.start() < set_true.start(), 'briefEditorIsOpen() guard must short-circuit BEFORE renderQueued = true'

def test_briefs_list_route_not_exempted():
    src = _src()
    m = re.search('function\\s+briefEditorIsOpen\\s*\\(\\s*\\)\\s*\\{(.*?)\\}', src, re.S)
    assert m, 'briefEditorIsOpen definition body not found'
    body = m.group(1)
    assert re.search('parts\\s*\\[\\s*1\\s*\\]', body), 'briefEditorIsOpen must key on parts[1] (the slug) so #/briefs stays live'
    assert 'briefs' in body, "briefEditorIsOpen must check parts[0] === 'briefs'"

def test_non_editor_routes_still_live():
    block = _live_rerender_block(_src())
    assert re.search('renderQueued\\s*=\\s*true', block), 'guard must not delete the renderQueued = true assignment'
    assert 'requestAnimationFrame' in block, 'guard must not delete the requestAnimationFrame live-render path'