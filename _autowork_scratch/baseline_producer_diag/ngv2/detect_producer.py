"""ngv2.detect_producer -- env-FSM detect PRODUCER implementation."""
import os
import re
import json
import hashlib
from typing import Any, Dict, List, Optional, Callable
PYTHON_BUILD_FILES = {'pyproject.toml', 'requirements.txt', 'requirements-dev.txt', 'setup.py', 'setup.cfg', 'Pipfile', '.python-version', 'runtime.txt'}
JS_BUILD_FILES = {'package.json'}
OTHER_BUILD_FILES = {'go.mod', 'Cargo.toml', 'Gemfile'}

def default_walk_fn(repo_root: str) -> List[tuple[str, str]]:
    """Default walk function to scan repository build and pin files."""
    SKIP_DIRS = {'.git', '.hg', '.svn', 'node_modules', '__pycache__', '.venv', 'venv', 'env', '.env', '.tox', '.mypy_cache', '.pytest_cache', 'build', 'dist', '.eggs', 'site-packages', '.cache'}
    build_and_pin_files = {'pyproject.toml', 'requirements.txt', 'requirements-dev.txt', 'setup.py', 'setup.cfg', 'Pipfile', '.python-version', 'runtime.txt', 'package.json'}
    results = []
    if not os.path.isdir(repo_root):
        return results
    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = sorted([d for d in dirnames if d not in SKIP_DIRS])
        for filename in sorted(filenames):
            if filename in build_and_pin_files:
                fullpath = os.path.join(dirpath, filename)
                relpath = os.path.relpath(fullpath, repo_root)
                relpath = relpath.replace('\\', '/')
                try:
                    with open(fullpath, 'r', encoding='utf-8', errors='replace') as f:
                        text = f.read()
                    results.append((relpath, text))
                except OSError:
                    pass
    return results

def parse_python_version_str(text: str) -> Optional[str]:
    """Extract python version from raw text."""
    match = re.search('\\b(2\\.\\d+|3\\.\\d+)(?:\\.\\d+)?\\b', text)
    if match:
        return match.group(1)
    match = re.search('\\b(\\d+\\.\\d+)\\b', text)
    if match:
        return match.group(1)
    return None

def parse_runtime_txt_version(text: str) -> Optional[str]:
    """Extract python version from runtime.txt format."""
    match = re.search('python-(\\d+\\.\\d+(?:\\.\\d+)?)', text, re.IGNORECASE)
    if match:
        parts = match.group(1).split('.')
        if len(parts) >= 2:
            return f'{parts[0]}.{parts[1]}'
    return parse_python_version_str(text)

def parse_pyproject_python_version(text: str) -> Optional[str]:
    """Extract python version from pyproject.toml format."""
    match = re.search('requires-python\\s*=\\s*["\\\']([^"\\\']+)["\\\']', text, re.IGNORECASE)
    if match:
        val = match.group(1)
        versions = re.findall('\\b\\d+\\.\\d+\\b', val)
        if versions:
            return versions[0]
    match = re.search('\\bpython\\s*=\\s*["\\\']([^"\\\']+)["\\\']', text, re.IGNORECASE)
    if match:
        val = match.group(1)
        versions = re.findall('\\b\\d+\\.\\d+\\b', val)
        if versions:
            return versions[0]
    return None

def parse_package_json_node_version(text: str) -> Optional[str]:
    """Extract node version from package.json engines block."""
    try:
        data = json.loads(text)
    except Exception:
        match = re.search('"node"\\s*:\\s*["\\\']([^"\\\']+)["\\\']', text)
        if match:
            val = match.group(1)
            ver_match = re.search('\\b(\\d+)\\b', val)
            if ver_match:
                return ver_match.group(1)
        return None
    if isinstance(data, dict):
        engines = data.get('engines')
        if isinstance(engines, dict):
            node_ver = engines.get('node')
            if isinstance(node_ver, str):
                match = re.search('\\b(\\d+)\\b', node_ver)
                if match:
                    return match.group(1)
    return None

def produce_detect_input(repo_root: str, pinned_commit: Optional[str]=None, *, walk_fn: Callable[[str], Any]=default_walk_fn, head_commit: Optional[str]=None, resolved_python_bin: Optional[str]=None, resolved_node_bin: Optional[str]=None) -> Dict[str, Any]:
    """Construct detect input by parsing build and pin files under repo_root."""
    files = list(walk_fn(repo_root))
    walk_dict = {}
    for relpath, text in files:
        basename = os.path.basename(relpath)
        walk_dict[basename] = text
    has_python = any((os.path.basename(r) in PYTHON_BUILD_FILES for r, _ in files))
    has_js = any((os.path.basename(r) in JS_BUILD_FILES for r, _ in files))
    if has_python and has_js:
        py_at_root = any((os.path.basename(r) in PYTHON_BUILD_FILES and '/' not in r.replace('\\', '/') for r, _ in files))
        js_at_root = any((os.path.basename(r) in JS_BUILD_FILES and '/' not in r.replace('\\', '/') for r, _ in files))
        if py_at_root and (not js_at_root):
            language = 'python'
        elif js_at_root and (not py_at_root):
            language = 'javascript'
        else:
            py_count = sum((1 for r, _ in files if os.path.basename(r) in PYTHON_BUILD_FILES))
            js_count = sum((1 for r, _ in files if os.path.basename(r) in JS_BUILD_FILES))
            if py_count >= js_count:
                language = 'python'
            else:
                language = 'javascript'
    elif has_python:
        language = 'python'
    elif has_js:
        language = 'javascript'
    else:
        has_other = any((os.path.basename(r) in OTHER_BUILD_FILES for r, _ in files))
        if has_other:
            language = None
        else:
            language = None
    build_files_list = []
    for relpath, _ in files:
        basename = os.path.basename(relpath)
        if language == 'python' and basename in PYTHON_BUILD_FILES:
            build_files_list.append(relpath)
        elif language == 'javascript' and basename in JS_BUILD_FILES:
            build_files_list.append(relpath)
        elif language is None and (basename in PYTHON_BUILD_FILES or basename in JS_BUILD_FILES or basename in OTHER_BUILD_FILES):
            build_files_list.append(relpath)
    build_files = sorted(list(set(build_files_list)))
    if pinned_commit is not None and head_commit is not None:
        final_pinned = pinned_commit
        final_head = head_commit
    elif pinned_commit is not None:
        final_pinned = pinned_commit
        final_head = pinned_commit
    elif head_commit is not None:
        final_pinned = head_commit
        final_head = head_commit
    else:
        hasher = hashlib.sha1()
        for relpath, text in sorted(files):
            hasher.update(relpath.encode('utf-8', errors='replace'))
            hasher.update(text.encode('utf-8', errors='replace'))
        placeholder = hasher.hexdigest()
        final_pinned = placeholder
        final_head = placeholder
    if resolved_python_bin is None and language == 'python':
        py_version = None
        if '.python-version' in walk_dict:
            py_version = parse_python_version_str(walk_dict['.python-version'])
        if not py_version and 'runtime.txt' in walk_dict:
            py_version = parse_runtime_txt_version(walk_dict['runtime.txt'])
        if not py_version and 'pyproject.toml' in walk_dict:
            py_version = parse_pyproject_python_version(walk_dict['pyproject.toml'])
        if py_version:
            resolved_python_bin = f'/usr/bin/python{py_version}'
    if resolved_node_bin is None and language == 'javascript':
        node_version = None
        if 'package.json' in walk_dict:
            node_version = parse_package_json_node_version(walk_dict['package.json'])
        if node_version:
            resolved_node_bin = '/usr/bin/node'
    return {'language': language, 'is_entry': True, 'build_files': build_files, 'head_commit': final_head, 'pinned_commit': final_pinned, 'resolved_python_bin': resolved_python_bin, 'resolved_node_bin': resolved_node_bin}