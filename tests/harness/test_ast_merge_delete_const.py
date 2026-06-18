import ast
from harness.git_integration import _ast_merge

def _parse_helper(code_str: str) -> tuple[list[str], list[str]]:
    tree = ast.parse(code_str)
    assigned_const_names = []
    def_class_names = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            assigned_const_names.append(node.targets[0].id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            assigned_const_names.append(node.target.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            def_class_names.append(node.name)
    return (assigned_const_names, def_class_names)

def test_janusmask_delete_removes_top_level_constant_assign():
    output_code = '# JANUSMASK_DELETE: SOME_CONST\n'
    target_code = 'SOME_CONST = 123\nKEPT_CONST = 456\n'
    merged = _ast_merge(output_code, target_code)
    consts, defs = _parse_helper(merged)
    assert 'SOME_CONST' not in consts
    assert 'KEPT_CONST' in consts

def test_janusmask_delete_removes_top_level_constant_annassign():
    output_code = '# JANUSMASK_DELETE: SOME_CONST\n'
    target_code = 'SOME_CONST: int = 123\nKEPT_CONST: int = 456\n'
    merged = _ast_merge(output_code, target_code)
    consts, defs = _parse_helper(merged)
    assert 'SOME_CONST' not in consts
    assert 'KEPT_CONST' in consts

def test_function_delete_path_still_removes_def():
    output_code = '# JANUSMASK_DELETE: some_func\n'
    target_code = 'def some_func():\n    pass\n\ndef kept_func():\n    pass\n'
    merged = _ast_merge(output_code, target_code)
    consts, defs = _parse_helper(merged)
    assert 'some_func' not in defs
    assert 'kept_func' in defs

def test_non_targeted_constant_preserved_through_delete_merge():
    output_code = '# JANUSMASK_DELETE: SOME_CONST\n'
    target_code = 'SOME_CONST = 123\nKEEP_CONST = 7\n'
    merged = _ast_merge(output_code, target_code)
    consts, defs = _parse_helper(merged)
    assert 'KEEP_CONST' in consts

def test_function_delete_path_unweakened():
    output_code = '# JANUSMASK_DELETE: func_a\n# JANUSMASK_DELETE: func_b\n'
    target_code = 'def func_a():\n    return 1\n\nasync def func_b():\n    return 2\n\nclass ClassC:\n    pass\n\ndef func_d():\n    return 4\n'
    merged = _ast_merge(output_code, target_code)
    consts, defs = _parse_helper(merged)
    assert 'func_a' not in defs
    assert 'func_b' not in defs
    assert 'ClassC' in defs
    assert 'func_d' in defs

def test_non_targeted_constant_preserved():
    output_code = '# JANUSMASK_DELETE: UNRELATED\n'
    target_code = 'KEEP_CONST = 7\nSOME_VAL: str = "hello"\n'
    merged = _ast_merge(output_code, target_code)
    consts, defs = _parse_helper(merged)
    assert 'KEEP_CONST' in consts
    assert 'SOME_VAL' in consts