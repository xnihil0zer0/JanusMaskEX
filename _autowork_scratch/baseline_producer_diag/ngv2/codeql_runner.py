"""ngv2.codeql_runner — deterministic, stdlib-only CodeQL-CLI adapter.

This module is a pure shell around the CodeQL CLI. The REAL ``codeql`` binary
lives at NGv2 runtime; this module NEVER invokes, imports, or spawns it. The
external command is abstracted behind an injected callable seam::

    runner(argv) -> (exit_code, stdout, stderr, sarif)

where ``argv`` is the CodeQL argument vector this module assembles and ``sarif``
is the parsed SARIF object the ``database analyze`` command would have produced
(``None`` for commands such as ``database create``). Every engine call is routed
through that injected seam, so the module is side-effect-free with respect to the
real environment and trivially testable with scripted doubles.

Only the Python standard library is imported.
"""
from __future__ import annotations
import os
from typing import Any, Callable, Dict, List, Optional, Tuple
Runner = Callable[[List[str]], Tuple[int, str, str, Any]]
SECURITY_SUITES: Dict[str, str] = {'python': 'python-security-extended.qls', 'javascript': 'javascript-security-extended.qls', 'go': 'go-security-extended.qls', 'java': 'java-security-extended.qls'}
FINDING_FIELDS: Tuple[str, ...] = ('rule_id', 'severity', 'message', 'file', 'line', 'cwe', 'description', 'source')
SEVERITY_MAP: Dict[str, str] = {'error': 'high', 'warning': 'medium', 'note': 'low'}
_DEFAULT_SEVERITY = 'medium'
_MESSAGE_LIMIT = 500

def _extract_cwes(tags: Any) -> List[str]:
    """Pull ``CWE-<n>`` identifiers out of a rule's ``properties.tags`` list."""
    cwes: List[str] = []
    if not isinstance(tags, (list, tuple)):
        return cwes
    for tag in tags:
        if not isinstance(tag, str):
            continue
        idx = tag.lower().rfind('cwe-')
        if idx >= 0:
            number = tag[idx + len('cwe-'):].strip()
            if number:
                cwes.append('CWE-' + number)
    return cwes

def _index_rules(run: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Build a ruleId -> rule mapping for one SARIF run."""
    driver = (run.get('tool') or {}).get('driver') or {}
    rules = driver.get('rules') or []
    index: Dict[str, Dict[str, Any]] = {}
    for rule in rules:
        if isinstance(rule, dict):
            ident = rule.get('id')
            if isinstance(ident, str):
                index[ident] = rule
    return index

def parse_sarif(sarif: Any) -> List[Dict[str, Any]]:
    """Translate a SARIF document into a flat list of finding dicts.

    Each finding contains exactly the keys in :data:`FINDING_FIELDS`. Missing
    locations, unknown rules, and absent CWE tags fall back to documented
    defaults; messages are truncated to :data:`_MESSAGE_LIMIT` characters.
    """
    findings: List[Dict[str, Any]] = []
    if not isinstance(sarif, dict):
        return findings
    for run in sarif.get('runs') or []:
        if not isinstance(run, dict):
            continue
        rules = _index_rules(run)
        for result in run.get('results') or []:
            if not isinstance(result, dict):
                continue
            rule_id = result.get('ruleId') or ''
            rule = rules.get(rule_id, {})
            level = (rule.get('defaultConfiguration') or {}).get('level') if isinstance(rule, dict) else None
            severity = SEVERITY_MAP.get(level, _DEFAULT_SEVERITY)
            description = ''
            if isinstance(rule, dict):
                short = rule.get('shortDescription') or {}
                description = short.get('text') or ''
            cwe = []
            if isinstance(rule, dict):
                properties = rule.get('properties') or {}
                cwe = _extract_cwes(properties.get('tags'))
            message = (result.get('message') or {}).get('text') or ''
            message = message[:_MESSAGE_LIMIT]
            file_uri = ''
            line = 0
            locations = result.get('locations') or []
            if locations and isinstance(locations[0], dict):
                physical = locations[0].get('physicalLocation') or {}
                artifact = physical.get('artifactLocation') or {}
                file_uri = artifact.get('uri') or ''
                region = physical.get('region') or {}
                line = region.get('startLine') or 0
            findings.append({'rule_id': rule_id, 'severity': severity, 'message': message, 'file': file_uri, 'line': line, 'cwe': cwe, 'description': description, 'source': 'codeql'})
    return findings

def _require_language(language: str) -> str:
    """Return the security suite for *language* or raise ValueError."""
    if language not in SECURITY_SUITES:
        raise ValueError('unsupported language %r (expected one of %s)' % (language, ', '.join(sorted(SECURITY_SUITES))))
    return SECURITY_SUITES[language]

def create_database(repo_path: str, language: str, runner: Runner) -> str:
    """Create a CodeQL database for *repo_path* in *language* via *runner*.

    Returns the deterministic database name ``<repo-basename>-<language>``.
    Raises ValueError for an unsupported language and RuntimeError if the
    injected runner reports a non-zero exit code.
    """
    _require_language(language)
    db_name = os.path.basename(os.path.normpath(repo_path)) + '-' + language
    argv = ['database', 'create', db_name, '--language=' + language, '--source-root', repo_path, '--overwrite']
    exit_code, _stdout, stderr, _sarif = runner(argv)
    if exit_code != 0:
        raise RuntimeError('codeql database create failed (exit %s): %s' % (exit_code, stderr))
    return db_name

def run_security_queries(database: str, language: str, runner: Runner) -> List[Dict[str, Any]]:
    """Run the security-extended suite for *language* against *database*.

    Returns the parsed findings. Raises ValueError for an unsupported language
    and RuntimeError if the injected runner reports a non-zero exit code.
    """
    suite = _require_language(language)
    argv = ['database', 'analyze', database, suite, '--format=sarif-latest', '--output=-']
    exit_code, _stdout, stderr, sarif = runner(argv)
    if exit_code != 0:
        raise RuntimeError('codeql database analyze failed (exit %s): %s' % (exit_code, stderr))
    return parse_sarif(sarif)

def verify_taint_path(database: str, source: str, sink: str, cwe: str, runner: Runner) -> Dict[str, Any]:
    """Confirm whether a taint path from *source* to *sink* exists in *database*.

    On a non-zero exit the result has ``confirmed=None`` and an ``error`` string.
    Otherwise ``confirmed`` is True when any finding was returned, and ``path``
    lists ``<file>:<line> — <message>`` entries for each finding.
    """
    argv = ['database', 'analyze', database, '--format=sarif-latest', '--output=-', '--source=' + source, '--sink=' + sink, '--cwe=' + cwe]
    exit_code, _stdout, stderr, sarif = runner(argv)
    if exit_code != 0:
        return {'confirmed': None, 'findings_count': 0, 'path': [], 'query_time_s': 0.0, 'error': stderr}
    findings = parse_sarif(sarif)
    path = ['%s:%s — %s' % (f['file'], f['line'], f['message']) for f in findings]
    return {'confirmed': bool(findings), 'findings_count': len(findings), 'path': path, 'query_time_s': 0.0, 'error': ''}

def run_custom_spec(database: str, ql_spec: str, runner: Runner) -> List[Dict[str, Any]]:
    """Run a custom QL spec against *database* through the injected runner.

    Returns parsed findings on success, or ``[{"error": <stderr>}]`` when the
    injected runner reports a non-zero exit code.
    """
    argv = ['database', 'analyze', database, ql_spec, '--format=sarif-latest', '--output=-']
    exit_code, _stdout, stderr, sarif = runner(argv)
    if exit_code != 0:
        return [{'error': stderr}]
    return parse_sarif(sarif)

def make_mock_runner(exit_code: int=0, stdout: str='', stderr: str='', sarif: Any=None) -> Runner:
    """Return a runner that ignores its argv and yields a constant 4-tuple."""

    def _runner(argv: List[str]) -> Tuple[int, str, str, Any]:
        return (exit_code, stdout, stderr, sarif)
    return _runner

def make_subprocess_runner(codeql_bin: str='codeql', *, cwd: Optional[str]=None, timeout: Optional[float]=None) -> Runner:
    """Return the REAL subprocess-backed runner that shells the codeql binary.

    The returned callable runs ``[codeql_bin] + argv`` and yields the
    ``(exit_code, stdout, stderr, sarif)`` 4-tuple the module's command builders
    expect. CodeQL 2.25.1 treats ``database analyze --output`` as a MANDATORY
    **file path** (``-`` is NOT a stdout stream), so any ``--output=-`` token in
    the argv is rewritten to a private temp SARIF file; after the run that file
    is parsed into the ``sarif`` slot (falling back to parsing stdout, which
    keeps scripted/mocked seams working) and is ALWAYS deleted. ``subprocess``
    and ``tempfile`` are imported lazily inside the body so this module stays
    importable with only stdlib at module scope and so the oracle can script it
    without ever spawning codeql.
    """

    def _runner(argv: List[str]) -> Tuple[int, str, str, Any]:
        import json as _json
        import subprocess as _subprocess
        import tempfile as _tempfile
        argv = list(argv)
        wants_sarif = any((isinstance(a, str) and a.startswith('--format=sarif') for a in argv))
        out_file: Optional[str] = None
        for i, a in enumerate(argv):
            if a == '--output=-':
                fd, out_file = _tempfile.mkstemp(suffix='.sarif', dir=cwd)
                os.close(fd)
                argv[i] = '--output=' + out_file
        full = [codeql_bin] + argv
        try:
            proc = _subprocess.run(full, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        except Exception as exc:
            if out_file is not None and os.path.exists(out_file):
                os.remove(out_file)
            return (1, '', 'codeql subprocess failed: %s' % exc, None)
        sarif: Any = None
        if wants_sarif:
            if out_file is not None and os.path.exists(out_file):
                try:
                    with open(out_file, 'r', encoding='utf-8') as fh:
                        text = fh.read()
                    if text.strip():
                        sarif = _json.loads(text)
                except (OSError, ValueError):
                    sarif = None
            if sarif is None and proc.stdout and proc.stdout.strip():
                try:
                    sarif = _json.loads(proc.stdout)
                except ValueError:
                    sarif = None
        if out_file is not None and os.path.exists(out_file):
            os.remove(out_file)
        return (proc.returncode, proc.stdout, proc.stderr, sarif)
    return _runner
def make_scripted_runner(script: Dict[str, Tuple[int, str, str, Any]], default: Tuple[int, str, str, Any]=(0, '', '', None)) -> Runner:
    """Return a runner that dispatches on the first argv token (the verb).

    Unknown verbs deterministically yield *default* and never raise.
    """

    def _runner(argv: List[str]) -> Tuple[int, str, str, Any]:
        verb = argv[0] if argv else ''
        return script.get(verb, default)
    return _runner
