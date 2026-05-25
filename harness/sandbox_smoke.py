"""Sandboxed import-smoke for accepted canary output (DD6).

Motivation
----------
The three W64 canary defects documented in
``brief_hooks_silent_canary_signals.md`` shipped because the orchestrator's
``BYPASS_FUZZER_TYPES`` accept path does no runtime validation beyond
``ast_enforcer.validate_code``. In particular, ``harness/task_id_normalizer.py``
contained a top-level ``import pytest`` that imports cleanly in the
orchestrator's own environment (pytest is installed there) but would crash
any worker trying to import the module with a stripped PYTHONPATH.

:func:`smoke_import` reproduces the worker env-scrub documented in
``state/impl_progress.jsonl`` 2026-04-19T15:13:53Z (B3 blocker #11). It
returns ``None`` on clean import, or a short error string prefixed with
``sandbox import failed:`` if the subprocess failed.

The scrubbed env is intentionally minimal: only the tempdir (which holds
the candidate module) is on ``PYTHONPATH``. That means legitimate
``from harness.<x> import <y>`` imports WILL fail the smoke — caller must
either inline the dependency into the candidate, or accept that canary
helpers are stdlib-only by contract (matches current ``BYPASS_FUZZER_TYPES``
intent).
"""
from __future__ import annotations
import pathlib
import subprocess
import sys
import tempfile
__all__ = ['smoke_import']
_WORKER_SCRUB_ENV = {'PATH': '/usr/bin:/bin', 'LANG': 'C'}

def smoke_import(module_name: str, module_src: str, *, timeout: float=5.0) -> str | None:
    """Import ``module_src`` under a scrubbed subprocess; return error on failure.

    Args:
        module_name: The name the candidate will be imported as (becomes the
            filename under the tempdir). Caller ensures it is a valid Python
            identifier.
        module_src: The candidate module source. Written to
            ``<tempdir>/<module_name>.py`` verbatim.
        timeout: Seconds to wait for the subprocess.

    Returns:
        ``None`` if the subprocess exits 0 (import succeeded). Otherwise a
        short error string starting with ``sandbox import failed:`` and
        containing the subprocess stderr (or stdout if stderr is empty).
        On timeout, returns ``sandbox import timed out``.
    """
    with tempfile.TemporaryDirectory() as td:
        td_path = pathlib.Path(td)
        mod_path = td_path / f'{module_name}.py'
        mod_path.write_text(module_src, encoding='utf-8')
        env = dict(_WORKER_SCRUB_ENV)
        env['PYTHONPATH'] = str(td_path)
        root = _discover_project_root()
        if root is not None:
            env['PYTHONPATH'] = f'{td_path}{os.pathsep}{root}'
        try:
            proc = subprocess.run([sys.executable, '-S', '-c', f'import {module_name}'], cwd=str(td_path), env=env, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return 'sandbox import timed out'
    if proc.returncode != 0:
        msg = proc.stderr.strip() or proc.stdout.strip() or 'subprocess exited nonzero with no output'
        return f'sandbox import failed: {msg}'
    return None

def _discover_project_root() -> pathlib.Path | None:
    here = pathlib.Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        if (parent / '.git').exists() or (parent / 'pyproject.toml').exists():
            return parent
    return None
import os