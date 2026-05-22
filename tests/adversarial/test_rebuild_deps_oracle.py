"""Operator-authored per-unit oracle for harness/rebuild/deps.py public units,
named ``test_<unit>_<behaviour>`` so the rebuild engine's ``pytest -k <unit>``
selects exactly one unit's tests (the shipped tests/test_deps.py names tests by
behaviour, which per-unit -k scoping can't isolate -> whole-file fallback ->
cascade across the multi-unit module).

Used as the verification oracle for the JanusMask->JR deps.py leaf rebuild (P2).
deps.py is pure stdlib; the tmp_path fixtures carry no JanusMask state, so this
runs identically in JR. Import is package-qualified (mirrors
tests/adversarial/test_rebuild_brief_status_oracle.py) -- it resolves against the
output repo's reconstructed harness.rebuild.deps."""

from harness.rebuild.deps import (
    discover_dependencies,
    external_units,
    module_has_top_level_external_import,
)


# ----- discover_dependencies -----
def test_discover_dependencies_requirements_wins_and_dedups(tmp_path):
    (tmp_path / "requirements.txt").write_text(
        "# a comment\nrequests==2.0  # inline\nRequests>=1.0\nflask\n",
        encoding="utf-8",
    )
    deps, files = discover_dependencies(tmp_path)
    # PEP 503 dedup keeps first-seen line; Requests collapses to requests.
    assert deps == ["requests==2.0", "flask"]
    assert files == ["requirements.txt"]


def test_discover_dependencies_follows_r_include(tmp_path):
    (tmp_path / "requirements.txt").write_text("-r base.txt\nflask\n", encoding="utf-8")
    (tmp_path / "base.txt").write_text("requests\n", encoding="utf-8")
    deps, files = discover_dependencies(tmp_path)
    assert "requests" in deps and "flask" in deps
    assert "requirements.txt" in files and "base.txt" in files


def test_discover_dependencies_falls_back_to_pyproject(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["requests>=2", "click"]\n', encoding="utf-8"
    )
    deps, files = discover_dependencies(tmp_path)
    assert deps == ["requests>=2", "click"]
    assert files == []  # no requirements manifest present


def test_discover_dependencies_ast_scan_when_no_manifest(tmp_path):
    (tmp_path / "mod.py").write_text("import requests\nimport os\n", encoding="utf-8")
    deps, files = discover_dependencies(tmp_path)
    assert "requests" in deps
    assert "os" not in deps  # stdlib excluded
    assert files == []


def test_discover_dependencies_empty_project(tmp_path):
    deps, files = discover_dependencies(tmp_path)
    assert deps == []
    assert files == []


# ----- external_units -----
def test_external_units_module_top_level_import(tmp_path):
    src = (
        "import inflection\n"
        "def uses(): return inflection.pluralize('x')\n"
        "def clean(): return 1\n"
    )
    assert external_units(src, {"inflection"}) == {"uses"}


def test_external_units_from_import_and_asname(tmp_path):
    src = (
        "from inflection import pluralize as p\n"
        "def a(): return p('x')\n"
        "def b(): return 2\n"
    )
    assert external_units(src, {"inflection"}) == {"a"}


def test_external_units_function_local_import(tmp_path):
    src = (
        "def a():\n    import inflection\n    return inflection.pluralize('x')\n"
        "def b(): return 3\n"
    )
    assert external_units(src, {"inflection"}) == {"a"}


def test_external_units_class_method(tmp_path):
    src = (
        "import inflection\n"
        "class C:\n"
        "    def m(self): return inflection.pluralize('x')\n"
        "    def n(self): return 4\n"
    )
    assert external_units(src, {"inflection"}) == {"m"}


def test_external_units_empty_when_no_externals(tmp_path):
    src = "import inflection\ndef a(): return inflection.x\n"
    assert external_units(src, set()) == set()
    assert external_units("def a(): pass", {"inflection"}) == set()


def test_external_units_unparseable_source_returns_empty(tmp_path):
    assert external_units("def (:::", {"inflection"}) == set()


# ----- module_has_top_level_external_import -----
def test_module_has_top_level_external_import_true_for_top_level(tmp_path):
    assert module_has_top_level_external_import("import inflection\n", {"inflection"}) is True
    assert module_has_top_level_external_import(
        "from inflection import pluralize\n", {"inflection"}
    ) is True


def test_module_has_top_level_external_import_false_for_function_local(tmp_path):
    src = "def f():\n    import inflection\n    return 1\n"
    assert module_has_top_level_external_import(src, {"inflection"}) is False


def test_module_has_top_level_external_import_false_when_no_externals(tmp_path):
    assert module_has_top_level_external_import("import inflection\n", set()) is False
    assert module_has_top_level_external_import("import os\n", {"inflection"}) is False


def test_module_has_top_level_external_import_unparseable_returns_false(tmp_path):
    assert module_has_top_level_external_import("def (:::", {"inflection"}) is False


# === P1/C9.17: per-unit-named oracles for the oracle-SKIP private units (so
# `pytest -k <unit>` scopes; the merged==original fuzz oracle is vacuous for these
# Path/AST-node-param impure helpers). Required to LAND deps.py clean-room into JR.
import ast

from harness.rebuild.deps import (
    _from_requirements,
    _from_pyproject,
    _from_setup_cfg,
    _from_setup_py,
    _project_py_files,
    _intra_project_names,
    _from_ast,
    _references,
)


def test_from_requirements_parses_dedups_and_follows_includes(tmp_path):
    (tmp_path / "requirements.txt").write_text(
        "-r base.txt\n# comment\nflask  # inline\n\n", encoding="utf-8"
    )
    (tmp_path / "base.txt").write_text("requests==2.0\n", encoding="utf-8")
    deps, files = _from_requirements(tmp_path)
    assert "requests==2.0" in deps and "flask" in deps
    assert "requirements.txt" in files and "base.txt" in files


def test_from_requirements_empty_returns_empty(tmp_path):
    deps, files = _from_requirements(tmp_path)
    assert deps == [] and files == []


def test_from_pyproject_reads_project_and_poetry_deps(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["requests>=2"]\n'
        '[tool.poetry.dependencies]\npython = "^3.11"\nclick = "*"\n',
        encoding="utf-8",
    )
    deps = _from_pyproject(tmp_path)
    assert "requests>=2" in deps
    assert "click" in deps
    assert "python" not in deps


def test_from_pyproject_missing_file_returns_empty(tmp_path):
    assert _from_pyproject(tmp_path) == []


def test_from_setup_cfg_reads_install_requires(tmp_path):
    (tmp_path / "setup.cfg").write_text(
        "[options]\ninstall_requires =\n    requests\n    flask\n", encoding="utf-8"
    )
    deps = _from_setup_cfg(tmp_path)
    assert "requests" in deps and "flask" in deps


def test_from_setup_cfg_missing_option_returns_empty(tmp_path):
    (tmp_path / "setup.cfg").write_text("[metadata]\nname = x\n", encoding="utf-8")
    assert _from_setup_cfg(tmp_path) == []


def test_from_setup_py_extracts_literal_install_requires(tmp_path):
    (tmp_path / "setup.py").write_text(
        "from setuptools import setup\n"
        "setup(name='x', install_requires=['requests', 'flask'])\n",
        encoding="utf-8",
    )
    assert _from_setup_py(tmp_path) == ["requests", "flask"]


def test_from_setup_py_missing_returns_empty(tmp_path):
    assert _from_setup_py(tmp_path) == []


def test_project_py_files_skips_vendor_and_hidden_dirs(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "top.py").write_text("y = 2\n", encoding="utf-8")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "junk.py").write_text("z = 3\n", encoding="utf-8")
    out = {p.as_posix() for p in _project_py_files(tmp_path)}
    assert any(o.endswith("top.py") for o in out)
    assert any(o.endswith("pkg/mod.py") for o in out)
    assert not any(".venv" in o for o in out)


def test_intra_project_names_includes_root_and_top_packages(tmp_path):
    from pathlib import Path as _P
    names = _intra_project_names(tmp_path, [_P("top.py"), _P("pkg/mod.py")])
    assert "top" in names
    assert "pkg" in names


def test_from_ast_finds_external_excludes_stdlib_and_intra(tmp_path):
    (tmp_path / "a.py").write_text("import requests\nimport os\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("import a\n", encoding="utf-8")
    deps = _from_ast(tmp_path)
    assert "requests" in deps
    assert "os" not in deps
    assert "a" not in deps


def test_references_detects_name_in_subtree(tmp_path):
    node = ast.parse("def f():\n    return pkg.thing()\n").body[0]
    assert _references(node, {"pkg"}) is True
    assert _references(node, {"other"}) is False
