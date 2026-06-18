"""RED-on-HEAD oracle for the static-cleanup dedupe / delegation fix.

This is a pure verification oracle (a pytest TEST FILE), not an implementation.
It asserts two paired facts about the repo:

  1. The hand-maintained static KEEP/DELETE allowlist has been removed from
     ``scripts/cleanup_stale_artifacts.py`` (no module-level ``KEEP_*``/``DELETE_*``
     constants and no ``categorize_root`` allowlist function survive).

  2. ``scripts/brief_status.py`` has been deduped to delegate to the canonical
     ``harness/brief_status.py`` -- it imports ``harness.brief_status``, references
     ``compute_brief_status``, and no longer defines its own duplicate
     ``run_green()``.  A non-vacuity witness imports ``scripts.brief_status`` and
     proves the CLI actually *routes* to ``harness.brief_status.compute_brief_status``
     (not just a dead import string), so a stub mutant of the declared
     ``mutation_target`` (``scripts.brief_status``) flips the witness RED.

All checks are RED against real HEAD (the allowlist + ``run_green`` still exist and
there is no harness delegation) and go GREEN once the paired impl lands.  The
oracle is hermetic: static source/AST reads plus an import-and-delegation witness
that redirects the repo-root lookup at an empty ``tmp_path``.  No live ``state/``,
no network, no live-daemon run.
"""
import ast
import importlib
import pathlib
import sys
import pytest
_HERE = pathlib.Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[2]
_SCRIPTS_DIR = _REPO_ROOT / 'scripts'
_CLEANUP_PATH = _SCRIPTS_DIR / 'cleanup_stale_artifacts.py'
_BRIEF_STATUS_PATH = _SCRIPTS_DIR / 'brief_status.py'
_KEEP_DELETE_PREFIXES = ('KEEP_', 'DELETE_')

def _parse(path: pathlib.Path) -> ast.Module:
    """Parse a source file into an AST, failing loudly if it is missing."""
    assert path.exists(), f'expected source file is missing: {path}'
    return ast.parse(path.read_text(encoding='utf-8'), filename=str(path))

def _assigned_names(tree: ast.Module):
    """Every simple ``Name`` assignment target anywhere in the module."""
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    names.append(tgt.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.append(node.target.id)
    return names

def _func_names(tree: ast.Module):
    return [n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]

def _imports_harness_brief_status(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == 'harness.brief_status' or alias.name == 'harness':
                    return True
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ''
            if mod == 'harness.brief_status' or mod == 'harness' or mod.startswith('harness.'):
                return True
    return False

def _references_compute_brief_status(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == 'compute_brief_status':
            return True
        if isinstance(node, ast.Name) and node.id == 'compute_brief_status':
            return True
        if isinstance(node, ast.alias) and node.name == 'compute_brief_status':
            return True
    return False

def test_cleanup_script_has_no_keep_delete_constants_or_categorize_root():
    """RED on HEAD: KEEP_*/DELETE_* constants + categorize_root still exist."""
    tree = _parse(_CLEANUP_PATH)
    keep_delete = [name for name in _assigned_names(tree) if name.startswith(_KEEP_DELETE_PREFIXES)]
    assert not keep_delete, f'static allowlist constants still present in scripts/cleanup_stale_artifacts.py: {keep_delete}'
    funcs = _func_names(tree)
    assert 'categorize_root' not in funcs, 'allowlist function categorize_root still present in scripts/cleanup_stale_artifacts.py'

def test_brief_status_imports_and_delegates_to_harness_compute_brief_status():
    """RED on HEAD: no harness.brief_status import / no compute_brief_status ref."""
    tree = _parse(_BRIEF_STATUS_PATH)
    assert _imports_harness_brief_status(tree), 'scripts/brief_status.py does not import harness.brief_status'
    assert _references_compute_brief_status(tree), 'scripts/brief_status.py does not reference compute_brief_status'

def test_brief_status_no_longer_defines_run_green_duplicate():
    """RED on HEAD: brief_status still defines its own duplicate run_green()."""
    tree = _parse(_BRIEF_STATUS_PATH)
    funcs = _func_names(tree)
    assert 'run_green' not in funcs, 'scripts/brief_status.py still defines its own duplicate run_green(); it should delegate to harness.brief_status instead'

def test_nonvacuity_witness_scripts_brief_status_routes_to_harness(monkeypatch, tmp_path):
    """GREEN only when the CLI actually calls compute_brief_status.

    Hermetic: the repo-root lookup is redirected at an empty tmp_path so HEAD's
    real classify() (which would otherwise glob the repo and shell out) stays
    inert.  We record calls to harness.brief_status.compute_brief_status; on HEAD
    (no delegation) and on any stub mutant it is never called -> RED.
    """
    hbs = importlib.import_module('harness.brief_status')
    sbs = importlib.import_module('scripts.brief_status')
    calls = {'n': 0}

    def _recorder(*args, **kwargs):
        calls['n'] += 1
        return []
    monkeypatch.setattr(hbs, 'compute_brief_status', _recorder, raising=False)
    sbs = importlib.reload(sbs)
    if hasattr(sbs, 'compute_brief_status'):
        monkeypatch.setattr(sbs, 'compute_brief_status', _recorder, raising=False)
    if hasattr(sbs, 'REPO'):
        monkeypatch.setattr(sbs, 'REPO', tmp_path, raising=False)
    monkeypatch.setattr(sys, 'argv', ['brief_status'])
    entry = getattr(sbs, 'main', None) or getattr(sbs, 'classify', None)
    assert entry is not None, 'scripts.brief_status exposes no main()/classify() entry point to exercise'
    try:
        entry()
    except SystemExit:
        pass
    except Exception:
        pass
    assert calls['n'] > 0, 'scripts.brief_status did NOT delegate to harness.brief_status.compute_brief_status (no routing observed)'

def test_allowlist_constants_absent_under_any_stub_rewrite():
    """Assert by KEEP_/DELETE_ prefix family so a rename cannot vacuously pass.

    Passes for any inert stub of scripts/cleanup_stale_artifacts.py (docstring
    only, no-op main()); fails only while allowlist-family constants survive.
    """
    tree = _parse(_CLEANUP_PATH)
    offenders = sorted((name for name in _assigned_names(tree) if name.startswith(_KEEP_DELETE_PREFIXES)))
    assert offenders == [], f'allowlist-family constants (KEEP_*/DELETE_*) survive a rewrite: {offenders}'

def test_oracle_is_hermetic_no_live_state_or_network():
    """This oracle must not reach the network or a live daemon/state."""
    src = _HERE.read_text(encoding='utf-8')
    forbidden = ('import socket', 'import requests', 'import httpx', 'import urllib', 'http.client', 'urlopen')
    leaks = [tok for tok in forbidden if tok in src]
    assert leaks == [], f'oracle references forbidden network primitives: {leaks}'
    assert 'tmp_path' in src, 'witness must redirect repo-root lookups at tmp_path'