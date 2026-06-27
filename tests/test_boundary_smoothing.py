import pytest
from hypothesis import given, strategies as st, settings
from typing import List, Dict, Any, Tuple, Optional
from harness.boundary_smoothing import get_leading_whitespace, detect_indentation, normalize_patch_indentation, unparse_decorator, get_line_states, find_end_line_lexical, parse_ast, parse_lexically, get_definitions, adjust_indentation, ensure_newline, find_best_match, is_leaf, get_child_indent, has_unmatched_ancestor, align_and_deduplicate_patches, smooth_boundaries, apply_with_sliding_retry

def test_verify_indentation_alignment():
    source_2_spaces = 'def foo():\n  pass\n'
    source_4_spaces = 'def foo():\n    pass\n'
    source_tabs = 'def foo():\n\tpass\n'
    assert detect_indentation(source_2_spaces) == (' ', 2)
    assert detect_indentation(source_4_spaces) == (' ', 4)
    assert detect_indentation(source_tabs) == ('\t', 1)
    patch_4_spaces = "def foo():\n    print('hello')\n    return 42\n"
    normalized = normalize_patch_indentation(source_2_spaces, patch_4_spaces)
    assert normalized == "def foo():\n  print('hello')\n  return 42\n"
    patch_2_spaces = "def foo():\n  print('hello')\n"
    normalized_tabs = normalize_patch_indentation(source_tabs, patch_2_spaces)
    assert normalized_tabs == "def foo():\n\tprint('hello')\n"

def test_verify_ast_identifier_matching():
    code = '\nclass OuterClass:\n    def method(self):\n        pass\n    class InnerClass:\n        def method(self):\n            pass\n'
    defs = parse_ast(code)
    assert defs is not None
    qualnames = {d['qualname']: d for d in defs}
    assert 'OuterClass' in qualnames
    assert 'OuterClass.method' in qualnames
    assert 'OuterClass.InnerClass' in qualnames
    assert 'OuterClass.InnerClass.method' in qualnames
    assert qualnames['OuterClass.InnerClass.method']['path'] == ['OuterClass', 'InnerClass', 'method']
    assert qualnames['OuterClass.InnerClass.method']['type'] == 'function'
    assert qualnames['OuterClass.InnerClass']['type'] == 'class'
    p_def = {'type': 'function', 'path': ['InnerClass', 'method']}
    match = find_best_match(p_def, defs)
    assert match is not None
    assert match['qualname'] == 'OuterClass.InnerClass.method'
    p_def_outer = {'type': 'function', 'path': ['OuterClass', 'method']}
    match_outer = find_best_match(p_def_outer, defs)
    assert match_outer is not None
    assert match_outer['qualname'] == 'OuterClass.method'

def test_verify_decorator_signature_parsing():
    code = '\n@register_state("active", priority=5)\n@custom_decorator\ndef my_function(x):\n    return x\n'
    defs = parse_ast(code)
    assert defs is not None
    func_def = next((d for d in defs if d['name'] == 'my_function'))
    assert len(func_def['decorators']) == 2
    assert func_def['decorators'][0] in ('@register_state("active", priority=5)', "@register_state('active', priority=5)")
    assert func_def['decorators'][1] == '@custom_decorator'
    lex_defs = parse_lexically(code)
    func_lex_def = next((d for d in lex_defs if d['name'] == 'my_function'))
    assert len(func_lex_def['decorators']) == 2
    assert func_lex_def['decorators'][0] in ('@register_state("active", priority=5)', "@register_state('active', priority=5)")
    assert func_lex_def['decorators'][1] == '@custom_decorator'

def test_verify_fallback_error_recovery():
    malformed_code = '\ndef broken_func(x, y\n    return x + y\n'
    assert parse_ast(malformed_code) is None
    defs = get_definitions(malformed_code)
    assert len(defs) == 1
    assert defs[0]['name'] == 'broken_func'
    assert defs[0]['type'] == 'function'

def test_verify_deduplication():
    source = '\ndef original_func():\n    return 1\n\ndef untouched_func():\n    return 2\n'
    patch = '\ndef original_func():\n    return 3\n'
    result = align_and_deduplicate_patches(source, patch)
    assert 'def original_func():' in result
    assert 'return 3' in result
    assert 'def untouched_func():' in result
    assert 'return 2' in result
    assert 'return 1' not in result
    assert result.count('def original_func():') == 1
    assert result.count('def untouched_func():') == 1

def test_verify_boundary_smoothing_integration():
    source = '\nimport sys\n\ndef first():\n    pass\n\nclass Worker:\n    def execute(self):\n        return "old"\n'
    patch = '\nimport os\nimport sys\n\ndef first():\n    print("new")\n\nclass Worker:\n    def execute(self):\n        return "new"\n\ndef extra_helper():\n    return True\n'
    result = align_and_deduplicate_patches(source, patch)
    assert 'import os' in result
    assert 'import sys' in result
    assert 'print("new")' in result
    assert 'return "new"' in result
    assert 'def extra_helper():' in result
    assert result.count('def first():') == 1
    assert result.count('class Worker:') == 1
    assert result.count('def execute(self):') == 1
    assert result.count('def extra_helper():') == 1

@given(src_style=st.sampled_from([(' ', 2), (' ', 3), (' ', 4), (' ', 8), ('\t', 1)]), patch_style=st.sampled_from([(' ', 2), (' ', 3), (' ', 4), (' ', 8), ('\t', 1)]))
@settings(deadline=None)
def test_verify_random_whitespace_indentation(src_style, patch_style):
    src_char, src_unit = src_style
    patch_char, patch_unit = patch_style
    src_indent = src_char * src_unit
    patch_indent = patch_char * patch_unit
    source = f'def foo():\n{src_indent}pass\n'
    patch = f'def foo():\n{patch_indent}pass\n'
    s_char, s_unit = detect_indentation(source)
    p_char, p_unit = detect_indentation(patch)
    assert s_char == src_char
    assert s_unit == src_unit
    assert p_char == patch_char
    assert p_unit == patch_unit
    normalized = normalize_patch_indentation(source, patch)
    assert normalized == f'def foo():\n{src_indent}pass\n'

def test_verify_malformed_ast_syntax_error_recovery():
    code = '\nclass OkClass:\n    def method(self):\n        pass\n\ndef broken(x)\n    pass\n\nclass AnotherOkClass:\n    def other_method(self):\n        pass\n'
    assert parse_ast(code) is None
    defs = parse_lexically(code)
    names = [d['name'] for d in defs]
    assert 'OkClass' in names
    assert 'method' in names
    assert 'broken' in names
    assert 'AnotherOkClass' in names
    assert 'other_method' in names

def test_verify_deeply_nested_decorators():
    code = '\n@decorator_one\nclass Top:\n    @decorator_two\n    class Mid:\n        @decorator_three\n        @decorator_four\n        def low_method(self):\n            pass\n'
    for parser in [parse_ast, parse_lexically]:
        defs = parser(code)
        assert defs is not None
        top_def = next((d for d in defs if d['name'] == 'Top'))
        mid_def = next((d for d in defs if d['name'] == 'Mid'))
        low_def = next((d for d in defs if d['name'] == 'low_method'))
        assert '@decorator_one' in top_def['decorators']
        assert '@decorator_two' in mid_def['decorators']
        assert '@decorator_three' in low_def['decorators']
        assert '@decorator_four' in low_def['decorators']

def test_verify_adjust_indentation_handling():
    lines = ['def foo():', '    pass']
    adjusted_positive = adjust_indentation(lines, 2, ' ')
    assert adjusted_positive == ['  def foo():', '      pass']
    adjusted_negative = adjust_indentation(lines, -2, ' ')
    assert adjusted_negative == ['def foo():', '  pass']
    assert adjust_indentation(lines, 0, ' ') == lines

def test_verify_empty_inputs_handling():
    assert align_and_deduplicate_patches('', 'def f(): pass') == 'def f(): pass'
    assert align_and_deduplicate_patches('def f(): pass', '') == 'def f(): pass'
    assert align_and_deduplicate_patches('   \n  ', 'def f(): pass') == 'def f(): pass'
    assert align_and_deduplicate_patches('def f(): pass', '   \n  ') == 'def f(): pass'

def test_verify_find_best_match_no_match():
    source_defs = [{'name': 'my_func', 'type': 'function', 'path': ['my_func']}]
    p_def_type_mismatch = {'name': 'my_func', 'type': 'class', 'path': ['my_func']}
    assert find_best_match(p_def_type_mismatch, source_defs) is None
    p_def_name_mismatch = {'name': 'other_func', 'type': 'function', 'path': ['other_func']}
    assert find_best_match(p_def_name_mismatch, source_defs) is None

def test_verify_sliding_retry_success():
    source = 'def dummy():\n    pass\n\ndef bar():\n    x = 1\n    y = 2\n\ndef dummy():\n    pass\n\ndef bar():\n    x = 1\n    y = (\n\ndef dummy():\n    pass\n'
    patch = 'def bar():\n    x = 1\n    y = 3\n'
    result = apply_with_sliding_retry(source, patch, 10)
    assert 'y = 3' in result
    assert 'y = 2' in result
    assert 'y = (' not in result

def test_verify_sliding_retry_top_bottom_boundaries():
    source_top = 'def foo():\n    x = (\n'
    patch_top = 'def foo():\n    x = 1\n'
    res_top = apply_with_sliding_retry(source_top, patch_top, 10)
    assert 'x = 1' in res_top
    source_bottom = 'def bar():\n    y = (\n'
    patch_bottom = 'def bar():\n    y = 2\n'
    res_bottom = apply_with_sliding_retry(source_bottom, patch_bottom, 10)
    assert 'y = 2' in res_bottom

def test_verify_comment_injection_rejection():
    source = 'def malicious_func():\n    pass\n'
    patch = "# def malicious_func():\n#     print('injected')\n"
    with pytest.raises(SyntaxError) as exc_info:
        apply_with_sliding_retry(source, patch, 5)
    assert 'Comment injection attempt detected' in str(exc_info.value)
    assert 'malicious_func' in str(exc_info.value)

def test_verify_formatting_false_positives():
    source = 'def dummy():\n    pass  # nominal preceding comment\n\ndef bar():\n    x = 1\n    y = 2\n\ndef dummy():\n    pass\n\ndef bar():\n    x = 1\n    y = (\n\ndef dummy():\n    pass\n'
    patch = 'def bar():\n    x = 1\n    y = 3\n'
    result = apply_with_sliding_retry(source, patch, 10)
    assert 'y = 3' in result

def test_verify_failed_compilation_fallback():
    source = 'def foo():\n    pass\n'
    patch = 'def foo():\n    x = (\n'
    with pytest.raises(SyntaxError):
        apply_with_sliding_retry(source, patch, 5)

def test_verify_sliding_retry_integration_success():
    source = 'import sys\n\ndef helper():\n    pass\n\nclass Calculator:\n    def add(self, a, b):\n        return a + b\n\ndef dummy():\n    pass\n\n# some extra comment\nclass Calculator:\n    def add(self, a, b):\n        return a + (  # syntax error here\n\ndef dummy():\n    pass\n'
    patch = 'class Calculator:\n    def add(self, a, b):\n        return a + b\n'
    result = apply_with_sliding_retry(source, patch, 10)
    assert 'return a + b' in result
    assert 'return a + (' not in result
    compile(result, '<string>', 'exec')

def test_verify_sliding_retry_integration_failure():
    source = 'class Calculator:\n    def add(self, a, b):\n        return a + b\n\nclass Calculator:\n    def add(self, a, b):\n        return a + (\n'
    patch = 'class Calculator:\n    def add(self, a, b):\n        return a + b\n'
    with pytest.raises(SyntaxError):
        apply_with_sliding_retry(source, patch, 1)

@given(num_comments=st.integers(min_value=0, max_value=10))
@settings(deadline=None)
def test_verify_random_line_offsets(num_comments):
    if num_comments > 0:
        comments = '\n'.join((f'# comment {i}' for i in range(num_comments))) + '\n'
    else:
        comments = ''
    source = f'def dummy():\n    pass\n\ndef bar():\n    x = 1\n    y = 2\n\ndef dummy():\n    pass\n{comments}def bar():\n    x = 1\n    y = (\n\ndef dummy():\n    pass\n'
    patch = 'def bar():\n    x = 1\n    y = 3\n'
    required_offset = 6 + num_comments
    if required_offset > 0:
        with pytest.raises(SyntaxError):
            apply_with_sliding_retry(source, patch, required_offset - 1)
    res = apply_with_sliding_retry(source, patch, required_offset)
    assert 'y = 3' in res
    assert 'y = (' not in res

@given(spaces=st.sampled_from(['  ', '    ', '\t']), newlines=st.sampled_from(['\n', '\n\n', '\r\n']), comment=st.sampled_from(['', '  # random comment\n', '# another comment\n']))
@settings(deadline=None)
def test_verify_random_noise_injections(spaces, newlines, comment):
    source = f'def foo():{newlines}{spaces}pass{newlines}'
    patch = f'{comment}def foo():{newlines}{spaces}print("hello"){newlines}'
    result = apply_with_sliding_retry(source, patch, 5)
    assert 'print("hello")' in result

def test_verify_comment_injection_vulnerability_regression():
    source = 'class Target:\n    pass\n'
    patch = '"""\nclass Target:\n    pass\n"""\n'
    with pytest.raises(SyntaxError) as exc_info:
        apply_with_sliding_retry(source, patch, 5)
    assert 'Comment injection attempt detected' in str(exc_info.value)
    assert 'Target' in str(exc_info.value)

def test_verify_spurious_formatting_rejections():
    source = "def dummy():\n    pass\n\ndef compute(data: List[int], mode: str = 'fast') -> Optional[Dict[str, Any]]:\n    return None\n\ndef dummy():\n    pass\n\ndef compute(data:List[int],mode:str='fast')->Optional[Dict[str,Any]]:\n    x = (\n\ndef dummy():\n    pass\n"
    patch = "def compute(data: List[int], mode: str = 'fast') -> Optional[Dict[str, Any]]:\n    return {'status': 'ok'}\n"
    result = apply_with_sliding_retry(source, patch, 10)
    assert "return {'status': 'ok'}" in result