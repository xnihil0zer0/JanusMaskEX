"""EVOLVE-BLOCK write-containment gate for the autocompiler.

Pure, stdlib-only module (uses only ``ast``/``tokenize`` and the standard
library -- no process spawn, no model, no network, no subprocess).

It exposes two functions:

``extract_evolve_ranges(src) -> list[tuple[int, int]]``
    A comment-tokenizer (mirroring the ``# JANUSMASK_DELETE:`` precedent at
    ``harness/git_integration.py:840-857``) that scans ``COMMENT`` tokens for
    paired ``# JM-EVOLVE-BLOCK-START`` / ``# JM-EVOLVE-BLOCK-END`` markers and
    returns the 1-based inclusive ``(start_line, end_line)`` ranges covering
    the lines *between* each marker pair.  Any malformed / unbalanced marker
    structure (open without close, close without open, un-pairable nesting) or
    source that fails to tokenize yields ``[]`` (fail-closed).

``check_write_containment(parent, cand, ranges) -> GateResult``
    A pure gate that parses both ``parent`` and ``cand`` with ``ast.parse`` and
    flags any AST node that is added/changed in the candidate whose source line
    falls outside every permitted range.  It returns
    ``GateResult(ok=True, ...)`` when every changed node lies fully inside a
    permitted range and ``GateResult(ok=False, reason=..., fix_hint=...)``
    otherwise.  It never raises (a parent/candidate that fails to parse is
    treated fail-closed as ``ok=False``).
"""
from __future__ import annotations
import ast
import io
import tokenize
try:
    from overseer.gates import GateResult
except Exception:
    from dataclasses import dataclass

    @dataclass
    class GateResult:
        """Minimal stand-in mirroring overseer.gates.GateResult(ok, reason, fix_hint)."""
        ok: bool
        reason: str = ''
        fix_hint: str = ''
_START_MARKER = '# JM-EVOLVE-BLOCK-START'
_END_MARKER = '# JM-EVOLVE-BLOCK-END'

def extract_evolve_ranges(src: str) -> list[tuple[int, int]]:
    """Return the EVOLVE-BLOCK line ranges parsed from ``src``.

    Scans only ``COMMENT`` tokens (so markers embedded inside string literals
    are ignored) for paired START/END markers and returns one inclusive
    ``(start_line, end_line)`` tuple per pair covering the lines strictly
    between the two marker comments.  Returns ``[]`` the moment any marker is
    unbalanced/malformed or the source cannot be tokenized.
    """
    try:
        readline = io.StringIO(src).readline
        tokens = list(tokenize.generate_tokens(readline))
    except (tokenize.TokenError, IndentationError, SyntaxError, ValueError):
        return []
    except Exception:
        return []
    ranges: list[tuple[int, int]] = []
    open_line: int | None = None
    for tok in tokens:
        if tok.type != tokenize.COMMENT:
            continue
        text = tok.string.strip()
        line = tok.start[0]
        if text == _START_MARKER:
            if open_line is not None:
                return []
            open_line = line
        elif text == _END_MARKER:
            if open_line is None:
                return []
            ranges.append((open_line + 1, line - 1))
            open_line = None
    if open_line is not None:
        return []
    return ranges

def _line_in_ranges(line: int, ranges: list[tuple[int, int]]) -> bool:
    for start, end in ranges:
        if start <= line <= end:
            return True
    return False

def _node_signatures(tree: ast.AST) -> dict[tuple, int]:
    """Multiset of *shallow* per-node signatures keyed by source location.

    Each signature captures a node's own type, location and primitive field
    values but deliberately excludes its child AST nodes, so that a change deep
    inside a container does not spuriously mark the (unchanged) container node
    itself as modified.  Nodes without a ``lineno`` (operators, contexts, the
    module root, ...) carry no location and are skipped.
    """
    sigs: dict[tuple, int] = {}
    for node in ast.walk(tree):
        lineno = getattr(node, 'lineno', None)
        if lineno is None:
            continue
        col = getattr(node, 'col_offset', 0)
        fields: list[tuple] = []
        for name, value in ast.iter_fields(node):
            if isinstance(value, ast.AST):
                continue
            if isinstance(value, list):
                if any((isinstance(v, ast.AST) for v in value)):
                    continue
                fields.append((name, tuple(value)))
            else:
                fields.append((name, value))
        sig = (lineno, col, type(node).__name__, tuple(fields))
        sigs[sig] = sigs.get(sig, 0) + 1
    return sigs

def check_write_containment(parent: str, cand: str, ranges: list[tuple[int, int]]) -> GateResult:
    """Gate a candidate edit against the permitted EVOLVE-BLOCK ranges.

    Returns ``GateResult(ok=True)`` when every AST node that is added or
    changed in ``cand`` relative to ``parent`` lies fully inside one of
    ``ranges``; returns ``GateResult(ok=False, ...)`` with a populated
    ``reason``/``fix_hint`` when any changed node falls outside every range.
    Identical sources pass trivially; a parent/candidate that fails to parse is
    rejected fail-closed.  Never raises.
    """
    if parent == cand:
        return GateResult(ok=True, reason='', fix_hint='')
    try:
        parent_tree = ast.parse(parent)
        cand_tree = ast.parse(cand)
    except (SyntaxError, ValueError):
        return GateResult(ok=False, reason='parent or candidate source failed to parse as Python AST', fix_hint='ensure both parent and candidate are syntactically valid Python before gating')
    except Exception:
        return GateResult(ok=False, reason='containment gate could not analyse the candidate', fix_hint='ensure both parent and candidate are syntactically valid Python before gating')
    parent_sigs = _node_signatures(parent_tree)
    cand_sigs = _node_signatures(cand_tree)
    violation_lines: set[int] = set()
    for sig, count in cand_sigs.items():
        if count - parent_sigs.get(sig, 0) > 0:
            lineno = sig[0]
            if not _line_in_ranges(lineno, ranges):
                violation_lines.add(lineno)
    if violation_lines:
        lines = sorted(violation_lines)
        return GateResult(ok=False, reason='candidate changes AST node(s) at line(s) %s outside the permitted EVOLVE-BLOCK ranges %s' % (lines, ranges), fix_hint='confine edits to lines inside the EVOLVE-BLOCK markers (permitted ranges: %s)' % (ranges,))
    return GateResult(ok=True, reason='', fix_hint='')