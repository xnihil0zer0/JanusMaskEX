"""RED oracle for gap#2b — diff-fuzzer cannot resolve EXTERNAL imports.

Non-``bypass_fuzzer`` meta-types (``io_adapter``, ``algorithm``, ...) run the
differential fuzzer, which executes the candidate in a plain subprocess whose
environment comes from ``harness.sandbox.sandbox_child_env``. That env is just
``os.environ.copy()`` (+ thread guards), so its ``PYTHONPATH`` is the JM root
only. An external leaf doing ``from ngv2.contracts import Finding`` is therefore
unimportable in the fuzz subprocess and fails the gate.

Fix (mirror of the smoke-gate BUG#2 fix in sandbox_smoke.py): when
``JANUSMASK_WORKING_DIR`` points at a non-self external root, prepend it to the
returned env's ``PYTHONPATH`` so the fuzz subprocess can import ``ngv2.*``.
Self builds (env unset or pointing at the repo itself) must be byte-identical.
"""
import os
import pathlib
import tempfile
import unittest
from unittest.mock import patch

from harness.sandbox import sandbox_child_env


class TestSandboxChildEnvExternal(unittest.TestCase):
    def setUp(self):
        self.patcher = patch('autocompiler.flags.ac_enabled', return_value=False)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    def test_external_working_dir_on_pythonpath(self):
        with tempfile.TemporaryDirectory() as ext:
            ext = str(pathlib.Path(ext).resolve())
            with patch.dict(os.environ, {'JANUSMASK_WORKING_DIR': ext}, clear=False):
                env = sandbox_child_env()
            parts = env.get('PYTHONPATH', '').split(os.pathsep)
            self.assertIn(ext, parts,
                          'external working_dir must be prepended to PYTHONPATH so '
                          'the fuzz subprocess can import external packages')

    def test_self_build_pythonpath_unchanged(self):
        env_no_wd = {k: v for k, v in os.environ.items() if k != 'JANUSMASK_WORKING_DIR'}
        with patch.dict(os.environ, env_no_wd, clear=True):
            baseline = os.environ.get('PYTHONPATH')
            env = sandbox_child_env()
            self.assertEqual(env.get('PYTHONPATH'), baseline,
                             'a self build (no JANUSMASK_WORKING_DIR) must not gain a PYTHONPATH entry')

    def test_self_working_dir_not_injected(self):
        from harness.paths import PROJECT_ROOT
        with patch.dict(os.environ, {'JANUSMASK_WORKING_DIR': str(PROJECT_ROOT)}, clear=False):
            baseline = os.environ.get('PYTHONPATH', '')
            env = sandbox_child_env()
            self.assertEqual(env.get('PYTHONPATH', ''), baseline,
                             'a self-pointing working_dir must not alter PYTHONPATH')


if __name__ == '__main__':
    unittest.main()
