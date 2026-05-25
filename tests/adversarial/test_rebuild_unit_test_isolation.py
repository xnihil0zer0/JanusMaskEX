"""Adversarial bar: a unit's reconstruction prompt must embed ONLY that unit's
own scoped tests, never a sibling/cross-module unit's oracle.

Regression guard for session #46: ``_read_unit_tests`` used to concatenate EVERY
file in ``descriptor.test_files`` into one ~51KB blob and embed it identically in
every unit's prompt -- led by an unrelated unit's oracle (e.g. a discover unit's
``module_import_graph`` test inside harvest's ``_is_impure`` prompt). Both blind
agents returned empty bodies on the oracle-skip frontier -> ``synthesis_or_ast_failed``,
blocking the whole discover/harvest oracle-skip cluster. The fix filters the
embedded tests per-unit using the SAME ``task._k_expr`` token the verification
gate uses, so prompt and gate can never drift.
"""

import types

from harness.rebuild import loop as _loop


TEST_SRC = '''import pytest
from harness.rebuild import harvest

CONST = 1


@pytest.fixture
def node():
    return harvest


def test_is_impure_basic(node):
    assert node._is_impure(node) is True


def test_is_impure_false(node):
    assert node._is_impure(node) is False


def test_class_is_stateful_basic():
    assert True


class TestModuleImportGraph:
    def test_resolves_relative(self):
        assert True
'''


def _unit(name, cls=None, whole_class=False):
    return types.SimpleNamespace(name=name, cls=cls, whole_class=whole_class)


def test_tokens_mirror_k_expr():
    # Free function: anchored function-form + CamelCase class-form, lowercased.
    assert _loop._unit_test_tokens(_unit('_is_impure')) == ['test_is_impure_', 'testisimpure']
    # Method unit: class-first single anchored token.
    assert _loop._unit_test_tokens(_unit('__post_init__', cls='TargetDescriptor')) == [
        'test_targetdescriptor_post_init_'
    ]


def test_filter_keeps_only_matching_unit_tests():
    out = _loop._filter_tests_for_unit(TEST_SRC, _loop._unit_test_tokens(_unit('_is_impure')))
    assert 'def test_is_impure_basic' in out
    assert 'def test_is_impure_false' in out
    # Sibling / cross-module units must NOT leak into this unit's prompt.
    assert 'class_is_stateful' not in out
    assert 'ModuleImportGraph' not in out
    # Module-level prologue (imports + fixtures) is preserved for context.
    assert 'import pytest' in out
    assert 'def node(' in out


def test_filter_returns_empty_for_unrelated_unit():
    assert _loop._filter_tests_for_unit(TEST_SRC, _loop._unit_test_tokens(_unit('nonexistent_fn'))) == ''


def test_read_unit_tests_isolates_per_unit(tmp_path):
    (tmp_path / 'test_gen.py').write_text(TEST_SRC, encoding='utf-8')
    desc = types.SimpleNamespace(
        test_files=['test_gen.py'], output_dir=tmp_path, source_root=tmp_path
    )
    scoped = _loop._read_unit_tests(desc, _unit('_is_impure'))
    assert 'is_impure' in scoped
    assert 'class_is_stateful' not in scoped
    assert 'ModuleImportGraph' not in scoped
    # Back-compat: no unit -> the full (unfiltered) text, for programmatic callers.
    full = _loop._read_unit_tests(desc)
    assert 'class_is_stateful' in full and 'ModuleImportGraph' in full
