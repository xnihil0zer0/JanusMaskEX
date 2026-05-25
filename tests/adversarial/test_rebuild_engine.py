"""Engine unit tests for the clean-room AST-rebuild engine (criterion 9, C9.1-C9.3).

These cover the deterministic, dispatch-free parts of the engine:
harvest (AST -> units + dep order), strip (skeletonize + stash), and the
oracle gate (merged==original via diff_fuzzer). The live single-unit
reconstruction (C9.3 keystone) is exercised out-of-band by
scripts/rebuild-replicant.sh because it spawns the dual agents.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import harness.rebuild.harvest as _harvest
import harness.rebuild.strip as _strip
import harness.rebuild.oracle as _oracle
import harness.rebuild.task as _task
import harness.rebuild.loop as _loop
from harness.rebuild.target import (
    TargetDescriptor,
    mathlib_descriptor,
    janusmask_module_descriptor,
)

_REPO = Path(__file__).resolve().parent.parent.parent
_MATHLIB = (_REPO / 'samples' / 'mathlib' / 'mathlib.py').read_text(encoding='utf-8')
_MATHLIB_REL = 'mathlib.py'


def test_public_entry_points_present():
    """The engine's public surface (CLI entry points + dataclasses) exists."""
    assert isinstance(_harvest.Unit, type)
    assert callable(_harvest.harvest_module)
    assert callable(_harvest.order_units)
    assert callable(_strip.strip_source)
    assert callable(_strip.materialize_skeleton)
    assert callable(_oracle.check_equivalence)
    assert callable(_oracle.main)
    assert callable(_task.build_unit_task)
    assert callable(_loop.init_output_repo)
    assert callable(_loop.reconstruct_unit)
    assert callable(_loop.reconstruct_all)
    assert callable(_loop.has_notimplemented)
    assert callable(_loop.main)


def _config():
    from harness.orchestrator import load_config
    return load_config(_REPO / 'harness' / 'config.yaml')


# ----- harvest (C9.2) -----

def test_harvest_finds_all_units():
    units = _harvest.harvest_module(_MATHLIB_REL, _MATHLIB)
    names = {u.name for u in units}
    assert names == {'gcd', 'is_prime', 'fib'}


def test_harvest_unit_metadata():
    units = {u.name: u for u in _harvest.harvest_module(_MATHLIB_REL, _MATHLIB)}
    gcd = units['gcd']
    assert gcd.module == _MATHLIB_REL
    assert gcd.qualname == 'mathlib.py:gcd'
    assert gcd.signature.startswith('def gcd(a: int, b: int)')
    assert '-> int' in gcd.signature
    assert gcd.docstring and 'greatest common divisor' in gcd.docstring


def test_order_units_is_deterministic_and_total():
    units = _harvest.harvest_module(_MATHLIB_REL, _MATHLIB)
    ordered = _harvest.order_units(units)
    assert {u.name for u in ordered} == {u.name for u in units}
    assert ordered == _harvest.order_units(units)


# ----- strip (C9.2) -----

def test_strip_replaces_bodies_with_notimplemented():
    skel = _strip.strip_source(_MATHLIB)
    tree = ast.parse(skel)
    fns = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    assert {f.name for f in fns} == {'gcd', 'is_prime', 'fib'}
    for f in fns:
        # body is (optional docstring Expr) + a single `raise NotImplementedError`
        raises = [s for s in f.body if isinstance(s, ast.Raise)]
        assert len(raises) == 1
        assert isinstance(raises[0].exc, ast.Name)
        assert raises[0].exc.id == 'NotImplementedError'


def test_strip_retains_signatures_and_docstrings():
    skel = _strip.strip_source(_MATHLIB)
    tree = ast.parse(skel)
    fns = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert fns['gcd'].returns is not None  # type hint retained
    assert ast.get_docstring(fns['gcd'])  # docstring retained


def test_strip_skeleton_is_importable_but_raises_when_called(tmp_path):
    skel = _strip.strip_source(_MATHLIB)
    mod_file = tmp_path / 'skel_mathlib.py'
    mod_file.write_text(skel, encoding='utf-8')
    ns: dict = {}
    exec(compile(skel, str(mod_file), 'exec'), ns)  # import-equivalent: defines fine
    with pytest.raises(NotImplementedError):
        ns['gcd'](12, 8)


def test_materialize_skeleton_round_trip(tmp_path):
    out = tmp_path / 'out'
    stash = tmp_path / 'stash'
    desc = mathlib_descriptor(out, stash, _REPO / 'samples' / 'mathlib')
    info = _strip.materialize_skeleton(desc)
    assert (out / 'mathlib.py').exists()
    assert (out / 'test_mathlib.py').exists()
    # stash holds the verbatim original OUTSIDE the output repo
    stash_file = Path(info['stash'][_MATHLIB_REL])
    assert stash_file.read_text(encoding='utf-8') == _MATHLIB
    assert str(out) not in str(stash_file)


# ----- oracle (C9.3 gate) -----

def test_oracle_original_equals_original():
    ok, msg = _oracle.check_equivalence(_MATHLIB, _MATHLIB, 'gcd', _config())
    assert ok, msg


def test_oracle_detects_wrong_body():
    wrong = _MATHLIB.replace('return a\n', 'return a + 1\n', 1)
    assert wrong != _MATHLIB
    ok, _msg = _oracle.check_equivalence(wrong, _MATHLIB, 'gcd', _config())
    assert not ok


# ----- task spec (C9.3 plumbing) -----

def test_build_unit_task_shape(tmp_path):
    out = tmp_path / 'out'
    stash = tmp_path / 'stash'
    desc = mathlib_descriptor(out, stash, _REPO / 'samples' / 'mathlib')
    units = {u.name: u for u in _harvest.harvest_module(_MATHLIB_REL, _MATHLIB)}
    spec = _task.build_unit_task(
        descriptor=desc,
        unit=units['gcd'],
        module_rel=_MATHLIB_REL,
        oracle_original_path='/abs/stash/mathlib.py.orig',
        sibling_signatures=[],
        unit_test_text='assert gcd(12, 8) == 4',
        parent_root=str(_REPO),
    )
    assert spec['task_id'] == 'RB_mathlib_gcd'
    assert spec['files_touched'] == ['mathlib.py']
    assert spec['constraints']['function_signature'].startswith('def gcd(')
    vcmd = spec['verification_command']
    assert 'harness/rebuild/oracle.py' in vcmd
    assert 'pytest' in vcmd
    assert '/abs/stash/mathlib.py.orig' in vcmd


def test_has_notimplemented_helper(tmp_path):
    skel = _strip.strip_source(_MATHLIB)
    f = tmp_path / 'm.py'
    f.write_text(skel, encoding='utf-8')
    assert _loop.has_notimplemented(f, 'gcd') is True
    # a reconstructed body no longer trips the guard
    f.write_text(_MATHLIB, encoding='utf-8')
    assert _loop.has_notimplemented(f, 'gcd') is False


def test_janusmask_module_descriptor_smoke(tmp_path):
    desc = janusmask_module_descriptor(
        name='safe_subpath',
        modules=['harness/safe_subpath.py'],
        test_files=['tests/test_safe_subpath.py'],
        output_dir=tmp_path / 'jr',
        stash_dir=tmp_path / 'stash',
        source_root=_REPO,
        seed_files=['harness/__init__.py'],
    )
    assert desc.name == 'safe_subpath'
    assert 'tests/test_safe_subpath.py' in desc.full_test_command
