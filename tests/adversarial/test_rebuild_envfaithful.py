"""C9.7 wiring: descriptor deps, needs_deps routing, venv-scoped vcmd, init provisioning.

These exercise the DIRECT-edit glue that connects the dogfooded
``harness.rebuild.deps`` + ``harness.rebuild.venv`` modules into the engine:
discovery -> descriptor fields, harvest needs_deps detection, the per-unit
verification command targeting the replicant venv + oracle-skip for dep units,
and ``init_output_repo`` materializing requirements.txt + provisioning .venv.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.rebuild import discover, harvest, loop, task, venv
from harness.rebuild.target import TargetDescriptor

SAMPLE = Path(__file__).resolve().parents[2] / 'samples' / 'dep_sample'


def _descriptor(tmp_path, **over):
    return discover.build_descriptor(
        SAMPLE,
        output_dir=tmp_path / 'out',
        stash_dir=tmp_path / 'stash',
        **over,
    )


def test_descriptor_carries_dependencies(tmp_path):
    d = _descriptor(tmp_path)
    assert d.dependencies == ['inflection']
    assert d.requirements_files == ['requirements.txt']
    assert d.python_exe is None  # not provisioned yet


def test_dep_import_names():
    assert loop._dep_import_names(['inflection']) == {'inflection'}
    assert loop._dep_import_names(['six>=1.16', 'requests[security]==2']) == {'six', 'requests'}
    assert loop._dep_import_names(['typing-extensions']) == {'typing_extensions'}


def test_harvest_flags_needs_deps_for_dep_module():
    src = (SAMPLE / 'textcase.py').read_text(encoding='utf-8')
    units = harvest.harvest_module('textcase.py', src, external_modules={'inflection'})
    assert units
    assert all(u.needs_deps for u in units)  # whole dep-importing module oracle-skips
    # Without the external set, no unit is flagged.
    units_plain = harvest.harvest_module('textcase.py', src)
    assert not any(u.needs_deps for u in units_plain)


def test_dep_unit_vcmd_is_oracle_skip_and_venv_scoped(tmp_path):
    d = _descriptor(tmp_path)
    d.python_exe = '/fake/out/.venv/bin/python'
    src = (SAMPLE / 'textcase.py').read_text(encoding='utf-8')
    units = harvest.harvest_module('textcase.py', src, external_modules={'inflection'})
    unit = next(u for u in units if u.name == 'pluralize_word')
    spec = task.build_unit_task(
        descriptor=d, unit=unit, module_rel='textcase.py',
        oracle_original_path='/tmp/textcase.py.orig', sibling_signatures=[],
        unit_test_text='', parent_root='/parent',
    )
    vcmd = spec['verification_command']
    assert 'oracle.py' not in vcmd  # oracle-skipped
    assert '/fake/out/.venv/bin/python -m pytest' in vcmd  # venv-scoped
    assert spec.get('meta_task_type') == 'harness_plumbing'


def test_pure_unit_keeps_oracle_and_ambient_python(tmp_path):
    # A no-dep module: units keep the merged==original oracle and ambient python.
    d = TargetDescriptor(
        name='puremod', source_root=tmp_path, modules=['puremod.py'],
        test_files=['test_puremod.py'], output_dir=tmp_path / 'out',
        stash_dir=tmp_path / 'stash', unit_test_selector='test_puremod.py -k {unit}',
    )
    # TYPED signature: a pure, fully-annotated unit keeps the merged==original
    # fuzz oracle (an UN-typed signature would route to tests-only -- C9.9 P1).
    src = 'def add(a: int, b: int) -> int:\n    """Sum."""\n    return a + b\n'
    units = harvest.harvest_module('puremod.py', src, external_modules=set())
    unit = units[0]
    assert unit.needs_deps is False and unit.untyped is False
    spec = task.build_unit_task(
        descriptor=d, unit=unit, module_rel='puremod.py',
        oracle_original_path='/tmp/puremod.py.orig', sibling_signatures=[],
        unit_test_text='', parent_root='/parent',
    )
    vcmd = spec['verification_command']
    assert 'oracle.py' in vcmd and ' && ' in vcmd  # full oracle gate
    assert 'python -m pytest' in vcmd
    assert '.venv' not in vcmd  # ambient python (no venv provisioned)
    assert spec.get('meta_task_type') is None


def test_init_output_repo_writes_requirements_and_gitignores_venv(tmp_path):
    d = _descriptor(tmp_path)
    loop.init_output_repo(d)
    out = d.output_dir
    req = (out / 'requirements.txt').read_text(encoding='utf-8')
    assert 'inflection' in req
    assert 'pytest' in req  # standalone-runnable: replicant carries its test runner
    assert '.venv/' in (out / '.gitignore').read_text(encoding='utf-8')


@pytest.mark.timeout(240)
def test_init_output_repo_provisions_venv(tmp_path):
    d = _descriptor(tmp_path)
    try:
        loop.init_output_repo(d)
    except Exception as exc:  # pragma: no cover - offline CI
        pytest.skip(f'venv/pip unavailable: {exc}')
    out = d.output_dir
    if not venv.venv_ready(out):  # pragma: no cover - offline CI
        pytest.skip('venv not provisioned (offline)')
    assert d.python_exe == str(venv.venv_python(out))
    # The replicant's venv has the external dep installed.
    import subprocess
    chk = subprocess.run(
        [str(venv.venv_python(out)), '-c', 'import inflection; print(inflection.pluralize("post"))'],
        capture_output=True, text=True,
    )
    assert chk.returncode == 0 and chk.stdout.strip() == 'posts'
