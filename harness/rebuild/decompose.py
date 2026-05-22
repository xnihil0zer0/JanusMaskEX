import ast
import ast

def decompose_function_body(func_source: str, budget: int) -> dict:
    """Split a single function's body into <= budget-sized statement segments.

    ``func_source`` is the exact source of ONE top-level function definition
    (optionally decorated/typed, optionally with a docstring). Returns a dict
    with 'header' (everything up to but not including the first non-docstring
    statement; a leading docstring stays in the header) and 'segments' (a list
    of contiguous runs of whole body statements at their original indentation,
    each run kept within ``budget`` except for a lone statement whose own
    source already exceeds it).
    """
    tree = ast.parse(func_source)
    func = next((node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))), None)
    if func is None:
        raise ValueError('no function definition found in source')
    lines = func_source.splitlines()
    body = func.body
    has_docstring = bool(body) and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str)
    statements = body[1:] if has_docstring else list(body)
    header_end = statements[0].lineno - 1 if statements else len(lines)
    header = '\n'.join(lines[:header_end])
    stmt_sources = ['\n'.join(lines[stmt.lineno - 1:stmt.end_lineno]) for stmt in statements]
    segments = []
    current = []
    current_len = 0
    for src in stmt_sources:
        if not current:
            current = [src]
            current_len = len(src)
            continue
        candidate_len = current_len + 1 + len(src)
        if candidate_len <= budget:
            current.append(src)
            current_len = candidate_len
        else:
            segments.append('\n'.join(current))
            current = [src]
            current_len = len(src)
    if current:
        segments.append('\n'.join(current))
    return {'header': header, 'segments': segments}

def recompose_function(header: str, segments: list[str]) -> str:
    """Reassemble a function from its header and body segments.

    Newline-join the header with every non-empty segment (skipping empty
    strings). With the segments produced by :func:`decompose_function_body`
    the result is AST-equivalent to the original function source.
    """
    parts = [header] + [s for s in segments if s]
    return '\n'.join(parts)
'Large-body decomposition for the clean-room rebuild engine.\n\nSplit ONE oversized function into byte-budget-sized contiguous statement\nsegments, then stitch the header and segments back into an AST-equivalent\nfunction. Pure, stdlib-only helpers used by the reconstruct-oversized driver.\n'