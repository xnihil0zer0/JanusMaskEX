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
the candidate module), the project root, and the project's site-packages
directories are on ``PYTHONPATH``. The tempdir + project root let
legitimate ``from harness.<x> import <y>`` imports resolve; the
site-packages dirs (discovered via :func:`_site_packages_dirs`, mirroring
``harness/embedded_test_runner.py:_pytest_site_dir``) make the gate
*venv-aware* so a submission that imports a third-party package which is
genuinely installed in the project's environment is smoke-tested with that
package on ``sys.path`` rather than failing spuriously under a bare ``-S``
interpreter.

This does NOT make the gate fail-open: a genuine import-time crash — an
``import`` of a package that is not installed anywhere, a module-level
``NameError``, or a ``SyntaxError`` — still fails the smoke. The gate only
stops rejecting imports that would in fact succeed in the worker's real
environment.
"""
from __future__ import annotations
import os
import pathlib
import site
import subprocess
import sys
import tempfile
__all__ = ['smoke_import']
_WORKER_SCRUB_ENV = {'PATH': '/usr/bin:/bin', 'LANG': 'C'}

def _site_packages_dirs() -> list[str]:
    """Return the project's site-packages directories (venv-aware).

    Mirrors ``harness/embedded_test_runner.py:_pytest_site_dir`` in intent:
    surface the real site-packages dir(s) of the interpreter running the
    orchestrator so the scrubbed ``-S`` subprocess can import third-party
    packages that are genuinely installed (e.g. inside the project venv).
    Uses only the stdlib :mod:`site` module. Returns a de-duplicated list of
    existing directories; missing/unavailable entries are skipped so the
    gate degrades to the prior tempdir+root behavior rather than crashing.
    """
    dirs: list[str] = []
    getters = (getattr(site, 'getsitepackages', None), getattr(site, 'getusersitepackages', None))
    for getter in getters:
        if getter is None:
            continue
        try:
            result = getter()
        except Exception:
            continue
        if isinstance(result, str):
            result = [result]
        for d in result:
            if d and os.path.isdir(d) and (d not in dirs):
                dirs.append(d)
    return dirs

def smoke_import(module_name: str, module_src: str, *, timeout: float=5.0, extra_paths: 'Iterable[str | os.PathLike]'=()) -> str | None:
    """Import ``module_src`` under a scrubbed subprocess; return error on failure.

    Args:
        module_name: The name the candidate will be imported as (becomes the
            filename under the tempdir). Caller ensures it is a valid Python
            identifier.
        module_src: The candidate module source. Written to
            ``<tempdir>/<module_name>.py`` verbatim.
        timeout: Seconds to wait for the subprocess.
        extra_paths: External dependency root(s) to make resolvable on both
            PYTHONPATH and (jailed) the ro-bind list.

    Returns:
        ``None`` if the subprocess exits 0 (import succeeded). Otherwise a
        short error string starting with ``sandbox import failed:`` and
        containing the subprocess stderr (or stdout if stderr is empty).
        On timeout, returns ``sandbox import timed out``.
    """
    from contextlib import ExitStack
    from harness.dbus_proxy import proxied_session_bus
    with tempfile.TemporaryDirectory() as td, ExitStack() as _dbus_stack:
        _dbus_sock = None
        td_path = pathlib.Path(td)
        mod_path = td_path / f'{module_name}.py'
        mod_path.write_text(module_src, encoding='utf-8')
        _extra = [str(p) for p in extra_paths if str(p)]
        if not _extra:
            try:
                _wd = os.environ.get('JANUSMASK_WORKING_DIR')
                if _wd:
                    from harness.paths import _target_is_self
                    if not _target_is_self(_wd):
                        _extra = [str(_wd)]
            except Exception:
                _extra = []
        env = dict(_WORKER_SCRUB_ENV)
        path_parts = [str(td_path)]
        root = _discover_project_root()
        if root is not None:
            path_parts.append(str(root))
        path_parts.extend(_site_packages_dirs())
        path_parts.extend(_extra)
        env['PYTHONPATH'] = os.pathsep.join(path_parts)
        cmd = [sys.executable, '-S', '-c', f'import {module_name}']
        from harness.orchestrator import load_config
        from harness import agent_jail
        if agent_jail.sandbox_enabled(load_config()):
            repo_root = root if root is not None else pathlib.Path(__file__).resolve().parents[1]
            state_dir = repo_root / 'state'
            extra_ro = [sys.base_prefix, sys.prefix] + _site_packages_dirs() + _extra
            try:
                _dbus_sock = _dbus_stack.enter_context(proxied_session_bus())
            except Exception:
                import shutil
                if shutil.which('xdg-dbus-proxy'):
                    raise RuntimeError('filtered D-Bus proxy failed to start')
                _dbus_sock = None
            try:
                cmd = agent_jail.build_jail_argv(['python3', '-S', '-c', f'import {module_name}'], repo_root=repo_root, work_dir=td_path, state_dir=state_dir, extra_ro=extra_ro, dbus_proxy_socket=_dbus_sock, bind_credentials=False)
                env['PATH'] = os.pathsep.join([os.path.join(sys.prefix, 'bin'), env['PATH']])
            except FileNotFoundError:
                return 'sandbox import failed: agent_sandbox.bwrap is enabled but bwrap is not on PATH; refusing to import the candidate unjailed (fail-closed)'
        try:
            proc = subprocess.run(cmd, cwd=str(td_path), env=env, capture_output=True, text=True, timeout=timeout)
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