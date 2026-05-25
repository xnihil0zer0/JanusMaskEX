"""B1 (session #37) contract: _ast_merge must order an AGENT-ADDED import
before the agent-added assignment that consumes it, and that assignment before
the function that annotates with it -- even when the import is NOT present in
the target.

The #36 def-time reorder (test_git_integration_annotation_forward_ref.py) moved
an agent's ``T = TypeVar('T')`` before the function that annotates with ``T``,
but only when ``from typing import TypeVar`` was ALREADY in the target. When the
blind agent introduces the import itself, ``name_lookup`` was built only from
('name'|'assign') keys, so the import (key ('import_from', ...)) was appended
AFTER the assignment that uses it -> NameError at import time.

Fix is two-part inside ``_ast_merge``: (1) import-bound names enter
``name_lookup``; (2) a final topological stabilization reorders the agent-added
nodes among themselves so each binder precedes its first consumer.

Each test asserts source order AND exec-imports the merged module (the strongest
gate -- def-time evaluation fails fast on a forward ref).
"""
import ast

from harness.git_integration import _ast_merge


def _toplevel_index(tree, *, assign=None, func=None, cls=None, import_name=None):
    for i, node in enumerate(tree.body):
        if assign is not None and isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Name) and t.id == assign for t in targets):
                return i
        if func is not None and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func:
            return i
        if cls is not None and isinstance(node, ast.ClassDef) and node.name == cls:
            return i
        if import_name is not None and isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                if (a.asname or a.name) == import_name:
                    return i
    raise AssertionError(f"node not found: assign={assign} func={func} cls={cls} import={import_name}")


def test_agent_added_importfrom_before_assign_before_func():
    # target stub has NO `from typing import TypeVar`; the agent introduces it.
    target_src = "def clamp(value, low, high):\n    raise NotImplementedError\n"
    agent_src = (
        "from typing import TypeVar\n"
        "T = TypeVar('T')\n"
        "def clamp(value: T, low: T, high: T) -> T:\n"
        "    return max(low, min(value, high))\n"
    )
    merged = _ast_merge(agent_src, target_src)
    tree = ast.parse(merged)
    assert _toplevel_index(tree, import_name="TypeVar") < _toplevel_index(tree, assign="T")
    assert _toplevel_index(tree, assign="T") < _toplevel_index(tree, func="clamp")
    ns: dict = {}
    exec(compile(merged, "<merged>", "exec"), ns)
    assert ns["clamp"](5, 0, 3) == 3


def test_agent_added_plain_import_before_module_level_use():
    target_src = "def area(r):\n    raise NotImplementedError\n"
    agent_src = (
        "import math\n"
        "TAU = 2 * math.pi\n"
        "def area(r):\n"
        "    return TAU / 2 * r * r\n"
    )
    merged = _ast_merge(agent_src, target_src)
    tree = ast.parse(merged)
    assert _toplevel_index(tree, import_name="math") < _toplevel_index(tree, assign="TAU")
    ns: dict = {}
    exec(compile(merged, "<merged>", "exec"), ns)
    assert abs(ns["area"](1.0) - 3.141592653589793) < 1e-9


def test_agent_added_import_aliased_chain():
    target_src = "def f():\n    raise NotImplementedError\n"
    agent_src = (
        "import math as m\n"
        "ROOT2 = m.sqrt(2)\n"
        "def f():\n"
        "    return ROOT2\n"
    )
    merged = _ast_merge(agent_src, target_src)
    tree = ast.parse(merged)
    assert _toplevel_index(tree, import_name="m") < _toplevel_index(tree, assign="ROOT2")
    ns: dict = {}
    exec(compile(merged, "<merged>", "exec"), ns)
    assert abs(ns["f"]() - 1.4142135623730951) < 1e-12


def test_three_node_agent_chain_topological():
    # import -> base assign -> derived assign -> func, all agent-added, scrambled
    # acceptance is purely that exec-import succeeds and order is binder-first.
    target_src = "def compute():\n    raise NotImplementedError\n"
    agent_src = (
        "from fractions import Fraction\n"
        "HALF = Fraction(1, 2)\n"
        "QUARTER = HALF * HALF\n"
        "def compute():\n"
        "    return QUARTER\n"
    )
    merged = _ast_merge(agent_src, target_src)
    tree = ast.parse(merged)
    assert _toplevel_index(tree, import_name="Fraction") < _toplevel_index(tree, assign="HALF")
    assert _toplevel_index(tree, assign="HALF") < _toplevel_index(tree, assign="QUARTER")
    ns: dict = {}
    exec(compile(merged, "<merged>", "exec"), ns)
    assert ns["compute"]() * 4 == 1


def test_existing_shared_import_path_unchanged():
    # regression guard: when the import IS shared with the target (the #36 case),
    # behavior is unchanged -- assign still lands before the function.
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
