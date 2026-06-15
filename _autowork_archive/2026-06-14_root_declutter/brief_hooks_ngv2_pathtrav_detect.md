---
interfaces: "creates the NEW standalone module ngv2/pathtrav_detect.py — a deterministic, stdlib-only CWE-22 (path traversal) recon scanner exposing detect_path_traversal(repo_path)->dict, the rules-as-data catalog PATHTRAV_RULES, SKIP_DIRS, and is_excluded_path(relpath)->bool; modelled byte-for-contract on the existing ngv2/deser_detect.py and emitting findings in the SAME finding-dict shape ngv2/pattern_scanner.py uses (id/file/line/code/severity/cwe/owasp/description) so they flow unchanged through ngv2/confidence_signals.py — making the committed oracle tests/ngv2/test_pathtrav_detect_wired.py GREEN"
dependencies: []
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

ngv2/pathtrav_detect.py — NEW deterministic CWE-22 (Path Traversal) recon scanner: walk a repo, flag archive-extraction / file-serving sinks (intrinsic: `.extractall` / `tarfile.open` / `zipfile.ZipFile` / `send_file`) and user-influenced `open(...)` / `os.path.join(...)` sinks (tainted), exclude vendored/test/docs paths, hardcoded-literal paths, and `secure_filename`-sanitized lines, returning a fixed-shape report whose `findings` match the `pattern_scanner` finding shape.

# Scope

CREATE the NEW single-file module `ngv2/pathtrav_detect.py` (NGv2 external-target task — `working_dir` = /home/xnihil0zer0/NobleGreedv2). This is the path-traversal analog of the already-shipped `ngv2/deser_detect.py` (CWE-502) and closes the third of the three missing detectors (502 done, 918 sibling, 22 here). The module is PURE and stdlib-only (`os` + `re`): no network, clock, randomness, uuid, subprocess, MCP, or third-party imports, and no import of any sibling Epic-4 leaf. It walks a caller-supplied repo root, scans `*.py` files line-by-line against a small rules-as-data catalog `PATHTRAV_RULES`, and returns a deterministic fixed-shape dict. Its `findings` carry the SAME keys `ngv2/pattern_scanner.py` emits (`id`/`file`/`line`/`code`/`severity`/`cwe`/`owasp`/`description`) so they flow unchanged through `ngv2/confidence_signals.py`.

TWO SINK TIERS (encoded by a per-rule `taint` boolean): INTRINSIC sinks (`taint: False` — archive extraction `.extractall` / `tarfile.open` / `zipfile.ZipFile` and Flask `send_file` / `send_from_directory`) are flagged whenever present (the classic ML "Zip/Tar Slip" and download-endpoint CWE-22 vectors — an extracted member or served path is attacker-controlled by definition). TAINTED sinks (`taint: True` — `open(...)` and `os.path.join(...)`) are flagged ONLY when the call ARGUMENTS carry a traversal/user-input marker (an f-string, a structural marker `..`/`+`/`%`/`.format`, or a user-input identifier substring like `filename`/`path`/`request`/`upload`).

FALSE-POSITIVE control mirrors `_e2e_run/sink_quality.py`: (1) `is_excluded_path` drops vendored / test / docs / examples / tooling files; (2) a tainted sink whose path is a single hardcoded literal with no marker (e.g. `open("README.md")`) is NOT a finding — string-literal bodies are blanked before the marker check so a word inside a hardcoded path (e.g. `path` in `open("/path/to/x.png")`) never counts, and the marker is checked on the call ARGUMENTS only so `os.path.join`'s own `path` token never self-trips; (3) a line sanitized via `secure_filename(` is NOT a finding; (4) pure comment lines never match.

DISPATCH DIRECTIVE — PATCH FORMAT (MANDATORY — WHOLE-FILE): this is a NEW single-file module, so emit the COMPLETE file for `ngv2/pathtrav_detect.py` (whole-file emission — NEVER a `__JANUSMASK_PATCHES__` symbol patch, never a manifest, never a dotted qualname). Reproduce it BYTE-FOR-BYTE exactly as follows:

```python
"""ngv2.pathtrav_detect -- deterministic CWE-22 (Path Traversal) scanner.

A PURE filesystem recon tool, modelled exactly on ``ngv2.deser_detect``: it
walks a caller-supplied repository root, scans ``*.py`` files for path/archive
*sinks* that can be steered outside an intended directory, and returns a
fixed-shape report dict whose ``findings`` carry the SAME finding keys
``ngv2.pattern_scanner`` emits (``id`` / ``file`` / ``line`` / ``code`` /
``severity`` / ``cwe`` / ``owasp`` / ``description``) so they flow unchanged
through ``ngv2.confidence_signals.resolve_signals``.

Two sink tiers:

* INTRINSIC sinks -- archive extraction (``.extractall`` / ``tarfile.open`` /
  ``zipfile.ZipFile``) and Flask file serving (``send_file`` /
  ``send_from_directory``). These are the classic ML "Zip/Tar Slip" and
  download-endpoint CWE-22 vectors; flagged whenever present (an extracted
  archive member or a served path is attacker-controlled by definition).
* TAINTED sinks -- ``open(...)`` and ``os.path.join(...)`` -- flagged ONLY when
  the line carries a traversal / user-input marker (``..`` , ``filename`` ,
  ``path`` , ``request`` , ...) AND is not a pure hardcoded-literal path.

Determinism / purity contract: no network, clock, randomness, subprocess, or
MCP; sorted traversal; regexes compiled once at import.

False-positive control (the CWE-22 analog of ``_e2e_run/sink_quality.py``):

* ``is_excluded_path`` drops vendored / test / docs / examples / tooling files.
* A tainted sink whose path is a single hardcoded literal with no traversal
  marker (e.g. ``open("README.md")``) is NOT a finding.
* A line that sanitizes via ``secure_filename(`` is NOT a finding.
* Pure comment / docstring lines never match.
"""
from __future__ import annotations
import os
import re
from typing import Any, Dict, List

__all__ = ['detect_path_traversal', 'PATHTRAV_RULES', 'SKIP_DIRS', 'is_excluded_path']

# rules-as-data: id -> finding metadata + line regex + a 'taint' flag. When
# taint is True the rule fires only with a traversal/user marker on the line;
# when False the sink is intrinsically dangerous and always fires.
PATHTRAV_RULES: Dict[str, Dict[str, Any]] = {
    'pathtrav_extractall': {
        'pattern': r'\.extractall\s*\(', 'taint': False,
        'severity': 'critical', 'cwe': 'CWE-22',
        'owasp': 'A01:2021-Broken Access Control',
        'description': 'Archive extractall can write outside the target dir (Zip/Tar Slip).',
    },
    'pathtrav_tarfile': {
        'pattern': r'\btarfile\.open\s*\(', 'taint': False,
        'severity': 'high', 'cwe': 'CWE-22',
        'owasp': 'A01:2021-Broken Access Control',
        'description': 'tarfile.open feeds extraction sinks vulnerable to path traversal.',
    },
    'pathtrav_zipfile': {
        'pattern': r'\bzipfile\.ZipFile\s*\(', 'taint': False,
        'severity': 'high', 'cwe': 'CWE-22',
        'owasp': 'A01:2021-Broken Access Control',
        'description': 'zipfile.ZipFile feeds extraction sinks vulnerable to path traversal.',
    },
    'pathtrav_send_file': {
        'pattern': r'\b(?:send_file|send_from_directory)\s*\(', 'taint': False,
        'severity': 'high', 'cwe': 'CWE-22',
        'owasp': 'A01:2021-Broken Access Control',
        'description': 'Flask file-serving sink can leak files via a traversal path.',
    },
    'pathtrav_open': {
        'pattern': r'\bopen\s*\(', 'taint': True,
        'severity': 'medium', 'cwe': 'CWE-22',
        'owasp': 'A01:2021-Broken Access Control',
        'description': 'open() on a user-influenced path (possible path traversal).',
    },
    'pathtrav_join': {
        'pattern': r'\bos\.path\.join\s*\(', 'taint': True,
        'severity': 'medium', 'cwe': 'CWE-22',
        'owasp': 'A01:2021-Broken Access Control',
        'description': 'os.path.join with a user-influenced component (possible traversal).',
    },
}
SKIP_DIRS = {'.git', 'node_modules', '__pycache__', '.venv', 'venv', '.tox',
             '.eggs', '.mypy_cache', 'dist', 'build', '.pytest_cache', '.idea',
             '.hg', '.svn', 'site-packages', '.cache'}
_MAX_CONTEXT = 150
_HIGH_RISK_COUNT = 5

_EXCLUDE_PATH = re.compile(
    r'(?:^|/)(?:_vendor/|vendor/|third[_-]?party/|node_modules/|'
    r'tests?/|testing/|fixtures?/|examples?/|samples?/|demo/|benchmark|'
    r'docs?/|scripts?/|_scripts/|ci/|\.github/|tools?/|setup\.py)',
    re.IGNORECASE,
)
# A call whose first argument is *only* a single string/bytes literal.
_PURE_STR_ARG = re.compile(r"""\(\s*[rbfu]*(['"]).*?\1\s*(?:,|\))""")
# A (non-f) string literal body, blanked so a marker inside a hardcoded path
# string (e.g. ``path`` in ``open("/path/to/x.png")``) is not counted.
_STR_LITERAL = re.compile(r"""([rbuRBU]*)(['"]).*?\2""")
# An f-string prefix -> intrinsically dynamic.
_FSTRING = re.compile(r"""\b[rbuRBU]*[fF][rbuRBU]*['"]""")
# Structural traversal / dynamic markers (after literal bodies are blanked).
_DYN_STRUCT = re.compile(r"\.\.|%|\.format\b|\+")
# User-input markers that make a tainted sink reachable. These are matched on
# the call ARGUMENTS only (after the sink name), so ``os.path.join`` itself
# never trips the ``path`` word.
# Matched as an identifier substring (``\w*...\w*``) so compound names like
# ``request_filename`` / ``user_path`` / ``upload_name`` are recognised; this is
# why ``base_dir`` / ``data_dir`` (no marker) are correctly NOT treated as taint.
_TAINT_WORDS = re.compile(
    r"\b\w*(?:user|request|filename|fname|filepath|file_?path|file_?name|"
    r"upload|param|input|member|arcname|entry|path|url|uri)\w*\b",
    re.IGNORECASE,
)
# A same-line sanitizer that neutralizes the traversal.
_SANITIZED = re.compile(r'\bsecure_filename\s*\(')
_COMPILED: List[tuple] = [
    (rid, re.compile(meta['pattern']), bool(meta['taint']))
    for rid, meta in PATHTRAV_RULES.items()
]


def is_excluded_path(relpath: str) -> bool:
    """True if ``relpath`` is vendored/test/docs/tooling -- not a shipped sink."""
    return bool(_EXCLUDE_PATH.search(relpath.replace('\\', '/')))


def _blank_literals(s: str) -> str:
    """Blank string-literal bodies so a marker inside a hardcoded path string
    does not make the argument look tainted."""
    return _STR_LITERAL.sub(lambda m: m.group(1) + m.group(2) * 2, s)


def _arg_is_tainted(code: str, match_end: int) -> bool:
    """True if the tainted-sink argument is plausibly user-influenced: an
    f-string, a structural marker (``..``/``+``/``%``/``.format``), or a
    user-input name -- evaluated on the arguments with literal bodies blanked.
    A pure hardcoded-literal path (e.g. ``open("README.md")``) is NOT tainted."""
    tail = code[match_end - 1:]  # start at the '(' of the call (the arguments)
    blanked = _blank_literals(tail)
    return bool(_FSTRING.search(tail) or _DYN_STRUCT.search(blanked)
                or _TAINT_WORDS.search(blanked))


def _risk_level(count: int) -> str:
    if count == 0:
        return 'none'
    if count >= _HIGH_RISK_COUNT:
        return 'high'
    if count >= 2:
        return 'medium'
    return 'low'


def detect_path_traversal(repo_path: str) -> Dict[str, Any]:
    """Scan ``repo_path`` for CWE-22 path-traversal sinks.

    Returns a deterministic, fixed-shape dict. A non-directory ``repo_path``
    yields the same shape with an ``error`` key and no findings.
    """
    if not os.path.isdir(repo_path):
        return {'repo_path': repo_path, 'files_checked': 0, 'has_path_traversal': False,
                'risk_level': 'none', 'total_findings': 0, 'findings': [],
                'error': f'Not a directory: {repo_path}'}
    files_checked = 0
    findings: List[Dict[str, Any]] = []
    for dirpath, dirnames, filenames in os.walk(repo_path):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for fname in sorted(filenames):
            if not fname.endswith('.py'):
                continue
            fullpath = os.path.join(dirpath, fname)
            relpath = os.path.relpath(fullpath, repo_path)
            if is_excluded_path(relpath):
                continue
            try:
                with open(fullpath, 'r', encoding='utf-8', errors='replace') as handle:
                    text = handle.read()
            except OSError:
                continue
            files_checked += 1
            for lineno, raw in enumerate(text.splitlines(), start=1):
                stripped = raw.strip()
                if not stripped or stripped.startswith('#'):
                    continue
                if _SANITIZED.search(raw):
                    continue
                for rid, regex, taint in _COMPILED:
                    m = regex.search(raw)
                    if not m:
                        continue
                    if taint and not _arg_is_tainted(raw, m.end()):
                        continue
                    meta = PATHTRAV_RULES[rid]
                    findings.append({
                        'id': rid, 'file': relpath, 'line': lineno,
                        'code': stripped[:_MAX_CONTEXT], 'severity': meta['severity'],
                        'cwe': meta['cwe'], 'owasp': meta['owasp'],
                        'description': meta['description'],
                    })
    findings.sort(key=lambda f: (f['file'], f['line'], f['id']))
    return {'repo_path': repo_path, 'files_checked': files_checked,
            'has_path_traversal': len(findings) > 0,
            'risk_level': _risk_level(len(findings)),
            'total_findings': len(findings), 'findings': findings}
```

POST-EMIT SELF-CHECK (mandatory): the emitted file defines exactly the four public names in `__all__` (`detect_path_traversal`, `PATHTRAV_RULES`, `SKIP_DIRS`, `is_excluded_path`); `PATHTRAV_RULES` has exactly six rules all with `cwe == 'CWE-22'`, mixing both `taint: True` and `taint: False`; the module imports only `os` / `re` / `typing`; there is NO network/clock/subprocess import.

# Required plan shape

EXACTLY ONE impl task. Use this task_id VERBATIM (the committed oracle and the operator decision file are keyed to it): `task_id`: `ngv2_pathtrav_detect`. meta_task_type=`data_model` (NEW pure stdlib recon module — single-file whole-file emission, no production-harness edit). priority: high. dependencies: []. working_dir: "/home/xnihil0zer0/NobleGreedv2". files_touched: `["ngv2/pathtrav_detect.py"]` ONLY. partial_edit semantics: WHOLE-FILE single-file emission per the DISPATCH DIRECTIVE — the DISPATCH DIRECTIVE — PATCH FORMAT block above (including the full pinned file content) MUST be copied VERBATIM into the task's `implementation_notes` so the blind worker sees it. verification_command: `python3 -m pytest -q tests/ngv2/test_pathtrav_detect_wired.py` (CWD-relative — NO `cd`). The committed RED oracle tests/ngv2/test_pathtrav_detect_wired.py is the authoritative acceptance contract — make it GREEN (13 tests); do NOT author new tests. `spec.functional_requirements` MUST be CONSOLIDATED to at most 5 entries, and `test_spec.unit_tests` MUST enumerate AT LEAST as many entries as `spec.functional_requirements` (validator floor: len(unit_tests) >= len(functional_requirements)); unit_tests entries are descriptors NAMING committed-oracle test cases (this does NOT authorize authoring new tests). `test_spec.regression_tests` MUST list at least two entries that NAME existing test cases from the committed oracle (plan descriptors referencing committed tests — this does NOT authorize authoring new tests), e.g. `test_detects_extractall_zip_slip_and_finding_shape`, `test_literal_open_is_not_flagged`, `test_secure_filename_sanitized_open_not_flagged`.

# Non-Goals

Do NOT touch `ngv2/pattern_scanner.py`, `ngv2/deser_detect.py`, `ngv2/confidence_signals.py`, `ngv2/semantic_signals.py`, `ngv2/sink_taxonomy.py`, or any other existing module — this leaf ships ONLY the new `ngv2/pathtrav_detect.py`. Catalog/scan-path INTEGRATION (wiring `detect_path_traversal` into the live scan catalog, selection_ranker demand terms, or `sink_taxonomy` weights) is OUT OF SCOPE — that integration is a separate downstream EDIT leaf; this brief delivers the standalone detector verified solely by its committed unit oracle. Do NOT author or modify any test — the oracle is committed and authoritative. Do NOT add AST/dataflow/inter-procedural taint analysis, network, wall-clock, randomness, subprocess, or logging. Do NOT import any third-party package or any sibling `ngv2/**` leaf. The argument-marker heuristic (literal-blanking + identifier-substring match) is the ONLY reachability proxy in scope.

# Inputs

The committed authoritative oracle tests/ngv2/test_pathtrav_detect_wired.py (currently RED — module does not yet exist). It pins: (i) the rules-as-data contract — `PATHTRAV_RULES` is a non-empty dict, every value has keys `{pattern,taint,severity,cwe,owasp,description}` with `cwe == 'CWE-22'` and a bool `taint`, the `extractall` sink is present, and both `taint: True` and `taint: False` rules exist; (ii) `SKIP_DIRS` superset; (iii) INTRINSIC positives — `tarfile.open(...)` + `.extractall(...)` detected as `pathtrav_tarfile` / `pathtrav_extractall` (severity `critical` for extractall), plus `zipfile.ZipFile` and `send_file`/`send_from_directory`; TAINTED positives — `open(filename, "rb")` and `os.path.join(base_dir, request_filename)` flagged; (iv) NEGATIVES / FP-exclusion — literal `open("README.md")` NOT flagged; `open(secure_filename(filename))` NOT flagged; comment lines ignored; sinks under `tests/`, `docs/`, `setup.py` excluded (and `is_excluded_path('gptcache/utils/response.py')` is False); `node_modules/` pruned; non-`.py` and json-only repos clean; (v) the non-directory `error` shape and byte-stable determinism; finding dicts carry exactly `{id,file,line,code,severity,cwe,owasp,description}`. Real-corpus grounding (zilliztech-gptcache): the detector fires on `open(img_path)` / `open(f_path,"wb")` / `Image.open(image_path)` / `zipfile.ZipFile(zip_filename,...)` (9 dynamic-path findings) while correctly dropping the literal `open("/path/to/merlion.png")`. stdlib only (`os`, `re`, `typing`).

# Deliverables

The NEW file `ngv2/pathtrav_detect.py` exactly as pinned in the DISPATCH DIRECTIVE: rules-as-data `PATHTRAV_RULES` (6 CWE-22 rules, intrinsic + tainted tiers), `SKIP_DIRS`, `is_excluded_path`, and `detect_path_traversal(repo_path)->dict` whose findings match the `pattern_scanner` finding shape. Verified GREEN by `python3 -m pytest -q tests/ngv2/test_pathtrav_detect_wired.py` (13 passed).
