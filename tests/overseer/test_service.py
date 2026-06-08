"""Oracle for overseer.service.OverseerService -- the composition root.

Uses an injected run_turn_fn so no agent is spawned; asserts the enabled-gate,
body adaptation, and status codes the WebUI handlers depend on.
"""
from __future__ import annotations

from overseer.service import OverseerService


def _svc(tmp_path, enabled, calls=None):
    cfg = {'overseer': {'enabled': enabled, 'store_path': 'state/overseer/sessions.json'}}
    state_dir = tmp_path / 'state'
    state_dir.mkdir(exist_ok=True)

    def fake_run(store, cid, text, **kw):
        if calls is not None:
            calls.append((cid, text, kw.get('rewind_to_index')))
        store.append_turn(cid, {'role': 'assistant', 'content': 'echo:' + text})
        return {'ok': True, 'text': 'echo:' + text, 'session_id': 'sid', 'tool_uses': []}

    return OverseerService(state_dir, cfg, run_turn_fn=fake_run)


def test_chat_send_blocked_when_disabled(tmp_path):
    status, body = _svc(tmp_path, enabled=False).chat_send({'text': 'hi'})
    assert status == 403 and body['error'] == 'overseer disabled'


def test_chat_send_runs_turn_when_enabled(tmp_path):
    calls = []
    status, body = _svc(tmp_path, enabled=True, calls=calls).chat_send({'text': 'hello'})
    assert status == 200
    assert body['text'] == 'echo:hello'
    assert 'conversation_id' in body and 'job_id' in body
    assert calls and calls[0][1] == 'hello'           # turn runner actually invoked


def test_chat_send_empty_text_rejected(tmp_path):
    status, body = _svc(tmp_path, enabled=True).chat_send({'text': '   '})
    assert status == 400


def test_chat_send_failure_maps_to_502(tmp_path):
    cfg = {'overseer': {'enabled': True, 'store_path': 'state/overseer/sessions.json'}}
    (tmp_path / 'state').mkdir()

    def boom(store, cid, text, **kw):
        return {'ok': False, 'error': 'spawn failed', 'text': 'spawn failed'}

    svc = OverseerService(tmp_path / 'state', cfg, run_turn_fn=boom)
    status, body = svc.chat_send({'text': 'hi'})
    assert status == 502 and body['ok'] is False


def test_mode_set_disabled_and_unknown(tmp_path):
    assert _svc(tmp_path, enabled=False).mode_set({'conversation_id': 'c', 'mode': 'observe'})[0] == 403
    status, body = _svc(tmp_path, enabled=True).mode_set({'conversation_id': 'nope', 'mode': 'observe'})
    assert status == 404


def test_mode_set_switches_within_conversation(tmp_path):
    svc = _svc(tmp_path, enabled=True)
    svc.chat_send({'text': 'hi'})                      # creates conv-1
    status, body = svc.mode_set({'conversation_id': 'conv-1', 'mode': 'analyze'})
    # analyze is a Tier-R fallback mode -> permitted without unlock
    assert status == 200 and body['ok'] is True and body['current_mode'] == 'analyze'


def test_resend_reruns_last_user_turn(tmp_path):
    calls = []
    svc = _svc(tmp_path, enabled=True, calls=calls)
    svc.chat_send({'text': 'first'})
    calls.clear()
    status, body = svc.chat_resend({'conversation_id': 'conv-1'})
    assert status == 200
    assert calls and calls[0][1] == 'first'           # last user text re-run
