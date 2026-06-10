"""RED oracle — authoritative contract for the ac-wire-determinism leaf
(harness/sandbox.py::sandbox_child_env + new helper).

Contract: a NEW module-level helper ``_maybe_determinism_env(env: dict) -> dict``
in ``harness/sandbox.py`` plus a single additive call inside
``sandbox_child_env`` (the returned env flows through the helper last).
Behavior:

- The helper resolves the flag AT CALL TIME via
  ``from autocompiler.flags import ac_enabled`` INSIDE its body (the
  ``_reap_spent_briefs_safe`` bridge precedent) so tests can monkeypatch
  ``autocompiler.flags.ac_enabled``.
- Flag OFF (the live default): the env is returned UNCHANGED — no
  ``sitecustomize.py`` is written, no PYTHONPATH entry added; the existing
  thread-guard/PYTHONPATH behavior of ``sandbox_child_env`` is byte-identical.
- Flag ON (``ac_enabled('determinism')``): the helper writes the
  ``autocompiler.determinism`` sitecustomize into a dedicated dir whose
  basename is ``janusmask_det_site`` and PREPENDS that dir to
  ``env['PYTHONPATH']`` (existing entries preserved as a suffix) — making two
  child interpreter runs byte-identical on entropy/clock probes.
- TOTAL: any internal error (flags import failure, raising ac_enabled, an
  unwritable dir) leaves the env unchanged — it can NEVER raise back into
  ``sandbox_child_env``.
"""
import inspect
import os
import subprocess
import sys

import pytest

import harness.sandbox as sandbox_mod
from harness.sandbox import sandbox_child_env

_SITE_BASENAME = 'janusmask_det_site'
_PROBE = ('import time, random, os\n'
          'print(time.time()); print(random.random()); print(os.urandom(4).hex())\n')


def test_helper_is_wired_into_sandbox_child_env():
    src = inspect.getsource(sandbox_child_env)
    assert '_maybe_determinism_env(' in src, \
        'sandbox_child_env must route its env through _maybe_determinism_env'
    assert hasattr(sandbox_mod, '_maybe_determinism_env')


def test_flag_off_env_unchanged(monkeypatch):
    # With determinism OFF there is no injection. The live config is now
    # default-ON, so force the flag OFF here to pin the OFF-path contract.
    import autocompiler.flags as flags_mod
    monkeypatch.setattr(flags_mod, 'ac_enabled', lambda key, *a, **k: False)
    env = sandbox_child_env({'PYTHONPATH': '/pre/existing'})
    assert _SITE_BASENAME not in (env.get('PYTHONPATH') or '')
    assert '/pre/existing' in env['PYTHONPATH']
    assert env['OPENBLAS_NUM_THREADS'] == '1'


def test_flag_on_prepends_site_dir_with_sitecustomize(monkeypatch):
    import autocompiler.flags as flags_mod
    monkeypatch.setattr(flags_mod, 'ac_enabled',
                        lambda key, *a, **k: key == 'determinism')
    env = sandbox_child_env({'PYTHONPATH': '/pre/existing'})
    parts = (env.get('PYTHONPATH') or '').split(os.pathsep)
    assert parts and os.path.basename(parts[0]) == _SITE_BASENAME
    site_file = os.path.join(parts[0], 'sitecustomize.py')
    assert os.path.isfile(site_file)
    from autocompiler.determinism import _SITECUSTOMIZE_CONTENT
    with open(site_file, 'r', encoding='utf-8') as fh:
        assert fh.read() == _SITECUSTOMIZE_CONTENT
    assert '/pre/existing' in parts  # edge case: existing entries preserved


def test_flag_on_makes_child_runs_deterministic(monkeypatch):
    import autocompiler.flags as flags_mod
    monkeypatch.setattr(flags_mod, 'ac_enabled',
                        lambda key, *a, **k: key == 'determinism')
    env = sandbox_child_env()
    env.pop('PYTHONHASHSEED', None)

    def run():
        proc = subprocess.run([sys.executable, '-c', _PROBE],
                              capture_output=True, text=True, timeout=60, env=env)
        assert proc.returncode == 0, proc.stderr
        return proc.stdout
    assert run() == run()


def test_raising_flag_reader_leaves_env_intact(monkeypatch):
    # Edge case: the bridge can never raise back into sandbox_child_env.
    import autocompiler.flags as flags_mod

    def _boom(*a, **k):
        raise RuntimeError('flag reader exploded')
    monkeypatch.setattr(flags_mod, 'ac_enabled', _boom)
    env = sandbox_child_env({'PYTHONPATH': '/pre/existing'})
    assert _SITE_BASENAME not in (env.get('PYTHONPATH') or '')
    assert env['MKL_NUM_THREADS'] == '1'
