import ast
import importlib
import sys
import uuid
from pathlib import Path
import pytest
from harness.git_integration import _ast_merge

def _get_unique_mod_name(prefix: str='temp_mod') -> str:
    return f'{prefix}_{uuid.uuid4().hex}'

def check_importable(code_str: str, tmp_path: Path) -> None:
    module_name = _get_unique_mod_name()
    module_file = tmp_path / f'{module_name}.py'
    module_file.write_text(code_str, encoding='utf-8')
    orig_path = list(sys.path)
    orig_modules = set(sys.modules.keys())
    sys.path.insert(0, str(tmp_path))
    try:
        importlib.import_module(module_name)
    finally:
        sys.path = orig_path
        new_keys = set(sys.modules.keys()) - orig_modules
        for k in new_keys:
            if k.startswith(module_name) or module_name in k:
                sys.modules.pop(k, None)

def assert_import_raises_name_error(code_str: str, tmp_path: Path) -> None:
    module_name = _get_unique_mod_name()
    module_file = tmp_path / f'{module_name}.py'
    module_file.write_text(code_str, encoding='utf-8')
    orig_path = list(sys.path)
    orig_modules = set(sys.modules.keys())
    sys.path.insert(0, str(tmp_path))
    try:
        with pytest.raises(NameError):
            importlib.import_module(module_name)
    finally:
        sys.path = orig_path
        new_keys = set(sys.modules.keys()) - orig_modules
        for k in new_keys:
            if k.startswith(module_name) or module_name in k:
                sys.modules.pop(k, None)

def test_ast_merge_wiring():
    """Assert wiring and reachability of _ast_merge with its positional signature."""
    import inspect
    sig = inspect.signature(_ast_merge)
    assert len(sig.parameters) >= 2
    res = _ast_merge('a = 1', 'b = 2')
    assert isinstance(res, str)
    assert 'a = 1' in res or 'a=1' in res
    assert 'b = 2' in res or 'b=2' in res

def test_ast_merge_transitive_hazard(tmp_path: Path):
    """Assert a transitive forward-ordering hazard (e.g. REG = _build() and a newly-appended _NEW_TABLE) imports without NameError.
    Also verifies NameError is raised if the hazard is not resolved (unimportable code).
    """
    broken_code = '\ndef _build(table=_NEW_TABLE):\n    return table\n\nREG = _build()\n_NEW_TABLE = {}\n'
    assert_import_raises_name_error(broken_code, tmp_path)
    target_code = 'REG = _build()'
    output_code = '\n_NEW_TABLE = {}\ndef _build(table=_NEW_TABLE):\n    return table\n'
    merged = _ast_merge(output_code, target_code)
    check_importable(merged, tmp_path)
    broken_code_2 = '\n_build = lambda: _NEW_TABLE\nREG = _build()\n_NEW_TABLE = {}\n'
    assert_import_raises_name_error(broken_code_2, tmp_path)
    target_code_2 = 'REG = _build()'
    output_code_2 = '\n_NEW_TABLE = {}\n_build = lambda: _NEW_TABLE\n'
    merged_2 = _ast_merge(output_code_2, target_code_2)
    check_importable(merged_2, tmp_path)

def test_no_hazard_merge_stays_importable_and_stable(tmp_path: Path):
    """Assert negative control: no hazard stays importable and byte-stable."""
    target_code = 'x = 10\n'
    output_code = 'x = 20\ny = 30\n'
    merged = _ast_merge(output_code, target_code)
    check_importable(merged, tmp_path)
    merged_again = _ast_merge(output_code, merged)
    assert merged_again == merged
    merged_self = _ast_merge(merged, merged)
    assert merged_self == merged

def test_merge_output_is_deterministic():
    """Assert merged output is deterministic across multiple calls."""
    target_code = '\nclass Foo:\n    def bar(self):\n        pass\n\ndef func():\n    pass\n\nx = 1\n'
    output_code = '\nclass Foo:\n    def bar(self):\n        return 1\n    def new_method(self):\n        return 2\n\ndef func():\n    return 3\n\nx = 2\ny = 4\n'
    results = [_ast_merge(output_code, target_code) for _ in range(5)]
    first_result = results[0]
    for r in results[1:]:
        assert r == first_result

def test_ast_merge_class_body_recursive(tmp_path: Path):
    """Assert recursive merging of class bodies up to depth limits."""
    target_code = '\nclass Outer:\n    class Inner:\n        def existing_method(self):\n            return 1\n'
    output_code = '\nclass Outer:\n    class Inner:\n        def new_method(self):\n            return 2\n'
    merged = _ast_merge(output_code, target_code)
    check_importable(merged, tmp_path)
    tree = ast.parse(merged)
    outer_class = next((n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Outer'))
    inner_class = next((n for n in outer_class.body if isinstance(n, ast.ClassDef) and n.name == 'Inner'))
    method_names = {n.name for n in inner_class.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert 'existing_method' in method_names
    assert 'new_method' in method_names

def test_ast_merge_main_guard_positioning(tmp_path: Path):
    """Assert that __main__ guard block is preserved at the end and new nodes are inserted before it."""
    target_code = '\nx = 1\n\nif __name__ == \'__main__\':\n    print("main")\n'
    output_code = '\nx = 2\ndef new_func():\n    return 42\n'
    merged = _ast_merge(output_code, target_code)
    check_importable(merged, tmp_path)
    tree = ast.parse(merged)
    assert isinstance(tree.body[-1], ast.If)
    func_node = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'new_func'))
    assert tree.body.index(func_node) < len(tree.body) - 1

def test_ast_merge_delete_directive(tmp_path: Path):
    """Assert that JANUSMASK_DELETE comment directives delete the specified top-level nodes."""
    target_code = '\ndef to_delete():\n    pass\n\ndef keep_this():\n    pass\n'
    output_code = '\n# JANUSMASK_DELETE: to_delete\n'
    merged = _ast_merge(output_code, target_code)
    check_importable(merged, tmp_path)
    tree = ast.parse(merged)
    func_names = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert 'to_delete' not in func_names
    assert 'keep_this' in func_names