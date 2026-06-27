"""ngv2.web_framework_detect — deterministic, stdlib-only web-framework recon.

Detect Python web frameworks (FastAPI, Flask, Django, ...) in a repository by
scanning dependency manifests and ``.py`` sources with regex import / route
signatures. The detector is a pure function of the filesystem rooted at the
caller-supplied ``repo_path`` (and of inputted text for the helpers): it does
NO network, clock, random, subprocess, or model access, and never performs an
implicit global scan. Imports are restricted to ``os``, ``re`` and ``pathlib``.
"""
import os
import re
from pathlib import Path
from typing import Dict, List, Optional
FRAMEWORKS: List[Dict[str, object]] = [{'name': 'fastapi', 'import_patterns': ['\\bfrom\\s+fastapi\\b', '\\bimport\\s+fastapi\\b'], 'config_markers': [], 'route_patterns': ['@\\w+\\.(?:get|post|put|delete|patch|options|head|websocket)\\s*\\(', '\\bAPIRouter\\s*\\('], 'package_names': ['fastapi']}, {'name': 'flask', 'import_patterns': ['\\bfrom\\s+flask\\b', '\\bimport\\s+flask\\b'], 'config_markers': [], 'route_patterns': ['@\\w+\\.route\\s*\\(', '\\.add_url_rule\\s*\\('], 'package_names': ['flask', 'Flask']}, {'name': 'django', 'import_patterns': ['\\bfrom\\s+django\\b', '\\bimport\\s+django\\b'], 'config_markers': ['manage.py', 'settings.py', 'wsgi.py', 'asgi.py'], 'route_patterns': ['\\burlpatterns\\b', '\\bre_path\\s*\\(', '\\bpath\\s*\\('], 'package_names': ['django', 'Django']}, {'name': 'tornado', 'import_patterns': ['\\bfrom\\s+tornado\\b', '\\bimport\\s+tornado\\b'], 'config_markers': [], 'route_patterns': ['\\bclass\\s+\\w+\\s*\\(\\s*tornado\\.web\\.RequestHandler\\b', '\\btornado\\.web\\.Application\\s*\\('], 'package_names': ['tornado']}, {'name': 'aiohttp', 'import_patterns': ['\\bfrom\\s+aiohttp\\b', '\\bimport\\s+aiohttp\\b'], 'config_markers': [], 'route_patterns': ['\\bweb\\.RouteTableDef\\s*\\(', '@routes\\.(?:get|post|put|delete|patch|head|view)\\s*\\(', '\\.router\\.add_(?:get|post|put|delete|route)\\s*\\('], 'package_names': ['aiohttp']}, {'name': 'bottle', 'import_patterns': ['\\bfrom\\s+bottle\\b', '\\bimport\\s+bottle\\b'], 'config_markers': [], 'route_patterns': ['@(?:route|get|post|put|delete)\\s*\\('], 'package_names': ['bottle']}, {'name': 'sanic', 'import_patterns': ['\\bfrom\\s+sanic\\b', '\\bimport\\s+sanic\\b'], 'config_markers': [], 'route_patterns': ['@\\w+\\.route\\s*\\(', '@\\w+\\.(?:get|post|put|delete|patch|websocket)\\s*\\('], 'package_names': ['sanic']}]
DEPENDENCY_FILES: List[str] = ['requirements.txt', 'requirements-dev.txt', 'pyproject.toml', 'setup.py', 'setup.cfg', 'Pipfile']
SKIP_DIRS = {'.git', '.hg', '.svn', 'node_modules', '__pycache__', '.venv', 'venv', 'env', '.env', '.tox', '.mypy_cache', '.pytest_cache', 'build', 'dist', '.eggs', 'site-packages'}
_VERSION_SPEC = re.compile('\\s*([<>=!~][^\\s#,;]*)')

def extract_version_from_deps(deps_text: str, package_names: List[str]) -> Optional[str]:
    """Return the version specifier for the first matching package, else None.

    Scans ``deps_text`` line by line (requirements.txt style) and, for the
    first line whose leading token equals one of ``package_names``
    (case-insensitively) and is followed by a version specifier, returns that
    specifier verbatim (e.g. ``"==2.3.0"`` or ``">=0.95"``). Lines without a
    specifier, comment lines, and blank lines never match.
    """
    for raw_line in deps_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#'):
            continue
        for package in package_names:
            head = re.escape(package)
            match = re.match(head + '(?=$|[\\s<>=!~;,\\[])', line, re.IGNORECASE)
            if not match:
                continue
            spec = _VERSION_SPEC.match(line, match.end())
            if spec:
                return spec.group(1)
    return None

def _package_in_deps(deps_text: str, package_names: List[str]) -> bool:
    """True if any of ``package_names`` is listed in the dependency text."""
    for raw_line in deps_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#'):
            continue
        for package in package_names:
            head = re.escape(package)
            if re.match(head + '(?=$|[\\s<>=!~;,\\[])', line, re.IGNORECASE):
                return True
    return False

def _read_text(path: str) -> str:
    """Read a file's text, tolerating decode errors and unreadable files."""
    try:
        return Path(path).read_text(encoding='utf-8', errors='ignore')
    except (OSError, ValueError):
        return ''

def _gather_dependency_text(repo_path: str) -> str:
    """Concatenate the text of all dependency manifests at the repo root."""
    chunks: List[str] = []
    for fname in DEPENDENCY_FILES:
        candidate = os.path.join(repo_path, fname)
        if os.path.isfile(candidate):
            chunks.append(_read_text(candidate))
    return '\n'.join(chunks)

def _error_result(repo_path: str, message: str) -> Dict[str, object]:
    """The fixed no-scan result shape returned for unusable inputs."""
    return {'repo_path': repo_path, 'error': message, 'files_checked': 0, 'frameworks': [], 'has_web_endpoints': False, 'total_routes': 0}

def detect_frameworks(repo_path: str) -> Dict[str, object]:
    """Detect web frameworks used under ``repo_path``.

    Returns a result dict with keys ``repo_path``, ``files_checked``,
    ``frameworks``, ``has_web_endpoints`` and ``total_routes``. Each detected
    framework (imported in source and/or declared as a dependency) is reported
    with ``name``, ``evidence_file``, ``import_count``, ``route_count``,
    ``in_dependencies`` and — when a versioned dependency is found — ``version``.
    A non-directory ``repo_path`` yields an ``error`` result with no matches.
    """
    if not repo_path or not os.path.isdir(repo_path):
        return _error_result(repo_path, 'path is not a readable directory')
    compiled = []
    for fw in FRAMEWORKS:
        compiled.append({'name': fw['name'], 'package_names': fw['package_names'], 'imports': [re.compile(p) for p in fw['import_patterns']], 'routes': [re.compile(p) for p in fw['route_patterns']]})
    deps_text = _gather_dependency_text(repo_path)
    import_counts = {fw['name']: 0 for fw in FRAMEWORKS}
    route_counts = {fw['name']: 0 for fw in FRAMEWORKS}
    evidence = {fw['name']: None for fw in FRAMEWORKS}
    files_checked = 0
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = sorted((d for d in dirs if d not in SKIP_DIRS))
        for fname in sorted(files):
            if not fname.endswith('.py'):
                continue
            files_checked += 1
            fpath = os.path.join(root, fname)
            text = _read_text(fpath)
            if not text:
                continue
            rel = os.path.relpath(fpath, repo_path)
            for spec in compiled:
                name = spec['name']
                imports_here = sum((len(rx.findall(text)) for rx in spec['imports']))
                if imports_here:
                    import_counts[name] += imports_here
                    if evidence[name] is None:
                        evidence[name] = rel
                if import_counts[name] > 0 or _package_in_deps(deps_text, spec['package_names']):
                    route_counts[name] += sum((len(rx.findall(text)) for rx in spec['routes']))
    frameworks: List[Dict[str, object]] = []
    total_routes = 0
    for fw in FRAMEWORKS:
        name = fw['name']
        in_deps = _package_in_deps(deps_text, fw['package_names'])
        imp = import_counts[name]
        if imp == 0 and (not in_deps):
            continue
        routes = route_counts[name] if imp > 0 else 0
        total_routes += routes
        entry: Dict[str, object] = {'name': name, 'evidence_file': evidence[name], 'import_count': imp, 'route_count': routes, 'in_dependencies': in_deps}
        if in_deps:
            version = extract_version_from_deps(deps_text, fw['package_names'])
            if version is not None:
                entry['version'] = version
        frameworks.append(entry)
    return {'repo_path': repo_path, 'files_checked': files_checked, 'frameworks': frameworks, 'has_web_endpoints': total_routes > 0, 'total_routes': total_routes}