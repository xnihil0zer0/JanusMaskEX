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
    new_body: list[ast.stmt] = []
    doc = ast.get_docstring(node, clean=False)
    if doc is not None:
        new_body.append(ast.Expr(value=ast.Constant(value=doc)))
    new_body.append(
        ast.Raise(exc=ast.Name(id='NotImplementedError', ctx=ast.Load()), cause=None)
    )
    node.body = new_body


def strip_source(source: str) -> str:
    """Return a skeleton of ``source``: every function/method body removed.

    Top-level functions AND class methods are stripped to ``docstring + raise
    NotImplementedError``. Signatures, type hints, decorators, docstrings,
    module imports/constants, class bases/keywords, and class-level assignments
    are retained. Output is ``ast.unparse``'d, so it is normalized (comments
    dropped) but byte-stable for downstream merges.
    """
    tree = ast.parse(source)
    # Embedded pytest tests are preserved verbatim (not stripped): harvest
    # excludes them as units, so a stripped test body would never be rebuilt and
    # would linger as a permanent NotImplementedError stub. Keeping them intact
    # lets the in-module tests act as a behavioural pin in the rebuilt module.
    from harness.rebuild.harvest import _is_test_function, _is_pytest_class  # lazy: no cycle
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if _is_test_function(node.name):
                continue
            _stripify(node)
        elif isinstance(node, ast.ClassDef):
            method_defs = [
                sub for sub in node.body
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            if _is_pytest_class(node.name, method_defs):
                continue
            for sub in method_defs:
                _stripify(sub)
    return ast.unparse(tree)


def materialize_skeleton(descriptor: TargetDescriptor) -> dict:
    """Write the skeleton + verbatim tests/seeds; stash originals out-of-repo.

    Returns ``{'stash': {module_rel: stash_abs_path, ...},
    'modules': [...], 'output_dir': str}``.
    """
    out = descriptor.output_dir
    stash = descriptor.stash_dir
    out.mkdir(parents=True, exist_ok=True)
    stash.mkdir(parents=True, exist_ok=True)
    stash_map: dict[str, str] = {}
    for mod in descriptor.modules:
        src = (descriptor.source_root / mod).read_text(encoding='utf-8')
        skel = strip_source(src)
        dst = out / mod
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(skel, encoding='utf-8')
        stash_file = stash / (mod.replace('/', '__') + '.orig')
        stash_file.write_text(src, encoding='utf-8')
        stash_map[mod] = str(stash_file)
    for rel in list(descriptor.test_files) + list(descriptor.seed_files):
        src = (descriptor.source_root / rel).read_text(encoding='utf-8')
        dst = out / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(src, encoding='utf-8')
    return {'stash': stash_map, 'modules': list(descriptor.modules), 'output_dir': str(out)}
