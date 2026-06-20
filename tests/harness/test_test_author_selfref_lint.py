"""Tests for the AST-based self-referential oracle assertion repair pass in harness/test_author.py."""
import ast
import pytest
from pathlib import Path
from harness.test_author import repair_selfref_assertions, author_oracle, GeneratedOracle

def test_repair_open_file_read() -> None:
    """Verify REPAIR: self-source read open(__file__).read() followed by assert '<LITERAL>' not in <src> is removed."""
    code = "def test_foo():\n    src = open(__file__).read()\n    assert 'some_literal_to_find' not in src\n    assert 1 + 1 == 2\n"
    repaired = repair_selfref_assertions(code)
    assert 'open(__file__)' not in repaired
    assert 'some_literal_to_find' not in repaired
    assert 'assert 1 + 1 == 2' in repaired
    ast.parse(repaired)

def test_preserve_hasattr() -> None:
    """Verify PRESERVE hasattr: assert not hasattr(mod, '<LITERAL>') checks are preserved."""
    code = "def test_foo():\n    import sys\n    mod = sys.modules[__name__]\n    assert not hasattr(mod, 'some_literal')\n    assert hasattr(mod, 'another')\n"
    repaired = repair_selfref_assertions(code)
    assert "hasattr(mod, 'some_literal')" in repaired or 'hasattr(mod, "some_literal")' in repaired
    assert "hasattr(mod, 'another')" in repaired or 'hasattr(mod, "another")' in repaired
    assert repaired.strip() == code.strip()

def test_clean_pass_through() -> None:
    """Verify CLEAN PASS-THROUGH: clean oracles are returned byte-identical."""
    code = 'def test_clean():\n    x = 1\n    assert x == 1\n'
    repaired = repair_selfref_assertions(code)
    assert repaired is code

def test_generality_arbitrary_literal_and_pathlib() -> None:
    """Verify GENERALITY: repair works for arbitrary literals and other read forms like Path(__file__).read_text()."""
    code = 'from pathlib import Path\ndef test_pathlib_read():\n    content = Path(__file__).read_text()\n    assert \'xyz_arbitrary_literal\' not in content\n    assert content.find(\'abc_arbitrary_literal\') == -1\n    assert content.find("other_lit") < 0\n'
    repaired = repair_selfref_assertions(code)
    assert 'Path(__file__).read_text()' not in repaired
    assert 'xyz_arbitrary_literal' not in repaired
    assert 'abc_arbitrary_literal' not in repaired
    assert 'other_lit' not in repaired
    ast.parse(repaired)

def test_non_self_source_preserved() -> None:
    """Verify NON-SELF SOURCE PRESERVED: assertions against non-self source are left intact."""
    code = "def test_other():\n    src = open('other_file.py').read()\n    assert 'secret_literal' not in src\n"
    repaired = repair_selfref_assertions(code)
    assert "open('other_file.py')" in repaired or 'open("other_file.py")' in repaired
    assert 'secret_literal' in repaired
    assert repaired is code

def test_end_to_end_regression_model() -> None:
    """Verify END-TO-END: test case modeled on live failure has self-source read/unsatisfiable assertions removed while keeping hasattr assertions."""
    code = "import sys\nimport inspect\nfrom pathlib import Path\n\ndef test_regression():\n    mod = sys.modules[__name__]\n    src = open(__file__).read()\n    assert not hasattr(mod, 'some_feature')\n    assert 'test_regression' not in src\n    assert 1 + 1 == 2\n"
    repaired = repair_selfref_assertions(code)
    assert "not hasattr(mod, 'some_feature')" in repaired or 'not hasattr(mod, "some_feature")' in repaired
    assert '1 + 1 == 2' in repaired
    assert 'open(__file__)' not in repaired
    assert 'not in src' not in repaired
    ast.parse(repaired)

def test_repair_nested_blocks_empty_padding() -> None:
    """Verify that removing assertions in nested blocks leaves them padded with ast.Pass()."""
    code = "def test_nested():\n    src = open(__file__).read()\n    if True:\n        assert 'test_nested' not in src\n    else:\n        assert 1 == 1\n"
    repaired = repair_selfref_assertions(code)
    assert 'if True:\n        pass' in repaired or 'if True:\n    pass' in repaired
    assert 'assert 1 == 1' in repaired
    ast.parse(repaired)

def test_repair_unused_bindings_scope() -> None:
    """Verify that removing assignments that become unused does not break other valid references, keeping them if used elsewhere."""
    code = "def test_used():\n    src = open(__file__).read()\n    assert 'test_used' not in src\n    print(src)\n"
    repaired = repair_selfref_assertions(code)
    assert 'open(__file__)' in repaired
    assert 'print(src)' in repaired
    assert 'not in src' not in repaired
    ast.parse(repaired)

def test_repair_syntax_error_fallback() -> None:
    """Verify that syntax errors during parsing are handled gracefully by returning original code."""
    code = "def test_invalid(\n    src = open(__file__).read()\n    assert 'foo' not in src\n"
    repaired = repair_selfref_assertions(code)
    assert repaired is code

def test_repair_multiple_read_calls() -> None:
    """Verify that multiple self-source reads in a single file are all successfully repaired."""
    code = "def test_multiple():\n    src1 = open(__file__).read()\n    src2 = Path(__file__).read_text()\n    assert 'test_multiple' not in src1\n    assert 'test_multiple' not in src2\n    assert 1 == 1\n"
    repaired = repair_selfref_assertions(code)
    assert 'src1' not in repaired
    assert 'src2' not in repaired
    assert '1 == 1' in repaired
    ast.parse(repaired)

def test_repair_author_oracle_integration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that repair_selfref_assertions is wired into author_oracle review branch."""

    def mock_gen_fn(prompt: str, session_dir: Path, attempt: int) -> tuple[str, str]:
        return ("def test_mock():\n    src = open(__file__).read()\n    assert 'test_mock' not in src\n    assert 1 == 1\n", 'pytest')
    monkeypatch.setattr('harness.test_author.oracle_is_non_vacuous', lambda *a, **kw: True)
    monkeypatch.setattr('harness.test_author.run_oracle_against', lambda *a, **kw: True)
    monkeypatch.setattr('harness.test_author._reviewed_oracle_revalidates', lambda *a, **kw: True)
    config = {'test_author': {'review_pass': True}}
    oracle = author_oracle(target_module_name='dummy', target_source='def dummy(): pass', spec={}, config=config, state_dir=str(tmp_path), gen_fn=mock_gen_fn, max_attempts=1)
    assert 'open(__file__)' not in oracle.test_code
    assert 'assert 1 == 1' in oracle.test_code