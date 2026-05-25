"""Adversarial battery for harness.sandbox_smoke.smoke_import (DD6).

Reproduces the W64 canary defects against the smoke validator and covers
env-scrub edge cases so future drift in worker sandbox env is caught.
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from harness.sandbox_smoke import smoke_import, _discover_project_root

def test_clean_stdlib_import_passes():
    src = 'import os\nimport sys\n\ndef f() -> int:\n    return 1\n'
    assert smoke_import('clean_stdlib', src) is None

def test_pytest_top_level_import_fails():
    src = 'import pytest\n\ndef f():\n    return 1\n'
    err = smoke_import('pytest_top', src)
    assert err is not None
    assert 'sandbox import failed' in err

def test_module_level_undefined_name_fails():
    src = '_probe = UNDEFINED_NAME\n'
    err = smoke_import('missing_name', src)
    assert err is not None
    assert 'sandbox import failed' in err

def test_syntax_error_fails():
    src = 'def f(:\n    pass\n'
    err = smoke_import('syntax_err', src)
    assert err is not None
    assert 'sandbox import failed' in err

def test_empty_source_passes():
    assert smoke_import('empty_mod', '') is None

def test_non_ascii_source_passes():
    src = "# é\ndef f() -> str:\n    return 'é'\n"
    assert smoke_import('non_ascii', src) is None

def test_timeout_on_infinite_loop():
    src = 'while True:\n    pass\n'
    err = smoke_import('inf_loop', src, timeout=1.0)
    assert err is not None
    assert 'timed out' in err

def test_cross_harness_import_passes_after_g16():
    src = 'from harness import git_integration\n\ndef f():\n    return 1\n'
    err = smoke_import('cross_module_g16_ok', src)
    assert err is None

def test_discover_project_root_finds_repo_root():
    result = _discover_project_root()
    assert result is not None
    assert (result / 'harness' / 'sandbox_smoke.py').exists()