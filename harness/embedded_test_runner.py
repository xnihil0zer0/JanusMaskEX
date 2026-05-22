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
__all__ = ['run_embedded_tests', 'should_run_embedded_tests']
_MODULE_NAME_RE = re.compile('^[A-Za-z_][A-Za-z0-9_]*$')
_WORKER_SCRUB_ENV = {'PATH': '/usr/bin:/bin', 'LANG': 'C'}

def should_run_embedded_tests(module_src: str) -> bool:
    """Return True iff ``module_src`` has a top-level pytest target.

    A top-level target is a ``FunctionDef`` whose name starts with
    ``test_`` or a ``ClassDef`` whose name starts with ``Test``. Parse
    failures return False — the AST-enforcer already rejects syntax
    errors on the accept path, so hitting this branch means the module
    is syntactically invalid and pytest collection would trivially fail.
    """
    raise NotImplementedError

def _pytest_site_dir() -> str:
    """Resolve pytest's parent site-packages directory.

    Decision B scrub spec: ``find_spec("pytest").submodule_search_locations[0]``
    gives the ``pytest`` package directory; its parent is the
    site-packages directory to expose on PYTHONPATH.
    """
    raise NotImplementedError

def run_embedded_tests(module_name: str, module_src: str, *, timeout: float=10.0) -> str | None:
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
    raise NotImplementedError