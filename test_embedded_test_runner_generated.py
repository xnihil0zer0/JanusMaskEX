from __future__ import annotations
# ----- should_run_embedded_tests -----
from harness.embedded_test_runner import should_run_embedded_tests


def test_should_run_embedded_tests_returns_true_for_top_level_test_function():
    src = "def test_foo():\n    assert True\n"
    assert should_run_embedded_tests(src) is True


def test_should_run_embedded_tests_returns_true_for_test_class():
    src = "class TestThing:\n    def test_method(self):\n        pass\n"
    assert should_run_embedded_tests(src) is True


def test_should_run_embedded_tests_returns_true_for_class_named_exactly_test():
    # "Test".startswith("Test") is True.
    src = "class Test:\n    pass\n"
    assert should_run_embedded_tests(src) is True


def test_should_run_embedded_tests_returns_true_for_function_named_test_underscore_only():
    # "test_".startswith("test_") is True even with nothing after.
    src = "def test_():\n    pass\n"
    assert should_run_embedded_tests(src) is True


def test_should_run_embedded_tests_returns_true_for_decorated_test_function():
    # Decorators do not change the node type; still a top-level FunctionDef.
    src = "import functools\n\n@functools.wraps\ndef test_decorated():\n    pass\n"
    assert should_run_embedded_tests(src) is True


def test_should_run_embedded_tests_finds_target_after_other_top_level_nodes():
    src = (
        "import os\n"
        "X = 1\n"
        "def helper():\n"
        "    return 2\n"
        "def test_later():\n"
        "    assert helper() == 2\n"
    )
    assert should_run_embedded_tests(src) is True


def test_should_run_embedded_tests_returns_false_for_syntax_error():
    # SyntaxError on parse is swallowed and yields False.
    src = "def test_broken(:\n    pass\n"
    assert should_run_embedded_tests(src) is False


def test_should_run_embedded_tests_returns_false_for_empty_source():
    assert should_run_embedded_tests("") is False


def test_should_run_embedded_tests_returns_false_when_no_targets():
    src = "import os\n\nX = 1\n\ndef helper():\n    return os.getcwd()\n"
    assert should_run_embedded_tests(src) is False


def test_should_run_embedded_tests_returns_false_for_function_named_test_without_underscore():
    # "test".startswith("test_") is False.
    src = "def test():\n    pass\n"
    assert should_run_embedded_tests(src) is False


def test_should_run_embedded_tests_returns_false_for_function_capital_test_prefix():
    # FunctionDef check is case-sensitive on "test_", so "Test_" does not match.
    src = "def Test_foo():\n    pass\n"
    assert should_run_embedded_tests(src) is False


def test_should_run_embedded_tests_returns_false_for_class_lowercase_test_prefix():
    # ClassDef check is case-sensitive on "Test", so "testThing" does not match.
    src = "class testThing:\n    pass\n"
    assert should_run_embedded_tests(src) is False


def test_should_run_embedded_tests_returns_false_for_class_not_starting_with_test():
    # "MyTest".startswith("Test") is False even though it contains "Test".
    src = "class MyTest:\n    pass\n"
    assert should_run_embedded_tests(src) is False


def test_should_run_embedded_tests_returns_false_for_async_test_function():
    # AsyncFunctionDef is not an ast.FunctionDef, so async targets are ignored.
    src = "async def test_async():\n    pass\n"
    assert should_run_embedded_tests(src) is False


def test_should_run_embedded_tests_returns_false_for_nested_test_function():
    # Only top-level nodes (tree.body) are inspected; nested defs do not count.
    src = "def wrapper():\n    def test_inner():\n        pass\n    return test_inner\n"
    assert should_run_embedded_tests(src) is False


def test_should_run_embedded_tests_returns_false_for_test_method_inside_non_test_class():
    # A test_ method lives in the class body, not tree.body, and the class
    # name does not start with "Test", so the module has no top-level target.
    src = "class Helper:\n    def test_method(self):\n        pass\n"
    assert should_run_embedded_tests(src) is False


# ----- _pytest_site_dir -----
"""Verification oracle for harness.embedded_test_runner._pytest_site_dir.

Target behaviour (spec):

    spec = importlib.util.find_spec("pytest")
    if spec is None or not spec.submodule_search_locations:
        raise RuntimeError("pytest not importable from orchestrator env")
    return os.path.dirname(spec.submodule_search_locations[0])

The single unit under test is the module-level function ``_pytest_site_dir``;
its token (name with leading/trailing underscores stripped) is
``pytest_site_dir``. Every test name embeds that token verbatim so
``pytest -k pytest_site_dir`` selects exactly this unit's tests.
"""


import importlib.util
import os
import types

import pytest

from harness.embedded_test_runner import _pytest_site_dir


def _real_pytest_location() -> str:
    """Independently resolve pytest's package directory (stdlib only)."""
    spec = importlib.util.find_spec("pytest")
    assert spec is not None and spec.submodule_search_locations
    return spec.submodule_search_locations[0]


def test_pytest_site_dir_returns_non_empty_str():
    """Happy path yields a non-empty string path."""
    result = _pytest_site_dir()
    assert isinstance(result, str)
    assert result


def test_pytest_site_dir_matches_find_spec_parent():
    """Result equals dirname of pytest's first submodule search location."""
    expected = os.path.dirname(_real_pytest_location())
    assert _pytest_site_dir() == expected


def test_pytest_site_dir_returns_existing_directory():
    """The resolved site-packages path is a real directory on disk."""
    result = _pytest_site_dir()
    assert os.path.isdir(result)


def test_pytest_site_dir_is_parent_of_pytest_package():
    """The returned directory is the parent that contains the pytest package."""
    result = _pytest_site_dir()
    pytest_pkg = _real_pytest_location()
    # The pytest package dir lives directly inside the returned site dir.
    assert os.path.dirname(pytest_pkg) == result
    assert os.path.isdir(os.path.join(result, "pytest"))


def test_pytest_site_dir_raises_when_spec_none(monkeypatch):
    """RuntimeError when find_spec('pytest') returns None."""
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    with pytest.raises(RuntimeError, match="not importable"):
        _pytest_site_dir()


def test_pytest_site_dir_raises_when_search_locations_none(monkeypatch):
    """RuntimeError when the spec has submodule_search_locations == None."""
    fake = types.SimpleNamespace(submodule_search_locations=None)
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: fake)
    with pytest.raises(RuntimeError, match="not importable"):
        _pytest_site_dir()


def test_pytest_site_dir_raises_when_search_locations_empty(monkeypatch):
    """RuntimeError when the spec has an empty submodule_search_locations."""
    fake = types.SimpleNamespace(submodule_search_locations=[])
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: fake)
    with pytest.raises(RuntimeError, match="not importable"):
        _pytest_site_dir()


def test_pytest_site_dir_uses_first_search_location(monkeypatch):
    """Only the FIRST search location is used; result is its parent dir."""
    first = os.path.join(os.sep, "fake", "site-packages", "pytest")
    second = os.path.join(os.sep, "other", "place", "pytest")
    fake = types.SimpleNamespace(submodule_search_locations=[first, second])
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: fake)
    assert _pytest_site_dir() == os.path.dirname(first)
