"""RED oracle: the worker's test_authoring path repairs self-defeating
self-referential source-scan assertions before saving/committing the oracle.

ROOT-CAUSE CONTEXT
------------------
``harness/test_author.repair_selfref_assertions`` (landed 8cebe55) strips the
self-defeating ``src = open(__file__).read(); assert 'X' not in src`` anti-cheat
pattern -- which is GUARANTEED to fail whenever the test file also contains the
mandated ``assert not hasattr(mod, 'X')`` lines (those lines embed the literal
'X'). But that repair is only wired into ``test_author.author_oracle`` /
``rebuild/loop.py``; it is NOT applied on the autowork daemon's worker dispatch
path (``orchestrator_worker.main`` saves the agent's raw test_authoring
submission verbatim). So an agent-authored oracle that adds an ``open(__file__)``
source scan lands a self-defeating test and dies ``verification_failed``
(witnessed: claudecap-parallel-isolation-oracle, commit_sha 00ef707).

CONTRACT (the fix this oracle pins)
-----------------------------------
On a ``test_authoring`` task, ``orchestrator_worker.main`` must run the lone
synthesized oracle code through ``test_author.repair_selfref_assertions`` before
``_save_final_output`` / ``_auto_commit_accepted``, so the saved oracle has the
self-referential source-scan assertions stripped while every other assertion
(notably ``hasattr`` checks) is preserved. The repair is fail-safe (any
exception leaves the code unchanged).

RED on HEAD: the saved output still contains the ``open(__file__)`` source scan.
"""
from __future__ import annotations
import json
import pathlib
import sys

import pytest


_POISONED_ORACLE = (
    "def test_no_sentinels():\n"
    "    import harness.autowork_daemon as ad\n"
    "    assert not hasattr(ad, '__JANUSMASK_PATCHES__')\n"
    "    assert not hasattr(ad, '__JANUSMASK_MANIFEST__')\n"
    "    src = open(__file__, 'r', encoding='utf-8').read()\n"
    "    assert '__JANUSMASK_PATCHES__' not in src\n"
    "    assert '__JANUSMASK_MANIFEST__' not in src\n"
)


def _run_worker_test_authoring(tmp_path, monkeypatch, task_id: str, oracle_code: str) -> str | None:
    """Drive worker.main() on a test_authoring task whose both agents submit the
    same oracle code; return the saved output code (state/output/<id>.py)."""
    state_dir = tmp_path / 'state'
    (state_dir / 'tasks').mkdir(parents=True, exist_ok=True)
    task = {
        'task_id': task_id,
        'title': 'selfref repair probe',
        'meta_task_type': 'test_authoring',
        'files_touched': [f'tests/harness/test_{task_id}.py'],
        'verification_command': f'python -m pytest tests/harness/test_{task_id}.py -q',
        'acceptance_criteria': ['noop'],
    }
    (state_dir / 'tasks' / f'{task_id}.json').write_text(json.dumps(task), encoding='utf-8')

    from harness import orchestrator as orch
    import harness.orchestrator_worker as worker

    base_cfg = orch.load_config(pathlib.Path('harness/config.yaml'))
    base_cfg.setdefault('synthesis', {})
    base_cfg['synthesis']['use_retry_module'] = False
    base_cfg['synthesis']['antigravity_mode'] = False
    base_cfg['synthesis']['active_agents'] = ['claude', 'gemini']
    monkeypatch.setattr(orch, 'load_config', lambda *_a, **_k: base_cfg)

    monkeypatch.setattr(orch, 'run_both_agents', lambda *a, **k: (oracle_code, oracle_code))
    monkeypatch.setattr(orch, 'run_agent_phase', lambda *a, **k: oracle_code)
    monkeypatch.setattr(orch, '_validate_submission', lambda code, agent, task: (True, []))
    monkeypatch.setattr(orch, '_try_auto_repair', lambda *a, **k: None)
    # stop the lifecycle after save so we capture the saved code without committing
    monkeypatch.setattr('harness.orchestrator._auto_commit_accepted', lambda *a, **k: True, raising=False)
    monkeypatch.setattr('harness.orchestrator._mark_processed', lambda *a, **k: None, raising=False)
    monkeypatch.setattr('harness.orchestrator_worker._detect_and_append_untracked_tests', lambda *a, **k: None, raising=False)

    monkeypatch.setattr(sys, 'argv', ['worker', '--state-dir', str(state_dir), '--task-id', task_id, '--config', 'harness/config.yaml'])
    try:
        worker.main()
    except SystemExit:
        pass
    out = state_dir / 'output' / f'{task_id}.py'
    return out.read_text(encoding='utf-8') if out.exists() else None


def test_worker_repairs_selfref_source_scan(tmp_path, monkeypatch):
    """The worker must strip the self-defeating open(__file__) source-scan
    assertions from a test_authoring oracle before saving it."""
    saved = _run_worker_test_authoring(tmp_path, monkeypatch, 'srf_strip', _POISONED_ORACLE)
    assert saved is not None, 'worker did not save any oracle output'
    assert 'not in src' not in saved, (
        'self-referential source-scan assertion was NOT stripped by the worker'
    )
    assert 'open(__file__' not in saved, (
        'open(__file__) self-source read was NOT stripped by the worker'
    )


def test_worker_preserves_hasattr_anticheat(tmp_path, monkeypatch):
    """The repair must PRESERVE the legitimate hasattr anti-cheat assertions."""
    saved = _run_worker_test_authoring(tmp_path, monkeypatch, 'srf_keep', _POISONED_ORACLE)
    assert saved is not None
    assert "hasattr(ad, '__JANUSMASK_PATCHES__')" in saved
    assert "hasattr(ad, '__JANUSMASK_MANIFEST__')" in saved


def test_worker_leaves_clean_oracle_unchanged(tmp_path, monkeypatch):
    """REGRESSION: an oracle with NO self-source scan is saved unchanged
    (idempotent / no spurious edits)."""
    clean = (
        "def test_clean():\n"
        "    import harness.autowork_daemon as ad\n"
        "    assert not hasattr(ad, '__JANUSMASK_PATCHES__')\n"
        "    assert ad is not None\n"
    )
    saved = _run_worker_test_authoring(tmp_path, monkeypatch, 'srf_clean', clean)
    assert saved is not None
    assert "hasattr(ad, '__JANUSMASK_PATCHES__')" in saved
    assert 'ad is not None' in saved


def test_no_patch_or_manifest_sentinels_in_module():
    """Anti-cheat: this is an oracle test, not a patch bundle."""
    import harness.orchestrator_worker as worker
    assert not hasattr(worker, '__JANUSMASK_PATCHES__')
    assert not hasattr(worker, '__JANUSMASK_MANIFEST__')
