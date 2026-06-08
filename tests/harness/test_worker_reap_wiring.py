"""RED oracle for the archive-on-integrate worker wiring.

Contract (harness/orchestrator_worker.py):

  * NEW top-level ``_reap_spent_briefs_safe(payload: dict) -> None`` -- the
    fail-safe bridge to ``tools.brief_reaper.reap_for_task``:
      - does NOTHING unless ``payload.get('outcome') == 'accepted'``
      - does NOTHING unless the config flag ``autowork.archive_spent_briefs`` is
        truthy (read via ``orch.load_config()``, nested-get, default OFF)
      - does NOTHING unless ``payload.get('task_id')`` is a non-empty string
      - otherwise lazily imports ``tools.brief_reaper.reap_for_task`` and calls
        it with the repo root, the task_id, and a keyword ``stamp`` (a date str)
      - is TOTALLY fail-safe: ANY exception (config read, import, reap) is
        swallowed -- it never raises.

  * ``_print_json_line(payload)`` still writes the JSON line AND now calls
    ``_reap_spent_briefs_safe(payload)`` -- but a failure in the reaper bridge
    must NEVER prevent the JSON line from being emitted or raise to the caller.
"""
import json

import pytest

import harness.orchestrator as orch
import harness.orchestrator_worker as ow


def test_helper_exists_and_is_callable():
    assert callable(getattr(ow, '_reap_spent_briefs_safe', None))


def test_print_json_line_invokes_reaper_bridge(monkeypatch, capsys):
    seen = []
    monkeypatch.setattr(ow, '_reap_spent_briefs_safe', lambda payload: seen.append(payload))
    ow._print_json_line({'outcome': 'accepted', 'task_id': 'T1'})
    out = capsys.readouterr().out
    assert json.loads(out.strip()) == {'outcome': 'accepted', 'task_id': 'T1'}
    assert seen == [{'outcome': 'accepted', 'task_id': 'T1'}]


def test_print_json_line_survives_a_throwing_bridge(monkeypatch, capsys):
    def _boom(payload):
        raise RuntimeError('reaper exploded')
    monkeypatch.setattr(ow, '_reap_spent_briefs_safe', _boom)
    # must NOT raise, and must STILL print the line
    ow._print_json_line({'outcome': 'accepted', 'task_id': 'T2'})
    assert json.loads(capsys.readouterr().out.strip())['task_id'] == 'T2'


def _set_flag(monkeypatch, on):
    monkeypatch.setattr(orch, 'load_config',
                        lambda *a, **k: {'autowork': {'archive_spent_briefs': on}})


def test_bridge_reaps_on_accepted_when_flag_on(monkeypatch):
    calls = []
    import tools.brief_reaper as br
    _set_flag(monkeypatch, True)
    monkeypatch.setattr(br, 'reap_for_task',
                        lambda repo_root, task_id, **kw: calls.append((task_id, kw)) or [])
    ow._reap_spent_briefs_safe({'outcome': 'accepted', 'task_id': 'leaf-x'})
    assert len(calls) == 1
    task_id, kw = calls[0]
    assert task_id == 'leaf-x'
    assert isinstance(kw.get('stamp'), str) and kw['stamp']


def test_bridge_noop_on_non_accepted(monkeypatch):
    calls = []
    import tools.brief_reaper as br
    _set_flag(monkeypatch, True)
    monkeypatch.setattr(br, 'reap_for_task',
                        lambda *a, **k: calls.append(1) or [])
    ow._reap_spent_briefs_safe({'outcome': 'rejected', 'task_id': 'leaf-x'})
    assert calls == []


def test_bridge_reaps_on_no_diff_when_flag_on(monkeypatch):
    # A no_diff terminal means the brief was already satisfied -> it is DONE and
    # must be reaped, same as an accepted terminal.
    calls = []
    import tools.brief_reaper as br
    _set_flag(monkeypatch, True)
    monkeypatch.setattr(br, 'reap_for_task',
                        lambda repo_root, task_id, **kw: calls.append((task_id, kw)) or [])
    ow._reap_spent_briefs_safe({'outcome': 'no_diff', 'task_id': 'leaf-nd'})
    assert len(calls) == 1
    task_id, kw = calls[0]
    assert task_id == 'leaf-nd'
    assert isinstance(kw.get('stamp'), str) and kw['stamp']


def test_bridge_noop_on_no_diff_when_flag_off(monkeypatch):
    calls = []
    import tools.brief_reaper as br
    _set_flag(monkeypatch, False)
    monkeypatch.setattr(br, 'reap_for_task',
                        lambda *a, **k: calls.append(1) or [])
    ow._reap_spent_briefs_safe({'outcome': 'no_diff', 'task_id': 'leaf-nd'})
    assert calls == []


def test_print_json_line_fires_reaper_for_no_diff_end_to_end(monkeypatch, capsys):
    # END-TO-END: drive the REAL _print_json_line emission chokepoint (NOT a hand
    # call of the bridge) with a no_diff terminal and the flag ON, and assert the
    # reaper is actually reached. The real _reap_spent_briefs_safe runs (flag
    # gate + outcome guard + task_id check); only the leaf reap_for_task is
    # stubbed. Closes the "never proven end-to-end" gap.
    import tools.brief_reaper as br
    _set_flag(monkeypatch, True)
    calls = []
    monkeypatch.setattr(br, 'reap_for_task',
                        lambda repo_root, task_id, **kw: calls.append((task_id, kw)) or [])
    ow._print_json_line({'outcome': 'no_diff', 'task_id': 'leaf-e2e', 'path': 'round1'})
    out = capsys.readouterr().out
    assert json.loads(out.strip())['outcome'] == 'no_diff'   # line still emitted
    assert len(calls) == 1 and calls[0][0] == 'leaf-e2e'      # reaper reached via emission


def test_bridge_noop_when_flag_off(monkeypatch):
    calls = []
    import tools.brief_reaper as br
    _set_flag(monkeypatch, False)
    monkeypatch.setattr(br, 'reap_for_task',
                        lambda *a, **k: calls.append(1) or [])
    ow._reap_spent_briefs_safe({'outcome': 'accepted', 'task_id': 'leaf-x'})
    assert calls == []


def test_bridge_swallows_reaper_exception(monkeypatch):
    import tools.brief_reaper as br
    _set_flag(monkeypatch, True)
    def _boom(*a, **k):
        raise RuntimeError('reap failed')
    monkeypatch.setattr(br, 'reap_for_task', _boom)
    # must not raise
    ow._reap_spent_briefs_safe({'outcome': 'accepted', 'task_id': 'leaf-x'})


def test_bridge_swallows_config_failure(monkeypatch):
    import tools.brief_reaper as br
    def _boom_cfg(*a, **k):
        raise RuntimeError('config read failed')
    monkeypatch.setattr(orch, 'load_config', _boom_cfg)
    called = []
    monkeypatch.setattr(br, 'reap_for_task', lambda *a, **k: called.append(1) or [])
    # config blew up -> swallowed, no reap
    ow._reap_spent_briefs_safe({'outcome': 'accepted', 'task_id': 'leaf-x'})
    assert called == []
