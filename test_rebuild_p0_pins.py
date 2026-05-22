"""Operator per-unit pins for the P0 clean-room rebuild batch (session #46).

For SELF-replication we POSSESS the original, so an oracle-SKIP unit (ast.*-typed
/ impure / untyped / unfuzzable -- merged==original fuzz is vacuous) is gated by a
behavioural pin DERIVED FROM and VERIFIED AGAINST the real original (C9.17c LAW),
NOT by a live gen_testless author call (~7 min each, the throughput/token sink).

Each test is named ``test_<unit>_<behaviour>`` so the rebuild loop's per-unit
``-k 'test_<unit>_'`` selector (task._k_expr) runs exactly this unit's pin and no
sibling's. Imports resolve to the module under rebuild in the OUTPUT repo when the
loop runs them there, and to JanusMask's own modules under the JM suite (so this
file also stands as a JM contract -- the assertions hold against the originals).
"""

import ast

from harness.rebuild import harvest


def _node(code: str):
    return ast.parse(code).body[0]


def _mod(code: str):
    return ast.parse(code)


def _ann(expr: str):
    return ast.parse(expr, mode="eval").body


# --- harvest._is_impure(node: ast.AST) -> bool ----------------------------------
def test_is_impure_detects_nondeterministic_and_io():
    assert harvest._is_impure(_node("def f():\n    return time.time()")) is True
    assert harvest._is_impure(_node("def f():\n    return random.random()")) is True
    assert harvest._is_impure(_node("def f(p):\n    return open(p)")) is True
    assert harvest._is_impure(_node("def f():\n    return os.path.join('a', 'b')")) is True


def test_is_impure_false_for_pure_body():
    assert harvest._is_impure(_node("def f(x):\n    return x + 1")) is False
    assert harvest._is_impure(_node("def f(s):\n    return s.upper()")) is False
    assert harvest._is_impure(_node("def f(xs):\n    return sorted(xs)")) is False


# --- harvest._module_global_names(tree: ast.Module) -> set[str] ------------------
def test_module_global_names_collects_top_level_bindings():
    g = harvest._module_global_names(_mod("X = 1\nY: int = 2\ndef f():\n    z = 3\nimport os"))
    assert "X" in g and "Y" in g
    assert "z" not in g


# --- harvest._mutates_module_globals(node, module_globals) -> bool ---------------
def test_mutates_module_globals_true_on_global_write():
    assert harvest._mutates_module_globals(_node("def f():\n    global X\n    X = 5"), {"X"}) is True


def test_mutates_module_globals_false_on_read_only():
    assert harvest._mutates_module_globals(_node("def f():\n    y = X + 1\n    return y"), {"X"}) is False


# --- harvest._signature_line(node) -> str ---------------------------------------
def test_signature_line_renders_def_header():
    got = harvest._signature_line(_node("def f(a, b: int = 3) -> bool:\n    return True"))
    assert got == "def f(a, b: int=3) -> bool:"


# --- harvest._has_relative_import(tree) -> bool ---------------------------------
def test_has_relative_import_true_on_dotted():
    assert harvest._has_relative_import(_mod("from .x import y")) is True


def test_has_relative_import_false_on_absolute():
    assert harvest._has_relative_import(_mod("import os\nfrom collections import OrderedDict")) is False


# --- harvest._class_is_stateful(node: ast.ClassDef) -> bool ---------------------
def test_class_is_stateful_true_when_self_state_shared():
    src = "class C:\n    def __init__(self):\n        self.x = 1\n    def g(self):\n        return self.x"
    assert harvest._class_is_stateful(_node(src)) is True


def test_class_is_stateful_false_when_stateless():
    assert harvest._class_is_stateful(_node("class C:\n    def g(self, a):\n        return a + 1")) is False


# --- harvest._is_self_mutating(node) -> bool ------------------------------------
def test_is_self_mutating_true_when_only_assigns_self():
    assert harvest._is_self_mutating(_node("def m(self):\n    self.x = 1")) is True


def test_is_self_mutating_false_when_returns_value():
    assert harvest._is_self_mutating(_node("def m(self, a):\n    return a * 2")) is False


# --- harvest._is_fuzzable_annotation(node) -> bool ------------------------------
def test_is_fuzzable_annotation_true_for_primitive():
    assert harvest._is_fuzzable_annotation(_ann("int")) is True


def test_is_fuzzable_annotation_false_for_ast_and_none():
    assert harvest._is_fuzzable_annotation(_ann("ast.AST")) is False
    assert harvest._is_fuzzable_annotation(None) is False


# --- harvest._has_unfuzzable_params(node) -> bool -------------------------------
def test_has_unfuzzable_params_true_for_ast_typed():
    assert harvest._has_unfuzzable_params(_node("def f(n: ast.AST):\n    return 1")) is True


def test_has_unfuzzable_params_false_for_primitive_typed():
    assert harvest._has_unfuzzable_params(_node("def f(x: int, s: str):\n    return 1")) is False


# --- harvest._has_untyped_params(node) -> bool ----------------------------------
def test_has_untyped_params_true_when_missing_annotation():
    assert harvest._has_untyped_params(_node("def f(x):\n    return x")) is True


def test_has_untyped_params_false_when_fully_typed():
    assert harvest._has_untyped_params(_node("def f(x: int):\n    return x")) is False


# --- harvest._is_pytest_class(name, method_defs) -> bool ------------------------
def test_is_pytest_class_true_for_test_prefixed_with_methods():
    md = [_node("def test_a(self):\n    assert True")]
    assert harvest._is_pytest_class("TestFoo", md) is True


def test_is_pytest_class_false_for_non_test_name():
    md = [_node("def test_a(self):\n    assert True")]
    assert harvest._is_pytest_class("Foo", md) is False


# --- harvest._is_test_function(name: str) -> bool -------------------------------
def test_is_test_function_recognizes_test_prefix():
    assert harvest._is_test_function("test_foo") is True
    assert harvest._is_test_function("test_") is True


def test_is_test_function_rejects_non_test():
    assert harvest._is_test_function("testbar") is False
    assert harvest._is_test_function("helper") is False
    assert harvest._is_test_function("setup_module") is False


# ================================ discover.py ===================================
def _make_proj(root):
    (root / "mypkg").mkdir()
    (root / "tests").mkdir()
    (root / "mypkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "mypkg" / "core.py").write_text(
        "from mypkg.utils import helper\n\ndef run():\n    return helper()\n", encoding="utf-8")
    (root / "mypkg" / "utils.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
    (root / "tests" / "test_core.py").write_text("def test_run():\n    assert True\n", encoding="utf-8")
    return root


def test_discover_modules_partitions_sources_tests_seeds(tmp_path):
    from harness.rebuild import discover
    mods, tests, seeds = discover.discover_modules(_make_proj(tmp_path))
    assert mods == ["mypkg/core.py", "mypkg/utils.py"]
    assert tests == ["tests/test_core.py"]
    assert seeds == ["mypkg/__init__.py"]


def test_module_import_graph_maps_intra_project_edges(tmp_path):
    from harness.rebuild import discover
    root = _make_proj(tmp_path)
    g = discover.module_import_graph(root, ["mypkg/core.py", "mypkg/utils.py"])
    assert g == {"mypkg/core.py": {"mypkg/utils.py"}, "mypkg/utils.py": set()}


def test_order_modules_places_callee_before_importer(tmp_path):
    from harness.rebuild import discover
    root = _make_proj(tmp_path)
    assert discover.order_modules(root, ["mypkg/core.py", "mypkg/utils.py"]) == [
        "mypkg/utils.py", "mypkg/core.py"]


def test_import_from_targets_resolves_absolute_and_relative():
    from harness.rebuild import discover
    abs_node = ast.parse("from mypkg.utils import helper").body[0]
    assert discover._import_from_targets("mypkg/core.py", abs_node) == ["mypkg.utils"]
    rel_node = ast.parse("from . import utils").body[0]
    assert discover._import_from_targets("mypkg/core.py", rel_node) == ["mypkg.utils"]


def test_build_descriptor_infers_modules_and_tests(tmp_path):
    from harness.rebuild import discover
    root = _make_proj(tmp_path)
    desc = discover.build_descriptor(
        root, output_dir=tmp_path / "out", stash_dir=tmp_path / "stash", name="probe")
    assert desc.name == "probe"
    assert desc.modules == ["mypkg/utils.py", "mypkg/core.py"]
    assert desc.test_files == ["tests/test_core.py"]


def test_is_test_file_true_for_test_module_basename():
    from harness.rebuild import discover
    assert discover._is_test_file("test_foo.py") is True


def test_is_test_file_false_for_non_test():
    from harness.rebuild import discover
    assert discover._is_test_file("core.py") is False
    assert discover._is_test_file("conftest.py") is False


def test_skip_dir_true_for_vcs_and_cache_dirs():
    from harness.rebuild import discover
    assert discover._skip_dir(("__pycache__",)) is True
    assert discover._skip_dir((".git",)) is True
    assert discover._skip_dir(("node_modules",)) is True
    assert discover._skip_dir((".venv",)) is True


def test_skip_dir_false_for_source_package():
    from harness.rebuild import discover
    assert discover._skip_dir(("mypkg",)) is False


def test_stem_map_maps_dotted_and_short_names():
    from harness.rebuild import discover
    m = discover._stem_map(["mypkg/core.py", "mypkg/utils.py", "top.py"])
    assert m["mypkg.core"] == "mypkg/core.py"
    assert m["core"] == "mypkg/core.py"
    assert m["utils"] == "mypkg/utils.py"
    assert m["top"] == "top.py"


# --- venv.provision_venv (impure subprocess; pin is the sole gate) ---------------
def test_provision_venv_creates_ready_interpreter(tmp_path):
    from harness.rebuild import venv
    venv.provision_venv(tmp_path)
    assert venv.venv_ready(tmp_path) is True
    assert (tmp_path / ".venv" / "bin" / "python").exists()


# ================================== venv.py =====================================
def test_venv_python_points_at_posix_interpreter(tmp_path):
    from harness.rebuild import venv
    assert venv.venv_python(tmp_path) == tmp_path / ".venv" / "bin" / "python"


def test_venv_ready_reflects_interpreter_existence(tmp_path):
    from harness.rebuild import venv
    assert venv.venv_ready(tmp_path) is False
    (tmp_path / ".venv" / "bin").mkdir(parents=True)
    (tmp_path / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
    assert venv.venv_ready(tmp_path) is True
