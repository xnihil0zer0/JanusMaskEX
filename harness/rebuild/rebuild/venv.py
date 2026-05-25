"""VENV: provision a replicant's OWN ``.venv`` + install its external deps.

Part of the clean-room rebuild engine. A reconstructed replicant must run
standalone like the original, which means it needs its own virtual environment
with the project's 3rd-party dependencies installed (those deps are discovered
by :mod:`harness.rebuild.deps` and used for verification only, never agent
synthesis). This module owns the provisioning side of that contract.

Every path derives from ``output_dir`` -- the replicant must be home-free, so
nothing here consults ``Path`` user-dir helpers, the ``HOME`` variable, or
shell user-expansion (see
tests/adversarial/test_replication_clean_room_static.py::TestHarnessHomeFree).
POSIX interpreter layout only (``<out>/.venv/bin/python``).

Pure stdlib (``subprocess`` / ``sys`` / ``pathlib``).
"""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path
_SENTINEL = '.jm_provisioned'

def venv_dir(output_dir) -> Path:
    """The replicant's ``.venv`` directory: ``Path(output_dir).resolve()/'.venv'``."""
    return Path(output_dir).resolve() / '.venv'

def venv_python(output_dir) -> Path:
    """The venv's POSIX interpreter: ``<out>/.venv/bin/python``."""
    return venv_dir(output_dir) / 'bin' / 'python'

def venv_ready(output_dir) -> bool:
    """True iff the provisioned interpreter exists under ``output_dir``."""
    return venv_python(output_dir).exists()

def _pip_args(output_dir, requirements_files, deps) -> list[str]:
    """Build the pip-install argument list for ``provision_venv``.

    Each ``requirements_files`` entry is resolved relative to ``output_dir``
    (kept as-is when already absolute) and contributes ``-r <abs>`` only when
    the file actually exists. Each ``deps`` entry is appended as a bare package
    argument.
    """
    out = Path(output_dir).resolve()
    args: list[str] = []
    for entry in requirements_files or []:
        req = Path(entry)
        if not req.is_absolute():
            req = out / entry
        if req.exists():
            args.extend(['-r', str(req)])
    for dep in deps or []:
        args.append(str(dep))
    return args

def provision_venv(output_dir, requirements_files=None, deps=None, *, base_python=None) -> Path:
    """Provision ``<out>/.venv`` and install the replicant's external deps.

    Idempotent and resumable. The venv is created via
    ``[base_python or sys.executable, '-m', 'venv', <venv_dir>]`` only when its
    interpreter is absent. Dependencies are then installed with the venv's own
    pip, but only when there is something to install AND the
    ``.jm_provisioned`` sentinel is not yet present; the sentinel is written
    after a successful install so a later call is a fast no-op. Returns
    :func:`venv_python` for ``output_dir``.
    """
    vdir = venv_dir(output_dir)
    vpy = venv_python(output_dir)
    if not vpy.exists():
        subprocess.run([base_python or sys.executable, '-m', 'venv', str(vdir)], check=True, capture_output=True, text=True)
    args = _pip_args(output_dir, requirements_files, deps)
    sentinel = vdir / _SENTINEL
    if args and (not sentinel.exists()):
        subprocess.run([str(vpy), '-m', 'pip', 'install', '--disable-pip-version-check', '-q', *args], check=True)
        sentinel.write_text('', encoding='utf-8')
    return vpy