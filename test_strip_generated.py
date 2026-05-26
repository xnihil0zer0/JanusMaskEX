"""Verification oracle for harness/rebuild/strip.py."""
from __future__ import annotations

import ast
from types import SimpleNamespace

import pytest

from harness.rebuild.strip import (
    _stripify,
    strip_source,
    materialize_skeleton,
)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _funcs_by_name(tree: ast.AST) -> dict:
    """Map every (async) function/method def in *tree* by name."""
    return {
        n.name: n
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _one_funcdef(src: str):
    """Parse *src* and return its single top-level (async) function def."""
    return ast.parse(src).body[0]


def _exec_module(source: str) -> dict:
    """Compile + exec *source* as a module, returning its namespace."""
    ns: dict = {}
    exec(compile(source, "<skeleton>", "exec"), ns)
    return ns


# --------------------------------------------------------------------------
# _stripify
# --------------------------------------------------------------------------

def test_stripify_mutates_in_place_and_returns_none():
    fn = _one_funcdef("def f():\n    a = 1\n    return a\n")
    result = _stripify(fn)
    assert result is None
    # original statements gone, ends in a raise.
    assert isinstance(fn.body[-1], ast.Raise)
    assert not any(isinstance(s, ast.Return) for s in fn.body)


def test_stripify_keeps_leading_docstring():
    fn = _one_funcdef('def f():\n    """keep me"""\n    return 1\n')
    _stripify(fn)
    assert len(fn.body) == 2
    assert isinstance(fn.body[0], ast.Expr)
    assert isinstance(fn.body[0].value, ast.Constant)
    assert fn.body[0].value.value == "keep me"
    assert isinstance(fn.body[1], ast.Raise)


def test_stripify_without_docstring_is_only_raise():
    fn = _one_funcdef("def f():\n    x = 1\n    y = 2\n    return x + y\n")
    _stripify(fn)
    assert len(fn.body) == 1
    assert isinstance(fn.body[0], ast.Raise)


def test_stripify_raises_notimplementederror():
    fn = _one_funcdef("def f():\n    return 1\n")
    _stripify(fn)
    raise_node = fn.body[-1]
    assert isinstance(raise_node, ast.Raise)
    assert raise_node.exc is not None
    assert "NotImplementedError" in ast.unparse(raise_node)


def test_stripify_produces_callable_that_raises():
    fn = _one_funcdef("def f(a, b):\n    return a + b\n")
    _stripify(fn)
    mod = ast.Module(body=[fn], type_ignores=[])
    ast.fix_missing_locations(mod)
    ns = {}
    exec(compile(mod, "<t>", "exec"), ns)
    with pytest.raises(NotImplementedError):
        ns["f"](1, 2)


def test_stripify_handles_async_function():
    fn = _one_funcdef("async def f():\n    await g()\n    return 1\n")
    assert isinstance(fn, ast.AsyncFunctionDef)
    _stripify(fn)
    assert isinstance(fn.body[-1], ast.Raise)
    assert not any(isinstance(s, ast.Return) for s in fn.body)


# --------------------------------------------------------------------------
# strip_source: basic contract
# --------------------------------------------------------------------------

def test_strip_source_returns_str():
    out = strip_source("def f():\n    return 1\n")
    assert isinstance(out, str)


def test_strip_source_output_is_valid_python():
    src = "def f(x):\n    return x * 2\n"
    out = strip_source(src)
    # parses and compiles -> importable skeleton.
    ast.parse(out)
    compile(out, "<skeleton>", "exec")


def test_function_body_replaced_with_raise():
    src = "def f(x):\n    y = x + 1\n    return y\n"
    out = strip_source(src)
    assert "x + 1" not in out
    assert "return y" not in out
    assert "NotImplementedError" in out


def test_stripped_function_raises_when_called():
    src = "def f(x):\n    return x * 2\n"
    out = strip_source(src)
    ns = _exec_module(out)
    with pytest.raises(NotImplementedError):
        ns["f"](21)


def test_docstring_is_retained_then_raise():
    src = 'def f():\n    """Hello doc."""\n    return 99\n'
    out = strip_source(src)
    assert "Hello doc." in out
    fn = _funcs_by_name(ast.parse(out))["f"]
    assert len(fn.body) == 2
    assert isinstance(fn.body[0], ast.Expr)
    assert fn.body[0].value.value == "Hello doc."
    assert isinstance(fn.body[1], ast.Raise)


def test_function_without_docstring_has_only_raise():
    src = "def f():\n    return 1\n"
    fn = _funcs_by_name(ast.parse(strip_source(src)))["f"]
    assert len(fn.body) == 1
    assert isinstance(fn.body[0], ast.Raise)


# --------------------------------------------------------------------------
# strip_source: signatures / decorators / annotations preserved
# --------------------------------------------------------------------------

def test_signature_and_annotations_preserved():
    src = "def f(a: int, b: str='x', *args, c: float=1.0, **kw) -> bool:\n    return a\n"
    orig = _funcs_by_name(ast.parse(src))["f"]
    new = _funcs_by_name(ast.parse(strip_source(src)))["f"]
    # whole arg spec (names, annotations, defaults, *args/**kw) round-trips.
    assert ast.dump(new.args) == ast.dump(orig.args)
    # return annotation retained.
    assert new.returns is not None
    assert ast.dump(new.returns) == ast.dump(orig.returns)
    assert new.name == "f"


def test_decorators_preserved():
    src = (
        "import functools\n"
        "@functools.cache\n"
        "@staticmethod\n"
        "def f():\n"
        "    return 1\n"
    )
    orig = _funcs_by_name(ast.parse(src))["f"]
    new = _funcs_by_name(ast.parse(strip_source(src)))["f"]
    assert [ast.dump(d) for d in new.decorator_list] == [
        ast.dump(d) for d in orig.decorator_list
    ]
    assert len(new.decorator_list) == 2


def test_async_function_is_stripped():
    src = "async def f(x):\n    await g(x)\n    return x\n"
    out = strip_source(src)
    fn = _funcs_by_name(ast.parse(out))["f"]
    assert isinstance(fn, ast.AsyncFunctionDef)
    assert isinstance(fn.body[-1], ast.Raise)
    assert "await" not in out


# --------------------------------------------------------------------------
# strip_source: module-level material preserved
# --------------------------------------------------------------------------

def test_module_imports_and_constants_retained():
    src = (
        '"""module doc"""\n'
        "import os\n"
        "from sys import argv\n"
        "CONST = 42\n"
        "NAME: str = 'hi'\n"
        "def f():\n"
        "    return CONST\n"
    )
    out = strip_source(src)
    assert "module doc" in out
    assert "import os" in out
    assert "from sys import argv" in out
    out_tree = ast.parse(out)
    # constant assignment + its value survive.
    assigns = {
        t.id: n
        for n in out_tree.body
        if isinstance(n, ast.Assign)
        for t in n.targets
        if isinstance(t, ast.Name)
    }
    assert "CONST" in assigns
    assert ast.literal_eval(assigns["CONST"].value) == 42
    ann = [n for n in out_tree.body if isinstance(n, ast.AnnAssign)]
    assert any(isinstance(n.target, ast.Name) and n.target.id == "NAME" for n in ann)


def test_module_with_no_functions_keeps_logic():
    src = "import os\nX = 1\nY = X + 1\n"
    out = strip_source(src)
    assert "import os" in out
    assert "NotImplementedError" not in out
    ns = _exec_module(out)
    assert ns["X"] == 1
    assert ns["Y"] == 2


def test_comments_are_normalized_away():
    src = "# top comment\ndef f():\n    # inner comment\n    return 1  # trailing\n"
    out = strip_source(src)
    # ast.unparse drops all comments.
    assert "#" not in out
    assert "comment" not in out


# --------------------------------------------------------------------------
# strip_source: classes
# --------------------------------------------------------------------------

def test_class_methods_stripped_structure_retained():
    src = (
        "class Base:\n"
        "    pass\n"
        "\n"
        "class C(Base, metaclass=type):\n"
        "    attr = 5\n"
        "    typed: int = 7\n"
        "    def method(self, x):\n"
        '        """method doc"""\n'
        "        return x * 2\n"
        "    @property\n"
        "    def prop(self):\n"
        "        return self.attr\n"
    )
    out = strip_source(src)
    tree = ast.parse(out)
    cls = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "C"][0]
    # bases + keywords retained.
    assert [ast.unparse(b) for b in cls.bases] == ["Base"]
    assert any(kw.arg == "metaclass" for kw in cls.keywords)
    # class-level assignments (value-bearing) retained.
    assert any(
        isinstance(n, ast.Assign)
        and any(getattr(t, "id", None) == "attr" for t in n.targets)
        for n in cls.body
    )
    assert any(
        isinstance(n, ast.AnnAssign) and getattr(n.target, "id", None) == "typed"
        for n in cls.body
    )
    # method body removed; docstring + raise remain.
    method = _funcs_by_name(tree)["method"]
    assert "x * 2" not in out
    assert "method doc" in out
    assert isinstance(method.body[-1], ast.Raise)
    # property decorator retained.
    prop = _funcs_by_name(tree)["prop"]
    assert [ast.unparse(d) for d in prop.decorator_list] == ["property"]


def test_class_method_raises_when_called():
    src = (
        "class C:\n"
        "    def m(self, x):\n"
        "        return x + 1\n"
    )
    out = strip_source(src)
    ns = _exec_module(out)
    inst = ns["C"]()
    with pytest.raises(NotImplementedError):
        inst.m(5)


# --------------------------------------------------------------------------
# strip_source: determinism / idempotence / edge cases
# --------------------------------------------------------------------------

def test_strip_source_is_deterministic_and_idempotent():
    src = (
        "import os\n"
        "def f(a):\n"
        '    """doc"""\n'
        "    return a\n"
        "class C:\n"
        "    def m(self):\n"
        "        return 1\n"
    )
    once = strip_source(src)
    # byte-stable: same input -> same output.
    assert strip_source(src) == once
    # stripping an already-stripped skeleton is a fixed point.
    assert strip_source(once) == once


def test_empty_source():
    assert strip_source("") == ""


# --------------------------------------------------------------------------
# materialize_skeleton
# --------------------------------------------------------------------------

def _descriptor(tmp_path, modules, *, test_files=(), seed_files=(), sources=None):
    """Build a duck-typed descriptor and lay down its source files."""
    src_root = tmp_path / "src"
    src_root.mkdir(parents=True, exist_ok=True)
    sources = sources or {}
    for rel, text in sources.items():
        p = src_root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return SimpleNamespace(
        source_root=src_root,
        output_dir=tmp_path / "out",
        stash_dir=tmp_path / "stash",
        modules=list(modules),
        test_files=list(test_files),
        seed_files=list(seed_files),
    )


def test_materialize_writes_stripped_skeleton(tmp_path):
    original = "def f(x):\n    # body comment\n    return x * 2\n"
    desc = _descriptor(tmp_path, ["mod.py"], sources={"mod.py": original})
    materialize_skeleton(desc)
    written = (desc.output_dir / "mod.py").read_text(encoding="utf-8")
    # output is the stripped skeleton, not the verbatim source.
    assert written == strip_source(original)
    assert "return x * 2" not in written
    assert "body comment" not in written
    assert "NotImplementedError" in written


def test_materialize_stashes_verbatim_original(tmp_path):
    original = "def f(x):\n    # KEEP THIS COMMENT\n    return x * 2\n"
    desc = _descriptor(tmp_path, ["mod.py"], sources={"mod.py": original})
    result = materialize_skeleton(desc)
    stash_path = result["stash"]["mod.py"]
    from pathlib import Path

    sp = Path(stash_path)
    assert sp.is_file()
    # stash is byte-for-byte the original (comments intact -> NOT stripped).
    assert sp.read_text(encoding="utf-8") == original
    assert "KEEP THIS COMMENT" in sp.read_text(encoding="utf-8")
    # kept under the stash dir, never inside the output repo.
    assert desc.stash_dir in sp.parents
    assert desc.output_dir not in sp.parents


def test_materialize_return_shape(tmp_path):
    desc = _descriptor(
        tmp_path,
        ["mod.py"],
        sources={"mod.py": "def f():\n    return 1\n"},
    )
    result = materialize_skeleton(desc)
    assert set(result) >= {"stash", "modules", "output_dir"}
    assert result["modules"] == ["mod.py"]
    assert result["output_dir"] == str(desc.output_dir)
    assert isinstance(result["stash"], dict)
    assert set(result["stash"]) == {"mod.py"}


def test_materialize_creates_output_and_stash_dirs(tmp_path):
    desc = _descriptor(
        tmp_path,
        ["mod.py"],
        sources={"mod.py": "def f():\n    return 1\n"},
    )
    assert not desc.output_dir.exists()
    assert not desc.stash_dir.exists()
    materialize_skeleton(desc)
    assert desc.output_dir.is_dir()
    assert desc.stash_dir.is_dir()


def test_materialize_handles_nested_module_paths(tmp_path):
    original = "def deep():\n    return 7\n"
    desc = _descriptor(
        tmp_path,
        ["pkg/sub/mod.py"],
        sources={"pkg/sub/mod.py": original},
    )
    result = materialize_skeleton(desc)
    # nested skeleton dir is created under the output repo.
    assert (desc.output_dir / "pkg" / "sub" / "mod.py").is_file()
    from pathlib import Path

    sp = Path(result["stash"]["pkg/sub/mod.py"])
    assert sp.is_file()
    assert sp.read_text(encoding="utf-8") == original


def test_materialize_distinct_stash_per_module_no_collision(tmp_path):
    desc = _descriptor(
        tmp_path,
        ["a/mod.py", "b/mod.py"],
        sources={
            "a/mod.py": "def a():\n    return 'AAA'\n",
            "b/mod.py": "def b():\n    return 'BBB'\n",
        },
    )
    result = materialize_skeleton(desc)
    from pathlib import Path

    pa = Path(result["stash"]["a/mod.py"])
    pb = Path(result["stash"]["b/mod.py"])
    # same basename, different dirs -> must not clobber each other.
    assert pa != pb
    assert "AAA" in pa.read_text(encoding="utf-8")
    assert "BBB" in pb.read_text(encoding="utf-8")
    assert result["modules"] == ["a/mod.py", "b/mod.py"]


def test_materialize_copies_test_and_seed_files_verbatim(tmp_path):
    # test/seed files contain real function bodies that must survive verbatim.
    test_src = "def test_x():\n    assert 1 + 1 == 2\n"
    seed_src = "PACKAGE_MARKER = 'seed'\n"
    desc = _descriptor(
        tmp_path,
        ["mod.py"],
        test_files=["tests/test_x.py"],
        seed_files=["pkg/__init__.py"],
        sources={
            "mod.py": "def f():\n    return 1\n",
            "tests/test_x.py": test_src,
            "pkg/__init__.py": seed_src,
        },
    )
    materialize_skeleton(desc)
    copied_test = (desc.output_dir / "tests" / "test_x.py").read_text(encoding="utf-8")
    copied_seed = (desc.output_dir / "pkg" / "__init__.py").read_text(encoding="utf-8")
    # verbatim: bodies NOT stripped, no NotImplementedError injected.
    assert copied_test == test_src
    assert copied_seed == seed_src
    assert "assert 1 + 1 == 2" in copied_test
    assert "NotImplementedError" not in copied_test


def test_materialize_multiple_modules_all_stripped_and_stashed(tmp_path):
    desc = _descriptor(
        tmp_path,
        ["one.py", "two.py"],
        sources={
            "one.py": "def one():\n    return 1\n",
            "two.py": "def two():\n    return 2\n",
        },
    )
    result = materialize_skeleton(desc)
    assert set(result["stash"]) == {"one.py", "two.py"}
    for rel in ("one.py", "two.py"):
        written = (desc.output_dir / rel).read_text(encoding="utf-8")
        assert "NotImplementedError" in written
        assert "return" not in written