import ast
import pytest
from harness.git_integration import _ast_merge

def _alias_names(merged_src: str) -> list[str]:
    tree = ast.parse(merged_src)
    names: list[str] = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names.extend((alias.name for alias in node.names))
    return names

def _import_from_entries(merged_src: str) -> list[tuple[str, int, str, str | None]]:
    tree = ast.parse(merged_src)
    entries: list[tuple[str, int, str, str | None]] = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ''
            level = node.level or 0
            for alias in node.names:
                entries.append((module, level, alias.name, alias.asname))
    return entries

def test_target_only_importfrom_preserved():
    target_src = 'from tools import webui_auth\nfrom tools import webui_control\n'
    agent_src = 'from tools import webui_control\n'
    merged_src = _ast_merge(agent_src, target_src)
    names = _alias_names(merged_src)
    assert 'webui_auth' in names
    assert 'webui_control' in names
    assert names.count('webui_control') == 1

def test_agent_importfrom_added():
    target_src = 'from x import a\n'
    agent_src = 'from x import a\nfrom x import b\n'
    merged_src = _ast_merge(agent_src, target_src)
    entries = _import_from_entries(merged_src)
    bound = [(mod, lvl, name) for mod, lvl, name, _as in entries]
    assert ('x', 0, 'a') in bound
    assert ('x', 0, 'b') in bound

def test_no_duplicate_importfrom_when_overlap():
    target_src = 'from x import a\n'
    agent_src = 'from x import a\n'
    merged_src = _ast_merge(agent_src, target_src)
    entries = _import_from_entries(merged_src)
    a_entries = [(mod, lvl, name) for mod, lvl, name, _as in entries if mod == 'x' and name == 'a']
    assert len(a_entries) == 1

def test_per_name_dedup_with_multiname_node():
    target_src = 'from x import a, b\n'
    agent_src = 'from x import b, c\n'
    merged_src = _ast_merge(agent_src, target_src)
    names = _alias_names(merged_src)
    assert names.count('a') == 1
    assert names.count('b') == 1
    assert names.count('c') == 1

def test_relative_import_level_distinct():
    target_src = 'from . import foo\n'
    agent_src = 'from .. import foo\n'
    merged_src = _ast_merge(agent_src, target_src)
    entries = _import_from_entries(merged_src)
    levels = sorted({lvl for _mod, lvl, name, _as in entries if name == 'foo'})
    assert 1 in levels
    assert 2 in levels

def test_aliased_import_keyed_on_asname():
    target_src = 'from x import y\n'
    agent_src = 'from x import y as z\n'
    merged_src = _ast_merge(agent_src, target_src)
    entries = _import_from_entries(merged_src)
    bound = {(mod, name, asname) for mod, _lvl, name, asname in entries}
    assert ('x', 'y', None) in bound
    assert ('x', 'y', 'z') in bound

def test_top_level_import_per_name_dedup():
    target_src = 'import os\nimport sys\n'
    agent_src = 'import os\nimport json\n'
    merged_src = _ast_merge(agent_src, target_src)
    names = _alias_names(merged_src)
    assert names.count('os') == 1
    assert names.count('sys') == 1
    assert names.count('json') == 1