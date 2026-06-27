"""ngv2.entrypoint_scan -- enumerate public attacker entry points in a clone.

Stage-1 (source-first) of the reachability cascade. Loads the rules-as-data
``entrypoint_sigs.json`` and walks a repository's ``*.py`` files to find:

* **web routes** (FastAPI/Flask/Django/aiohttp/tornado) -- only for frameworks
  the **revived** ``ngv2.web_framework_detect.detect_frameworks`` actually finds
  in the clone (so a stray ``@app.get`` regex in a repo with no web framework is
  not counted),
* **CLI entry points** (click/argparse), and
* **MFF model-load boundaries** (Gap G6): ``torch.load`` / ``pickle.load`` /
  ``joblib.load`` / keras / safetensors / ``from_pretrained`` /
  ``load_pretrained_model`` -- treated as attacker boundaries because the model
  *file* is the attacker input, the case the param-derived filter silently drops.

Pure and stdlib-only (``os`` / ``re`` / ``json``); deterministic (sorted walk).
The framework detector is an injected seam (defaults to the real revived module)
so the oracle is hermetic. No network, clock, randomness, or subprocess.
"""
from __future__ import annotations
import json
import os
import re
from typing import Any, Callable, Dict, List, Optional

__all__ = ['load_entrypoint_sigs', 'scan_entrypoints', 'DEFAULT_RULES_PATH', 'SKIP_DIRS']

DEFAULT_RULES_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'data', 'ngv2', 'reachability_rules', 'entrypoint_sigs.json')
SKIP_DIRS = {'.git', '.hg', '.svn', 'node_modules', '__pycache__', '.venv',
             'venv', 'env', '.tox', '.mypy_cache', '.pytest_cache', 'build',
             'dist', '.eggs', 'site-packages', '.cache'}
_EXCLUDE_PATH = re.compile(
    r'(?:^|/)(?:_vendor/|vendor/|third[_-]?party/|tests?/|testing/|'
    r'fixtures?/|examples?/|samples?/|docs?/)', re.IGNORECASE)


def load_entrypoint_sigs(rules_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Load and lightly validate the entry-point signature catalog.

    Returns the list under the top-level ``entrypoints`` key. Raises
    ``FileNotFoundError`` if the rules file is absent and ``ValueError`` if it is
    malformed.
    """
    path = rules_path or DEFAULT_RULES_PATH
    with open(path, 'r', encoding='utf-8') as handle:
        data = json.load(handle)
    entries = data.get('entrypoints') if isinstance(data, dict) else None
    if not isinstance(entries, list) or not entries:
        raise ValueError('entrypoint_sigs.json must hold a non-empty "entrypoints" list')
    return entries


def _present_frameworks(clone_path: str,
                        detect_frameworks: Optional[Callable[[str], Any]]) -> set:
    """Names of web frameworks the revived detector finds in the clone."""
    if detect_frameworks is None:
        from ngv2.web_framework_detect import detect_frameworks as detect_frameworks
    try:
        result = detect_frameworks(clone_path)
    except Exception:
        return set()
    frameworks = result.get('frameworks') if isinstance(result, dict) else None
    names = set()
    for fw in frameworks or []:
        name = fw.get('name') if isinstance(fw, dict) else None
        if name:
            names.add(name)
    return names


def scan_entrypoints(clone_path: str, rules_path: Optional[str] = None,
                     detect_frameworks: Optional[Callable[[str], Any]] = None
                     ) -> List[Dict[str, Any]]:
    """Enumerate public entry points under ``clone_path``.

    Returns a deterministic list of dicts with keys ``file`` (repo-relative),
    ``line``, ``kind`` (``route``/``cli``/``model_load``), ``framework``,
    ``attacker_boundary`` (``network``/``cli``/``model_file``) and ``code``.
    Web-route signatures only fire for frameworks ``detect_frameworks`` reports;
    CLI and MFF model-load signatures always apply. A non-directory path -> [].
    """
    if not os.path.isdir(clone_path):
        return []
    sigs = load_entrypoint_sigs(rules_path)
    present = _present_frameworks(clone_path, detect_frameworks)
    compiled = []
    for entry in sigs:
        framework = entry.get('framework')
        kind = entry.get('kind')
        boundary = entry.get('attacker_boundary')
        if kind == 'route' and framework not in present:
            continue  # require the revived web_framework_detect to confirm it
        for pat in entry.get('signature_regex') or []:
            compiled.append((framework, kind, boundary, re.compile(pat)))
    found: List[Dict[str, Any]] = []
    for dirpath, dirnames, filenames in os.walk(clone_path):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for fname in sorted(filenames):
            if not fname.endswith('.py'):
                continue
            fullpath = os.path.join(dirpath, fname)
            relpath = os.path.relpath(fullpath, clone_path)
            if _EXCLUDE_PATH.search(relpath.replace('\\', '/')):
                continue
            try:
                with open(fullpath, 'r', encoding='utf-8', errors='replace') as handle:
                    text = handle.read()
            except OSError:
                continue
            for lineno, raw in enumerate(text.splitlines(), start=1):
                stripped = raw.strip()
                if not stripped or stripped.startswith('#'):
                    continue
                for framework, kind, boundary, regex in compiled:
                    if regex.search(raw):
                        found.append({'file': relpath, 'line': lineno, 'kind': kind,
                                      'framework': framework,
                                      'attacker_boundary': boundary,
                                      'code': stripped[:150]})
    found.sort(key=lambda e: (e['file'], e['line'], e['kind'], e['framework']))
    return found
