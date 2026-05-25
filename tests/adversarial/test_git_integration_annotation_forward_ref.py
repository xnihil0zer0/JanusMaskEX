"""C9.10 P0 contract: _ast_merge must place an agent-introduced top-level
helper BEFORE the node whose DEF-TIME subtree references it (annotations,
decorators, base classes, defaults) — not only Assign/AnnAssign values.

The live failure (#35 geopack `clamp`): the blind agent "improved" an
un-typed signature with `T = TypeVar('T')`; the G17 forward-reference reorder
scanned only top-level Assign/AnnAssign values, so the TypeVar assignment was
appended AFTER the function that annotates with it -> NameError at import
(annotations evaluate at def time) -> rolled back to stub.

Each test merges an agent body that adds a helper used in a def-time position
over a stub target, then both asserts source order AND exec-imports the merged
module (the strongest gate — def-time evaluation fails fast on a forward ref).
"""
import ast

from harness.git_integration import _ast_merge


def _toplevel_index(tree: ast.Module, *, assign=None, func=None, cls=None) -> int:
    for i, node in enumerate(tree.body):
        if assign is not None and isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Name) and t.id == assign for t in targets):
                return i
        if func is not None and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func:
            return i
        if cls is not None and isinstance(node, ast.ClassDef) and node.name == cls:
            return i
    raise AssertionError(f"node not found: assign={assign} func={func} cls={cls}")


def test_typevar_annotation_reordered_before_function():
    # import shared with target (kept at top); agent adds the TypeVar assign
    target_src = "from typing import TypeVar\ndef clamp(value, low, high):\n    raise NotImplementedError\n"
    agent_src = (
        "from typing import TypeVar\n"
        "T = TypeVar('T')\n"
        "def clamp(value: T, low: T, high: T) -> T:\n"
        "    return max(low, min(value, high))\n"
    )
    merged = _ast_merge(agent_src, target_src)
    tree = ast.parse(merged)
    assert _toplevel_index(tree, assign="T") < _toplevel_index(tree, func="clamp")
    ns: dict = {}
    exec(compile(merged, "<merged>", "exec"), ns)
    assert ns["clamp"](5, 0, 3) == 3


def test_return_annotation_reordered_before_function():
    target_src = "from typing import TypeVar\ndef ident(x):\n    raise NotImplementedError\n"
    agent_src = (
        "from typing import TypeVar\n"
        "R = TypeVar('R')\n"
        "def ident(x: R) -> R:\n"
        "    return x\n"
    )
    merged = _ast_merge(agent_src, target_src)
    tree = ast.parse(merged)
    assert _toplevel_index(tree, assign="R") < _toplevel_index(tree, func="ident")
    ns: dict = {}
    exec(compile(merged, "<merged>", "exec"), ns)
    assert ns["ident"](7) == 7


def test_decorator_reordered_before_function():
    target_src = "def f():\n    raise NotImplementedError\n"
    agent_src = (
        "def deco(fn):\n"
        "    return fn\n"
        "@deco\n"
        "def f():\n"
        "    return 1\n"
    )
    merged = _ast_merge(agent_src, target_src)
    tree = ast.parse(merged)
    assert _toplevel_index(tree, func="deco") < _toplevel_index(tree, func="f")
    ns: dict = {}
    exec(compile(merged, "<merged>", "exec"), ns)
    assert ns["f"]() == 1


def test_base_class_reordered_before_subclass():
    target_src = "class C:\n    pass\n"
    agent_src = (
        "class Base:\n"
        "    def kind(self):\n"
        "        return 'base'\n"
        "class C(Base):\n"
        "    pass\n"
    )
    merged = _ast_merge(agent_src, target_src)
    tree = ast.parse(merged)
    assert _toplevel_index(tree, cls="Base") < _toplevel_index(tree, cls="C")
    ns: dict = {}
    exec(compile(merged, "<merged>", "exec"), ns)
    assert ns["C"]().kind() == "base"


def test_default_value_reordered_before_function():
    target_src = "def g(x):\n    raise NotImplementedError\n"
    agent_src = (
        "SENTINEL = object()\n"
        "def g(x=SENTINEL):\n"
        "    return x is SENTINEL\n"
    )
    merged = _ast_merge(agent_src, target_src)
    tree = ast.parse(merged)
    assert _toplevel_index(tree, assign="SENTINEL") < _toplevel_index(tree, func="g")
    ns: dict = {}
    exec(compile(merged, "<merged>", "exec"), ns)
    assert ns["g"]() is True


def test_annassign_value_reorder_still_works():
    # regression guard: the pre-existing Assign/AnnAssign-value scan must survive.
    target_src = "Z = 1\n"
    agent_src = "BASE = 10\nZ = BASE + 1\n"
    merged = _ast_merge(agent_src, target_src)
    tree = ast.parse(merged)
    assert _toplevel_index(tree, assign="BASE") < _toplevel_index(tree, assign="Z")
    ns: dict = {}
    exec(compile(merged, "<merged>", "exec"), ns)
    assert ns["Z"] == 11
