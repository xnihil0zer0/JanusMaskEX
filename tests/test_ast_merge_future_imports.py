import ast
import pytest
from harness.git_integration import _ast_merge

def test_future_import_inserted_at_index_zero_no_main_guard():
    target_code = "x = 1\ny = 2\n"
    output_code = "from __future__ import annotations\n"
    merged = _ast_merge(output_code, target_code)
    # Check that it compiles
    compile(merged, '<merged>', 'exec')
    # Parse and check AST structure
    tree = ast.parse(merged)
    assert isinstance(tree.body[0], ast.ImportFrom)
    assert tree.body[0].module == '__future__'
    assert tree.body[1].targets[0].id == 'x'

def test_future_import_inserted_at_index_zero_with_main_guard_increments_guard_idx():
    target_code = (
        "import sys\n"
        "if __name__ == '__main__':\n"
        "    sys.exit(0)\n"
    )
    output_code = (
        "from __future__ import annotations\n"
        "def helper(): pass\n"
    )
    merged = _ast_merge(output_code, target_code)
    compile(merged, '<merged>', 'exec')
    tree = ast.parse(merged)
    
    # Expected structure:
    # 0: from __future__ import annotations
    # 1: import sys
    # 2: def helper(): pass
    # 3: if __name__ == '__main__': ...
    assert isinstance(tree.body[0], ast.ImportFrom)
    assert tree.body[0].module == '__future__'
    assert isinstance(tree.body[1], ast.Import)
    assert isinstance(tree.body[2], ast.FunctionDef)
    assert tree.body[2].name == 'helper'
    assert isinstance(tree.body[3], ast.If)
    assert tree.body[3].test.left.id == '__name__'

def test_multiple_future_imports_all_land_before_other_body_nodes():
    target_code = "x = 1\n"
    output_code = "from __future__ import annotations\nfrom __future__ import division\n"
    merged = _ast_merge(output_code, target_code)
    compile(merged, '<merged>', 'exec')
    tree = ast.parse(merged)
    # Both must be at index 0 and 1
    assert isinstance(tree.body[0], ast.ImportFrom) and tree.body[0].module == '__future__'
    assert isinstance(tree.body[1], ast.ImportFrom) and tree.body[1].module == '__future__'
    assert isinstance(tree.body[2], ast.Assign)

def test_non_future_import_from_still_inserted_at_guard_idx():
    target_code = "import sys\nif __name__ == '__main__':\n    pass\n"
    output_code = "from typing import List\n"
    merged = _ast_merge(output_code, target_code)
    compile(merged, '<merged>', 'exec')
    tree = ast.parse(merged)
    # Expected: import sys -> from typing import List -> if __name__ == '__main__'
    assert isinstance(tree.body[0], ast.Import)
    assert isinstance(tree.body[1], ast.ImportFrom)
    assert tree.body[1].module == 'typing'
    assert isinstance(tree.body[2], ast.If)

def test_merged_source_with_future_import_compiles_without_syntax_error():
    target_code = "def foo():\n    pass\n"
    output_code = "from __future__ import annotations\n"
    merged = _ast_merge(output_code, target_code)
    # Compile will raise SyntaxError if __future__ is not first
    try:
        compile(merged, '<merged>', 'exec')
    except SyntaxError as e:
        pytest.fail(f"Compilation failed: {e}")

def test_ast_merge_submission_introduces_future_annotations_round_trip_compiles():
    target_code = (
        "import os\n"
        "if __name__ == '__main__':\n"
        "    print(os.getcwd())\n"
    )
    output_code = (
        "from __future__ import annotations\n"
        "def run(x: list[int]) -> None:\n"
        "    pass\n"
    )
    merged = _ast_merge(output_code, target_code)
    compile(merged, '<merged>', 'exec')
    tree = ast.parse(merged)
    # check that we have __future__ annotations at very top
    assert isinstance(tree.body[0], ast.ImportFrom) and tree.body[0].module == '__future__'

def test_ast_merge_no_future_import_behavior_unchanged_against_golden_output():
    target_code = "def foo():\n    return 1\n"
    output_code = "def bar():\n    return 2\n"
    merged = _ast_merge(output_code, target_code)
    # This should be identical to the old logic.
    # Old logic appends bar.
    expected = "def foo():\n    return 1\n\ndef bar():\n    return 2"
    assert ast.dump(ast.parse(merged)) == ast.dump(ast.parse(expected))

def test_future_imports_always_appear_before_any_non_future_statement_in_merged_body():
    target_code = "import os\nclass A:\n    pass\n"
    output_code = "from __future__ import annotations\nfrom __future__ import print_function\n"
    merged = _ast_merge(output_code, target_code)
    compile(merged, '<merged>', 'exec')
    tree = ast.parse(merged)
    # All __future__ imports must be at the very top of body
    future_seen_non_future = False
    for node in tree.body:
        is_future = isinstance(node, ast.ImportFrom) and node.module == '__future__'
        if is_future:
            assert not future_seen_non_future, "Found __future__ import after non-future statement"
        else:
            future_seen_non_future = True

def test_existing_future_import_in_target_not_duplicated_when_submission_repeats_it():
    target_code = "from __future__ import annotations\nx = 1\n"
    output_code = "from __future__ import annotations\n"
    merged = _ast_merge(output_code, target_code)
    compile(merged, '<merged>', 'exec')
    tree = ast.parse(merged)
    # Count of __future__ imports should be exactly 1
    futures = [node for node in tree.body if isinstance(node, ast.ImportFrom) and node.module == '__future__']
    assert len(futures) == 1

def test_class_body_merge_unaffected_by_future_import_handling():
    # Class body merging should not try to place any __future__ import at index 0 of module body
    # nor does a ClassDef body contain __future__ imports.
    # Target contains ClassDef A with some methods, agent defines A with other methods.
    target_code = "class A:\n    def foo(self):\n        pass\n"
    output_code = "class A:\n    def bar(self):\n        pass\n"
    merged = _ast_merge(output_code, target_code)
    compile(merged, '<merged>', 'exec')
    tree = ast.parse(merged)
    # A's body should contain foo and bar
    cls_a = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'A'][0]
    methods = {n.name for n in cls_a.body if isinstance(n, ast.FunctionDef)}
    assert 'foo' in methods
    assert 'bar' in methods

def test_future_import_and_docstring_ordering():
    target_code = '"""docstring"""\nx = 1\n'
    output_code = 'from __future__ import annotations\n'
    merged = _ast_merge(output_code, target_code)
    compile(merged, '<merged>', 'exec')
    tree = ast.parse(merged)
    # Expected structure: 
    # tree.body[0] is Docstring (Expr with Constant string)
    # tree.body[1] is ImportFrom (__future__ annotations)
    # tree.body[2] is Assign (x = 1)
    assert isinstance(tree.body[0], ast.Expr) and isinstance(tree.body[0].value, ast.Constant) and isinstance(tree.body[0].value.value, str)
    assert isinstance(tree.body[1], ast.ImportFrom) and tree.body[1].module == '__future__'
    assert isinstance(tree.body[2], ast.Assign)

def test_existing_future_import_preserved_if_not_in_output():
    target_code = 'from __future__ import division\nx = 1\n'
    output_code = 'from __future__ import annotations\n'
    merged = _ast_merge(output_code, target_code)
    compile(merged, '<merged>', 'exec')
    tree = ast.parse(merged)
    # Expected both division and annotations imports
    assert isinstance(tree.body[0], ast.ImportFrom) and tree.body[0].module == '__future__'
    assert isinstance(tree.body[1], ast.ImportFrom) and tree.body[1].module == '__future__'
    features = {tree.body[0].names[0].name, tree.body[1].names[0].name}
    assert features == {'division', 'annotations'}
    assert isinstance(tree.body[2], ast.Assign)


def test_target_duplicate_future_imports_deduplicated():
    target_code = "from __future__ import annotations\nfrom __future__ import annotations\nx = 1\n"
    output_code = "from __future__ import annotations\n"
    merged = _ast_merge(output_code, target_code)
    compile(merged, '<merged>', 'exec')
    tree = ast.parse(merged)
    # Count of __future__ imports should be exactly 1
    futures = [node for node in tree.body if isinstance(node, ast.ImportFrom) and node.module == '__future__']
    assert len(futures) == 1


def test_future_names_not_reordered_by_forward_reference_pass():
    target_code = "x = annotations\n"
    output_code = "from __future__ import annotations\n"
    merged = _ast_merge(output_code, target_code)
    compile(merged, '<merged>', 'exec')
    tree = ast.parse(merged)
    # Even though target uses 'annotations' at definition time,
    # the __future__ import must NOT be reordered to right before 'x = annotations'.
    # It must remain at the very top (index 0).
    assert isinstance(tree.body[0], ast.ImportFrom)
    assert tree.body[0].module == '__future__'
    assert isinstance(tree.body[1], ast.Assign)


