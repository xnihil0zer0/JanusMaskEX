"""AST/file crossover for the autocompiler genetic loop.

This module composes child candidates out of two parents without ever
touching real git or invoking the real ``_ast_merge`` directly.  All
merge work is delegated through an *injected* seam so the production
wiring (``harness.git_integration._ast_merge``) and the test fakes share
one call path.
"""
from __future__ import annotations
import ast
from typing import Callable, Dict, Mapping
MergeSeam = Callable[[str, str], str]

def _is_valid_python(source: str) -> bool:
    """Return ``True`` when ``source`` parses as valid Python."""
    if not isinstance(source, str):
        return False
    try:
        ast.parse(source)
    except (SyntaxError, ValueError):
        return False
    return True

def ast_crossover(code_a: str, code_b: str, merge_seam: MergeSeam) -> str:
    """Compose ``code_a`` and ``code_b`` via the injected ``merge_seam``.

    The seam is responsible for the additive, non-overlapping symbol
    merge (production injects ``harness.git_integration._ast_merge``).  The
    seam is called exactly once with ``(code_a, code_b)``.  This function is
    fail-safe: if the seam raises, or returns something that is not valid
    Python source, ``code_a`` is returned unchanged.
    """
    try:
        merged = merge_seam(code_a, code_b)
    except Exception:
        return code_a
    if not _is_valid_python(merged):
        return code_a
    return merged

def file_crossover(files_a: Mapping[str, str], files_b: Mapping[str, str], fitness_a: Mapping[str, float], fitness_b: Mapping[str, float]) -> Dict[str, str]:
    """Pick per-file winners to build a child file-map.

    Files present on only one side are kept verbatim.  For files present on
    both sides the version from the higher-``score`` parent wins; a tie
    prefers side ``A``.  Pure and deterministic -- no git, no I/O.
    """
    score_a = float(fitness_a.get('score', 0.0))
    score_b = float(fitness_b.get('score', 0.0))
    b_wins = score_b > score_a
    child: Dict[str, str] = {}
    for path, content in files_a.items():
        child[path] = content
    for path, content in files_b.items():
        if path not in child or b_wins:
            child[path] = content
    return child