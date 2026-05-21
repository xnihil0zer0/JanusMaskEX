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
    """Replace the body of *node* with a single ``raise NotImplementedError``.

    The function/method is mutated in place: every statement in its body is
    discarded except a leading docstring (if present), which is retained so the
    skeleton keeps its documentation. A ``raise NotImplementedError(...)`` is
    appended as the final (and possibly only) statement, turning the definition
    into a callable stub that errors when invoked.

    Returns ``None``; the mutation happens on *node* itself.
    """
    new_body: list[ast.stmt] = []
    if node.body:
        first = node.body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
            new_body.append(first)
    raise_stmt = ast.Raise(exc=ast.Call(func=ast.Name(id='NotImplementedError', ctx=ast.Load()), args=[], keywords=[]), cause=None)
    new_body.append(raise_stmt)
    node.body = new_body
    ast.fix_missing_locations(node)

def strip_source(source: str) -> str:
    """Return a skeleton of ``source``: every function/method body removed.

    Top-level functions AND class methods are stripped to ``docstring + raise
    NotImplementedError``. Signatures, type hints, decorators, docstrings,
    module imports/constants, class bases/keywords, and class-level assignments
    are retained. Output is ``ast.unparse``'d, so it is normalized (comments
    dropped) but byte-stable for downstream merges.
    """
    tree = ast.parse(source)

    def _process(body: list[ast.stmt]) -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                _stripify(node)
            elif isinstance(node, ast.ClassDef):
                _process(node.body)
    _process(tree.body)
    return ast.unparse(tree)

def materialize_skeleton(descriptor: TargetDescriptor) -> dict:
    """Write the skeleton + verbatim tests/seeds; stash originals out-of-repo.

    Returns ``{'stash': {module_rel: stash_abs_path, ...},
    'modules': [...], 'output_dir': str}``.
    """
    source_root = Path(descriptor.source_root)
    output_dir = Path(descriptor.output_dir)
    stash_dir = Path(descriptor.stash_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stash_dir.mkdir(parents=True, exist_ok=True)
    stash: dict[str, str] = {}
    for module_rel in descriptor.modules:
        raw = (source_root / module_rel).read_bytes()
        original = raw.decode('utf-8')
        dst_path = output_dir / module_rel
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        dst_path.write_text(strip_source(original), encoding='utf-8')
        flat_name = '__'.join(Path(module_rel).parts) + '.orig'
        stash_path = stash_dir / flat_name
        stash_path.write_bytes(raw)
        stash[module_rel] = str(stash_path)
    for rel in list(descriptor.test_files) + list(descriptor.seed_files):
        dst_path = output_dir / rel
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        dst_path.write_bytes((source_root / rel).read_bytes())
    return {'stash': stash, 'modules': list(descriptor.modules), 'output_dir': str(output_dir)}