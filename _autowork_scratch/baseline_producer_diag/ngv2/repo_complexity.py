"""Pure, deterministic, stdlib-only repository-complexity triage gate.

This module characterizes a target codebase purely from the local filesystem
paths it is pointed at: it counts source lines of code per language, parses a
handful of dependency manifests, and emits a coarse size verdict
('skip'/'shallow'/'deep').  It performs no network, clock, subprocess, random,
LLM, GPU, or MCP side effects -- identical inputs always yield identical
outputs (gate class: pure_fuzz).

Public surface (frozen by tests/test_repo_complexity.py):

    EXT_LANG            mapping of file extension -> language name
    SKIP_DIRS           directory names pruned during the walk
    DEP_FILES           manifest filename -> ecosystem
    count_lines         count significant LOC in a single file
    parse_dependencies  extract lowercased dependency names from a repo
    check_complexity    walk a repo and return its complexity summary
"""
from __future__ import annotations
import glob
import json
import os
import re
from typing import Dict, List, Set
try:
    import tomllib as _tomllib
except Exception:
    _tomllib = None
_EXT_LANG_PAIRS = [('.py', 'python'), ('.js', 'javascript'), ('.ts', 'typescript'), ('.go', 'go'), ('.rs', 'rust'), ('.java', 'java'), ('.c', 'c'), ('.h', 'c'), ('.cpp', 'cpp'), ('.sh', 'shell'), ('.md', 'markdown'), ('.yaml', 'yaml'), ('.yml', 'yaml'), ('.json', 'json'), ('.toml', 'toml')]
EXT_LANG: Dict[str, str] = dict(_EXT_LANG_PAIRS)
SKIP_DIRS: Set[str] = {'.git', 'node_modules', '__pycache__', '.venv', 'venv', 'dist', 'build', '.pytest_cache', '.mypy_cache', '.tox', '.eggs', '.idea', '.vscode', 'vendor', 'target', 'coverage', '.cache'}
_DEP_FILE_PAIRS = [('requirements.txt', 'pip'), ('pyproject.toml', 'pip'), ('package.json', 'npm'), ('go.mod', 'go'), ('Cargo.toml', 'cargo'), ('Gemfile', 'gem')]
DEP_FILES: Dict[str, str] = dict(_DEP_FILE_PAIRS)
_NON_CODE_LANGS: Set[str] = {'markdown', 'json', 'yaml', 'toml'}
_DEP_DELIMITERS = '=<>~!;@[ \t,()'

def count_lines(filepath: str) -> int:
    """Count significant lines of code in *filepath*.

    A line counts when, after stripping surrounding whitespace, it is
    non-empty and does not begin with ``#`` or ``//``.  Any OSError/IOError
    while reading the file is swallowed and yields ``0``.
    """
    total = 0
    try:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as handle:
            for raw in handle:
                stripped = raw.strip()
                if not stripped:
                    continue
                if stripped.startswith('#') or stripped.startswith('//'):
                    continue
                total += 1
    except (OSError, IOError):
        return 0
    return total

def _dep_name(spec: str) -> str:
    """Reduce a single requirement spec to its bare, lowercased name."""
    spec = spec.strip()
    for index, char in enumerate(spec):
        if char in _DEP_DELIMITERS:
            spec = spec[:index]
            break
    return spec.strip().lower()

def _parse_requirements(text: str) -> Set[str]:
    """Parse a pip ``requirements*.txt`` body into a set of names."""
    names: Set[str] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith('#') or line.startswith('-'):
            continue
        name = _dep_name(line)
        if name:
            names.add(name)
    return names

def _toml_project_dependencies(text: str) -> List[str]:
    """Extract the raw ``[project].dependencies`` strings from pyproject text."""
    if _tomllib is not None:
        try:
            data = _tomllib.loads(text)
        except Exception:
            data = None
        if isinstance(data, dict):
            project = data.get('project')
            if isinstance(project, dict):
                deps = project.get('dependencies')
                if isinstance(deps, list):
                    return [d for d in deps if isinstance(d, str)]
            return []
    found: List[str] = []
    in_project = False
    in_deps = False
    quoted = re.compile('\\"([^\\"]*)\\"|\'([^\']*)\'')
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith('[') and line.endswith(']'):
            in_project = line == '[project]'
            in_deps = False
            continue
        if not in_project:
            continue
        if in_deps:
            for match in quoted.findall(line):
                value = match[0] or match[1]
                if value:
                    found.append(value)
            if ']' in line:
                in_deps = False
            continue
        if re.match('dependencies\\s*=', line):
            after = line.split('=', 1)[1]
            for match in quoted.findall(after):
                value = match[0] or match[1]
                if value:
                    found.append(value)
            if ']' not in after:
                in_deps = True
            continue
    return found

def _parse_pyproject(text: str) -> Set[str]:
    """Parse ``pyproject.toml`` [project] dependencies into a name set."""
    names: Set[str] = set()
    for spec in _toml_project_dependencies(text):
        name = _dep_name(spec)
        if name:
            names.add(name)
    return names

def _parse_package_json(text: str) -> Set[str]:
    """Parse npm ``package.json`` dependencies + devDependencies."""
    names: Set[str] = set()
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return names
    if not isinstance(data, dict):
        return names
    for section in ('dependencies', 'devDependencies'):
        block = data.get(section)
        if isinstance(block, dict):
            for ident in block:
                if isinstance(ident, str) and ident.strip():
                    names.add(ident.strip().lower())
    return names

def _parse_go_mod(text: str) -> Set[str]:
    """Parse ``go.mod`` require directives (module paths containing '/')."""
    names: Set[str] = set()
    in_block = False
    for raw in text.splitlines():
        line = raw.strip()
        comment = line.find('//')
        if comment != -1:
            line = line[:comment].strip()
        if not line:
            continue
        if line.startswith('require') and line.rstrip().endswith('('):
            in_block = True
            continue
        if in_block and line == ')':
            in_block = False
            continue
        token = ''
        if in_block:
            parts = line.split()
            if parts:
                token = parts[0]
        elif line.startswith('require'):
            parts = line.split()
            if len(parts) >= 2:
                token = parts[1]
        if token and '/' in token:
            names.add(token.lower())
    return names

def parse_dependencies(repo_path: str) -> Set[str]:
    """Collect lowercased dependency names from a repository's manifests.

    Recognized manifests at the top level of *repo_path*:

      * ``requirements*.txt`` -- pip pinned requirements
      * ``pyproject.toml``    -- [project] dependencies
      * ``package.json``      -- dependencies + devDependencies
      * ``go.mod``            -- require directives (module paths)

    Missing or unreadable manifests are silently skipped; the result is the
    union of every name found.  Always returns a set.
    """
    names: Set[str] = set()
    for req_path in sorted(glob.glob(os.path.join(repo_path, 'requirements*.txt'))):
        text = _read_text(req_path)
        if text is not None:
            names |= _parse_requirements(text)
    pyproject = _read_text(os.path.join(repo_path, 'pyproject.toml'))
    if pyproject is not None:
        names |= _parse_pyproject(pyproject)
    pkg = _read_text(os.path.join(repo_path, 'package.json'))
    if pkg is not None:
        names |= _parse_package_json(pkg)
    gomod = _read_text(os.path.join(repo_path, 'go.mod'))
    if gomod is not None:
        names |= _parse_go_mod(gomod)
    return names

def _read_text(path: str):
    """Read a text file, returning its contents or None on any IO error."""
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as handle:
            return handle.read()
    except (OSError, IOError):
        return None

def check_complexity(repo_path: str) -> Dict[str, object]:
    """Characterize the repository rooted at *repo_path*.

    Walks the tree (pruning :data:`SKIP_DIRS` in-place), counting LOC for any
    file whose extension is in :data:`EXT_LANG`.  Returns a dict with keys::

        repo_path, total_loc, code_loc, total_files, languages,
        primary_language, n_dependencies, verdict, reason

    ``code_loc`` sums only genuine source languages (documentation/config
    languages such as markdown/json/yaml/toml contribute to ``total_loc`` but
    not ``code_loc``).  The verdict is ``skip`` when ``code_loc < 500``,
    ``shallow`` when ``code_loc < 5000``, otherwise ``deep``.

    A path that is not an existing directory yields an error dict (with
    ``total_loc`` 0 and ``verdict`` 'error') rather than raising.
    """
    if not os.path.isdir(repo_path):
        return {'error': 'not a directory: %s' % repo_path, 'repo_path': repo_path, 'total_loc': 0, 'code_loc': 0, 'total_files': 0, 'languages': {}, 'primary_language': None, 'n_dependencies': 0, 'verdict': 'error', 'reason': 'path is not an existing directory'}
    total_loc = 0
    code_loc = 0
    total_files = 0
    lang_loc: Dict[str, int] = {}
    for dirpath, dirnames, filenames in os.walk(repo_path):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for filename in filenames:
            ext = os.path.splitext(filename)[1].lower()
            language = EXT_LANG.get(ext)
            if language is None:
                continue
            loc = count_lines(os.path.join(dirpath, filename))
            total_loc += loc
            total_files += 1
            lang_loc[language] = lang_loc.get(language, 0) + loc
            if language not in _NON_CODE_LANGS:
                code_loc += loc
    ordered = sorted(lang_loc.items(), key=lambda item: (-item[1], item[0]))
    languages: Dict[str, int] = {name: loc for name, loc in ordered}
    primary_language = ordered[0][0] if ordered else None
    n_dependencies = len(parse_dependencies(repo_path))
    if code_loc < 500:
        verdict = 'skip'
    elif code_loc < 5000:
        verdict = 'shallow'
    else:
        verdict = 'deep'
    reason = '%s: code_loc=%d across %d file(s) in %d language(s); total_loc=%d, dependencies=%d' % (verdict, code_loc, total_files, len(languages), total_loc, n_dependencies)
    return {'repo_path': repo_path, 'total_loc': total_loc, 'code_loc': code_loc, 'total_files': total_files, 'languages': languages, 'primary_language': primary_language, 'n_dependencies': n_dependencies, 'verdict': verdict, 'reason': reason}