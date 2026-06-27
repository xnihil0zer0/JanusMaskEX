"""Source-metadata ablation transform (ngv2/ablation.py, Epic A / LEAF A2).

Pure, stdlib-only (``ast`` + ``re``), string-in / string-out.  No file,
network, subprocess, or LLM access; fully deterministic.

Public surface
--------------
- :func:`ablate_source_code` -- strip module/class/function docstrings and
  all comments while preserving executable semantics.  Idempotent.
- :func:`obfuscate_pathnames` -- rewrite pathname string literals according
  to an injected ``file_map`` (old -> new), leaving everything else intact.
"""
from __future__ import annotations
import ast
import re
from typing import Dict, Match
__all__ = ['ablate_source_code', 'obfuscate_pathnames']
_DOCSTRING_HOSTS = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)

def _is_docstring_stmt(stmt: ast.stmt) -> bool:
    """Return True if ``stmt`` is a bare string-constant expression."""
    return isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str)

def _strip_docstrings(tree: ast.Module) -> ast.Module:
    """Remove leading docstrings from every docstring-hosting node.

    A function/class body that becomes empty is back-filled with ``pass`` so
    the regenerated source stays syntactically valid.  Module bodies may be
    empty, so no filler is needed there.
    """
    for node in ast.walk(tree):
        if not isinstance(node, _DOCSTRING_HOSTS):
            continue
        body = node.body
        if body and _is_docstring_stmt(body[0]):
            body.pop(0)
            if not body and (not isinstance(node, ast.Module)):
                filler = ast.Pass()
                body.append(filler)
    ast.fix_missing_locations(tree)
    return tree
_STRING_OR_COMMENT = re.compile('\n      (?P<string>\n          (?:[rbufRBUF]{0,3})\n          (?:\n                \'\'\'(?:\\\\.|[^\\\\])*?\'\'\'\n              | \\"\\"\\"(?:\\\\.|[^\\\\])*?\\"\\"\\"\n              | \'(?:\\\\.|[^\'\\\\\\n])*\'\n              | "(?:\\\\.|[^"\\\\\\n])*"\n          )\n      )\n    | (?P<comment>\\#[^\\n]*)\n    ', re.VERBOSE | re.DOTALL)

def _drop_comment(match: Match[str]) -> str:
    """Replacement callback: erase comments, keep string literals verbatim."""
    if match.group('comment') is not None:
        return ''
    return match.group('string')

def _strip_inline_comments(source: str) -> str:
    """Guarded regex pass that removes comments without touching strings."""
    return _STRING_OR_COMMENT.sub(_drop_comment, source)

def ablate_source_code(src: str) -> str:
    """Strip docstrings and comments, preserving executable semantics.

    The AST is re-emitted via :func:`ast.unparse` (which already drops
    comments), then a guarded regex pass runs as a defensive sweep.  The
    transform is idempotent: ``ablate_source_code(ablate_source_code(x))``
    equals ``ablate_source_code(x)``.
    """
    tree = ast.parse(src)
    _strip_docstrings(tree)
    regenerated = ast.unparse(tree)
    return _strip_inline_comments(regenerated)

def obfuscate_pathnames(src: str, file_map: Dict[str, str]) -> str:
    """Rewrite pathname literals appearing in ``src`` per ``file_map``.

    ``file_map`` maps an old pathname to its replacement.  Keys absent from
    ``src`` leave the source unchanged for that entry.  Longer keys are
    substituted first so a path that is a prefix of another is not partially
    rewritten.  The result is returned as a string and remains valid Python.
    """
    result = src
    for old_path, new_path in sorted(file_map.items(), key=lambda kv: len(kv[0]), reverse=True):
        result = result.replace(old_path, new_path)
    return result