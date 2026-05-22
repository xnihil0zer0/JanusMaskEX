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
    raise NotImplementedError

def recompose_function(header: str, segments: list[str]) -> str:
    """Reassemble a function from its header and body segments.

    Newline-join the header with every non-empty segment (skipping empty
    strings). With the segments produced by :func:`decompose_function_body`
    the result is AST-equivalent to the original function source.
    """
    raise NotImplementedError
'Large-body decomposition for the clean-room rebuild engine.\n\nSplit ONE oversized function into byte-budget-sized contiguous statement\nsegments, then stitch the header and segments back into an AST-equivalent\nfunction. Pure, stdlib-only helpers used by the reconstruct-oversized driver.\n'