"""STRIP: emit a skeleton (bodies -> NotImplementedError) + stash originals.

``strip_source`` replaces every top-level function body with its docstring
followed by ``raise NotImplementedError``, retaining the signature, type
hints, decorators, and all module-level imports/constants/classes. The
skeleton is the minimal seed: it parses and imports, but every call raises
until a body is reconstructed.

``materialize_skeleton`` writes the skeleton tree + verbatim test/seed files
into the output repo, and stashes the verbatim originals in a stash dir kept
OUTSIDE the output repo so the replicant never carries the answer key.
"""
from __future__ import annotations
import ast
from pathlib import Path
from harness.rebuild.target import TargetDescriptor

def _stripify(node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
    raise NotImplementedError

def strip_source(source: str) -> str:
    """Return a skeleton of ``source``: every function/method body removed.

    Top-level functions AND class methods are stripped to ``docstring + raise
    NotImplementedError``. Signatures, type hints, decorators, docstrings,
    module imports/constants, class bases/keywords, and class-level assignments
    are retained. Output is ``ast.unparse``'d, so it is normalized (comments
    dropped) but byte-stable for downstream merges.
    """
    raise NotImplementedError

def materialize_skeleton(descriptor: TargetDescriptor) -> dict:
    """Write the skeleton + verbatim tests/seeds; stash originals out-of-repo.

    Returns ``{'stash': {module_rel: stash_abs_path, ...},
    'modules': [...], 'output_dir': str}``.
    """
    raise NotImplementedError