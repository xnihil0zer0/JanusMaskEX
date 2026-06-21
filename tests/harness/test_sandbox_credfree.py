import os
import sys
import shutil
import pytest
from pathlib import Path
from unittest.mock import MagicMock
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from harness.agent_jail import bwrap_available, build_jail_argv
if not bwrap_available():
    pytest.skip('bwrap unavailable', allow_module_level=True)
from harness.sandbox import Sandbox, SandboxConfig, BatchRunner, BatchWorkerPool

@pytest.fixture(scope='module')
def setup_dummy_credentials():
    gemini_dir = Path.home() / '.gemini'
    gemini_file = gemini_dir / 'oauth_creds.json'
    claude_dir = Path.home() / '.claude'
    claude_file = claude_dir / '.credentials.json'
    gemini_existed = gemini_file.exists()
    gemini_old_content = gemini_file.read_bytes() if gemini_existed else None
    claude_existed = claude_file.exists()
    claude_old_content = claude_file.read_bytes() if claude_existed else None
    gemini_dir.mkdir(parents=True, exist_ok=True)
    gemini_file.write_text('{"secret": "real-host-gemini-creds-12345"}')
    claude_dir.mkdir(parents=True, exist_ok=True)
    claude_file.write_text('{"secret": "real-host-claude-creds-12345"}')
    yield {'gemini_path': gemini_file, 'gemini_secret': b'real-host-gemini-creds-12345', 'claude_path': claude_file, 'claude_secret': b'real-host-claude-creds-12345'}
    if gemini_existed:
        gemini_file.write_bytes(gemini_old_content)
    else:
        try:
            gemini_file.unlink()
        except OSError:
            pass
    if claude_existed:
        claude_file.write_bytes(claude_old_content)
    else:
        try:
            claude_file.unlink()
        except OSError:
            pass

def test_cred_read_blocked(setup_dummy_credentials, tmp_path):
    sb = Sandbox(config=SandboxConfig(), session_id='test_cred_read_blocked')
    sb._sandbox_dir = tmp_path / 'sandbox_test'
    sb._sandbox_dir.mkdir()
    code_gemini = '\ndef read_gemini():\n    import os\n    try:\n        with open(os.path.expanduser("~/.gemini/oauth_creds.json"), "rb") as f:\n            return f.read()\n    except Exception as e:\n        return str(type(e).__name__)\n'
    res_gemini = sb.execute(code_gemini, 'read_gemini')
    code_claude = '\ndef read_claude():\n    import os\n    try:\n        with open(os.path.expanduser("~/.claude/.credentials.json"), "rb") as f:\n            return f.read()\n    except Exception as e:\n        return str(type(e).__name__)\n'
    res_claude = sb.execute(code_claude, 'read_claude')
    assert res_gemini.return_value != setup_dummy_credentials['gemini_secret']
    assert res_claude.return_value != setup_dummy_credentials['claude_secret']
    sb.cleanup()

def test_batch_runner_cred_read_blocked(setup_dummy_credentials, tmp_path):
    runner = BatchRunner(config=SandboxConfig(), session_id='test_batch_cred_read_blocked')
    runner._sandbox_dir = tmp_path / 'sandbox_batch_test'
    runner._sandbox_dir.mkdir()
    code = '\ndef read_creds(fpath):\n    import os\n    try:\n        with open(os.path.expanduser(fpath), "rb") as f:\n            return f.read()\n    except Exception as e:\n        return str(type(e).__name__)\n'
    inputs = [{'args': ['~/.gemini/oauth_creds.json']}, {'args': ['~/.claude/.credentials.json']}]
    batch_res = runner.execute_batch(code, 'read_creds', inputs)
    assert batch_res.batch_error is None
    results = batch_res.results
    assert results[0].return_value != setup_dummy_credentials['gemini_secret']
    assert results[1].return_value != setup_dummy_credentials['claude_secret']
    runner.cleanup()

def test_pool_worker_cred_read_blocked(setup_dummy_credentials):
    config = SandboxConfig()
    with BatchWorkerPool(1, config=config, session_id='test_pool_cred') as pool:
        code = '\ndef read_creds(fpath):\n    import os\n    try:\n        with open(os.path.expanduser(fpath), "rb") as f:\n            return f.read()\n    except Exception as e:\n        return str(type(e).__name__)\n'
        inputs = [{'args': ['~/.gemini/oauth_creds.json']}, {'args': ['~/.claude/.credentials.json']}]
        batch_res = pool.submit(code, 'read_creds', inputs)
        assert batch_res.batch_error is None
        results = batch_res.results
        assert results[0].return_value != setup_dummy_credentials['gemini_secret']
        assert results[1].return_value != setup_dummy_credentials['claude_secret']

def test_jailed_popen_argv(monkeypatch):
    import subprocess
    import harness.sandbox
    assert hasattr(harness.sandbox, '_jailed_popen')
    captured_args = []

    def mock_popen(cmd, *args, **kwargs):
        captured_args.append(cmd)
        return MagicMock()
    monkeypatch.setattr(subprocess, 'Popen', mock_popen)
    harness.sandbox._jailed_popen(['python', '-c', 'pass'], cwd='/tmp', env={})
    assert len(captured_args) == 1
    jailed_argv = captured_args[0]
    assert '--unshare-net' in jailed_argv
    assert '--unshare-ipc' in jailed_argv
    home_dir = str(Path.home().resolve())
    for i, token in enumerate(jailed_argv):
        if token in ('--bind', '--ro-bind'):
            source_path = jailed_argv[i + 1]
            resolved_source = str(Path(source_path).resolve())
            assert not resolved_source.startswith(str(Path.home() / '.gemini'))
            assert not resolved_source.startswith(str(Path.home() / '.claude'))
            assert resolved_source != home_dir

def test_sandbox_execute_benign_roundtrip(tmp_path):
    sb = Sandbox(config=SandboxConfig(), session_id='test_benign_sandbox')
    sb._sandbox_dir = tmp_path / 'sandbox_benign'
    sb._sandbox_dir.mkdir()
    code = 'def f(x): return x + 1'
    res = sb.execute(code, 'f', args=[42])
    assert res.success is True
    assert res.return_value == 43
    sb.cleanup()

def test_batch_runner_benign_roundtrip(tmp_path):
    runner = BatchRunner(config=SandboxConfig(), session_id='test_benign_batch')
    runner._sandbox_dir = tmp_path / 'sandbox_batch'
    runner._sandbox_dir.mkdir()
    code = 'def f(x): return x + 1'
    inputs = [{'args': [i]} for i in range(10)]
    batch_res = runner.execute_batch(code, 'f', inputs)
    assert batch_res.batch_error is None
    assert batch_res.completed_inputs == 10
    for i, res in enumerate(batch_res.results):
        assert res.success is True
        assert res.return_value == i + 1
    runner.cleanup()

def test_pool_worker_benign_roundtrip():
    config = SandboxConfig()
    with BatchWorkerPool(2, config=config, session_id='test_benign_pool') as pool:
        code = 'def f(x): return x + 1'
        inputs = [{'args': [i]} for i in range(10)]
        batch_res = pool.submit(code, 'f', inputs)
        assert batch_res.batch_error is None
        assert batch_res.completed_inputs == 10
        for i, res in enumerate(batch_res.results):
            assert res.success is True
            assert res.return_value == i + 1

def test_differential_fuzz_equivalence():
    code_a = 'def add(a: int, b: int) -> int:\n    return a + b\n'
    code_b = 'def add(a: int, b: int) -> int:\n    return b + a\n'
    config = {'sandbox': {'memory_limit_mb': 256, 'cpu_time_limit_seconds': 3}, 'fuzzing': {'timeout_per_input_ms': 1000, 'seed': 42, 'function_level_inputs': 10}, 'batch_execution': {'enabled': True, 'worker_pool_size': 1}}
    from harness.diff_fuzzer import differential_fuzz
    fuzz_res = differential_fuzz(code_a, code_b, 'add', config, session_id='test_equiv')
    assert fuzz_res.equivalent is True
    assert fuzz_res.error is None
    assert fuzz_res.matching_inputs > 0

def test_differential_fuzz_equivalence_pool():
    code_a = 'def add(a: int, b: int) -> int:\n    return a + b\n'
    code_b = 'def add(a: int, b: int) -> int:\n    return b + a\n'
    config = {'sandbox': {'memory_limit_mb': 256, 'cpu_time_limit_seconds': 3}, 'fuzzing': {'timeout_per_input_ms': 1000, 'seed': 42, 'function_level_inputs': 10}, 'batch_execution': {'enabled': True, 'worker_pool_size': 2}}
    from harness.diff_fuzzer import differential_fuzz
    fuzz_res = differential_fuzz(code_a, code_b, 'add', config, session_id='test_equiv_pool')
    assert fuzz_res.equivalent is True
    assert fuzz_res.error is None
    assert fuzz_res.matching_inputs > 0

def test_skip_guard():
    from harness.agent_jail import bwrap_available
    assert bwrap_available() is True