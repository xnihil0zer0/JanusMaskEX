"""ngv2.sink_reachability_gate -- deterministic constant-vs-external sink-argument
reachability gate.

Separates "the sink fires" from "attacker input reaches the sink". Given a sink
name and the source snippets of every call site, it AST-classifies each call
argument as a literal constant or an externally-influenced value, and reports
whether the sink is attacker-reachable. A dangerous sink that is only ever
invoked with HARDCODED constant arguments is reported ``constant_only`` /
``may_confirm=False`` rather than allowed to confirm.

Pure, stdlib-only (``ast``, ``typing``) and deterministic: identical inputs
produce a byte-identical output dict. Sink names are processed ONLY as ast data,
never executed.
"""
import ast
from typing import List, Dict, Any

def _sink_tail(sink_name: str) -> str:
    """Return the bare tail used for matching (last dotted segment)."""
    return sink_name.split('.')[-1]

def _callee_matches(node: ast.Call, tail: str) -> bool:
    """True if the call's callee bare-name or dotted-attribute tail == tail."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == tail
    if isinstance(func, ast.Attribute):
        return func.attr == tail
    return False

def _is_constant(node: ast.AST) -> bool:
    """Recursively decide whether an argument node is a pure literal constant.

    CONSTANT = ast.Constant (str/num/bytes/bool/None); a tuple/list whose elements
    are all constant; a dict whose keys and values are all constant; or a pure
    constant string/number concatenation ('a' + 'b') with all operands constant.
    """
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return all((_is_constant(elt) for elt in node.elts))
    if isinstance(node, ast.Dict):
        return all((key is not None and _is_constant(key) and _is_constant(value) for key, value in zip(node.keys, node.values)))
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _is_constant(node.left) and _is_constant(node.right)
    return False

def _site_has_external_arg(snippet: str, tail: str) -> bool:
    """Parse snippet; True if any matched call passes a non-constant argument."""
    try:
        tree = ast.parse(snippet)
    except (SyntaxError, ValueError):
        return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not _callee_matches(node, tail):
            continue
        args: List[ast.AST] = list(node.args)
        args.extend((kw.value for kw in node.keywords))
        for arg in args:
            if isinstance(arg, ast.Starred):
                arg = arg.value
            if not _is_constant(arg):
                return True
    return False

def assess_sink_reachability(sink_name: str, call_sites: List[str]) -> Dict[str, Any]:
    """Assess whether a dangerous sink is reachable by external input.

    For each snippet in ``call_sites`` the function ast-parses the source and
    inspects every ``ast.Call`` whose callee bare-name or dotted tail equals
    ``sink_name`` (or its dotted tail). If any such matched call receives an
    argument that is not a literal constant, the site is recorded once (in input
    order, de-duplicated) and the sink is deemed reachable.

    Returns a fixed-shape dict::

        {reachable, external_input_sites, all_constant, status, may_confirm}

    with derived invariants ``status == 'reachable'`` iff ``reachable`` else
    ``'constant_only'``, ``may_confirm == reachable`` and
    ``all_constant == (not reachable)``.
    """
    tail = _sink_tail(sink_name)
    external_input_sites: List[str] = []
    seen = set()
    for snippet in call_sites:
        if snippet in seen:
            continue
        if _site_has_external_arg(snippet, tail):
            external_input_sites.append(snippet)
            seen.add(snippet)
    reachable = bool(external_input_sites)
    all_constant = not reachable
    status = 'reachable' if reachable else 'constant_only'
    may_confirm = reachable
    return {'reachable': reachable, 'external_input_sites': external_input_sites, 'all_constant': all_constant, 'status': status, 'may_confirm': may_confirm}