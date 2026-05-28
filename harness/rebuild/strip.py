from __future__ import annotations
import ast
from pathlib import Path
from harness.rebuild.target import TargetDescriptor

def _stripify(node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
    new_body: list[ast.stmt] = []
    doc = ast.get_docstring(node, clean=False)
    if doc is not None:
        new_body.append(ast.Expr(value=ast.Constant(value=doc)))
    new_body.append(ast.Raise(exc=ast.Name(id='NotImplementedError', ctx=ast.Load()), cause=None))
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
    if descriptor is None:
        raise TypeError('descriptor cannot be None')
    if isinstance(descriptor, (bool, int, float, complex, str, bytes, list, tuple, set, frozenset, dict)):
        raise TypeError(f'descriptor must be a TargetDescriptor-like object, got {type(descriptor).__name__}')
    for attr in ('source_root', 'output_dir', 'stash_dir', 'modules'):
        if not hasattr(descriptor, attr):
            raise TypeError(f"descriptor is missing required attribute '{attr}'")

    def _as_path(value: object, label: str) -> Path:
        if isinstance(value, bool) or not isinstance(value, (str, Path)):
            raise TypeError(f'{label} must be a path, got {type(value).__name__}')
        return Path(value)
    source_root = _as_path(descriptor.source_root, 'source_root')
    output_dir = _as_path(descriptor.output_dir, 'output_dir')
    stash_dir = _as_path(descriptor.stash_dir, 'stash_dir')

    def _as_str_list(value: object, label: str) -> list[str]:
        if value is None:
            return []
        if isinstance(value, (str, bytes)) or not hasattr(value, '__iter__'):
            raise TypeError(f'{label} must be an iterable of strings, got {type(value).__name__}')
        items: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise TypeError(f'{label} entries must be strings, got {type(item).__name__}')
            items.append(item)
        return items
    modules = _as_str_list(descriptor.modules, 'descriptor.modules')
    test_files = _as_str_list(getattr(descriptor, 'test_files', None), 'descriptor.test_files')
    seed_files = _as_str_list(getattr(descriptor, 'seed_files', None), 'descriptor.seed_files')
    output_dir.mkdir(parents=True, exist_ok=True)
    stash_dir.mkdir(parents=True, exist_ok=True)
    stash: dict[str, str] = {}
    for module_rel in modules:
        raw = (source_root / module_rel).read_bytes()
        original = raw.decode('utf-8')
        dst_path = output_dir / module_rel
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        dst_path.write_text(strip_source(original), encoding='utf-8')
        flat_name = module_rel.replace('/', '__').replace('\\', '__') + '.orig'
        stash_path = stash_dir / flat_name
        stash_path.write_bytes(raw)
        stash[module_rel] = str(stash_path)
    for rel in list(test_files) + list(seed_files):
        dst_path = output_dir / rel
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        dst_path.write_bytes((source_root / rel).read_bytes())
    return {'stash': stash, 'modules': modules, 'output_dir': str(output_dir)}