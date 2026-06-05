"""Lazy-derived symbol / interface ledger.

This is a pure, read-derived helper.  It records the top-level signatures that
were *actually* committed by accepted tasks and resolves a downstream task's
``spec.interfaces`` prose against what upstream siblings really produced.

Design constraints (see task ``symbol-ledger-module``):

* Brand-new standalone module -- it edits no existing module and modifies no
  existing class method, and it lands entirely outside the
  ``_NEVER_AUTO_APPROVE`` deny-list.
* ``record_symbols`` re-reads ``state/impl_progress.jsonl`` and the referenced
  committed files on *every* call (lazy derivation); nothing is persisted or
  cached between calls.
* Signature extraction REUSES ``harness/ast_enforcer.py`` -- in particular its
  ``_extract_func_name_from_signature`` helper and the FunctionDef /
  AsyncFunctionDef handling -- rather than inventing a new parser.
* ``resolve_interfaces`` performs NO config-flag gating (the staging caller
  owns that) and returns its input UNCHANGED on any miss.
"""
from __future__ import annotations
import ast
import json
import re
from pathlib import Path
try:
    from harness import ast_enforcer as _ast_enforcer
except Exception:
    _ast_enforcer = None
__all__ = ['record_symbols', 'resolve_interfaces']

def _ledger_path(state_dir: Path) -> Path:
    """Locate the append-only progress ledger under ``state_dir``.

    The canonical layout is ``state_dir/state/impl_progress.jsonl``; we fall
    back to ``state_dir/impl_progress.jsonl`` if a flatter layout is in use.
    """
    primary = state_dir / 'state' / 'impl_progress.jsonl'
    if primary.exists():
        return primary
    alt = state_dir / 'impl_progress.jsonl'
    if alt.exists():
        return alt
    return primary

def _iter_accepted_rows(ledger: Path):
    """Yield accepted ``auto_commit`` rows from the ledger, in append order.

    Blank lines, malformed JSON, non-object rows, and an entirely absent ledger
    file are all tolerated -- they simply produce no rows.
    """
    try:
        text = ledger.read_text(encoding='utf-8')
    except OSError:
        return
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except (ValueError, TypeError):
            continue
        if not isinstance(row, dict):
            continue
        if row.get('phase') == 'accepted' and row.get('event') == 'auto_commit':
            yield row

def _signature_of(node) -> str:
    """Render the committed signature ``name(args) -> ret`` for a def node.

    The return-type is unparsed straight from the FunctionDef annotation, the
    same source the ast_enforcer reads.
    """
    args = ast.unparse(node.args)
    sig = f'{node.name}({args})'
    if node.returns is not None:
        sig += f' -> {ast.unparse(node.returns)}'
    return sig

def _name_of(signature: str, node) -> str:
    """Resolve the symbol name, reusing the ast_enforcer name primitive."""
    if _ast_enforcer is not None:
        extractor = getattr(_ast_enforcer, '_extract_func_name_from_signature', None)
        if extractor is not None:
            try:
                name = extractor(signature)
            except Exception:
                name = None
            if name:
                return name
    return node.name

def _extract_signatures(source: str) -> dict[str, str]:
    """Map top-level function/async-function names to committed signatures.

    A file that fails to parse yields nothing rather than raising.
    """
    out: dict[str, str] = {}
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return out
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            signature = _signature_of(node)
            out[_name_of(signature, node)] = signature
    return out

def record_symbols(state_dir: Path) -> dict[str, str]:
    """Derive top-level committed signatures from accepted ledger rows.

    Reads ``state/impl_progress.jsonl`` under ``state_dir`` at call time, keeps
    only rows with ``phase == "accepted"`` and ``event == "auto_commit"``,
    opens each referenced committed file (resolved relative to ``state_dir``),
    and extracts its top-level signatures.  The result is freshly derived on
    every call -- nothing is persisted or cached.  Duplicate names resolve to
    the last accepted row (ledger append order).
    """
    state_dir = Path(state_dir)
    ledger = _ledger_path(state_dir)
    mapping: dict[str, str] = {}
    for row in _iter_accepted_rows(ledger):
        files = row.get('files')
        if not isinstance(files, (list, tuple)):
            continue
        for rel in files:
            if not isinstance(rel, str) or not rel:
                continue
            path = Path(rel)
            if not path.is_absolute():
                path = state_dir / path
            try:
                if not path.is_file():
                    continue
                source = path.read_text(encoding='utf-8')
            except OSError:
                continue
            mapping.update(_extract_signatures(source))
    return mapping

def resolve_interfaces(interfaces_spec: str, state_dir: Path) -> str:
    """Rewrite ``interfaces_spec`` prose to committed signatures.

    For every symbol name resolvable from :func:`record_symbols`, occurrences
    of that bare name in ``interfaces_spec`` are rewritten to its committed
    signature.  On any miss -- empty mapping, missing/empty ledger, or no named
    symbol present in the prose -- the input is returned byte-for-byte
    unchanged.  No config-flag gating is performed here.
    """
    if not isinstance(interfaces_spec, str):
        return interfaces_spec
    mapping = record_symbols(Path(state_dir))
    if not mapping:
        return interfaces_spec
    names = [name for name in mapping if name]
    if not names:
        return interfaces_spec
    names.sort(key=len, reverse=True)
    pattern = re.compile('\\b(?:' + '|'.join((re.escape(n) for n in names)) + ')\\b')

    def _replace(match: re.Match) -> str:
        return mapping.get(match.group(0), match.group(0))
    return pattern.sub(_replace, interfaces_spec)