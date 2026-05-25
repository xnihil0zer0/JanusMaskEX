"""Adversarial bar for can_run_parallel_path_normalization.

These tests are xfail-strict until the can_run_parallel_path_normalization
dispatch lands path-normalization (pathlib.Path(p).resolve() or
os.path.realpath) inside `_files_overlap` in
`harness/autowork_parallelism.py`. On accept, drop the xfail markers (or
flip them to non-xfail) so they become regression guards. They assert the
same invariant the task's verification_command checks, but split into
three discrete pytest cases so each surface form of the bug is its own
failure.

Backlog-review session-22 report rank "Session #24 P4 target list":
`can_run_parallel` is the dispatch-time conflict detector that decides
whether the autowork daemon may spawn two workers concurrently. It is
called from `harness/autowork_daemon.py` in the dispatch loop. The
existing comparison in `_files_overlap` uses raw string equality on file
paths, so a plan that declares one task's `files_touched` as the relative
string `"harness/__init__.py"` and another task's `files_touched` as
the absolute `"/home/.../harness/__init__.py"` slips through as
non-overlapping. The fix normalizes both sides via
`pathlib.Path(p).resolve()` before equality / prefix checks.

The third test (disjoint paths) is intentionally NOT xfail-marked: it
is a regression guard for the no-conflict happy path and must pass both
pre- and post-dispatch.
"""

from __future__ import annotations

import pathlib

import pytest


def _import_can_run_parallel():
    """Import the helper lazily so the module-level adversarial collection
    does not fail if the harness package layout shifts mid-session."""
    from harness.autowork_parallelism import can_run_parallel

    return can_run_parallel


def test_relative_vs_absolute_path_detected_as_conflict():
    """The canonical failure mode the dispatch fixes.

    Task A declares the relative path "harness/__init__.py"; task B
    declares the absolute resolution of the same on-disk file. The
    current `_files_overlap` does a raw `==` comparison and returns
    False, so `can_run_parallel` (incorrectly) returns True. Post-fix,
    both paths normalize to the same canonical string and the helper
    returns False (conflict detected).
    """
    can_run_parallel = _import_can_run_parallel()
    abs_init = str(pathlib.Path("harness/__init__.py").resolve())
    task_a = {"task_id": "A", "files_touched": ["harness/__init__.py"]}
    task_b = {"task_id": "B", "files_touched": [abs_init]}
    # Sanity: the two surface forms must be distinct strings — otherwise
    # the test would pass even without the fix.
    assert task_a["files_touched"][0] != task_b["files_touched"][0], (
        "test setup invariant: relative and absolute forms must differ as "
        "raw strings for this case to exercise the bug"
    )
    assert can_run_parallel(task_a, task_b) is False, (
        "mixed relative-vs-absolute referencing the same on-disk file "
        "must be detected as a conflict — can_run_parallel must return False"
    )


def test_relative_vs_relative_normalized_path_detected_as_conflict():
    """Two relative paths in different surface forms for the same file.

    "harness/__init__.py" vs "./harness/__init__.py" — pathlib.Path's
    resolve() collapses both to the same canonical absolute path. The
    pre-fix `_files_overlap` does a raw `==` comparison and returns
    False; post-fix the normalization step makes them equal.
    """
    can_run_parallel = _import_can_run_parallel()
    task_a = {"task_id": "A", "files_touched": ["harness/__init__.py"]}
    task_b = {"task_id": "B", "files_touched": ["./harness/__init__.py"]}
    assert task_a["files_touched"][0] != task_b["files_touched"][0], (
        "test setup invariant: the two relative surface forms must differ "
        "as raw strings"
    )
    assert can_run_parallel(task_a, task_b) is False, (
        "two relative-path surface forms ('harness/__init__.py' vs "
        "'./harness/__init__.py') that resolve to the same on-disk file "
        "must be detected as a conflict — can_run_parallel must return False"
    )


def test_disjoint_paths_remain_parallel_safe():
    """Regression guard (NOT xfail): genuinely disjoint files must continue
    to be allowed to run in parallel post-fix.

    This protects against an over-broad normalization that collapses
    unrelated files into the same canonical form (e.g. a buggy
    implementation that always returns True from `_files_overlap`).
    """
    can_run_parallel = _import_can_run_parallel()
    task_c = {"task_id": "C", "files_touched": ["harness/__init__.py"]}
    task_d = {"task_id": "D", "files_touched": ["tools/webui_server.py"]}
    assert can_run_parallel(task_c, task_d) is True, (
        "genuinely disjoint files must remain parallel-safe; "
        "can_run_parallel must return True"
    )
