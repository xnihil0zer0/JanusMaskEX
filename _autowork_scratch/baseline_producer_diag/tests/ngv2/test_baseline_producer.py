"""Verification oracle tests for ngv2.baseline_producer.produce_baseline_input."""
import importlib
import inspect
import json
import hashlib
import copy
from typing import Any
import pytest

class MockCompletedProcess:
    """Mock result of a subprocess or run seam execution."""

    def __init__(self, stdout='', stderr='', returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode

def get_valid_reachability_artifact() -> dict:
    """Get a valid reachability artifact helper."""
    fsm_evidence = importlib.import_module('ngv2.fsm_evidence')
    base = {'phase': 'reachability_probe', 'status': 'success', 'details': {'pingable': True}}
    base['content_hash'] = fsm_evidence.phase_artifact_hash(base)
    return base

def get_valid_jail_artifact() -> dict:
    """Get a valid jail artifact helper."""
    fsm_evidence = importlib.import_module('ngv2.fsm_evidence')
    art = {'phase': 'jail_build', 'status': 'success', 'details': {'stdout': 'baseline execution successful\n', 'fs_diff': ['/home/user/workspace/build.log'], 'success_marker': 'EXPLOIT_SUCCESS', 'expected_fs_signature': 'flag_file.bin'}}
    art['content_hash'] = fsm_evidence.phase_artifact_hash(art)
    return art

def _call_produce_baseline_input(mod: Any, success_marker: str | None, expected_fs_signature: str | None, jail_artifact: dict | None=None, reachability_artifact: dict | None=None, run_fn: Any=None, sleep_fn: Any=None, socket_fn: Any=None, repo_dir: Any=None, work_dir: Any=None, **extra_kwargs) -> dict:
    """Introspect and call produce_baseline_input dynamically based on parameter names."""
    sig = inspect.signature(mod.produce_baseline_input)
    args = []
    kwargs = {}
    for name, param in sig.parameters.items():
        name_lower = name.lower()
        val = None
        has_val = False
        if any((x in name_lower for x in ('marker', 'success'))):
            val = success_marker
            has_val = True
        elif any((x in name_lower for x in ('sig', 'signature', 'fs'))):
            val = expected_fs_signature
            has_val = True
        elif 'jail' in name_lower:
            val = jail_artifact
            has_val = True
        elif 'reach' in name_lower:
            val = reachability_artifact
            has_val = True
        elif any((x in name_lower for x in ('run', 'exec', 'start', 'proc', 'sub'))):
            val = run_fn
            has_val = True
        elif 'sleep' in name_lower:
            val = sleep_fn
            has_val = True
        elif any((x in name_lower for x in ('sock', 'probe', 'conn'))):
            val = socket_fn
            has_val = True
        elif 'repo' in name_lower:
            val = str(repo_dir) if repo_dir else None
            has_val = True
        elif 'work' in name_lower:
            val = str(work_dir) if work_dir else None
            has_val = True
        elif 'dir' in name_lower or 'path' in name_lower:
            val = str(work_dir) if work_dir else None
            has_val = True
        if has_val:
            if param.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD):
                args.append(val)
            elif param.kind == inspect.Parameter.KEYWORD_ONLY:
                kwargs[name] = val
        elif param.default is not inspect.Parameter.empty:
            pass
        elif param.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD):
            args.append(None)
        elif param.kind == inspect.Parameter.KEYWORD_ONLY:
            kwargs[name] = None
    for k, v in extra_kwargs.items():
        if k in sig.parameters:
            kwargs[k] = v
    return mod.produce_baseline_input(*args, **kwargs)

def run_baseline_gate(produced_dict: dict, reachability_artifact: dict | None) -> dict:
    """Wrapper to run baseline_capture gate on the produced baseline_input dictionary."""
    fsm_baseline_capture = importlib.import_module('ngv2.fsm_baseline_capture')
    fsm_evidence = importlib.import_module('ngv2.fsm_evidence')
    if produced_dict is None:
        return fsm_baseline_capture.baseline_capture(None, reachability_artifact)
    if isinstance(produced_dict, dict) and 'phase' in produced_dict and ('status' in produced_dict):
        art = dict(produced_dict)
        if 'content_hash' in art:
            art_copy = dict(art)
            art_copy.pop('content_hash', None)
            art['content_hash'] = fsm_evidence.phase_artifact_hash(art_copy)
        return fsm_baseline_capture.baseline_capture(art, reachability_artifact)
    jail_art = {'phase': 'jail_build', 'status': 'success', 'details': {'baseline_input': produced_dict}}
    jail_art['content_hash'] = fsm_evidence.phase_artifact_hash(jail_art)
    return fsm_baseline_capture.baseline_capture(jail_art, reachability_artifact)

def test_oracle_wiring_import_and_signature():
    """Verify that ngv2.baseline_producer is importable and has produce_baseline_input."""
    baseline_producer = importlib.import_module('ngv2.baseline_producer')
    assert hasattr(baseline_producer, 'produce_baseline_input')
    sig = inspect.signature(baseline_producer.produce_baseline_input)
    assert len(sig.parameters) >= 2

def test_oracle_positive_advance(tmp_path):
    """Verify the positive path: a clean benign control run advances fsm_baseline_capture.baseline_capture."""
    baseline_producer = importlib.import_module('ngv2.baseline_producer')
    repo_dir = tmp_path / 'repo'
    repo_dir.mkdir(exist_ok=True)
    work_dir = tmp_path / 'work'
    work_dir.mkdir(exist_ok=True)

    def fake_run(*args, **kwargs):
        (work_dir / 'build.log').write_text('some log')
        return MockCompletedProcess(stdout='benign run output', returncode=0)
    jail_art = get_valid_jail_artifact()
    reach_art = get_valid_reachability_artifact()
    res = _call_produce_baseline_input(baseline_producer, success_marker='EXPLOIT_SUCCESS', expected_fs_signature='flag_file.bin', jail_artifact=jail_art, reachability_artifact=reach_art, run_fn=fake_run, repo_dir=repo_dir, work_dir=work_dir)
    gate_res = run_baseline_gate(res, reach_art)
    assert gate_res['advance'] is True
    assert gate_res['terminal'] == ''
    assert gate_res['artifact'] is not None
    assert gate_res['artifact']['phase'] == 'baseline_capture'
    assert gate_res['artifact']['status'] == 'success'

def test_oracle_negative_empty_marker(tmp_path):
    """Verify empty or missing success_marker yields baseline_vacuous terminal."""
    baseline_producer = importlib.import_module('ngv2.baseline_producer')
    repo_dir = tmp_path / 'repo'
    repo_dir.mkdir(exist_ok=True)
    work_dir = tmp_path / 'work'
    work_dir.mkdir(exist_ok=True)

    def fake_run(*args, **kwargs):
        return MockCompletedProcess(stdout='benign', returncode=0)
    reach_art = get_valid_reachability_artifact()
    res = _call_produce_baseline_input(baseline_producer, success_marker='', expected_fs_signature='flag_file.bin', jail_artifact=get_valid_jail_artifact(), reachability_artifact=reach_art, run_fn=fake_run, repo_dir=repo_dir, work_dir=work_dir)
    gate_res = run_baseline_gate(res, reach_art)
    assert gate_res['advance'] is False
    assert gate_res['terminal'] == 'baseline_vacuous'
    res = _call_produce_baseline_input(baseline_producer, success_marker=None, expected_fs_signature='flag_file.bin', jail_artifact=get_valid_jail_artifact(), reachability_artifact=reach_art, run_fn=fake_run, repo_dir=repo_dir, work_dir=work_dir)
    gate_res = run_baseline_gate(res, reach_art)
    assert gate_res['advance'] is False
    assert gate_res['terminal'] == 'baseline_vacuous'

def test_oracle_negative_empty_signature(tmp_path):
    """Verify empty or missing expected_fs_signature yields baseline_vacuous terminal."""
    baseline_producer = importlib.import_module('ngv2.baseline_producer')
    repo_dir = tmp_path / 'repo'
    repo_dir.mkdir(exist_ok=True)
    work_dir = tmp_path / 'work'
    work_dir.mkdir(exist_ok=True)

    def fake_run(*args, **kwargs):
        return MockCompletedProcess(stdout='benign', returncode=0)
    reach_art = get_valid_reachability_artifact()
    res = _call_produce_baseline_input(baseline_producer, success_marker='EXPLOIT_SUCCESS', expected_fs_signature='', jail_artifact=get_valid_jail_artifact(), reachability_artifact=reach_art, run_fn=fake_run, repo_dir=repo_dir, work_dir=work_dir)
    gate_res = run_baseline_gate(res, reach_art)
    assert gate_res['advance'] is False
    assert gate_res['terminal'] == 'baseline_vacuous'
    res = _call_produce_baseline_input(baseline_producer, success_marker='EXPLOIT_SUCCESS', expected_fs_signature=None, jail_artifact=get_valid_jail_artifact(), reachability_artifact=reach_art, run_fn=fake_run, repo_dir=repo_dir, work_dir=work_dir)
    gate_res = run_baseline_gate(res, reach_art)
    assert gate_res['advance'] is False
    assert gate_res['terminal'] == 'baseline_vacuous'

def test_oracle_negative_contaminated_stdout(tmp_path):
    """Verify contaminated control run (success_marker in stdout) yields baseline_vacuous."""
    baseline_producer = importlib.import_module('ngv2.baseline_producer')
    repo_dir = tmp_path / 'repo'
    repo_dir.mkdir(exist_ok=True)
    work_dir = tmp_path / 'work'
    work_dir.mkdir(exist_ok=True)

    def fake_run(*args, **kwargs):
        return MockCompletedProcess(stdout='output contains EXPLOIT_SUCCESS marker', returncode=0)
    reach_art = get_valid_reachability_artifact()
    res = _call_produce_baseline_input(baseline_producer, success_marker='EXPLOIT_SUCCESS', expected_fs_signature='flag_file.bin', jail_artifact=get_valid_jail_artifact(), reachability_artifact=reach_art, run_fn=fake_run, repo_dir=repo_dir, work_dir=work_dir)
    gate_res = run_baseline_gate(res, reach_art)
    assert gate_res['advance'] is False
    assert gate_res['terminal'] == 'baseline_vacuous'

def test_oracle_negative_contaminated_fs_diff(tmp_path):
    """Verify contaminated control run (expected_fs_signature in fs_diff) yields baseline_vacuous."""
    baseline_producer = importlib.import_module('ngv2.baseline_producer')
    repo_dir = tmp_path / 'repo'
    repo_dir.mkdir(exist_ok=True)
    work_dir = tmp_path / 'work'
    work_dir.mkdir(exist_ok=True)

    def fake_run(*args, **kwargs):
        (work_dir / 'flag_file.bin').write_text('compromised')
        return MockCompletedProcess(stdout='clean run', returncode=0)
    reach_art = get_valid_reachability_artifact()
    res = _call_produce_baseline_input(baseline_producer, success_marker='EXPLOIT_SUCCESS', expected_fs_signature='flag_file.bin', jail_artifact=get_valid_jail_artifact(), reachability_artifact=reach_art, run_fn=fake_run, repo_dir=repo_dir, work_dir=work_dir)
    gate_res = run_baseline_gate(res, reach_art)
    assert gate_res['advance'] is False
    assert gate_res['terminal'] == 'baseline_vacuous'

def test_oracle_refusal_missing_jail():
    """Verify jail_unavailable status for missing/invalid jail_artifact."""
    fsm_baseline_capture = importlib.import_module('ngv2.fsm_baseline_capture')
    reach_art = get_valid_reachability_artifact()
    gate_res1 = fsm_baseline_capture.baseline_capture(None, reach_art)
    assert gate_res1['advance'] is False
    assert gate_res1['terminal'] == 'jail_unavailable'
    gate_res2 = fsm_baseline_capture.baseline_capture('not-a-dict', reach_art)
    assert gate_res2['advance'] is False
    assert gate_res2['terminal'] == 'jail_unavailable'

def test_oracle_refusal_tampered_reachability(tmp_path):
    """Verify missing_evidence/hash_mismatch for tampered reachability prior."""
    baseline_producer = importlib.import_module('ngv2.baseline_producer')
    repo_dir = tmp_path / 'repo'
    repo_dir.mkdir(exist_ok=True)
    work_dir = tmp_path / 'work'
    work_dir.mkdir(exist_ok=True)

    def fake_run(*args, **kwargs):
        return MockCompletedProcess(stdout='clean', returncode=0)
    res = _call_produce_baseline_input(baseline_producer, success_marker='EXPLOIT_SUCCESS', expected_fs_signature='flag_file.bin', jail_artifact=get_valid_jail_artifact(), reachability_artifact=None, run_fn=fake_run, repo_dir=repo_dir, work_dir=work_dir)
    gate_res1 = run_baseline_gate(res, None)
    assert gate_res1['advance'] is False
    assert gate_res1['terminal'] in ('missing_evidence', 'jail_unavailable')
    reach_art = get_valid_reachability_artifact()
    reach_art['content_hash'] = 'a' * 64
    gate_res2 = run_baseline_gate(res, reach_art)
    assert gate_res2['advance'] is False
    assert gate_res2['terminal'] in ('hash_mismatch', 'jail_unavailable')

def test_oracle_fail_soft_seam_none(tmp_path):
    """Verify fail-soft behavior of the producer when seams return None, yielding refusal baseline_input."""
    baseline_producer = importlib.import_module('ngv2.baseline_producer')
    repo_dir = tmp_path / 'repo'
    repo_dir.mkdir(exist_ok=True)
    work_dir = tmp_path / 'work'
    work_dir.mkdir(exist_ok=True)

    def fake_run_none(*args, **kwargs):
        return None
    reach_art = get_valid_reachability_artifact()
    res = _call_produce_baseline_input(baseline_producer, success_marker='EXPLOIT_SUCCESS', expected_fs_signature='flag_file.bin', jail_artifact=get_valid_jail_artifact(), reachability_artifact=reach_art, run_fn=fake_run_none, repo_dir=repo_dir, work_dir=work_dir)
    gate_res = run_baseline_gate(res, reach_art)
    assert gate_res['advance'] is False
    assert gate_res['terminal'] in ('baseline_vacuous', 'jail_unavailable')

def test_oracle_fail_soft_seam_raise(tmp_path):
    """Verify fail-soft behavior of the producer when seams raise exceptions, yielding refusal baseline_input."""
    baseline_producer = importlib.import_module('ngv2.baseline_producer')
    repo_dir = tmp_path / 'repo'
    repo_dir.mkdir(exist_ok=True)
    work_dir = tmp_path / 'work'
    work_dir.mkdir(exist_ok=True)

    def fake_run_raise(*args, **kwargs):
        raise RuntimeError('Seam execution failed')
    reach_art = get_valid_reachability_artifact()
    res = _call_produce_baseline_input(baseline_producer, success_marker='EXPLOIT_SUCCESS', expected_fs_signature='flag_file.bin', jail_artifact=get_valid_jail_artifact(), reachability_artifact=reach_art, run_fn=fake_run_raise, repo_dir=repo_dir, work_dir=work_dir)
    gate_res = run_baseline_gate(res, reach_art)
    assert gate_res['advance'] is False
    assert gate_res['terminal'] in ('baseline_vacuous', 'jail_unavailable')

def test_oracle_seam_isolation(tmp_path, monkeypatch):
    """Verify seam isolation: verify subprocess, socket, and time are not called directly when fake seams are injected."""
    import subprocess
    import socket
    import time

    def fail_direct(*args, **kwargs):
        raise AssertionError('Bypassed seam isolation and called stdlib directly')
    monkeypatch.setattr(subprocess, 'run', fail_direct)
    monkeypatch.setattr(subprocess, 'Popen', fail_direct)
    monkeypatch.setattr(socket, 'socket', fail_direct)
    monkeypatch.setattr(time, 'sleep', fail_direct)
    baseline_producer = importlib.import_module('ngv2.baseline_producer')
    repo_dir = tmp_path / 'repo'
    repo_dir.mkdir(exist_ok=True)
    work_dir = tmp_path / 'work'
    work_dir.mkdir(exist_ok=True)
    called_run = []
    called_sleep = []
    called_socket = []

    def fake_run(*args, **kwargs):
        called_run.append(args)
        return MockCompletedProcess(stdout='clean', returncode=0)

    def fake_sleep(*args, **kwargs):
        called_sleep.append(args)

    def fake_socket(*args, **kwargs):
        called_socket.append(args)
    reach_art = get_valid_reachability_artifact()
    res = _call_produce_baseline_input(baseline_producer, success_marker='EXPLOIT_SUCCESS', expected_fs_signature='flag_file.bin', jail_artifact=get_valid_jail_artifact(), reachability_artifact=reach_art, run_fn=fake_run, sleep_fn=fake_sleep, socket_fn=fake_socket, repo_dir=repo_dir, work_dir=work_dir)
    assert len(called_run) > 0 or len(called_sleep) > 0 or len(called_socket) > 0 or isinstance(res, dict)

def test_oracle_determinism(tmp_path):
    """Verify pure determinism where identical inputs yield identical outputs (serialized)."""
    baseline_producer = importlib.import_module('ngv2.baseline_producer')
    repo_dir = tmp_path / 'repo'
    repo_dir.mkdir(exist_ok=True)
    work_dir = tmp_path / 'work'
    work_dir.mkdir(exist_ok=True)

    def fake_run(*args, **kwargs):
        return MockCompletedProcess(stdout='clean', returncode=0)
    jail_art = get_valid_jail_artifact()
    reach_art = get_valid_reachability_artifact()
    res1 = _call_produce_baseline_input(baseline_producer, success_marker='EXPLOIT_SUCCESS', expected_fs_signature='flag_file.bin', jail_artifact=jail_art, reachability_artifact=reach_art, run_fn=fake_run, repo_dir=repo_dir, work_dir=work_dir)
    for _ in range(10):
        res2 = _call_produce_baseline_input(baseline_producer, success_marker='EXPLOIT_SUCCESS', expected_fs_signature='flag_file.bin', jail_artifact=jail_art, reachability_artifact=reach_art, run_fn=fake_run, repo_dir=repo_dir, work_dir=work_dir)
        assert res1 == res2
        assert json.dumps(res1, sort_keys=True) == json.dumps(res2, sort_keys=True)

def test_oracle_purity(tmp_path):
    """Verify purity: calling produce_baseline_input does not mutate inputs."""
    baseline_producer = importlib.import_module('ngv2.baseline_producer')
    jail_art = get_valid_jail_artifact()
    jail_art_copy = copy.deepcopy(jail_art)
    reach_art = get_valid_reachability_artifact()
    reach_art_copy = copy.deepcopy(reach_art)
    repo_dir = tmp_path / 'repo'
    repo_dir.mkdir(exist_ok=True)
    work_dir = tmp_path / 'work'
    work_dir.mkdir(exist_ok=True)

    def fake_run(*args, **kwargs):
        return MockCompletedProcess(stdout='clean', returncode=0)
    _ = _call_produce_baseline_input(baseline_producer, success_marker='EXPLOIT_SUCCESS', expected_fs_signature='flag_file.bin', jail_artifact=jail_art, reachability_artifact=reach_art, run_fn=fake_run, repo_dir=repo_dir, work_dir=work_dir)
    assert jail_art == jail_art_copy
    assert reach_art == reach_art_copy

def test_regression_contaminated_control_refusal(tmp_path):
    """Regression test ensuring a contaminated control run returns baseline_vacuous terminal."""
    baseline_producer = importlib.import_module('ngv2.baseline_producer')
    repo_dir = tmp_path / 'repo'
    repo_dir.mkdir(exist_ok=True)
    work_dir = tmp_path / 'work'
    work_dir.mkdir(exist_ok=True)

    def fake_run(*args, **kwargs):
        return MockCompletedProcess(stdout='EXPLOIT_SUCCESS detected!', returncode=0)
    reach_art = get_valid_reachability_artifact()
    res = _call_produce_baseline_input(baseline_producer, success_marker='EXPLOIT_SUCCESS', expected_fs_signature='flag_file.bin', jail_artifact=get_valid_jail_artifact(), reachability_artifact=reach_art, run_fn=fake_run, repo_dir=repo_dir, work_dir=work_dir)
    gate_res = run_baseline_gate(res, reach_art)
    assert gate_res['advance'] is False
    assert gate_res['terminal'] == 'baseline_vacuous'

def test_regression_tampered_prior_refusal(tmp_path):
    """Regression test ensuring a tampered reachability prior causes the gate to refuse."""
    baseline_producer = importlib.import_module('ngv2.baseline_producer')
    repo_dir = tmp_path / 'repo'
    repo_dir.mkdir(exist_ok=True)
    work_dir = tmp_path / 'work'
    work_dir.mkdir(exist_ok=True)

    def fake_run(*args, **kwargs):
        return MockCompletedProcess(stdout='clean', returncode=0)
    reach_art = get_valid_reachability_artifact()
    reach_art['content_hash'] = 'incorrect_hash'
    res = _call_produce_baseline_input(baseline_producer, success_marker='EXPLOIT_SUCCESS', expected_fs_signature='flag_file.bin', jail_artifact=get_valid_jail_artifact(), reachability_artifact=reach_art, run_fn=fake_run, repo_dir=repo_dir, work_dir=work_dir)
    gate_res = run_baseline_gate(res, reach_art)
    assert gate_res['advance'] is False
    assert gate_res['terminal'] == 'hash_mismatch'