import ast
import pytest
from harness.git_integration import _ast_merge

def test_future_import_inserted_at_index_zero_no_main_guard():
    target = "def foo():\n    pass\n"
    output = "from __future__ import annotations\ndef foo():\n    pass\n"
    merged = _ast_merge(output, target)
    expected = "from __future__ import annotations\n\ndef foo():\n    pass"
    assert merged.strip() == expected.strip()

def test_future_import_inserted_at_index_zero_with_main_guard_increments_guard_idx():
    target = "def foo():\n    pass\n\nif __name__ == '__main__':\n    foo()\n"
    output = "from __future__ import annotations\n"
    merged = _ast_merge(output, target)
    # The __future__ import must land at index 0, and the main guard block is preserved.
    # New additions from out_nodes usually insert before the main guard, but __future__ should land at index 0.
    parsed = ast.parse(merged)
    assert isinstance(parsed.body[0], ast.ImportFrom)
    assert parsed.body[0].module == '__future__'
    # Verify main guard is the last node
    assert isinstance(parsed.body[-1], ast.If)

def test_multiple_future_imports_all_land_before_other_body_nodes():
    target = "def foo():\n    pass\n"
    output = "from __future__ import annotations\nfrom __future__ import division\n"
    merged = _ast_merge(output, target)
    parsed = ast.parse(merged)
    assert isinstance(parsed.body[0], ast.ImportFrom)
    assert parsed.body[0].module == '__future__'
    assert parsed.body[0].names[0].name == 'annotations'
    assert isinstance(parsed.body[1], ast.ImportFrom)
    assert parsed.body[1].module == '__future__'
    assert parsed.body[1].names[0].name == 'division'
    assert isinstance(parsed.body[2], ast.FunctionDef)
