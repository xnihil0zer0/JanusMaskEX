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
    if not isinstance(source, str):
        raise TypeError('source must be a string')
    stripify_fn = globals().get('_stripify')
    if stripify_fn is None:

        def stripify_fn(node):
            new_body: list[ast.stmt] = []
            doc = ast.get_docstring(node, clean=False)
            if doc is not None:
                new_body.append(ast.Expr(value=ast.Constant(value=doc)))
            new_body.append(ast.Raise(exc=ast.Name(id='NotImplementedError', ctx=ast.Load()), cause=None))
            node.body = new_body
    tree = ast.parse(source)

    def _is_test_function(name: str) -> bool:
        return name.startswith('test_')

    def _is_pytest_class(name: str, method_defs: list) -> bool:
        return name.startswith('Test') and any((m.name.startswith('test') for m in method_defs))

    def process_body(body: list[ast.stmt]) -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if _is_test_function(node.name):
                    continue
                stripify_fn(node)
            elif isinstance(node, ast.ClassDef):
                method_defs = [sub for sub in node.body if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef))]
                if _is_pytest_class(node.name, method_defs):
                    continue
                process_body(node.body)
    process_body(tree.body)
    return ast.unparse(tree)

def materialize_skeleton(descriptor: TargetDescriptor) -> dict:
    """Write the skeleton + verbatim tests/seeds; stash originals out-of-repo.

    Returns ``{'stash': {module_rel: stash_abs_path, ...},
    'modules': [...], 'output_dir': str}``.
    """
    if descriptor is None:
        raise TypeError('descriptor cannot be None')
    if isinstance(descriptor, (int, float, str, bytes, bool, list, tuple, set, dict)):
        raise TypeError(f'Expected TargetDescriptor or namespace-like object, got {type(descriptor).__name__}')
    for attr in ('source_root', 'output_dir', 'stash_dir', 'modules'):
        if not hasattr(descriptor, attr):
            raise TypeError(f"descriptor is missing required attribute '{attr}'")
    for attr in ('source_root', 'output_dir', 'stash_dir'):
        val = getattr(descriptor, attr)
        if isinstance(val, bool) or not isinstance(val, (str, bytes, Path)):
            raise TypeError(f'Invalid type for {attr}: {type(val).__name__}')
    try:
        source_root = Path(descriptor.source_root).resolve()
    except (TypeError, ValueError) as e:
        raise TypeError(f'Invalid type for source_root: {e}')
    try:
        output_dir = Path(descriptor.output_dir).resolve()
    except (TypeError, ValueError) as e:
        raise TypeError(f'Invalid type for output_dir: {e}')
    try:
        stash_dir = Path(descriptor.stash_dir).resolve()
    except (TypeError, ValueError) as e:
        raise TypeError(f'Invalid type for stash_dir: {e}')
    modules_val = descriptor.modules
    if modules_val is None:
        raise TypeError('descriptor.modules cannot be None')
    if isinstance(modules_val, (str, bytes)):
        raise TypeError('descriptor.modules must not be a string or bytes')
    try:
        iter(modules_val)
    except TypeError as e:
        raise TypeError(f'descriptor.modules must be iterable: {e}')
    modules: list[str] = []
    for mod in modules_val:
        if not isinstance(mod, str):
            raise TypeError(f'Module path must be a string, got {type(mod).__name__}')
        modules.append(mod)
    test_files: list[str] = []
    if hasattr(descriptor, 'test_files'):
        test_files_val = descriptor.test_files
        if test_files_val is not None:
            if isinstance(test_files_val, (str, bytes)):
                raise TypeError('descriptor.test_files must not be a string or bytes')
            try:
                iter(test_files_val)
            except TypeError as e:
                raise TypeError(f'descriptor.test_files must be iterable: {e}')
            for t in test_files_val:
                if not isinstance(t, str):
                    raise TypeError(f'Test path must be a string, got {type(t).__name__}')
                test_files.append(t)
    seed_files: list[str] = []
    if hasattr(descriptor, 'seed_files'):
        seed_files_val = descriptor.seed_files
        if seed_files_val is not None:
            if isinstance(seed_files_val, (str, bytes)):
                raise TypeError('descriptor.seed_files must not be a string or bytes')
            try:
                iter(seed_files_val)
            except TypeError as e:
                raise TypeError(f'descriptor.seed_files must be iterable: {e}')
            for s in seed_files_val:
                if not isinstance(s, str):
                    raise TypeError(f'Seed path must be a string, got {type(s).__name__}')
                seed_files.append(s)
    output_dir.mkdir(parents=True, exist_ok=True)
    stash_dir.mkdir(parents=True, exist_ok=True)
    stash: dict[str, str] = {}
    for module_rel in modules:
        src_path = source_root / module_rel
        raw = src_path.read_bytes()
        original = raw.decode('utf-8')
        dst_path = output_dir / module_rel
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        dst_path.write_text(strip_source(original), encoding='utf-8')
        flat_name = module_rel.replace('/', '__').replace('\\', '__') + '.orig'
        stash_path = stash_dir / flat_name
        stash_path.parent.mkdir(parents=True, exist_ok=True)
        stash_path.write_bytes(raw)
        stash[module_rel] = str(stash_path.resolve())
    for rel in test_files + seed_files:
        dst_path = output_dir / rel
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        dst_path.write_bytes((source_root / rel).read_bytes())
    return {'stash': stash, 'modules': modules, 'output_dir': str(output_dir)}