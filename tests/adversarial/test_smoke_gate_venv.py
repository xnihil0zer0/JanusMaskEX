"""Venv-awareness oracle for harness.sandbox_smoke.smoke_import (B1).

B1 TIGHTEN_SMOKE_GATE makes the import-smoke gate venv-aware: a submission
that imports a third-party package which is genuinely installed in the
project's environment is smoke-tested with that package on ``sys.path``,
rather than failing spuriously under a bare ``-S`` interpreter.

Crucially, the gate must stay FAIL-aware -- a genuine import-time crash
still smoke-FAILS (the gate is not fail-open / always-pass).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from harness.sandbox_smoke import smoke_import, _site_packages_dirs


def test_stdlib_import_smoke_passes():
    # (i) A module importing only stdlib packages smoke-passes.
    src = "import json\nimport collections\n\nDATA = collections.OrderedDict()\n"
    assert smoke_import("venv_stdlib_ok", src) is None


def test_missing_package_still_smoke_fails():
    # (ii-a) A genuine missing import still fails -- gate is not fail-open.
    src = "import nonexistent_pkg_xyz_b1\n"
    err = smoke_import("venv_missing_pkg", src)
    assert err is not None
    assert "sandbox import failed" in err


def test_module_level_nameerror_still_smoke_fails():
    # (ii-b) A module-level NameError still fails -- gate is not fail-open.
    src = "VALUE = THIS_NAME_IS_NOT_DEFINED\n"
    err = smoke_import("venv_nameerror", src)
    assert err is not None
    assert "sandbox import failed" in err


def test_installed_third_party_package_smoke_passes_via_venv():
    # (iii) A package present in the project's site-packages that would fail
    # under a bare -S interpreter now smoke-passes thanks to venv-awareness.
    # pytest is necessarily installed (it is running this test) and is a
    # third-party (non-stdlib) package, so it exercises the venv path.
    src = "import pytest\n\ndef f():\n    return pytest.__name__\n"
    assert smoke_import("venv_pytest_ok", src) is None


def test_site_packages_dirs_discovers_existing_dirs():
    # The helper must surface only real, existing directories (or none),
    # never crash, so the gate degrades gracefully rather than erroring.
    dirs = _site_packages_dirs()
    assert isinstance(dirs, list)
    for d in dirs:
        assert isinstance(d, str)
        assert Path(d).is_dir()
    # In the test environment pytest is importable, so at least one
    # site-packages directory must have been discovered.
    assert dirs, "expected at least one site-packages dir in this env"
