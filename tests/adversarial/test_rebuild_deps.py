"""Contract for harness.rebuild.deps (C9.7 dep discovery + external-import detection).

This file is the dual-agent verification ORACLE for the dogfooded
``harness.rebuild.deps`` module: ``discover_dependencies`` (extract a project's
external/3rd-party deps + the manifests they came from) and ``external_units``
(which top-level functions reference a name imported from an external dep, so
the rebuild engine can route them to the oracle-skip + fuzzer-bypass path).
"""

from __future__ import annotations

import harness.rebuild.deps as deps


def test_public_surface():
    assert 'harness.rebuild.deps' == deps.__name__
    assert callable(deps.discover_dependencies)
    assert callable(deps.external_units)
    assert callable(deps.module_has_top_level_external_import)


def test_discover_requirements(tmp_path):
    (tmp_path / 'requirements.txt').write_text(
        'six>=1.16.0\n# a full-line comment\nrequests==2.0  # inline comment\n-e .\n\n',
        encoding='utf-8',
    )
    (tmp_path / 'mod.py').write_text('import os\n', encoding='utf-8')
    found, req_files = deps.discover_dependencies(tmp_path)
    names = {x.split(';')[0].split('>=')[0].split('==')[0].strip().lower() for x in found}
    assert 'six' in names
    assert 'requests' in names
    assert 'requirements.txt' in req_files
    # comment lines and editable/option lines are not dependencies
    assert not any(x.lstrip().startswith(('#', '-')) for x in found)


def test_discover_pyproject(tmp_path):
    (tmp_path / 'pyproject.toml').write_text(
        '[project]\nname = "demo"\nversion = "0.1"\n'
        'dependencies = ["toml>=0.10", "click"]\n',
        encoding='utf-8',
    )
    (tmp_path / 'mod.py').write_text('import sys\n', encoding='utf-8')
    found, _ = deps.discover_dependencies(tmp_path)
    joined = ' '.join(found)
    assert 'toml' in joined
    assert 'click' in joined


def test_discover_ast_fallback(tmp_path):
    (tmp_path / 'pkgmod.py').write_text(
        'import os\nimport zzz_external_pkg\nfrom another_ext import thing\n',
        encoding='utf-8',
    )
    found, req_files = deps.discover_dependencies(tmp_path)
    assert 'zzz_external_pkg' in found
    assert 'another_ext' in found
    assert 'os' not in found  # stdlib excluded
    assert req_files == []  # no manifest present


def test_discover_excludes_intra_project(tmp_path):
    # A module importing a sibling project module is NOT an external dependency.
    (tmp_path / 'alpha.py').write_text('import beta\nimport zzz_ext_two\n', encoding='utf-8')
    (tmp_path / 'beta.py').write_text('VALUE = 1\n', encoding='utf-8')
    found, _ = deps.discover_dependencies(tmp_path)
    assert 'beta' not in found
    assert 'zzz_ext_two' in found


def test_discover_precedence_requirements_over_ast(tmp_path):
    # An explicit manifest wins; the AST import fallback is not consulted.
    (tmp_path / 'requirements.txt').write_text('six\n', encoding='utf-8')
    (tmp_path / 'mod.py').write_text('import zzz_should_be_ignored\n', encoding='utf-8')
    found, _ = deps.discover_dependencies(tmp_path)
    assert any('six' in x for x in found)
    assert not any('zzz_should_be_ignored' in x for x in found)


def test_external_units_detects_attribute_use():
    src = (
        'import inflection\n\n'
        'def a(x):\n    return inflection.pluralize(x)\n\n'
        'def b(y):\n    return y + 1\n'
    )
    eu = deps.external_units(src, {'inflection'})
    assert 'a' in eu
    assert 'b' not in eu


def test_external_units_detects_from_import():
    src = (
        'from inflection import pluralize\n\n'
        'def a(x):\n    return pluralize(x)\n'
    )
    eu = deps.external_units(src, {'inflection'})
    assert 'a' in eu


def test_external_units_empty_without_external():
    src = 'import os\n\ndef a(x):\n    return os.getcwd()\n'
    assert deps.external_units(src, {'inflection'}) == set()


def test_external_units_empty_when_no_external_modules():
    src = 'import inflection\n\ndef a(x):\n    return inflection.pluralize(x)\n'
    assert deps.external_units(src, set()) == set()


# -- C9.8: function-LEVEL external import detection ---------------------------
# A module with NO top-level dep import but a function-local import only needs
# the dep for THAT unit; the rest can still use the merged==original oracle.


def test_external_units_detects_function_local_import():
    src = (
        'def a(x):\n'
        '    import inflection\n'
        '    return inflection.pluralize(x)\n\n'
        'def b(y):\n    return y + 1\n'
    )
    eu = deps.external_units(src, {'inflection'})
    assert 'a' in eu
    assert 'b' not in eu


def test_external_units_detects_function_local_from_import():
    src = (
        'def a(x):\n'
        '    from inflection import pluralize\n'
        '    return pluralize(x)\n'
    )
    assert 'a' in deps.external_units(src, {'inflection'})


def test_external_units_method_local_import():
    src = (
        'class C:\n'
        '    def m(self, x):\n'
        '        import inflection\n'
        '        return inflection.pluralize(x)\n'
        '    def n(self, x):\n'
        '        return x\n'
    )
    eu = deps.external_units(src, {'inflection'})
    assert 'm' in eu
    assert 'n' not in eu


def test_module_has_top_level_external_import():
    assert deps.module_has_top_level_external_import(
        'import inflection\n\ndef a():\n    return 1\n', {'inflection'}
    ) is True
    assert deps.module_has_top_level_external_import(
        'from inflection import pluralize\n\ndef a():\n    return pluralize(1)\n', {'inflection'}
    ) is True
    # function-local import is NOT a top-level import
    assert deps.module_has_top_level_external_import(
        'def a():\n    import inflection\n    return 1\n', {'inflection'}
    ) is False
    assert deps.module_has_top_level_external_import(
        'import os\n\ndef a():\n    return 1\n', {'inflection'}
    ) is False
    assert deps.module_has_top_level_external_import('def a():\n    return 1\n', set()) is False
