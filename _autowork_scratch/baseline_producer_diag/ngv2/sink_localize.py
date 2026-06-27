"""Deterministic, stdlib-only TAINT-FORWARDING sink localization.

This module answers a single question for a regex scanner hit (a line that
contains a dangerous call such as ``subprocess.Popen(...)``):

    "Is the ENCLOSING function a genuine, callable, taint-FORWARDING
    entrypoint for that sink -- i.e. does it pass its own parameters into
    the dangerous call -- or is the dangerous call fed only constants /
    module globals (e.g. a hardcoded Dockerfile template)?"

Why this exists
---------------
The empty-hunt fallback in :mod:`ngv2.hunt_lead_client` turns each
``pattern_scanner`` hit into an agy-shaped candidate and attaches the *enclosing
def name* as the callable entrypoint, regardless of whether that function
actually forwards attacker input into the sink. Downstream, ``poc_writer``'s
``default_resolver`` ranks that function first (its body mentions ``subprocess``)
and synthesizes ``from <module> import <func>; <func>(payload)`` -- which the
``poc_authenticity`` gate then correctly REJECTS because the payload never
reaches the sink (triton's ``create_dockerfile_linux`` is the canonical
example: it builds a Dockerfile *string* from literals and runs a fixed build
command; its parameters never touch the subprocess argv).

This helper performs a lightweight intra-procedural taint-forwarding analysis
over the containing FILE so candidates can point at genuinely exploitable,
parameter-forwarding entrypoints, and non-forwarding hits can be deprioritized
or dropped.

Contract
--------
:func:`localize_sink` ``(file_path, line, sink_token=None) -> dict`` returns a
dict with keys:

* ``symbol``     -- the enclosing function name, or ``''`` if module-level / unknown.
* ``forwarding`` -- bool: does the dangerous call reference an enclosing-function
                    parameter (directly or via simple local data-flow)?
* ``confidence`` -- one of ``'high'`` (forwarding entrypoint), ``'low'``
                    (enclosing function but NO forwarding), or ``'unknown'``
                    (no enclosing function / could not analyze).
* ``rank``       -- a small int for stable ordering: ``0`` high, ``1`` unknown,
                    ``2`` low. Lower sorts first.

Pure & fail-soft: no I/O beyond reading the cited file, no network, no clock,
no randomness, stdlib only. ANY parse/IO/analysis error returns the neutral
``unknown`` result (never raises) so callers can fall back to current behavior.
"""
from __future__ import annotations
import ast
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Set
__all__ = ['localize_sink', 'analyze_source', 'CONFIDENCE_RANK']
CONFIDENCE_RANK: Dict[str, int] = {'high': 0, 'unknown': 1, 'low': 2}
_SINK_TOKENS: Set[str] = {'os.system', 'os.popen', 'subprocess.popen', 'subprocess.call', 'subprocess.run', 'subprocess.check_output', 'subprocess.check_call', 'asyncio.create_subprocess_exec', 'asyncio.create_subprocess_shell', 'create_subprocess_exec', 'create_subprocess_shell', 'commands.getoutput', 'popen', 'system', 'eval', 'exec', 'execfile', 'compile', 'pickle.load', 'pickle.loads', 'cpickle.load', 'cpickle.loads', '_pickle.load', '_pickle.loads', 'marshal.load', 'marshal.loads', 'yaml.load', 'yaml.unsafe_load', 'yaml.full_load', 'torch.load', 'joblib.load', 'dill.load', 'dill.loads', 'load', 'loads', 'requests.get', 'requests.post', 'requests.put', 'requests.delete', 'requests.head', 'requests.patch', 'requests.request', 'urllib.request.urlopen', 'urllib2.urlopen', 'urlopen', 'httpx.get', 'httpx.post', 'httpx.client', 'aiohttp.clientsession', 'get', 'post', 'open', 'io.open', 'codecs.open', 'os.open', 'send_file', 'send_from_directory', 'shutil.copy', 'shutil.move', 'shutil.rmtree'}
_UNKNOWN: Dict[str, Any] = {'symbol': '', 'forwarding': False, 'confidence': 'unknown', 'rank': CONFIDENCE_RANK['unknown']}

def _result(symbol: str, forwarding: bool, confidence: str) -> Dict[str, Any]:
    return {'symbol': symbol, 'forwarding': bool(forwarding), 'confidence': confidence, 'rank': CONFIDENCE_RANK.get(confidence, CONFIDENCE_RANK['unknown'])}

def _dotted_name(func: ast.AST) -> str:
    """Dotted call name for ``ast.Call.func`` (e.g. ``subprocess.Popen``)."""
    parts: List[str] = []
    node = func
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    elif not parts:
        return ''
    return '.'.join(reversed(parts))

def _matches_sink(dotted: str, sink_token: Optional[str]) -> bool:
    """True if ``dotted`` is a known dangerous sink (optionally filtered by token)."""
    if not dotted:
        return False
    low = dotted.lower()
    tail = low.split('.')[-1]
    if sink_token:
        st = sink_token.strip().lower()
        st_tail = st.split('.')[-1]
        if st and (st == low or st_tail == tail or st in low or low.endswith('.' + st_tail)):
            return True
    return low in _SINK_TOKENS or tail in _SINK_TOKENS

def _names_in_expr(node: ast.AST) -> Set[str]:
    """All bare ``Name`` ids referenced anywhere under ``node`` (loads & roots).

    For attribute/subscript chains (``request.args['x']``) the ROOT name is
    captured because ``ast.walk`` reaches the underlying ``ast.Name``.
    """
    out: Set[str] = set()
    if node is None:
        return out
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            out.add(child.id)
    return out

def _collect_tainted(fnode: ast.AST, params: Set[str]) -> Set[str]:
    """Closure of names tainted by ``params`` via simple local assignments.

    Starts from the function parameters and grows: any local target whose value
    expression references an already-tainted name becomes tainted too. Iterated
    to a fixpoint so chains (``a = param; b = a + x``) propagate. f-strings,
    BinOp concatenation, ``.format``/``.join`` and subscript/attribute access of
    a tainted root are all covered because :func:`_names_in_expr` walks the whole
    value expression.
    """
    tainted: Set[str] = set(params)
    assigns: List[tuple] = []
    for child in ast.walk(fnode):
        if isinstance(child, ast.Assign):
            value = child.value
            targets: List[str] = []
            for tgt in child.targets:
                targets.extend(_assign_target_names(tgt))
            if targets:
                assigns.append((targets, value))
        elif isinstance(child, ast.AnnAssign) and child.value is not None:
            targets = _assign_target_names(child.target)
            if targets:
                assigns.append((targets, child.value))
        elif isinstance(child, (ast.AugAssign,)):
            targets = _assign_target_names(child.target)
            if targets:
                assigns.append((targets, child.value))
        elif isinstance(child, ast.NamedExpr):
            targets = _assign_target_names(child.target)
            if targets:
                assigns.append((targets, child.value))
    for _ in range(len(assigns) + 1):
        changed = False
        for targets, value in assigns:
            refs = _names_in_expr(value)
            if refs & tainted:
                for t in targets:
                    if t not in tainted:
                        tainted.add(t)
                        changed = True
        if not changed:
            break
    return tainted

def _assign_target_names(tgt: ast.AST) -> List[str]:
    out: List[str] = []
    if isinstance(tgt, ast.Name):
        out.append(tgt.id)
    elif isinstance(tgt, (ast.Tuple, ast.List)):
        for elt in tgt.elts:
            out.extend(_assign_target_names(elt))
    return out

def _param_names(fnode: ast.AST) -> Set[str]:
    out: Set[str] = set()
    args = getattr(fnode, 'args', None)
    if args is None:
        return out
    for group in (getattr(args, 'posonlyargs', []) or [], args.args or [], args.kwonlyargs or []):
        for a in group:
            if a.arg not in ('self', 'cls'):
                out.add(a.arg)
    if args.vararg is not None:
        out.add(args.vararg.arg)
    if args.kwarg is not None:
        out.add(args.kwarg.arg)
    return out

def _call_references(call: ast.Call, tainted: Set[str]) -> bool:
    """Does any positional/keyword arg of ``call`` reference a tainted name?"""
    if not tainted:
        return False
    for arg in call.args:
        if _names_in_expr(arg) & tainted:
            return True
    for kw in call.keywords:
        if kw.value is not None and _names_in_expr(kw.value) & tainted:
            return True
    return False

def analyze_source(source: str, line: Optional[int]=None, sink_token: Optional[str]=None) -> Dict[str, Any]:
    """Analyze already-read ``source`` (string). See :func:`localize_sink`."""
    if not isinstance(source, str) or not source.strip():
        return dict(_UNKNOWN)
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, TypeError, RecursionError):
        return dict(_UNKNOWN)
    enclosing: Dict[int, ast.AST] = {}

    def _attach(node: ast.AST, func: Optional[ast.AST]) -> None:
        for child in ast.iter_child_nodes(node):
            enclosing[id(child)] = func
            nf = child if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else func
            _attach(child, nf)
    _attach(tree, None)
    candidates: List[tuple] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            dotted = _dotted_name(node.func)
            if _matches_sink(dotted, sink_token):
                ln = getattr(node, 'lineno', 0) or 0
                col = getattr(node, 'col_offset', 0) or 0
                candidates.append((ln, col, node))
    if not candidates:
        return dict(_UNKNOWN)
    candidates.sort(key=lambda t: (t[0], t[1]))
    if line is not None:
        try:
            target_line = int(line)
        except (TypeError, ValueError):
            target_line = None
    else:
        target_line = None
    if target_line is not None:
        chosen = min(candidates, key=lambda t: (abs(t[0] - target_line), t[0], t[1]))
    else:
        chosen = candidates[0]
    call_node = chosen[2]
    fnode = enclosing.get(id(call_node))
    if not isinstance(fnode, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return _result('', False, 'unknown')
    params = _param_names(fnode)
    tainted = _collect_tainted(fnode, params)
    forwarding = _call_references(call_node, tainted)
    confidence = 'high' if forwarding else 'low'
    return _result(fnode.name, forwarding, confidence)

def localize_sink(file_path: Any, line: Optional[int]=None, sink_token: Optional[str]=None) -> Dict[str, Any]:
    """Taint-forwarding localization for a scanner hit.

    ``file_path`` is the path to the file containing the dangerous call.
    ``line`` (optional) is the hit line number to disambiguate when several
    sinks of the same kind exist. ``sink_token`` (optional) is the dangerous
    call token from the scanner/sink_extract (e.g. ``'subprocess.Popen'``) used
    to pick the right call when multiple sink kinds appear.

    Returns the localization dict (see module docstring). Never raises.
    """
    try:
        with open(file_path, 'r', errors='replace') as fh:
            source = fh.read()
    except Exception:
        return dict(_UNKNOWN)
    try:
        return analyze_source(source, line=line, sink_token=sink_token)
    except Exception:
        return dict(_UNKNOWN)