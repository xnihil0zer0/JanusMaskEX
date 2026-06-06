"""RED oracle for NGv2 external-build BUG #2: smoke_import is hard-rooted at JM.

``smoke_import`` runs the candidate under a scrubbed PYTHONPATH = [tempdir,
``_discover_project_root()`` (always the JM repo), site-packages] and, on the
jailed path, ro-binds only sys.base_prefix/sys.prefix/site-packages. So a
candidate that does ``from ngv2.contracts import ...`` (an EXTERNAL dependency
living under the external working_dir) is unresolvable -> ``smoke_failed``. The
smoke gate fires for ``bypass_fuzzer`` meta-types (e.g. ``orchestration``), which
is exactly what an Epic-2 external child uses.

Fix: ``smoke_import(module_name, module_src, *, timeout=..., extra_paths=())``
appends ``extra_paths`` to BOTH the PYTHONPATH ``path_parts`` AND the jail
``extra_ro`` binds. When ``extra_paths`` is empty it falls back to the external
``JANUSMASK_WORKING_DIR`` (set on the worker by the daemon gap#3 fix; ignored for
a self build) so external children resolve their deps with no call-site change.
"""
import os

import pytest

from harness.sandbox_smoke import smoke_import


def _make_pkg(tmp_path):
    """A package dir ext/pkg/mod.py with a symbol X, returned as the path-root."""
    root = tmp_path / 'ext'
    pkg = root / 'pkg'
    pkg.mkdir(parents=True)
    (pkg / '__init__.py').write_text('', encoding='utf-8')
    (pkg / 'mod.py').write_text('X = 42\n', encoding='utf-8')
    return root


CANDIDATE = 'from pkg.mod import X\nassert X == 42\n'


def test_extra_paths_resolves_external_dep(tmp_path):
    root = _make_pkg(tmp_path)
    err = smoke_import('_cand_ep', CANDIDATE, extra_paths=[str(root)])
    assert err is None, f'expected clean import with extra_paths, got: {err}'


def test_without_extra_paths_external_dep_fails(tmp_path):
    root = _make_pkg(tmp_path)
    err = smoke_import('_cand_noep', CANDIDATE)
    assert err is not None, 'external dep must NOT resolve without extra_paths/env'


def test_working_dir_env_fallback_resolves(tmp_path, monkeypatch):
    """Worker path: no explicit extra_paths, but JANUSMASK_WORKING_DIR (external) is set."""
    root = _make_pkg(tmp_path)
    monkeypatch.setenv('JANUSMASK_WORKING_DIR', str(root))
    err = smoke_import('_cand_env', CANDIDATE)
    assert err is None, f'env-fallback should resolve external dep, got: {err}'


def test_self_build_env_ignored(tmp_path, monkeypatch):
    """A self build (JANUSMASK_WORKING_DIR unset/self) must not gain extra paths."""
    monkeypatch.delenv('JANUSMASK_WORKING_DIR', raising=False)
    root = _make_pkg(tmp_path)
    err = smoke_import('_cand_self', CANDIDATE)
    assert err is not None, 'self build must not silently resolve an external dep'
