"""C9.8 contract: multi-module / cross-dep / cycle / class-method rebuild.

Deterministic unit-level proofs for the engine extensions (no live rebuild):
- module ordering (callee module first) with import-cycle fallback to source order;
- the intra-project module import graph;
- cross-module call detection;
- needs_deps routing: blanket (top-level dep) vs per-unit (function-local) vs
  transitive (a module that imports a dep-bearing module);
- global unit ordering across modules (every callee before its caller);
- class/method-aware stub detection + task spec.

Uses the samples/wordtools fixture (casing<->text import cycle, a class with
methods, the inflection dep, a test-less metrics module).
"""

from __future__ import annotations

import pathlib
import shutil

from harness.rebuild import discover, harvest, loop, task
from harness.test_author import GeneratedOracle

_REPO = pathlib.Path(__file__).resolve().parents[2]
_SAMPLE = _REPO / "samples" / "wordtools"


def _src(name: str) -> str:
    return (_SAMPLE / name).read_text(encoding="utf-8")


def _descriptor(tmp_path):
    return discover.build_descriptor(
        _SAMPLE,
        output_dir=tmp_path / "out",
        stash_dir=tmp_path / "stash",
        name="wordtools",
    )


# -- module import graph + ordering ------------------------------------------


def test_module_import_graph():
    mods = ["casing.py", "metrics.py", "text.py"]
    graph = discover.module_import_graph(_SAMPLE, mods)
    assert graph["casing.py"] == {"text.py"}
    assert graph["text.py"] == {"casing.py"}
    assert graph["metrics.py"] == set()


def test_order_modules_callee_first_noncyclic(tmp_path):
    # a imports b imports c (a chain, no cycle) -> order c, b, a.
    (tmp_path / "a.py").write_text("import b\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("import c\n", encoding="utf-8")
    (tmp_path / "c.py").write_text("X = 1\n", encoding="utf-8")
    ordered = discover.order_modules(tmp_path, ["a.py", "b.py", "c.py"])
    assert ordered.index("c.py") < ordered.index("b.py") < ordered.index("a.py")


def test_order_modules_cycle_is_total_and_deterministic():
    # casing <-> text is an import cycle: ordering must not error, must include
    # every module exactly once, and must be deterministic across runs (the
    # visiting-guard breaks the cycle the same way each time).
    mods = ["casing.py", "metrics.py", "text.py"]
    ordered = discover.order_modules(_SAMPLE, mods)
    assert sorted(ordered) == sorted(mods)
    assert ordered == discover.order_modules(_SAMPLE, mods)


# -- cross-module call detection ---------------------------------------------


def test_unit_cross_calls_casing():
    aliases = {"text": "text.py", "metrics": "metrics.py"}
    cc = harvest.unit_cross_calls(_src("casing.py"), aliases)
    assert ("text.py", "split_words") in cc.get("to_title", set())


def test_unit_cross_calls_text():
    aliases = {"casing": "casing.py", "metrics": "metrics.py"}
    cc = harvest.unit_cross_calls(_src("text.py"), aliases)
    assert ("casing.py", "to_snake") in cc.get("split_words", set())


# -- needs_deps routing ------------------------------------------------------


def test_needs_deps_blanket_for_top_level_import():
    units = harvest.harvest_module("casing.py", _src("casing.py"), external_modules={"inflection"})
    assert units and all(u.needs_deps for u in units)


def test_needs_deps_per_unit_for_function_local_import():
    src = (
        "def a(x):\n    import inflection\n    return inflection.pluralize(x)\n\n"
        "def b(y):\n    return y + 1\n"
    )
    units = {u.name: u for u in harvest.harvest_module("m.py", src, external_modules={"inflection"})}
    assert units["a"].needs_deps is True
    assert units["b"].needs_deps is False


def test_propagate_needs_deps_transitive(tmp_path):
    desc = _descriptor(tmp_path)
    ext = loop._dep_import_names(desc.dependencies)
    assert "inflection" in ext
    src_by = {m: _src(m) for m in desc.modules}
    units_by = {
        m: harvest.harvest_module(m, src_by[m], include_methods=True, external_modules=ext)
        for m in desc.modules
    }
    loop._propagate_needs_deps(desc, ext, src_by, units_by)
    # casing imports inflection (top-level) -> blanket; text imports casing
    # (transitive) -> tainted too; metrics is pure -> oracle path.
    assert all(u.needs_deps for u in units_by["casing.py"])
    assert all(u.needs_deps for u in units_by["text.py"])
    assert not any(u.needs_deps for u in units_by["metrics.py"])


# -- global unit ordering ----------------------------------------------------


def test_global_order_callees_before_callers():
    mods = ["casing.py", "metrics.py", "text.py"]
    units_by = {m: harvest.harvest_module(m, _src(m), include_methods=True) for m in mods}
    cross_by = {
        m: harvest.unit_cross_calls(_src(m), {k[:-3]: k for k in mods if k != m})
        for m in mods
    }
    ordered = loop._global_order(units_by, cross_by, mods)
    pos = {u.qualname: i for i, (_, u) in enumerate(ordered)}
    # intra-module: split_words -> word_count; cross-module: to_snake before
    # split_words; to_title (casing) after split_words (text); method after fn.
    assert pos["text.py:split_words"] < pos["text.py:word_count"]
    assert pos["casing.py:to_snake"] < pos["text.py:split_words"]
    assert pos["text.py:split_words"] < pos["casing.py:to_title"]
    assert pos["casing.py:to_snake"] < pos["casing.py:Caser.snake"]


# -- class/method-aware stub detection + task spec ---------------------------


def test_has_notimplemented_method_aware(tmp_path):
    stub = (
        "class Caser:\n"
        "    def snake(self, name):\n"
        "        raise NotImplementedError\n"
    )
    f = tmp_path / "casing.py"
    f.write_text(stub, encoding="utf-8")
    assert loop.has_notimplemented(f, "snake", cls="Caser") is True
    f.write_text(
        "class Caser:\n    def snake(self, name):\n        return name.lower()\n",
        encoding="utf-8",
    )
    assert loop.has_notimplemented(f, "snake", cls="Caser") is False


# -- multi-test-file selector + loop<->test-author integration ---------------


def test_multifile_unit_selector(tmp_path):
    (tmp_path / "a.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("def g():\n    return 2\n", encoding="utf-8")
    (tmp_path / "test_a.py").write_text("from a import f\n\ndef test_f():\n    assert f() == 1\n", encoding="utf-8")
    (tmp_path / "test_b.py").write_text("from b import g\n\ndef test_g():\n    assert g() == 2\n", encoding="utf-8")
    desc = discover.build_descriptor(tmp_path, output_dir=tmp_path / "o", stash_dir=tmp_path / "s")
    assert "{unit}" in desc.unit_test_selector
    assert "test_a.py" in desc.unit_test_selector and "test_b.py" in desc.unit_test_selector


def test_modules_without_tests(tmp_path):
    desc = _descriptor(tmp_path)
    testless = loop.modules_without_tests(desc)
    assert "metrics.py" in testless
    assert "casing.py" not in testless and "text.py" not in testless


def test_ensure_testless_oracles_injected_gen(tmp_path):
    # Copy the sample so the generated test file does not pollute the repo sample.
    sample_copy = tmp_path / "wordtools"
    shutil.copytree(_SAMPLE, sample_copy)
    desc = discover.build_descriptor(
        sample_copy, output_dir=tmp_path / "out", stash_dir=tmp_path / "stash", name="wt"
    )
    captured = {}

    # P1/C9.16: ensure_testless_oracles now authors PER UNIT, so the injected gen_fn
    # is called once per unit and must return that unit's OWN test (each importing
    # only its own unit -- a multi-unit test would fail the per-unit real-impl gate
    # that execs the unit's source slice standalone).
    def gen_fn(prompt, *, session_dir, attempt):
        captured["session_dir"] = pathlib.Path(session_dir)
        if "def char_total" in prompt:
            return ("from metrics import char_total\n\n"
                    "def test_char_total():\n    assert char_total(['ab', 'c']) == 3\n",
                    "python -m pytest -q")
        return ("from metrics import longest\n\n"
                "def test_longest():\n    assert longest(['a', 'bbb', 'cc']) == 'bbb'\n",
                "python -m pytest -q")

    generated = loop.ensure_testless_oracles(desc, gen_fn=gen_fn)
    assert "metrics.py" in generated
    assert isinstance(generated["metrics.py"], GeneratedOracle)
    # the generated test was written into the OUTPUT repo and registered -- NEVER
    # into the committed source tree (#35: that would dirty an arbitrary input
    # project and make the module no-longer test-less on the next run).
    assert (desc.output_dir / "test_metrics_generated.py").is_file()
    assert not (sample_copy / "test_metrics_generated.py").exists()
    assert "test_metrics_generated.py" in desc.test_files
    assert "{unit}" in desc.unit_test_selector
    # per-unit authoring: BOTH units' tests landed in the combined oracle file.
    combined = (desc.output_dir / "test_metrics_generated.py").read_text()
    assert "test_char_total" in combined and "test_longest" in combined
    # independent session dir handed to the role
    assert "test_author" in captured["session_dir"].parts


# -- P3: large-body detection + decomposer integration -----------------------


def test_unit_exceeds_byte_budget():
    units = harvest.harvest_module("metrics.py", _src("metrics.py"))
    small = next(u for u in units if u.name == "char_total")
    assert loop.unit_exceeds_byte_budget(_src("metrics.py"), small) is False
    big_src = "def huge():\n" + "\n".join(f"    x{i} = {i}" for i in range(2000)) + "\n    return 0\n"
    big = harvest.harvest_module("m.py", big_src)[0]
    assert loop.unit_exceeds_byte_budget(big_src, big) is True
    # configurable budget
    assert loop.unit_exceeds_byte_budget(
        _src("metrics.py"), small, {"rebuild": {"unit_byte_budget": 1}}
    ) is True


def test_decompose_oversized_unit_invokes_decomposer(tmp_path):
    big_src = "def huge():\n" + "\n".join(f"    x{i} = {i}" for i in range(50)) + "\n    return 0\n"
    unit = harvest.harvest_module("m.py", big_src)[0]
    result = loop.decompose_oversized_unit(unit, big_src, {}, tmp_path / "state")
    assert result.subtasks  # the decomposer produced a follow-up plan


def test_build_unit_task_method_aware(tmp_path):
    desc = _descriptor(tmp_path)
    units = harvest.harvest_module("casing.py", _src("casing.py"), include_methods=True)
    snake = next(u for u in units if u.cls == "Caser" and u.name == "snake")
    spec = task.build_unit_task(
        descriptor=desc,
        unit=snake,
        module_rel="casing.py",
        oracle_original_path="/dev/null",
        sibling_signatures=[],
        unit_test_text="",
        parent_root=str(_REPO),
    )
    assert "Caser" in spec["task_id"]
    assert "class Caser" in spec["specification"]
    assert "METHOD" in spec["specification"]


# -- P1 (C9.9): untyped-signature routing + live test-author gen_fn -----------


def test_has_untyped_params_detection():
    # an un-annotated value param -> untyped; self/cls exempt; no-arg trivially typed.
    src = (
        "def untyped(x):\n    return x\n\n"
        "def typed(x: int) -> int:\n    return x\n\n"
        "def noarg() -> int:\n    return 0\n\n"
        "def star(*args):\n    return args\n\n"
        "class C:\n"
        "    def m(self, y):\n        return y\n"
        "    def n(self, y: int) -> int:\n        return y\n"
    )
    units = {u.qualname: u for u in harvest.harvest_module("m.py", src, include_methods=True)}
    assert units["m.py:untyped"].untyped is True
    assert units["m.py:typed"].untyped is False
    assert units["m.py:noarg"].untyped is False  # no value params -> not a fuzz risk
    assert units["m.py:star"].untyped is True  # *args without annotation
    assert units["m.py:C.m"].untyped is True  # self exempt, y un-typed
    assert units["m.py:C.n"].untyped is False  # self exempt, y typed


def test_untyped_unit_routes_to_oracle_skip(tmp_path):
    # An UN-typed pure unit must drop the merged==original fuzz oracle (the no-hint
    # fuzz domain is unconstrained -> false value-divergence, the #34 longest reject)
    # and route to the tests-only / fuzzer-bypass path.
    desc = _descriptor(tmp_path)
    src = "def f(x):\n    return x + 1\n"
    unit = harvest.harvest_module("u.py", src)[0]
    assert unit.untyped is True and unit.impure is False and unit.needs_deps is False
    spec = task.build_unit_task(
        descriptor=desc, unit=unit, module_rel="u.py",
        oracle_original_path="/dev/null", sibling_signatures=[],
        unit_test_text="", parent_root=str(_REPO),
    )
    assert spec.get("meta_task_type") == "harness_plumbing"
    assert "oracle.py" not in spec["verification_command"]


def test_typed_pure_unit_keeps_oracle(tmp_path):
    desc = _descriptor(tmp_path)
    src = "def f(x: int) -> int:\n    return x + 1\n"
    unit = harvest.harvest_module("u.py", src)[0]
    assert unit.untyped is False
    spec = task.build_unit_task(
        descriptor=desc, unit=unit, module_rel="u.py",
        oracle_original_path="/dev/null", sibling_signatures=[],
        unit_test_text="", parent_root=str(_REPO),
    )
    assert "meta_task_type" not in spec
    assert "oracle.py" in spec["verification_command"]


def test_extract_python_block_strips_fence():
    from harness import test_author
    fenced = "Here is the file:\n```python\nimport pytest\n\ndef test_x():\n    assert 1\n```\nDone."
    out = test_author._extract_python_block(fenced)
    assert out.startswith("import pytest")
    assert "```" not in out and "Done." not in out
    bare = "```\nx = 1\n```"
    assert test_author._extract_python_block(bare).strip() == "x = 1"
    unfenced = "def test_y():\n    assert 2\n"
    assert "def test_y" in test_author._extract_python_block(unfenced)


# -- P2 (C9.9): packages + relative-import resolution ------------------------


def test_relative_base_resolution():
    # module pkg/sub.py (dotted pkg.sub, package pkg)
    assert discover.relative_base("pkg/sub.py", 1) == ["pkg"]  # current package
    assert discover.relative_base("pkg/sub.py", 2) == []  # parent / top-level
    assert discover.relative_base("pkg/sub.py", 3) is None  # beyond top-level
    # deeper package pkg/sub/deep.py (package pkg.sub)
    assert discover.relative_base("pkg/sub/deep.py", 1) == ["pkg", "sub"]
    assert discover.relative_base("pkg/sub/deep.py", 2) == ["pkg"]


def _make_pkg(tmp_path):
    pkg = tmp_path / "shapes"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("from .area import square\n", encoding="utf-8")
    # geom.py: leaf callee
    (pkg / "geom.py").write_text(
        "def side(n: int) -> int:\n    return n\n", encoding="utf-8"
    )
    # area.py imports geom relatively (from .geom import side)
    (pkg / "area.py").write_text(
        "from .geom import side\n\n"
        "def square(n: int) -> int:\n    return side(n) * side(n)\n",
        encoding="utf-8",
    )
    return tmp_path


def test_module_import_graph_relative(tmp_path):
    root = _make_pkg(tmp_path)
    mods = ["shapes/area.py", "shapes/geom.py"]
    graph = discover.module_import_graph(root, mods)
    # area.py imports geom.py via a RELATIVE import (from .geom import side)
    assert "shapes/geom.py" in graph["shapes/area.py"]
    assert graph["shapes/geom.py"] == set()  # geom imports nothing intra-project


def test_order_modules_relative_callee_first(tmp_path):
    root = _make_pkg(tmp_path)
    mods = ["shapes/area.py", "shapes/geom.py"]
    order = discover.order_modules(root, mods)
    # the relatively-imported callee (geom) precedes its importer (area)
    assert order.index("shapes/geom.py") < order.index("shapes/area.py")


def test_unit_cross_calls_relative(tmp_path):
    src = (
        "from .geom import side\n\n"
        "def square(n: int) -> int:\n    return side(n) * side(n)\n"
    )
    aliases = {"shapes.geom": "shapes/geom.py", "geom": "shapes/geom.py"}
    cross = harvest.unit_cross_calls(src, aliases, "shapes/area.py")
    assert cross.get("square") == {("shapes/geom.py", "side")}


def test_unit_cross_calls_relative_submodule(tmp_path):
    # ``from . import geom`` then geom.side(...) -> alias-style cross call
    src = (
        "from . import geom\n\n"
        "def square(n: int) -> int:\n    return geom.side(n) * geom.side(n)\n"
    )
    aliases = {"shapes.geom": "shapes/geom.py", "geom": "shapes/geom.py"}
    cross = harvest.unit_cross_calls(src, aliases, "shapes/area.py")
    assert cross.get("square") == {("shapes/geom.py", "side")}


def test_relative_import_routes_to_oracle_skip(tmp_path):
    # A relative import makes the merged==original oracle (which execs the source
    # standalone) raise ImportError -> the unit must route to tests-only.
    desc = _descriptor(tmp_path)
    src = (
        "from .geom import side\n\n"
        "def square(n: int) -> int:\n    return side(n) * side(n)\n"
    )
    unit = harvest.harvest_module("shapes/area.py", src)[0]
    assert unit.rel_import is True
    spec = task.build_unit_task(
        descriptor=desc, unit=unit, module_rel="shapes/area.py",
        oracle_original_path="/dev/null", sibling_signatures=[],
        unit_test_text="", parent_root=str(_REPO),
    )
    assert spec.get("meta_task_type") == "harness_plumbing"
    assert "oracle.py" not in spec["verification_command"]
    # an absolute-import module keeps the oracle
    abs_unit = harvest.harvest_module("flat.py", "def f(n: int) -> int:\n    return n\n")[0]
    assert abs_unit.rel_import is False


# -- P3 (C9.9): stateful class-granular reconstruction -----------------------

_STATEFUL = (
    "class Counter:\n"
    '    """A running counter."""\n'
    "    def __init__(self, start: int) -> None:\n"
    "        self.n = start\n"
    "    def inc(self) -> None:\n"
    "        self.n += 1\n"
    "    def value(self) -> int:\n"
    "        return self.n\n"
)
_STATELESS = (
    "class Helper:\n"
    "    def a(self, x: int) -> int:\n        return x + 1\n"
    "    def b(self, x: int) -> int:\n        return x + 2\n"
)


def test_class_is_stateful_detection():
    stateful_node = next(n for n in __import__("ast").parse(_STATEFUL).body)
    stateless_node = next(n for n in __import__("ast").parse(_STATELESS).body)
    assert harvest._class_is_stateful(stateful_node) is True
    assert harvest._class_is_stateful(stateless_node) is False


def test_harvest_emits_whole_class_unit():
    units = harvest.harvest_module("c.py", _STATEFUL, include_methods=True)
    assert len(units) == 1
    u = units[0]
    assert u.whole_class is True and u.cls == "Counter" and u.name == "Counter"
    assert set(u.methods) == {"__init__", "inc", "value"}
    # skeleton reveals the public API but no real body (bodies are stubbed)
    assert "def inc(self)" in u.class_skeleton
    assert "self.n += 1" not in u.class_skeleton
    assert "NotImplementedError" in u.class_skeleton
    # a STATELESS class keeps per-method units (#34)
    pm = harvest.harvest_module("h.py", _STATELESS, include_methods=True)
    assert {x.name for x in pm} == {"a", "b"}
    assert all(not x.whole_class for x in pm)


def test_build_unit_task_whole_class(tmp_path):
    desc = _descriptor(tmp_path)
    unit = harvest.harvest_module("c.py", _STATEFUL, include_methods=True)[0]
    spec = task.build_unit_task(
        descriptor=desc, unit=unit, module_rel="c.py",
        oracle_original_path="/dev/null", sibling_signatures=[],
        unit_test_text="def test_counter():\n    c = Counter(0)\n    c.inc()\n    assert c.value() == 1\n",
        parent_root=str(_REPO),
    )
    assert spec["task_id"] == "RB_wordtools_Counter"  # class-scoped, not per-method
    assert "ENTIRE" in spec["specification"]
    assert "def value(self)" in spec["specification"]  # skeleton in the spec
    # a class is gated by its tests, never the per-function fuzzer / oracle
    assert spec.get("meta_task_type") == "harness_plumbing"
    assert "oracle.py" not in spec["verification_command"]


def test_class_has_notimplemented(tmp_path):
    stub = tmp_path / "c.py"
    from harness.rebuild.strip import strip_source
    stub.write_text(strip_source(_STATEFUL), encoding="utf-8")
    assert loop.class_has_notimplemented(stub, "Counter") is True
    real = tmp_path / "c2.py"
    real.write_text(_STATEFUL, encoding="utf-8")
    assert loop.class_has_notimplemented(real, "Counter") is False
