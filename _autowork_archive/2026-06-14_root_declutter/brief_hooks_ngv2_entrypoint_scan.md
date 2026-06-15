---
interfaces: "creates NEW ngv2/entrypoint_scan.py exposing scan_entrypoints(clone_path, rules_path, detect_frameworks)->list and load_entrypoint_sigs — Stage-1 public entry-point enumeration that REVIVES ngv2.web_framework_detect on a live path and implements the G6 MFF model-load boundary"
dependencies: ["ngv2_entrypoint_sigs_data"]
meta_task_type: data_model
spec_author: "Phase-III BUILD-PREP agent (JanusMask)"
spec_reviewed_by: "owner (CodeQL CLI use APPROVED 2026-06-12)"
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

ngv2/entrypoint_scan.py — NEW Stage-1 entry-point enumerator: find web routes (only for frameworks the revived web_framework_detect confirms), CLI entry points, and — Gap G6 — MFF model-load attacker boundaries (torch.load/pickle.load/joblib/keras/safetensors/from_pretrained/load_pretrained_model).

# Scope

CREATE the NEW single-file module `ngv2/entrypoint_scan.py`. It loads the rules-as-data `data/ngv2/reachability_rules/entrypoint_sigs.json` (dependency `ngv2_entrypoint_sigs_data`) and walks a clone's `*.py` files. Web-route signatures fire ONLY for frameworks that the REVIVED `ngv2.web_framework_detect.detect_frameworks` actually reports for the clone (this is the live import that un-orphans web_framework_detect); CLI and MFF model-load signatures always apply. G6: model-load loaders are emitted as attacker boundaries (`attacker_boundary='model_file'`) because the model FILE is the attacker input — the case the param-derived filter silently drops. Pure, stdlib-only (`os`/`re`/`json`); the framework detector is an injected seam defaulting to the real module, so the oracle is hermetic.

DISPATCH DIRECTIVE — PATCH FORMAT (MANDATORY — WHOLE-FILE): this is a NEW single-file module, so emit the COMPLETE file for `ngv2/entrypoint_scan.py` (whole-file emission — NEVER a `__JANUSMASK_PATCHES__` symbol patch, never a manifest, never a dotted qualname). Reproduce it BYTE-FOR-BYTE exactly as follows:

```python
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
```

POST-EMIT SELF-CHECK (mandatory): the module imports only `os`/`re`/`json`/`typing`; route signatures are gated on detect_frameworks; model_load entries carry `attacker_boundary='model_file'`; no network/clock/subprocess import.

# Required plan shape

EXACTLY ONE impl task. Use this task_id VERBATIM (the committed oracle is keyed to it): `task_id`: `ngv2_entrypoint_scan`. meta_task_type=`data_model` (NEW pure module — single-file whole-file emission, no production-harness edit). priority: high. dependencies: ["ngv2_entrypoint_sigs_data"]. working_dir: "/home/xnihil0zer0/NobleGreedv2". files_touched: `["ngv2/entrypoint_scan.py"]` ONLY. partial_edit semantics: WHOLE-FILE single-file emission per the DISPATCH DIRECTIVE — the DISPATCH DIRECTIVE block above (including the full pinned file content) MUST be copied VERBATIM into the task's `implementation_notes` so the blind worker sees it. verification_command: `python3 -m pytest -q tests/ngv2/test_entrypoint_scan_wired.py` (CWD-relative — NO `cd`). The committed RED oracle tests/ngv2/test_entrypoint_scan_wired.py is the authoritative acceptance contract — make it GREEN (8 tests); do NOT author new tests. `spec.functional_requirements` MUST be CONSOLIDATED to at most 5 entries, and `test_spec.unit_tests` MUST enumerate AT LEAST as many entries as `spec.functional_requirements` (validator floor: len(unit_tests) >= len(functional_requirements)); unit_tests entries are descriptors NAMING committed-oracle test cases (this does NOT authorize authoring new tests). `test_spec.regression_tests` MUST list at least two entries naming committed oracle cases: `test_detects_fastapi_route_only_when_framework_present`, `test_g6_mff_model_load_is_attacker_boundary`. `test_spec.edge_cases` (≥2, reflected in those test names): `test_route_regex_suppressed_without_framework`, `test_excluded_paths_and_nondir`, `test_default_path_uses_real_web_framework_detect` — including the integration-style case `test_default_path_uses_real_web_framework_detect`.

# Non-Goals

Do NOT add taint/dataflow analysis (the forward trace is CodeQL's job, Stage 2). Do NOT touch web_framework_detect, deser_detect, or any other module. Do NOT add network, clock, randomness, subprocess, or logging. Do NOT hardcode the entry-point catalog in Python — it MUST load the JSON rules file. Catalog/scan-path INTEGRATION into the live driver is a separate downstream leaf.

# Inputs

The committed oracle tests/ngv2/test_entrypoint_scan_wired.py (RED — module absent). It pins: default rules load; a FastAPI route detected only when the framework is present; the same route regex SUPPRESSED when no framework is imported/declared; the G6 MFF torch.load model-load boundary; argparse CLI entry points; excluded test/docs paths and non-dir → []; the integration/live-path case proving the default path loads the revived ngv2.web_framework_detect into sys.modules; and an injected-detector case.

# Deliverables

The NEW file `ngv2/entrypoint_scan.py` exactly as pinned in the DISPATCH DIRECTIVE, verified GREEN by `python3 -m pytest -q tests/ngv2/test_entrypoint_scan_wired.py` (8 passed).
