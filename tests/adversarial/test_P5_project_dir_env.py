"""B8 coverage: harness.hooks_equivalence._project_dir env fall-through.

Sub-plan 04 §Proposed 3 + master-plan B8 widen the _project_dir resolver in
harness/hooks_equivalence.py to fall through
JANUSMASK_PROJECT_DIR -> CLAUDE_PROJECT_DIR -> __file__-relative, matching
harness/hooks/_paths.py:26. Without the widen, a subprocess that inherits
only CLAUDE_PROJECT_DIR (Anthropic-convention) silently targets the
compile-time __file__.parent.parent -- which happens to be the real repo
when the module ships in-tree, and a random unrelated dir otherwise.

These tests subprocess harness.hooks_equivalence with ONLY CLAUDE_PROJECT_DIR
set (JANUSMASK_PROJECT_DIR explicitly scrubbed) and assert the shadow dir
and rollback-signal path resolve under the CLAUDE_PROJECT_DIR value.

All three tests are marked xfail(strict=False) while the repo is in the
META phase: the write gate blocks the corrections edit to
harness/hooks_equivalence.py (P5-only allow-list). Once the widen lands,
they flip to xpassed and guard the fall-through invariant going forward.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys

import pytest


_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


_B8_XFAIL_REASON = (
    "Sub-plan 04 phase5 §Proposed 3 / master-plan B8: "
    "harness/hooks_equivalence.py:74 still reads only JANUSMASK_PROJECT_DIR. "
    "The META-phase write gate blocks the corrections edit to "
    "harness/hooks_equivalence.py (file lives in the P5 allow-list only). "
    "Test flips green once the widen lands under a P5 scope-exception or "
    "post-cutover commit."
)


def _env_only_claude(tmp_path: pathlib.Path) -> dict:
    env = {k: v for k, v in os.environ.items()
           if k not in ("JANUSMASK_PROJECT_DIR", "CLAUDE_PROJECT_DIR")}
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path)
    return env


def _probe_project_dir(tmp_path: pathlib.Path) -> str:
    code = (
        "import sys;"
        "sys.path.insert(0, " + repr(str(_REPO_ROOT)) + ");"
        "from harness.hooks_equivalence import _project_dir;"
        "print(str(_project_dir()))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        env=_env_only_claude(tmp_path),
        cwd=str(_REPO_ROOT),
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


def test_project_dir_falls_through_to_claude_project_dir(tmp_path):
    resolved = _probe_project_dir(tmp_path)
    assert pathlib.Path(resolved) == tmp_path, (
        "expected _project_dir() to resolve to " + str(tmp_path)
        + " via CLAUDE_PROJECT_DIR fall-through; got " + repr(resolved)
    )


def test_shadow_dir_resolves_under_claude_project_dir(tmp_path):
    """maybe_record_shadow's shadow-dir default routes through _project_dir.
    When CLAUDE_PROJECT_DIR is the only env set, the shadow JSONL must
    land under that dir -- not under the __file__-relative fallback."""
    code = (
        "import sys;"
        "sys.path.insert(0, " + repr(str(_REPO_ROOT)) + ");"
        "from harness.hooks_equivalence import _resolve_shadow_dir;"
        "print(str(_resolve_shadow_dir(None)))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        env=_env_only_claude(tmp_path),
        cwd=str(_REPO_ROOT),
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    resolved = pathlib.Path(proc.stdout.strip())
    assert resolved.is_relative_to(tmp_path), (
        "shadow dir " + str(resolved)
        + " should live under CLAUDE_PROJECT_DIR=" + str(tmp_path)
    )


def test_signal_path_resolves_under_claude_project_dir(tmp_path):
    """fire_drain_rollback's default signal path routes through
    _resolve_signal_path -> _project_dir. Same fall-through invariant."""
    code = (
        "import sys;"
        "sys.path.insert(0, " + repr(str(_REPO_ROOT)) + ");"
        "from harness.hooks_equivalence import _resolve_signal_path;"
        "print(str(_resolve_signal_path(None)))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        env=_env_only_claude(tmp_path),
        cwd=str(_REPO_ROOT),
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    resolved = pathlib.Path(proc.stdout.strip())
    assert resolved.is_relative_to(tmp_path), (
        "signal path " + str(resolved)
        + " should live under CLAUDE_PROJECT_DIR=" + str(tmp_path)
    )
