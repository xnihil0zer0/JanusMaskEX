"""ngv2.codeql_lead_source -- CodeQL-backed PRIMARY lead source for the hunt FSM.

The hunt's regex ``pattern_scanner`` surfaces SYNTACTIC sinks, not attacker
REACHABLE ones, so synthesized PoCs die at the ``poc_authenticity`` /
``sink_reachability`` gates. CodeQL's security-extended suites give true
interprocedural source->sink taint, so a finding it emits is reachability
VERIFIED by construction.

This module is the bridge between :mod:`ngv2.codeql_runner` (the pure CLI shell)
and the agy candidate shape the rest of the FSM consumes
(see :func:`ngv2.hunt_lead_client._normalize_candidate`). Two public entry
points:

* :func:`codeql_scan` -- detect languages, build a DB per language, run the
  security suite, parse the SARIF, and ENRICH each finding with the sink code
  line (``call_sites``), an inferred ``sink_name``, a normalized CWE
  ``category``, the taint SOURCE location (pulled from SARIF ``codeFlows`` /
  ``relatedLocations``, which :func:`codeql_runner.parse_sarif` drops), and
  ``reachable=True``.
* :func:`findings_to_candidates` -- map enriched findings onto the EXACT agy
  candidate shape, importable without ever invoking codeql.

Stdlib-only at module scope, deterministic, and fail-soft: any
subprocess/parse/IO error in :func:`codeql_scan` yields ``[]`` (never raises);
a per-finding enrichment error keeps the finding with best-effort fields.
"""
from __future__ import annotations

import os
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from ngv2 import codeql_runner

# Fail-soft optional imports -- mirror how sink_extract is consumed elsewhere.
try:  # pragma: no cover - trivial import guard
    from ngv2 import sink_extract as _sink_extract
except Exception:  # pragma: no cover
    _sink_extract = None  # type: ignore

DEFAULT_CODEQL_BIN = '/home/xnihil0zer0/tools/codeql/codeql'

_LANG_EXTENSIONS = {
    'python': ('.py',),
    'javascript': ('.js', '.jsx', '.ts', '.tsx', '.mjs', '.cjs'),
}
_SKIP_DIRS = {'.git', '.venv', 'venv', 'node_modules', '__pycache__',
              'build', 'dist', '.tox', '.mypy_cache', '.pytest_cache'}
_CONTEXT_LINES = 1


def detect_languages(repo_path: str) -> List[str]:
    """Return the CodeQL languages present in ``repo_path`` (deterministic order).

    ``python`` if any ``.py`` exists; ``javascript`` if any JS/TS file exists.
    Bounded walk that skips vendored/VCS dirs. Fail-soft: any error -> ``[]``.
    """
    found = {lang: False for lang in _LANG_EXTENSIONS}
    if not isinstance(repo_path, str) or not os.path.isdir(repo_path):
        return []
    try:
        for root, dirs, files in os.walk(repo_path):
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith('.')]
            for name in files:
                for lang, exts in _LANG_EXTENSIONS.items():
                    if not found[lang] and name.endswith(exts):
                        found[lang] = True
            if all(found.values()):
                break
    except Exception:
        return []
    # Deterministic order: python before javascript.
    return [lang for lang in ('python', 'javascript') if found[lang]]


def detect_codeql_bin(codeql_bin: Optional[str] = None) -> Optional[str]:
    """Resolve the codeql binary: arg > env NGV2_CODEQL_BIN > default path > PATH.

    Returns the resolved path/name, or ``None`` when nothing is usable.
    """
    candidates: List[str] = []
    if codeql_bin:
        candidates.append(codeql_bin)
    env = os.environ.get('NGV2_CODEQL_BIN')
    if env:
        candidates.append(env)
    candidates.append(DEFAULT_CODEQL_BIN)
    for cand in candidates:
        try:
            if os.path.isfile(cand) and os.access(cand, os.X_OK):
                return cand
        except Exception:
            continue
    # Fall back to PATH lookup of bare 'codeql'.
    try:
        import shutil
        which = shutil.which('codeql')
        if which:
            return which
    except Exception:
        pass
    return None


def codeql_available(codeql_bin: Optional[str] = None) -> bool:
    """True when a codeql binary can be resolved (does NOT execute it)."""
    return detect_codeql_bin(codeql_bin) is not None


def _normalize_cwe(cwe: Any) -> str:
    """Strip the SARIF zero-pad and pick the primary CWE.

    ``['CWE-078', 'CWE-088']`` -> ``'CWE-78'``. Non-list / empty -> ``''``.
    """
    items: List[str] = []
    if isinstance(cwe, (list, tuple)):
        items = [c for c in cwe if isinstance(c, str)]
    elif isinstance(cwe, str):
        items = [cwe]
    for raw in items:
        low = raw.strip()
        idx = low.lower().rfind('cwe-')
        if idx < 0:
            continue
        number = low[idx + len('cwe-'):].strip().lstrip('0') or '0'
        return 'CWE-' + number
    return ''


def _read_snippet(repo_path: str, rel_file: str, line: Any) -> str:
    """Read the sink code line (+ a little context) from ``repo/rel_file``.

    Fail-soft: missing file / bad line -> ``''``. Returns the stripped sink line
    with one line of surrounding context joined by newlines.
    """
    if not rel_file or not isinstance(line, int) or line <= 0:
        return ''
    try:
        abs_path = rel_file if os.path.isabs(rel_file) else os.path.join(repo_path, rel_file)
        with open(abs_path, 'r', errors='replace') as fh:
            lines = fh.readlines()
    except Exception:
        return ''
    if line > len(lines):
        return ''
    # The sink line itself, left-stripped so it is ALWAYS parseable on its own
    # (ast.parse rejects indented source) -- the reachability gate ast-parses
    # each call_site, so an indented multi-line block silently reads as
    # unreachable. ``textwrap.dedent`` only removes the COMMON leading
    # whitespace, which is insufficient when the sink sits in a nested block, so
    # we pin the stripped sink line as the parseable snippet.
    sink_line = lines[line - 1].strip()
    return sink_line


def _extract_source_location(result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Pull the taint SOURCE physical location from a SARIF result.

    Preference order: first ``codeFlows[].threadFlows[].locations[0]`` (the taint
    entry point), else the first ``relatedLocations[]`` with a region. Returns
    ``{'file', 'line'}`` or ``None``. :func:`codeql_runner.parse_sarif` drops
    this, so we read it directly off the raw SARIF result.
    """
    if not isinstance(result, dict):
        return None

    def _phys_to_loc(phys: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(phys, dict):
            return None
        artifact = phys.get('artifactLocation') or {}
        uri = artifact.get('uri') if isinstance(artifact, dict) else None
        region = phys.get('region') or {}
        start = region.get('startLine') if isinstance(region, dict) else None
        if not uri:
            return None
        return {'file': uri, 'line': start or 0}

    code_flows = result.get('codeFlows')
    if isinstance(code_flows, list):
        for flow in code_flows:
            thread_flows = (flow or {}).get('threadFlows') if isinstance(flow, dict) else None
            if not isinstance(thread_flows, list):
                continue
            for tf in thread_flows:
                locs = (tf or {}).get('locations') if isinstance(tf, dict) else None
                if not isinstance(locs, list) or not locs:
                    continue
                first = locs[0] if isinstance(locs[0], dict) else {}
                phys = (first.get('location') or {}).get('physicalLocation') if isinstance(first, dict) else None
                loc = _phys_to_loc(phys)
                if loc is not None:
                    return loc
    related = result.get('relatedLocations')
    if isinstance(related, list):
        for rl in related:
            phys = rl.get('physicalLocation') if isinstance(rl, dict) else None
            loc = _phys_to_loc(phys)
            if loc is not None:
                return loc
    return None


# Rule-implied sink hints for findings whose snippet does not parse to a known
# dotted call (best-effort fallback so sink_name is never empty for known rules).
_RULE_SINK_HINTS = {
    'py/command-line-injection': 'subprocess.Popen',
    'py/shell-command-constructed-from-input': 'os.system',
    'py/code-injection': 'eval',
    'py/unsafe-deserialization': 'pickle.loads',
    'py/server-side-request-forgery': 'requests.get',
    'py/full-server-side-request-forgery': 'requests.get',
    'py/path-injection': 'open',
    'py/sql-injection': 'cursor.execute',
}


def _index_raw_results(sarif: Any) -> List[Dict[str, Any]]:
    """Flatten raw SARIF results across runs (preserves order)."""
    out: List[Dict[str, Any]] = []
    if not isinstance(sarif, dict):
        return out
    for run in sarif.get('runs') or []:
        if not isinstance(run, dict):
            continue
        for result in run.get('results') or []:
            if isinstance(result, dict):
                out.append(result)
    return out


def _enrich(finding: Dict[str, Any], raw_result: Optional[Dict[str, Any]],
            repo_path: str) -> Dict[str, Any]:
    """Enrich one parsed finding with snippet, sink_name, normalized CWE, source.

    Best-effort and never raises: each sub-step is guarded so a parse/IO error on
    one field keeps the finding with the other fields populated.
    """
    out = dict(finding)
    out['source'] = 'codeql'
    out['reachable'] = True

    # Normalize CWE -> primary category.
    try:
        category = _normalize_cwe(finding.get('cwe'))
    except Exception:
        category = ''
    out['category'] = category

    # Read the sink code line for the call_sites snippet.
    snippet = ''
    try:
        snippet = _read_snippet(repo_path, finding.get('file', ''), finding.get('line'))
    except Exception:
        snippet = ''
    out['call_sites'] = [snippet] if snippet else []

    # Infer sink_name: sink_extract on the snippet, else rule-implied hint.
    sink_name = ''
    try:
        if snippet and _sink_extract is not None:
            extracted = _sink_extract.extract_sink(snippet)
            if extracted is not None:
                sink_name = extracted.get('sink_name') or ''
                # Prefer the snippet-derived category when we have one and the
                # SARIF CWE was empty.
                if not category and extracted.get('category'):
                    out['category'] = extracted['category']
    except Exception:
        sink_name = ''
    if not sink_name:
        sink_name = _RULE_SINK_HINTS.get(finding.get('rule_id', ''), '')
    out['sink_name'] = sink_name

    # Extract the taint SOURCE location from the raw SARIF result.
    try:
        src = _extract_source_location(raw_result) if raw_result is not None else None
    except Exception:
        src = None
    if src is not None:
        out['source_location'] = src

    return out


def codeql_scan(repo_path: str, *, db_root: str = 'tmp/codeql',
                codeql_bin: Optional[str] = None,
                languages: Optional[List[str]] = None,
                runner: Optional[codeql_runner.Runner] = None,
                query_suite: Optional[str] = None,
                timeout: int = 900) -> List[Dict[str, Any]]:
    """Build a CodeQL DB per detected language, run the security suite, enrich.

    Returns a list of enriched, reachability-verified finding dicts. Reuses
    :mod:`ngv2.codeql_runner` for the DB build/analyze seam (so tests can inject
    a scripted ``runner``). When ``runner`` is not given the real subprocess
    runner is constructed from the resolved codeql binary.

    Fail-soft: any subprocess / parse / IO error returns ``[]`` and NEVER raises.
    """
    if not isinstance(repo_path, str) or not os.path.isdir(repo_path):
        return []

    langs = languages if languages is not None else detect_languages(repo_path)
    if not langs:
        return []

    use_runner = runner
    if use_runner is None:
        resolved = detect_codeql_bin(codeql_bin)
        if not resolved:
            return []
        try:
            use_runner = codeql_runner.make_subprocess_runner(resolved, timeout=timeout)
        except Exception:
            return []

    enriched: List[Dict[str, Any]] = []
    for language in langs:
        if language not in codeql_runner.SECURITY_SUITES:
            continue
        try:
            db_name = codeql_runner.create_database(repo_path, language, use_runner)
        except Exception:
            continue
        # Collect both parsed findings AND raw results so we can recover the
        # taint source location parse_sarif drops. We re-run analyze through the
        # same seam to capture the raw SARIF.
        try:
            sarif = _run_analyze_raw(db_name, language, use_runner, query_suite)
        except Exception:
            continue
        try:
            parsed = codeql_runner.parse_sarif(sarif)
        except Exception:
            parsed = []
        raw_results = _index_raw_results(sarif)
        for idx, finding in enumerate(parsed):
            raw = raw_results[idx] if idx < len(raw_results) else None
            try:
                enriched.append(_enrich(finding, raw, repo_path))
            except Exception:
                # Per-finding failure -> keep best-effort minimal record.
                rec = dict(finding)
                rec['source'] = 'codeql'
                rec['reachable'] = True
                rec.setdefault('category', '')
                rec.setdefault('call_sites', [])
                rec.setdefault('sink_name', '')
                enriched.append(rec)
    return enriched


def _run_analyze_raw(database: str, language: str,
                     runner: codeql_runner.Runner,
                     query_suite: Optional[str]) -> Any:
    """Run the security suite and return the RAW SARIF object (not parsed).

    Mirrors :func:`codeql_runner.run_security_queries`'s argv but returns the
    SARIF the runner produced so source-location extraction can read codeFlows.
    Raises on a non-zero exit so :func:`codeql_scan` can skip the language.
    """
    suite = query_suite or codeql_runner.SECURITY_SUITES[language]
    argv = ['database', 'analyze', database, suite, '--format=sarif-latest', '--output=-']
    exit_code, _stdout, stderr, sarif = runner(argv)
    if exit_code != 0:
        raise RuntimeError('codeql analyze failed (exit %s): %s' % (exit_code, stderr))
    return sarif


def findings_to_candidates(findings: List[Dict[str, Any]],
                           target: Any) -> List[Dict[str, Any]]:
    """Map enriched CodeQL findings onto the agy candidate shape EXACTLY.

    Carries ``sink_name``, ``call_sites`` (the sink snippet), ``category``
    (normalized CWE), ``evidence`` (``["file:line"]``), the
    ``codeql_reachable``/``reachable`` flag, and the taint ``source`` entry
    location (as ``source_location``, helps poc entrypoint). Importable without
    invoking codeql. Reuses :func:`hunt_lead_client._normalize_candidate` so the
    output is byte-identical to the agy/regex paths.
    """
    if not isinstance(findings, list):
        return []
    # Import lazily so this module stays importable even if hunt_lead_client
    # changes; fall back to a local replication if needed.
    try:
        from ngv2.hunt_lead_client import _normalize_candidate
    except Exception:
        _normalize_candidate = None  # type: ignore

    candidates: List[Dict[str, Any]] = []
    for index, finding in enumerate(findings):
        if not isinstance(finding, dict):
            continue
        category = finding.get('category') or _normalize_cwe(finding.get('cwe')) or 'CWE-000'
        sink_name = finding.get('sink_name') or ''
        call_sites = finding.get('call_sites')
        if not isinstance(call_sites, list):
            call_sites = [call_sites] if call_sites else []
        file_uri = finding.get('file') or ''
        line = finding.get('line') or 0
        evidence = ['{0}:{1}'.format(file_uri, line)] if file_uri else []
        snippet = call_sites[0] if call_sites else ''
        title = '{0} via {1}'.format(category, sink_name or finding.get('rule_id') or 'sink')
        raw: Dict[str, Any] = {
            'title': title,
            'category': category,
            'severity': finding.get('severity') or 'high',
            'description': finding.get('description') or finding.get('message') or '',
            'evidence': evidence,
            'sink_name': sink_name,
            'call_sites': call_sites,
            'expected_signature': snippet,
            'cwe': category,
            'source': 'codeql',
            'codeql_reachable': True,
            'reachable': True,
        }
        # Carry the taint source entry-point location for poc grounding.
        src = finding.get('source_location')
        if isinstance(src, dict):
            raw['source_location'] = src
            src_file = src.get('file')
            if src_file:
                raw['entrypoint'] = '{0}:{1}'.format(src_file, src.get('line') or 0)
        if _normalize_candidate is not None:
            cand = _normalize_candidate(raw, index, target)
        else:  # pragma: no cover - defensive fallback
            cand = dict(raw)
            cand.setdefault('id', 'HUNT-{0:03d}'.format(index + 1))
            cand.setdefault('target', target)
            cand.setdefault('expected_fs_signature', 'pwned_marker')
            cand.setdefault('success_marker', 'VULNERABLE')
        if cand is not None:
            # _normalize_candidate may not preserve our extra flags; re-assert.
            cand['source'] = 'codeql'
            cand['codeql_reachable'] = True
            cand['reachable'] = True
            candidates.append(cand)
    return candidates
