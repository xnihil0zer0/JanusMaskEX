"""RED oracle (NGv2 Epic-1 auto-decompose, gap #4 / working_dir propagation 3/3):
the planner must root the normalizer's existing-test glob at the plan's EXTERNAL
working_dir, not JM's cwd, so an external child plan's impl verification_command
maps to the external repo's own oracle (not a JM-rooted smoke import).

cli.main calls normalize_plan(final_plan, repo_root=Path.cwd()) (cli.py:296),
which for an external child plan globs JM's tests/** (miss) -> the child's vcmd
is mangled. The fix introduces a small top-level helper cli._effective_repo_root
that returns the brief's external working_dir as the glob root (and Path.cwd()
for self/empty/missing), wired into that call.

RED on HEAD: cli._effective_repo_root does not exist (AttributeError).

GREEN after the fix: the helper classifies external vs self correctly. Hermetic:
external paths live under tmp_path (outside the JM repo); self == Path.cwd().
"""
from __future__ import annotations

import types
from pathlib import Path

from harness.planner import cli


def _obj(working_dir):
    return types.SimpleNamespace(working_dir=working_dir)


def test_external_working_dir_used_as_root(tmp_path) -> None:
    ext = str(tmp_path / "ext_target")
    assert cli._effective_repo_root(_obj(ext)) == Path(ext)


def test_none_working_dir_falls_back_to_cwd() -> None:
    assert cli._effective_repo_root(_obj(None)) == Path.cwd()


def test_empty_working_dir_falls_back_to_cwd() -> None:
    assert cli._effective_repo_root(_obj("")) == Path.cwd()


def test_self_working_dir_falls_back_to_cwd() -> None:
    # working_dir pointing at the JM repo itself (self) keeps the cwd root.
    assert cli._effective_repo_root(_obj(str(Path.cwd()))) == Path.cwd()


def test_missing_attr_falls_back_to_cwd() -> None:
    assert cli._effective_repo_root(types.SimpleNamespace()) == Path.cwd()
