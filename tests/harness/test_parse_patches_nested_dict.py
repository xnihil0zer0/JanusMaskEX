"""RED oracle for harness.git_integration._parse_patches nested-dict normalization.

Pins the DESIRED post-fix behavior: a nested-dict ``__JANUSMASK_PATCHES__``
source normalizes to a flat list of ``{'file','kind','name','code'}`` symbol
entries, while the existing flat-list form and the no/malformed-patches
None discipline are unchanged.

RED on HEAD: the nested-dict value is an ``ast.Dict`` (not an ``ast.List``),
so HEAD returns ``None`` for ``test_nested_dict_normalized``.
"""
from harness.git_integration import _parse_patches

def test_nested_dict_normalized():
    src = "\n__JANUSMASK_PATCHES__ = {\n    'pkg/mod.py': {'foo': 'def foo(): return 1', 'bar': 'def bar(): return 2'},\n    'tests/test_x.py': {'test_a': 'def test_a(): assert 1 == 1'},\n}\n"
    result = _parse_patches(src)
    assert isinstance(result, list)
    assert len(result) == 3
    for entry in result:
        assert 'file' in entry
        assert 'kind' in entry
        assert 'name' in entry
        assert 'code' in entry
        assert entry['kind'] == 'symbol'
    by_name = {entry['name']: entry for entry in result}
    assert set(by_name) == {'foo', 'bar', 'test_a'}
    assert by_name['foo']['file'] == 'pkg/mod.py'
    assert by_name['bar']['file'] == 'pkg/mod.py'
    assert by_name['test_a']['file'] == 'tests/test_x.py'
    assert 'return 1' in by_name['foo']['code']
    assert 'return 2' in by_name['bar']['code']
    assert 'assert' in by_name['test_a']['code']

def test_flat_list_unchanged():
    src = "\n__JANUSMASK_PATCHES__ = [\n    {'file': 'a.py', 'kind': 'symbol', 'name': 'foo', 'code': 'def foo(): return 2'},\n]\n"
    result = _parse_patches(src)
    assert isinstance(result, list)
    assert len(result) == 1
    entry = result[0]
    assert entry['file'] == 'a.py'
    assert entry['kind'] == 'symbol'
    assert entry['name'] == 'foo'
    assert 'return 2' in entry['code']

def test_no_patches_returns_none():
    assert _parse_patches('x = 1\n') is None
    assert _parse_patches("__JANUSMASK_MANIFEST__ = {'a.py': 'x = 1'}\n") is None
    assert _parse_patches('def (:::') is None
    malformed = "\n__JANUSMASK_PATCHES__ = {'pkg/mod.py': 'not a dict'}\n"
    assert _parse_patches(malformed) is None