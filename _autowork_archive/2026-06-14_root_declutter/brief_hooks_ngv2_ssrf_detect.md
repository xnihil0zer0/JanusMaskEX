---
interfaces: "creates the NEW standalone module ngv2/ssrf_detect.py — a deterministic, stdlib-only CWE-918 (SSRF) recon scanner exposing detect_ssrf(repo_path)->dict, the rules-as-data catalog SSRF_RULES, SKIP_DIRS, and is_excluded_path(relpath)->bool; modelled byte-for-contract on the existing ngv2/deser_detect.py and emitting findings in the SAME finding-dict shape ngv2/pattern_scanner.py uses (id/file/line/code/severity/cwe/owasp/description) so they flow unchanged through ngv2/confidence_signals.py — making the committed oracle tests/ngv2/test_ssrf_detect_wired.py GREEN"
dependencies: []
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

ngv2/ssrf_detect.py — NEW deterministic CWE-918 (Server-Side Request Forgery) recon scanner: walk a repo, flag HTTP-client sinks (`requests` / `urllib` / `httpx`) whose request URL is non-constant (attacker-influenceable), exclude vendored/test/docs/tooling paths and hardcoded-literal URLs, and return a fixed-shape report whose `findings` match the `pattern_scanner` finding shape.

# Scope

CREATE the NEW single-file module `ngv2/ssrf_detect.py` (NGv2 external-target task — `working_dir` = /home/xnihil0zer0/NobleGreedv2). This is the SSRF analog of the already-shipped `ngv2/deser_detect.py` (CWE-502) and closes the second of the three missing detectors (502 done, 918 here, 22 sibling). The module is PURE and stdlib-only (`os` + `re`): no network, clock, randomness, uuid, subprocess, MCP, or third-party imports, and no import of any sibling Epic-4 leaf. It walks a caller-supplied repo root, scans `*.py` files line-by-line against a small rules-as-data catalog `SSRF_RULES`, and returns a deterministic fixed-shape dict. Its `findings` carry the SAME keys `ngv2/pattern_scanner.py` emits (`id`/`file`/`line`/`code`/`severity`/`cwe`/`owasp`/`description`) so they flow unchanged through `ngv2/confidence_signals.py` (which reads `finding['id']` / `finding['cwe']`).

FALSE-POSITIVE control mirrors `_e2e_run/sink_quality.py`: (1) `is_excluded_path` drops vendored / test / docs / examples / tooling files; (2) a sink whose URL is a single hardcoded string literal with no dynamic marker (e.g. `requests.get("https://fixed.api/x")`) is NOT a finding — only name / f-string / concatenated / `.format` URLs are flagged, and dynamic-markers are evaluated with string-literal bodies blanked so a word inside a hardcoded URL never counts; (3) pure comment lines never match.

DISPATCH DIRECTIVE — PATCH FORMAT (MANDATORY — WHOLE-FILE): this is a NEW single-file module, so emit the COMPLETE file for `ngv2/ssrf_detect.py` (whole-file emission — NEVER a `__JANUSMASK_PATCHES__` symbol patch, never a manifest, never a dotted qualname). Reproduce it BYTE-FOR-BYTE exactly as follows:

```python
"""ngv2.ssrf_detect -- deterministic CWE-918 (Server-Side Request Forgery) scanner.

A PURE filesystem recon tool, modelled exactly on ``ngv2.deser_detect``: it
walks a caller-supplied repository root, scans ``*.py`` files for HTTP-client
*sinks* whose request URL is plausibly attacker-influenced (``requests`` /
``urllib`` / ``httpx``), and returns a fixed-shape report dict whose
``findings`` carry the SAME finding keys ``ngv2.pattern_scanner`` emits
(``id`` / ``file`` / ``line`` / ``code`` / ``severity`` / ``cwe`` / ``owasp`` /
``description``) so they flow unchanged through
``ngv2.confidence_signals.resolve_signals``.

Determinism / purity contract (identical to deser_detect):

* No network, clock, randomness, uuid, subprocess, or MCP.
* Filesystem access stays within the caller-provided root.
* Sorted directory traversal -> byte-stable output for identical inputs.
* All regexes compiled once at import time.

False-positive control (the SSRF analog of ``_e2e_run/sink_quality.py``):

* ``is_excluded_path`` drops vendored / test / docs / examples / tooling files
  -- a sink there is not a shipped, attacker-reachable library sink.
* A sink whose URL argument is a single hardcoded string literal with no
  dynamic marker (e.g. ``requests.get("https://fixed.api/x")``) is NOT a
  finding; only dynamic / name / f-string / concatenated URLs are flagged.
* Pure comment / docstring lines never match.
"""
from __future__ import annotations
import os
import re
from typing import Any, Dict, List

__all__ = ['detect_ssrf', 'SSRF_RULES', 'SKIP_DIRS', 'is_excluded_path']

# rules-as-data: id -> finding metadata + the line regex that detects the sink.
# Every rule is CWE-918. Keep this catalog small and grounded in the corpus
# (gptcache/litellm/etc. reach the network via requests / urllib / httpx).
SSRF_RULES: Dict[str, Dict[str, str]] = {
    'ssrf_requests': {
        'pattern': r'\brequests\.(?:get|post|put|patch|delete|head|request)\s*\(',
        'severity': 'high', 'cwe': 'CWE-918',
        'owasp': 'A10:2021-Server-Side Request Forgery',
        'description': 'HTTP request via requests with a non-constant URL (possible SSRF).',
    },
    'ssrf_urllib': {
        'pattern': r'\b(?:urllib\.request\.urlopen|urlopen|urllib\.request\.Request)\s*\(',
        'severity': 'high', 'cwe': 'CWE-918',
        'owasp': 'A10:2021-Server-Side Request Forgery',
        'description': 'urllib URL open with a non-constant URL (possible SSRF).',
    },
    'ssrf_httpx': {
        'pattern': r'\bhttpx\.(?:get|post|put|patch|delete|head|request|stream)\s*\(',
        'severity': 'high', 'cwe': 'CWE-918',
        'owasp': 'A10:2021-Server-Side Request Forgery',
        'description': 'HTTP request via httpx with a non-constant URL (possible SSRF).',
    },
}
SKIP_DIRS = {'.git', 'node_modules', '__pycache__', '.venv', 'venv', '.tox',
             '.eggs', '.mypy_cache', 'dist', 'build', '.pytest_cache', '.idea',
             '.hg', '.svn', 'site-packages', '.cache'}
_MAX_CONTEXT = 150
_HIGH_RISK_COUNT = 5

# Vendored / test / docs / tooling paths: a sink here is not a claimable
# shipped-library SSRF (mirrors _e2e_run/sink_quality.py _EXCLUDE_PATH).
_EXCLUDE_PATH = re.compile(
    r'(?:^|/)(?:_vendor/|vendor/|third[_-]?party/|node_modules/|'
    r'tests?/|testing/|fixtures?/|examples?/|samples?/|demo/|benchmark|'
    r'docs?/|scripts?/|_scripts/|ci/|\.github/|tools?/|setup\.py)',
    re.IGNORECASE,
)
# A call whose first argument is *only* a single string/bytes literal.
_PURE_STR_ARG = re.compile(r"""\(\s*[rbfu]*(['"]).*?\1\s*(?:,|\))""")
# A (non-f) string literal body, used to blank out literal contents so a
# dynamic marker that happens to live INSIDE a hardcoded URL string is ignored.
_STR_LITERAL = re.compile(r"""([rbuRBU]*)(['"]).*?\2""")
# An f-string prefix -> intrinsically dynamic.
_FSTRING = re.compile(r"""\b[rbuRBU]*[fF][rbuRBU]*['"]""")
# Structural dynamic markers (after literal bodies are blanked).
_DYN_STRUCT = re.compile(r"%|\.format\b|\+")
# URL-name markers that the URL is attacker-influenceable.
_DYN_WORDS = re.compile(
    r"\b(?:url|uri|endpoint|host|target|link|addr|address|server|req|request|"
    r"user|param|params|input|base_?url|dep)\b",
    re.IGNORECASE,
)
_COMPILED: List[tuple] = [(rid, re.compile(meta['pattern'])) for rid, meta in SSRF_RULES.items()]


def is_excluded_path(relpath: str) -> bool:
    """True if ``relpath`` is vendored/test/docs/tooling -- not a shipped sink."""
    return bool(_EXCLUDE_PATH.search(relpath.replace('\\', '/')))


def _blank_literals(s: str) -> str:
    """Replace string-literal bodies with empty quotes so dynamic markers found
    INSIDE a literal (e.g. ``user`` in ``"https://user.example.com"``) don't
    falsely make the argument look dynamic."""
    return _STR_LITERAL.sub(lambda m: m.group(1) + m.group(2) * 2, s)


def _is_literal_url_call(code: str, match_end: int) -> bool:
    """True if the sink's URL argument is a pure hardcoded string literal with
    no dynamic marker -- e.g. ``requests.get("https://fixed.api/x")`` -- i.e.
    NOT SSRF. Dynamic markers are evaluated on the arguments with literal
    bodies blanked, so content inside the URL string never counts."""
    tail = code[match_end - 1:]  # start at the '(' of the call (the arguments)
    blanked = _blank_literals(tail)
    if _FSTRING.search(tail) or _DYN_STRUCT.search(blanked) or _DYN_WORDS.search(blanked):
        return False
    return bool(_PURE_STR_ARG.match(tail))


def _risk_level(count: int) -> str:
    if count == 0:
        return 'none'
    if count >= _HIGH_RISK_COUNT:
        return 'high'
    if count >= 2:
        return 'medium'
    return 'low'


def detect_ssrf(repo_path: str) -> Dict[str, Any]:
    """Scan ``repo_path`` for CWE-918 SSRF sinks with dynamic URLs.

    Returns a deterministic, fixed-shape dict. A non-directory ``repo_path``
    yields the same shape with an ``error`` key and no findings.
    """
    if not os.path.isdir(repo_path):
        return {'repo_path': repo_path, 'files_checked': 0, 'has_ssrf': False,
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
                for rid, regex in _COMPILED:
                    m = regex.search(raw)
                    if not m:
                        continue
                    if _is_literal_url_call(raw, m.end()):
                        continue
                    meta = SSRF_RULES[rid]
                    findings.append({
                        'id': rid, 'file': relpath, 'line': lineno,
                        'code': stripped[:_MAX_CONTEXT], 'severity': meta['severity'],
                        'cwe': meta['cwe'], 'owasp': meta['owasp'],
                        'description': meta['description'],
                    })
    findings.sort(key=lambda f: (f['file'], f['line'], f['id']))
    return {'repo_path': repo_path, 'files_checked': files_checked,
            'has_ssrf': len(findings) > 0, 'risk_level': _risk_level(len(findings)),
            'total_findings': len(findings), 'findings': findings}
```

POST-EMIT SELF-CHECK (mandatory): the emitted file defines exactly the four public names in `__all__` (`detect_ssrf`, `SSRF_RULES`, `SKIP_DIRS`, `is_excluded_path`); `SSRF_RULES` has exactly three rules all with `cwe == 'CWE-918'`; the module imports only `os` / `re` / `typing`; there is NO network/clock/subprocess import.

# Required plan shape

EXACTLY ONE impl task. Use this task_id VERBATIM (the committed oracle and the operator decision file are keyed to it): `task_id`: `ngv2_ssrf_detect`. meta_task_type=`data_model` (NEW pure stdlib recon module — single-file whole-file emission, no production-harness edit). priority: high. dependencies: []. working_dir: "/home/xnihil0zer0/NobleGreedv2". files_touched: `["ngv2/ssrf_detect.py"]` ONLY. partial_edit semantics: WHOLE-FILE single-file emission per the DISPATCH DIRECTIVE — the DISPATCH DIRECTIVE — PATCH FORMAT block above (including the full pinned file content) MUST be copied VERBATIM into the task's `implementation_notes` so the blind worker sees it. verification_command: `python3 -m pytest -q tests/ngv2/test_ssrf_detect_wired.py` (CWD-relative — NO `cd`). The committed RED oracle tests/ngv2/test_ssrf_detect_wired.py is the authoritative acceptance contract — make it GREEN (13 tests); do NOT author new tests. `spec.functional_requirements` MUST be CONSOLIDATED to at most 5 entries, and `test_spec.unit_tests` MUST enumerate AT LEAST as many entries as `spec.functional_requirements` (validator floor: len(unit_tests) >= len(functional_requirements)); unit_tests entries are descriptors NAMING committed-oracle test cases (this does NOT authorize authoring new tests). `test_spec.regression_tests` MUST list at least two entries that NAME existing test cases from the committed oracle (plan descriptors referencing committed tests — this does NOT authorize authoring new tests), e.g. `test_detects_requests_dynamic_url_and_finding_shape`, `test_hardcoded_literal_url_is_not_flagged`, `test_excluded_paths_are_skipped`.

# Non-Goals

Do NOT touch `ngv2/pattern_scanner.py`, `ngv2/deser_detect.py`, `ngv2/confidence_signals.py`, `ngv2/semantic_signals.py`, `ngv2/sink_taxonomy.py`, or any other existing module — this leaf ships ONLY the new `ngv2/ssrf_detect.py`. Catalog/scan-path INTEGRATION (wiring `detect_ssrf` into the live scan catalog, selection_ranker demand terms, or `sink_taxonomy` weights) is OUT OF SCOPE — that integration is a separate downstream EDIT leaf; this brief delivers the standalone detector verified solely by its committed unit oracle. Do NOT author or modify any test — the oracle is committed and authoritative. Do NOT add taint/AST/dataflow analysis, network, wall-clock, randomness, subprocess, or logging. Do NOT import any third-party package or any sibling `ngv2/**` leaf. Do NOT add inter-procedural reachability — the literal-URL drop is the only reachability proxy in scope.

# Inputs

The committed authoritative oracle tests/ngv2/test_ssrf_detect_wired.py (currently RED — module does not yet exist). It pins: (i) the rules-as-data contract — `SSRF_RULES` is a non-empty dict, every value has keys `{pattern,severity,cwe,owasp,description}` with `cwe == 'CWE-918'`, and the three client families requests/urllib/httpx are represented; (ii) `SKIP_DIRS` superset; (iii) POSITIVES — `requests.get(url)` (dynamic name), `urlopen(target_url)`, `httpx.get(user_endpoint)`, `requests.get(f"https://{host}/api")`, `requests.post("https://api/" + path)` all detected with id `ssrf_*`, cwe `CWE-918`, and the finding dict carrying exactly `{id,file,line,code,severity,cwe,owasp,description}`; (iv) NEGATIVES / FP-exclusion — a hardcoded literal `requests.get("https://fixed.example.com/health")` is NOT flagged; comment/docstring lines ignored; sinks under `tests/`, `docs/`, `vendor/`, `setup.py` excluded (and `is_excluded_path('gptcache/utils/response.py')` is False); `node_modules/` & `.venv/` pruned; non-`.py` and json-only repos clean; (v) risk-level scaling, the non-directory `error` shape, and byte-stable determinism. Real-corpus grounding (zilliztech-gptcache): the detector fires on `requests.get(dep.data)` and `requests.get(url)` (2 precise findings, 0 FP). stdlib only (`os`, `re`, `typing`).

# Deliverables

The NEW file `ngv2/ssrf_detect.py` exactly as pinned in the DISPATCH DIRECTIVE: rules-as-data `SSRF_RULES` (3 CWE-918 rules), `SKIP_DIRS`, `is_excluded_path`, and `detect_ssrf(repo_path)->dict` whose findings match the `pattern_scanner` finding shape. Verified GREEN by `python3 -m pytest -q tests/ngv2/test_ssrf_detect_wired.py` (13 passed).
