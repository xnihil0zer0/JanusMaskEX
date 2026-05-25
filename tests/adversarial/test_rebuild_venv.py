"""Contract for harness.rebuild.venv (C9.7 environment-faithful provisioning).

The dual-agent verification ORACLE for the dogfooded ``harness.rebuild.venv``
module: a replicant provisions its OWN ``<out>/.venv`` and installs its external
deps so a clone runs standalone. All paths derive from ``output_dir`` (NEVER
``Path.home()`` -- the replicant must be $HOME-free, see
tests/adversarial/test_replication_clean_room_static.py::TestHarnessHomeFree).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import harness.rebuild.venv as venv


def test_public_surface():
    assert 'harness.rebuild.venv' == venv.__name__
    for fn in ('provision_venv', 'venv_python', 'venv_ready', 'venv_dir'):
        assert callable(getattr(venv, fn))


def test_venv_python_is_posix_layout(tmp_path):
    p = venv.venv_python(tmp_path)
    assert p.name == 'python'
    assert p.parent.name == 'bin'
    assert p.parent.parent.name == '.venv'
    assert p.parent.parent.parent == Path(tmp_path).resolve()


def test_venv_dir_under_output(tmp_path):
    assert venv.venv_dir(tmp_path) == Path(tmp_path).resolve() / '.venv'


def test_venv_ready_false_before_provision(tmp_path):
    assert venv.venv_ready(tmp_path) is False


def test_no_path_home_in_source():
    src = Path(venv.__file__).read_text(encoding='utf-8')
    for bad in ('Path.home', 'expanduser', '$HOME', "environ['HOME']", 'environ.get("HOME"'):
        assert bad not in src


@pytest.mark.timeout(120)
def test_provision_creates_and_is_idempotent(tmp_path):
    vpy = venv.provision_venv(tmp_path)  # no deps -> create the venv only
    vpy = Path(vpy)
    assert vpy.exists()
    assert venv.venv_ready(tmp_path) is True
    # The provisioned interpreter actually runs.
    out = subprocess.run([str(vpy), '-c', 'print(40 + 2)'], capture_output=True, text=True)
    assert out.returncode == 0
    assert out.stdout.strip() == '42'
    # Idempotent: a second call returns the same interpreter and does not raise.
    vpy2 = Path(venv.provision_venv(tmp_path))
    assert vpy2 == vpy
    assert venv.venv_ready(tmp_path) is True


@pytest.mark.timeout(180)
def test_provision_installs_dependency(tmp_path):
    # Network-guarded: install a tiny pure-python dep into the replicant venv.
    try:
        vpy = Path(venv.provision_venv(tmp_path, deps=['inflection']))
    except Exception as exc:  # pragma: no cover - offline CI
        pytest.skip(f'venv/pip unavailable: {exc}')
    chk = subprocess.run(
        [str(vpy), '-c', 'import inflection; print(inflection.pluralize("post"))'],
        capture_output=True, text=True,
    )
    if chk.returncode != 0:  # pragma: no cover - offline CI
        pytest.skip(f'pip install offline/failed: {chk.stderr[-200:]}')
    assert chk.stdout.strip() == 'posts'


@pytest.mark.timeout(180)
def test_provision_installs_from_requirements_file(tmp_path):
    (tmp_path / 'requirements.txt').write_text('inflection\n', encoding='utf-8')
    try:
        vpy = Path(venv.provision_venv(tmp_path, requirements_files=['requirements.txt']))
    except Exception as exc:  # pragma: no cover - offline CI
        pytest.skip(f'venv/pip unavailable: {exc}')
    chk = subprocess.run(
        [str(vpy), '-c', 'import inflection; print(inflection.underscore("DeviceType"))'],
        capture_output=True, text=True,
    )
    if chk.returncode != 0:  # pragma: no cover - offline CI
        pytest.skip(f'pip install offline/failed: {chk.stderr[-200:]}')
    assert chk.stdout.strip() == 'device_type'
