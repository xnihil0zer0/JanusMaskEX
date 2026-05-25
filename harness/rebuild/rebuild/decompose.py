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
    func = None
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func = node
            break
    if func is None:
        raise ValueError('no function definition found in func_source')
    lines = func_source.splitlines()
    body = func.body
    has_docstring = bool(body) and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str)
    real_stmts = body[1:] if has_docstring else body
    if has_docstring:
        header_end = body[0].end_lineno
    elif real_stmts:
        header_end = real_stmts[0].lineno - 1
    else:
        header_end = len(lines)
    header = '\n'.join(lines[:header_end])
    segments = []
    i = 0
    n = len(real_stmts)
    while i < n:
        run_start = real_stmts[i].lineno
        run_end = real_stmts[i].end_lineno
        j = i + 1
        while j < n:
            candidate_end = real_stmts[j].end_lineno
            candidate = '\n'.join(lines[run_start - 1:candidate_end])
            if len(candidate) <= budget:
                run_end = candidate_end
                j += 1
            else:
                break
        segments.append('\n'.join(lines[run_start - 1:run_end]))
        i = j
    return {'header': header, 'segments': segments}

def recompose_function(header: str, segments: list[str]) -> str:
    """Reassemble a function from its header and body segments.

    Newline-join the header with every non-empty segment (skipping empty
    strings). With the segments produced by :func:`decompose_function_body`
    the result is AST-equivalent to the original function source.
    """
    parts = [header]
    for seg in segments:
        if seg:
            parts.append(seg)
    return '\n'.join(parts)
'Large-body decomposition for the clean-room rebuild engine.\n\nSplit ONE oversized function into byte-budget-sized contiguous statement\nsegments, then stitch the header and segments back into an AST-equivalent\nfunction. Pure, stdlib-only helpers used by the reconstruct-oversized driver.\n'