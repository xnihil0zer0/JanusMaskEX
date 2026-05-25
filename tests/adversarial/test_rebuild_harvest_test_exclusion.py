"""Contract: harvest_module must NOT harvest embedded pytest tests as units.

Many ``harness/`` modules carry an embedded pytest class or module-level
``test_*`` functions as in-file tests. Those are not reconstructible code -- the
clean-room rebuild engine must preserve them verbatim in the skeleton (where they
act as an in-module behavioural pin), never strip+reconstruct them blind. A real
domain class that merely starts with ``Test`` (e.g. an exception) must still be
harvested normally.
"""

from harness.rebuild.harvest import harvest_module
from harness.rebuild.strip import strip_source


def test_module_level_test_functions_excluded():
    src = (
        "def real_fn(x: int) -> int:\n"
        "    return x + 1\n\n"
        "def test_real_fn_adds_one():\n"
        "    assert real_fn(1) == 2\n"
    )
    names = [u.name for u in harvest_module("m.py", src, include_methods=True)]
    assert names == ["real_fn"]


def test_pytest_class_methods_excluded():
    src = (
        "def fmt(s: str) -> str:\n"
        "    return s.upper()\n\n"
        "class TestFmt:\n"
        "    def test_upper(self):\n"
        "        assert fmt('a') == 'A'\n"
        "    def test_empty(self):\n"
        "        assert fmt('') == ''\n"
    )
    names = [u.name for u in harvest_module("m.py", src, include_methods=True)]
    assert names == ["fmt"]


def test_real_test_prefixed_domain_class_not_excluded():
    # A Test-prefixed class with NO test* methods is a real domain class, kept.
    src = (
        "class TestHarness:\n"
        "    def __init__(self, n: int) -> None:\n"
        "        self.n = n\n"
        "    def run(self) -> int:\n"
        "        return self.n\n"
    )
    units = harvest_module("m.py", src, include_methods=True)
    names = {u.name for u in units}
    # The real class' methods (run / __init__) are harvested; nothing is dropped
    # as a "test".
    assert names and not any(n.startswith("test_") for n in names)


def test_stateful_pytest_class_excluded():
    # Even a stateful (setup-bearing) pytest class is excluded wholesale.
    src = (
        "def parse(s: str) -> int:\n"
        "    return int(s)\n\n"
        "class TestParse:\n"
        "    def setup_method(self):\n"
        "        self.cases = ['1', '2']\n"
        "    def test_parses(self):\n"
        "        assert parse(self.cases[0]) == 1\n"
    )
    names = [u.name for u in harvest_module("m.py", src, include_methods=True)]
    assert names == ["parse"]


def test_strip_preserves_embedded_tests():
    # strip_source must be SYMMETRIC with harvest: the real fn body is stubbed,
    # but embedded test bodies are kept verbatim (harvest will not rebuild them,
    # so a stripped test body would linger as a permanent stub).
    src = (
        "def real_fn(x: int) -> int:\n"
        "    return x + 1\n\n"
        "def test_real_fn_adds_one():\n"
        "    assert real_fn(1) == 2\n\n"
        "class TestRealFn:\n"
        "    def test_two(self):\n"
        "        assert real_fn(2) == 3\n"
    )
    skeleton = strip_source(src)
    # The real function is stubbed exactly once; the tests keep their asserts.
    assert skeleton.count("raise NotImplementedError") == 1
    assert skeleton.count("assert real_fn") == 2
    assert "class TestRealFn" in skeleton
