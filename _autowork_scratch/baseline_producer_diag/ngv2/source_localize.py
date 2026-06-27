"""Deterministic, stdlib-only TAINT-SOURCE localization.

This module analyzes a python source file to classify the kind of taint source
at a specific line, returning metadata needed to drive a PoC.
"""
from __future__ import annotations
import ast
from typing import Any, Dict, List, Optional, Set, Tuple
_UNKNOWN: Dict[str, Any] = {'kind': 'unknown', 'framework': '', 'route_path': '', 'http_method': '', 'param_name': '', 'app_object': '', 'app_factory': '', 'symbol': '', 'confidence': 'unknown'}

def _dotted_name(func: ast.AST) -> str:
    """Dotted call name for ast.Call.func."""
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

def _attach(node: ast.AST, func: Optional[ast.AST]=None, enclosing: Optional[Dict[int, ast.AST]]=None) -> Dict[int, ast.AST]:
    """Recursively builds id(node) -> enclosing FunctionDef/AsyncFunctionDef map."""
    if enclosing is None:
        enclosing = {}
    for child in ast.iter_child_nodes(node):
        enclosing[id(child)] = func
        nf = child if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else func
        _attach(child, nf, enclosing)
    return enclosing

def _param_names(fnode: ast.AST) -> Set[str]:
    """Extracts all parameter names from a FunctionDef/AsyncFunctionDef."""
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

def _first_fastapi_param(fnode: ast.AST) -> str:
    """Extracts the first non-self/non-request parameter name for FastAPI."""
    args = getattr(fnode, 'args', None)
    if args is None:
        return ''
    for group in (getattr(args, 'posonlyargs', []) or [], args.args or [], args.kwonlyargs or []):
        for a in group:
            if a.arg not in ('self', 'cls', 'request'):
                return a.arg
    return ''

def _get_attr_chain(node: ast.AST) -> Optional[List[str]]:
    """Resolves attribute chains, e.g. request.args."""
    parts: List[str] = []
    curr = node
    while isinstance(curr, ast.Attribute):
        parts.append(curr.attr)
        curr = curr.value
    if isinstance(curr, ast.Name):
        parts.append(curr.id)
        return list(reversed(parts))
    return None

def _names_in_expr(node: ast.AST) -> Set[str]:
    """All bare Name ids referenced anywhere under node."""
    out: Set[str] = set()
    if node is None:
        return out
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            out.add(child.id)
    return out

def _extract_subscript_slice_value(node: ast.Subscript) -> str:
    """Extracts string value from subscript slice."""
    sl = node.slice
    if isinstance(sl, ast.Constant):
        return str(sl.value)
    if isinstance(sl, ast.Index):
        if isinstance(sl.value, ast.Constant):
            return str(sl.value.value)
        elif isinstance(sl.value, ast.Str):
            return str(sl.value.s)
    if isinstance(sl, ast.Str):
        return str(sl.s)
    return ''

def _extract_call_first_arg_str(node: ast.Call) -> str:
    """Extracts string value from first argument of a Call."""
    if node.args:
        arg = node.args[0]
        if isinstance(arg, ast.Constant):
            return str(arg.value)
        elif isinstance(arg, ast.Str):
            return str(arg.s)
    return ''

def _extract_deser_param(node: ast.Call) -> str:
    """Extracts bare Name arg from a deser call."""
    if node.args:
        arg = node.args[0]
        if isinstance(arg, ast.Name):
            return arg.id
    return ''

def _has_web_route_decorator(fnode: ast.AST) -> bool:
    """True if fnode has a web route decorator (flask/fastapi)."""
    if not isinstance(fnode, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return False
    for dec in getattr(fnode, 'decorator_list', []):
        dec_func = dec.func if isinstance(dec, ast.Call) else dec
        droot = _dotted_name(dec_func)
        if droot:
            _, _, verb = droot.rpartition('.')
            if verb in {'route', 'get', 'post', 'put', 'delete', 'patch'}:
                return True
    return False

def _find_app_factory(tree: ast.AST, enclosing: Dict[int, ast.AST]) -> Dict[str, str]:
    """Maps app_object -> app_factory enclosing function name."""
    app_factories: Dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            val = node.value
            if isinstance(val, ast.Call):
                dotted = _dotted_name(val.func)
                if dotted in {'Flask', 'flask.Flask', 'FastAPI', 'fastapi.FastAPI'}:
                    f = enclosing.get(id(val))
                    if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        for target in node.targets:
                            if isinstance(target, ast.Name):
                                app_factories[target.id] = f.name
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            val = node.value
            if isinstance(val, ast.Call):
                dotted = _dotted_name(val.func)
                if dotted in {'Flask', 'flask.Flask', 'FastAPI', 'fastapi.FastAPI'}:
                    f = enclosing.get(id(val))
                    if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if isinstance(node.target, ast.Name):
                            app_factories[node.target.id] = f.name
    return app_factories

def _get_node_source_type(node: ast.AST, fnode: Optional[ast.AST], params: Set[str]) -> str:
    """Classifies source kind for a candidate node."""
    if fnode is not None:
        if _has_web_route_decorator(fnode):
            return 'http'
        args = getattr(fnode, 'args', None)
        if args and args.args and (args.args[0].arg == 'request'):
            chain = None
            if isinstance(node, ast.Subscript):
                chain = _get_attr_chain(node.value)
            elif isinstance(node, ast.Call):
                chain = _get_attr_chain(node.func)
            elif isinstance(node, ast.Attribute):
                chain = _get_attr_chain(node)
            if chain and len(chain) >= 2 and (chain[0] == 'request') and (chain[1] in {'GET', 'POST'}):
                return 'http'
    if isinstance(node, ast.Subscript):
        chain = _get_attr_chain(node.value)
        if chain and len(chain) >= 2 and (chain[0] == 'request') and (chain[1] in {'args', 'form', 'values', 'json', 'GET', 'POST', 'files', 'headers', 'cookies'}):
            return 'http'
    elif isinstance(node, ast.Call):
        chain = _get_attr_chain(node.func)
        if chain and len(chain) >= 3 and (chain[0] == 'request') and (chain[1] in {'args', 'form', 'values', 'json', 'GET', 'POST', 'files', 'headers', 'cookies'}) and (chain[2] == 'get'):
            return 'http'
    elif isinstance(node, ast.Attribute):
        chain = _get_attr_chain(node)
        if chain and len(chain) >= 2 and (chain[0] == 'request') and (chain[1] in {'args', 'form', 'values', 'json', 'GET', 'POST', 'files', 'headers', 'cookies'}):
            return 'http'
    if isinstance(node, ast.Subscript):
        chain = _get_attr_chain(node.value)
        if chain == ['sys', 'argv']:
            return 'cli'
    elif isinstance(node, ast.Call):
        dotted = _dotted_name(node.func)
        if dotted.startswith('click') or dotted.startswith('argparse') or dotted.endswith('parse_args') or dotted.endswith('add_argument') or dotted.endswith('parse_known_args'):
            return 'cli'
    if isinstance(node, ast.Subscript):
        chain = _get_attr_chain(node.value)
        if chain == ['os', 'environ']:
            return 'env'
    elif isinstance(node, ast.Call):
        chain = _get_attr_chain(node.func)
        if chain == ['os', 'getenv'] or chain == ['os', 'environ', 'get']:
            return 'env'
    if isinstance(node, ast.Call):
        dotted = _dotted_name(node.func)
        if dotted in {'pickle.loads', 'pickle.load', 'yaml.load', 'yaml.unsafe_load', 'torch.load', 'joblib.load', 'marshal.loads', 'marshal.load'}:
            return 'deser'
    if isinstance(node, ast.Call):
        dotted = _dotted_name(node.func)
        if dotted in {'open', 'io.open', 'codecs.open'}:
            if node.args and fnode is not None:
                if _names_in_expr(node.args[0]) & params:
                    return 'file'
    return 'unknown'

def analyze_source(source: str, line: Optional[int]=None) -> Dict[str, Any]:
    if not isinstance(source, str) or not source.strip():
        return dict(_UNKNOWN)
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, TypeError, RecursionError):
        return dict(_UNKNOWN)
    enclosing = _attach(tree, None)
    candidates: List[Tuple[int, int, ast.AST]] = []
    for node in ast.walk(tree):
        is_cand = False
        if isinstance(node, ast.Subscript):
            chain = _get_attr_chain(node.value)
            if chain and len(chain) >= 2 and (chain[0] == 'request') and (chain[1] in {'args', 'form', 'values', 'json', 'GET', 'POST', 'files', 'headers', 'cookies'}):
                is_cand = True
            elif chain == ['os', 'environ']:
                is_cand = True
            elif chain == ['sys', 'argv']:
                is_cand = True
        elif isinstance(node, ast.Call):
            chain = _get_attr_chain(node.func)
            if chain and len(chain) >= 3 and (chain[0] == 'request') and (chain[1] in {'args', 'form', 'values', 'json', 'GET', 'POST', 'files', 'headers', 'cookies'}) and (chain[2] == 'get'):
                is_cand = True
            elif chain == ['os', 'getenv']:
                is_cand = True
            elif chain == ['os', 'environ', 'get']:
                is_cand = True
            else:
                dotted = _dotted_name(node.func)
                if dotted in {'pickle.loads', 'pickle.load', 'yaml.load', 'yaml.unsafe_load', 'torch.load', 'joblib.load', 'marshal.loads', 'marshal.load'}:
                    is_cand = True
                elif dotted in {'open', 'io.open', 'codecs.open'}:
                    is_cand = True
                elif dotted.startswith('click') or dotted.startswith('argparse') or dotted.endswith('parse_args') or dotted.endswith('add_argument') or dotted.endswith('parse_known_args'):
                    is_cand = True
        elif isinstance(node, ast.Attribute):
            chain = _get_attr_chain(node)
            if chain and len(chain) >= 2 and (chain[0] == 'request') and (chain[1] in {'args', 'form', 'values', 'json', 'GET', 'POST', 'files', 'headers', 'cookies'}):
                is_cand = True
        if is_cand:
            ln = getattr(node, 'lineno', 0) or 0
            col = getattr(node, 'col_offset', 0) or 0
            candidates.append((ln, col, node))
    if not candidates:
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if _has_web_route_decorator(node):
                    ln = getattr(node, 'lineno', 0) or 0
                    col = getattr(node, 'col_offset', 0) or 0
                    candidates.append((ln, col, node))
    if not candidates:
        return dict(_UNKNOWN)
    try:
        target_line = int(line) if line is not None else 0
    except (TypeError, ValueError):
        target_line = 0

    def _node_priority(n: ast.AST) -> int:
        if isinstance(n, (ast.Subscript, ast.Call)):
            return 0
        if isinstance(n, ast.Attribute):
            return 1
        return 2
    chosen = min(candidates, key=lambda t: (abs(t[0] - target_line), t[0], t[1], _node_priority(t[2])))
    chosen_node = chosen[2]
    if isinstance(chosen_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        fnode = chosen_node
    else:
        fnode = enclosing.get(id(chosen_node))
    symbol = fnode.name if fnode is not None else ''
    params = _param_names(fnode) if fnode is not None else set()
    framework = ''
    route_path = ''
    http_method = ''
    app_object = ''
    if fnode is not None:
        for dec in getattr(fnode, 'decorator_list', []):
            dec_func = dec.func if isinstance(dec, ast.Call) else dec
            droot = _dotted_name(dec_func)
            if not droot:
                continue
            head, _, verb = droot.rpartition('.')
            if verb in {'route', 'get', 'post', 'put', 'delete', 'patch'}:
                app_object = head
                framework = 'flask' if verb == 'route' else 'fastapi'
                if isinstance(dec, ast.Call) and dec.args:
                    first_arg = dec.args[0]
                    if isinstance(first_arg, ast.Constant):
                        route_path = str(first_arg.value)
                    elif isinstance(first_arg, ast.Str):
                        route_path = str(first_arg.s)
                if verb == 'route':
                    http_method = 'GET'
                    if isinstance(dec, ast.Call):
                        for kw in dec.keywords:
                            if kw.arg == 'methods' and isinstance(kw.value, (ast.List, ast.Tuple)):
                                methods_elts = kw.value.elts
                                if methods_elts:
                                    first_method = methods_elts[0]
                                    if isinstance(first_method, ast.Constant):
                                        http_method = str(first_method.value).upper()
                                    elif isinstance(first_method, ast.Str):
                                        http_method = str(first_method.s).upper()
                else:
                    http_method = verb.upper()
                break
    if framework == '' and fnode is not None:
        args = getattr(fnode, 'args', None)
        if args and args.args and (args.args[0].arg == 'request'):
            chain = None
            if isinstance(chosen_node, ast.Subscript):
                chain = _get_attr_chain(chosen_node.value)
            elif isinstance(chosen_node, ast.Call):
                chain = _get_attr_chain(chosen_node.func)
            elif isinstance(chosen_node, ast.Attribute):
                chain = _get_attr_chain(chosen_node)
            if chain and len(chain) >= 2 and (chain[0] == 'request') and (chain[1] in {'GET', 'POST'}):
                framework = 'django'
                http_method = chain[1]
    app_factory = ''
    if framework in {'flask', 'fastapi'} and app_object:
        app_factories = _find_app_factory(tree, enclosing)
        app_factory = app_factories.get(app_object, '')
    param_name = ''
    if framework == 'fastapi' and fnode is not None:
        param_name = _first_fastapi_param(fnode)
    elif isinstance(chosen_node, ast.Subscript):
        chain = _get_attr_chain(chosen_node.value)
        if chain and len(chain) >= 2 and (chain[0] == 'request') and (chain[1] in {'args', 'form', 'values', 'json', 'GET', 'POST', 'files', 'headers', 'cookies'}):
            param_name = _extract_subscript_slice_value(chosen_node)
        elif chain == ['os', 'environ']:
            param_name = _extract_subscript_slice_value(chosen_node)
    elif isinstance(chosen_node, ast.Call):
        chain = _get_attr_chain(chosen_node.func)
        if chain and len(chain) >= 3 and (chain[0] == 'request') and (chain[1] in {'args', 'form', 'values', 'json', 'GET', 'POST', 'files', 'headers', 'cookies'}) and (chain[2] == 'get'):
            param_name = _extract_call_first_arg_str(chosen_node)
        elif chain == ['os', 'getenv']:
            param_name = _extract_call_first_arg_str(chosen_node)
        elif chain == ['os', 'environ', 'get']:
            param_name = _extract_call_first_arg_str(chosen_node)
        else:
            dotted = _dotted_name(chosen_node.func)
            if dotted in {'pickle.loads', 'pickle.load', 'yaml.load', 'yaml.unsafe_load', 'torch.load', 'joblib.load', 'marshal.loads', 'marshal.load'}:
                param_name = _extract_deser_param(chosen_node)
            elif dotted in {'open', 'io.open', 'codecs.open'}:
                if chosen_node.args and fnode is not None:
                    names = _names_in_expr(chosen_node.args[0]) & params
                    if names:
                        param_name = sorted(list(names))[0]
    kind = _get_node_source_type(chosen_node, fnode, params)
    if kind == 'unknown' or fnode is None:
        confidence = 'unknown'
    elif param_name or route_path or kind == 'cli':
        confidence = 'high'
    else:
        confidence = 'low'
    return {'kind': kind, 'framework': framework, 'route_path': route_path, 'http_method': http_method, 'param_name': param_name, 'app_object': app_object, 'app_factory': app_factory, 'symbol': symbol, 'confidence': confidence}

def localize_source(file_path: Any, line: Optional[int]=None) -> Dict[str, Any]:
    try:
        with open(file_path, 'r', errors='replace') as fh:
            source = fh.read()
    except Exception:
        return dict(_UNKNOWN)
    try:
        return analyze_source(source, line=line)
    except Exception:
        return dict(_UNKNOWN)