"""Embedded pytest runner for bypass-eligible candidate modules (DD6-cat2).

Motivation
----------
Row 2 of ``brief_hooks_silent_canary_signals.md``'s per-bug table documents
the W64 defect where a canary shipped with ``assert 0.1 + 0.2 == 0.3``
inside an embedded test. ``validate_code`` does not execute tests and
``sandbox_smoke.smoke_import`` only checks clean import — so the failing
assertion never manifested on the accept path. :func:`run_embedded_tests`
closes that signal gap by actually running pytest against any candidate
that ships top-level ``test_*`` functions or ``Test*`` classes.

Scrub policy
------------
Per ``brief_hooks_dd6_post_w71_decisions.md`` §3 Decision B, this module
deviates from :mod:`harness.sandbox_smoke`'s fully-hermetic scrub in
exactly one place: ``PYTHONPATH`` exposes pytest's site-packages directory
so the subprocess can ``import pytest``. All other scrub guarantees are
preserved:

* ``PATH`` locked to ``/usr/bin:/bin``.
* ``LANG=C`` (no locale-dependent behavior).
* ``-S`` flag (no automatic site-packages discovery beyond the explicit
  pytest path we hand it).
* ``subprocess.run(env=ENV, ...)`` — no inheritance of parent env vars.

Any future edit that further relaxes this scrub MUST author a new brief
amend before landing (see Decision B "Pin").
"""
from __future__ import annotations

import ast
import importlib.util
import os
import pathlib
import re
import subprocess
import sys
import tempfile

__all__ = ["run_embedded_tests", "should_run_embedded_tests"]


_MODULE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_WORKER_SCRUB_ENV = {
    "PATH": "/usr/bin:/bin",
    "LANG": "C",
}


def should_run_embedded_tests(module_src: str) -> bool:
    """Return True iff ``module_src`` has a top-level pytest target.

    A top-level target is a ``FunctionDef`` whose name starts with
    ``test_`` or a ``ClassDef`` whose name starts with ``Test``. Parse
    failures return False — the AST-enforcer already rejects syntax
    errors on the accept path, so hitting this branch means the module
    is syntactically invalid and pytest collection would trivially fail.
    """
    try:
        tree = ast.parse(module_src)
    except SyntaxError:
        return False
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
            return True
        if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            return True
    return False


def _pytest_site_dir() -> str:
    """Resolve pytest's parent site-packages directory.

    Decision B scrub spec: ``find_spec("pytest").submodule_search_locations[0]``
    gives the ``pytest`` package directory; its parent is the
    site-packages directory to expose on PYTHONPATH.
    """
    spec = importlib.util.find_spec("pytest")
    if spec is None or not spec.submodule_search_locations:
        raise RuntimeError("pytest not importable from orchestrator env")
    return os.path.dirname(spec.submodule_search_locations[0])


def run_embedded_tests(
    module_name: str,
    module_src: str,
    *,
    timeout: float = 10.0,
) -> str | None:
    """Run pytest against ``module_src`` under a scrubbed subprocess.

    Args:
        module_name: Valid Python identifier used as the candidate
            filename under the tempdir (``<td>/<module_name>.py``).
        module_src: Candidate module source. Written verbatim.
        timeout: Seconds to wait for each pytest invocation (collect
            phase and run phase are gated separately).

    Returns:
        ``None`` if the gate deems the module test-less OR if pytest
        exits 0 for both collect-only and the actual run. Otherwise a
        short error string: ``embedded tests collect failed: ...``,
        ``embedded tests failed: ...``, or ``embedded tests timed out``.
    """
    if not should_run_embedded_tests(module_src):
        return None
    if not _MODULE_NAME_RE.match(module_name):
        return f"embedded tests rejected: invalid module_name {module_name!r}"

    # Lazy in-body imports (no new module-level imports / top-level symbols).
    from harness.orchestrator import load_config
    from harness.agent_jail import build_jail_argv, sandbox_enabled
    from harness.paths import PROJECT_ROOT, STATE_DIR

    config = load_config()
    sandboxed = sandbox_enabled(config)

    # SEC-5a: config-driven verify allowlists. Read with safe .get() + [] defaults
    # so configs omitting agent_sandbox.verify_extra_ro / verify_extra_rw stay
    # backward compatible. verify_extra_ro is ADDED to the existing
    # sys.base_prefix / sys.prefix ro binds; verify_extra_rw becomes the rw allowlist.
    _sb = config.get("agent_sandbox", {})
    _verify_extra_ro = list(_sb.get("verify_extra_ro", []))
    _verify_extra_rw = list(_sb.get("verify_extra_rw", []))

    pytest_site = _pytest_site_dir()

    with tempfile.TemporaryDirectory() as td:
        td_path = pathlib.Path(td)
        mod_path = td_path / f"{module_name}.py"
        mod_path.write_text(module_src, encoding="utf-8")
        env = dict(_WORKER_SCRUB_ENV)
        env["PYTHONPATH"] = f"{td_path}{os.pathsep}{pytest_site}"

        # When sandboxing, the subprocess runs a bare ``python3`` inside the
        # bwrap jail; prepend the venv bin dir so it resolves to the
        # pytest-bearing venv interpreter rather than /usr/bin/python3.
        python = "python3" if sandboxed else sys.executable
        if sandboxed:
            env["PATH"] = f"{os.path.join(sys.prefix, 'bin')}{os.pathsep}{env['PATH']}"

        collect_argv = [
            python,
            "-S",
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            f"{module_name}.py",
        ]
        if sandboxed:
            # SEC-3 fail-closed: build_jail_argv raises FileNotFoundError when
            # the sandbox is enabled but bwrap is not on PATH. Catch it and
            # return a clean rejection string instead of letting it propagate
            # and crash; critically, NO unjailed subprocess is dispatched.
            try:
                collect_argv = build_jail_argv(
                    collect_argv,
                    repo_root=PROJECT_ROOT,
                    work_dir=str(td_path),
                    state_dir=STATE_DIR,
                    extra_ro=[sys.base_prefix, sys.prefix, *_verify_extra_ro],
                    extra_rw=_verify_extra_rw,
                )
            except FileNotFoundError:
                return (
                    "embedded tests failed: agent_sandbox.bwrap is enabled but "
                    "bwrap is not on PATH; refusing to run unjailed (fail-closed)"
                )
        try:
            proc = subprocess.run(
                collect_argv,
                cwd=str(td_path),
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return "embedded tests timed out"
        if proc.returncode != 0:
            msg = (
                proc.stderr.strip()
                or proc.stdout.strip()
                or "subprocess exited nonzero with no output"
            )
            return f"embedded tests collect failed: {msg}"

        run_argv = [
            python,
            "-S",
            "-m",
            "pytest",
            "-x",
            "--no-header",
            "-q",
            f"{module_name}.py",
        ]
        if sandboxed:
            # SEC-3 fail-closed (symmetric to the collect_argv guard above).
            try:
                run_argv = build_jail_argv(
                    run_argv,
                    repo_root=PROJECT_ROOT,
                    work_dir=str(td_path),
                    state_dir=STATE_DIR,
                    extra_ro=[sys.base_prefix, sys.prefix, *_verify_extra_ro],
                    extra_rw=_verify_extra_rw,
                )
            except FileNotFoundError:
                return (
                    "embedded tests failed: agent_sandbox.bwrap is enabled but "
                    "bwrap is not on PATH; refusing to run unjailed (fail-closed)"
                )
        try:
            proc = subprocess.run(
                run_argv,
                cwd=str(td_path),
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return "embedded tests timed out"
    if proc.returncode != 0:
        msg = (
            proc.stdout.strip()
            or proc.stderr.strip()
            or "subprocess exited nonzero with no output"
        )
        return f"embedded tests failed: {msg}"
    return None
