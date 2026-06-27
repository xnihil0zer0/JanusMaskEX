"""Pure, deterministic adversarial injection scorer for ngv2.

Compares a sealed injection log against a scan-results file to compute the
detection rate and attribute each detected injection to a pipeline layer.

The module is stdlib-only and fully deterministic: there is no clock, network,
or randomness anywhere. Every input is a plain JSON file and every output is a
function of those inputs, so the same files always produce the same result.
"""
from typing import Any, Dict, List, Optional, Tuple
import json
DETECTION_LAYERS: Tuple[str, ...] = ('scanner', 'semgrep', 'joern', 'codeql', 'claude_code')
CYCLE_RESULT_KEYS: Tuple[str, ...] = ('cycle', 'repo', 'total_injections', 'detected_count', 'evaded_count', 'detection_rate', 'evasion_rate', 'per_injection', 'per_layer_breakdown', 'per_cwe_breakdown', 'per_complexity_breakdown')

def _load_json(path: str) -> Any:
    """Read and parse a JSON document from ``path``."""
    with open(path, 'r') as f:
        return json.load(f)

def load_injection_log(path: str) -> Dict[str, Any]:
    """Load a sealed injection log; require an ``injections`` list.

    Raises ``ValueError`` when the document is not an object or is missing the
    ``injections`` key, so a malformed log fails loudly instead of silently
    scoring zero injections.
    """
    data = _load_json(path)
    if not isinstance(data, dict) or 'injections' not in data:
        raise ValueError("injection log missing 'injections' key: %r" % (path,))
    if not isinstance(data['injections'], list):
        raise ValueError("injection log 'injections' must be a list: %r" % (path,))
    return data

def load_scan_results(path: str) -> Dict[str, Any]:
    """Load a scan-results document and normalise it to a ``findings`` list.

    If the document already carries a ``findings`` list it is used as-is.
    Otherwise every top-level key ending in ``_findings`` (e.g.
    ``scanner_findings``, ``semgrep_findings``) is concatenated, in document
    order, into a synthesised ``findings`` list.
    """
    data = _load_json(path)
    if not isinstance(data, dict):
        raise ValueError('scan results must be a JSON object: %r' % (path,))
    findings: List[Dict[str, Any]] = []
    existing = data.get('findings')
    if isinstance(existing, list):
        findings.extend(existing)
    else:
        for field, value in data.items():
            if field.endswith('_findings') and isinstance(value, list):
                findings.extend(value)
    data['findings'] = findings
    return data

def _file_match(injection_file: str, detection_file: str) -> bool:
    """True when two paths refer to the same file, allowing prefix differences.

    The injection log records repo-relative paths while a scanner may report a
    longer absolute/checkout-relative path (or vice versa); a match holds when
    one path is the other path with a leading directory prefix stripped.
    """
    if not injection_file or not detection_file:
        return False
    if injection_file == detection_file:
        return True
    if detection_file.endswith('/' + injection_file):
        return True
    if injection_file.endswith('/' + detection_file):
        return True
    return False

def match_injection_to_detection(injection: Dict[str, Any], detections: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Return the first detection whose file and line cover ``injection``.

    A detection matches when its file resolves to the injection's file and its
    reported ``line`` falls within the inclusive ``[line_start, line_end]``
    range. Returns ``None`` when nothing matches.
    """
    injection_file = injection.get('file', '')
    line_start = injection.get('line_start')
    line_end = injection.get('line_end')
    for detection in detections:
        if not _file_match(injection_file, detection.get('file', '')):
            continue
        line = detection.get('line')
        if line is None:
            continue
        if line_start is not None and line < line_start:
            continue
        if line_end is not None and line > line_end:
            continue
        return detection
    return None

def classify_detection_layer(detection: Dict[str, Any]) -> str:
    """Attribute a detection to one of ``DETECTION_LAYERS``.

    Precedence: an explicit ``source`` wins first, then any layer named in
    ``grounding_evidence``, then the presence of a ``rule_id`` (semgrep-style)
    or an ``id`` (scanner finding). Anything unrecognised falls back to
    ``claude_code``.
    """
    source = str(detection.get('source') or '').lower()
    if source == 'codeql':
        return 'codeql'
    if source == 'joern':
        return 'joern'
    if source == 'semgrep':
        return 'semgrep'
    if source in ('analyzer', 'scanner'):
        return 'scanner'
    evidence = detection.get('grounding_evidence')
    if isinstance(evidence, list):
        for entry in evidence:
            if not isinstance(entry, dict):
                continue
            layer = str(entry.get('layer') or '').lower()
            if layer in DETECTION_LAYERS:
                return layer
    if detection.get('rule_id'):
        return 'semgrep'
    if detection.get('id'):
        return 'scanner'
    return 'claude_code'

def score_injection_cycle(injection_log_path: str, scan_results_path: str) -> Dict[str, Any]:
    """Score one injection cycle against its scan results.

    Returns a dict whose keys are exactly ``CYCLE_RESULT_KEYS``: headline
    counts and rates, a per-injection breakdown, and aggregate breakdowns by
    layer, CWE, and complexity. Detection/evasion rates guard against division
    by zero by falling back to a denominator of 1 when there are no injections.
    """
    injection_log = load_injection_log(injection_log_path)
    scan_results = load_scan_results(scan_results_path)
    findings = scan_results.get('findings', [])
    injections = injection_log.get('injections', [])
    total = len(injections)
    per_injection: List[Dict[str, Any]] = []
    per_layer: Dict[str, Dict[str, int]] = {layer: {'total_exposed': total, 'detected': 0} for layer in DETECTION_LAYERS}
    per_cwe: Dict[str, Dict[str, int]] = {}
    per_complexity: Dict[str, Dict[str, int]] = {}
    detected_count = 0
    for injection in injections:
        cwe = injection.get('cwe', 'UNKNOWN')
        complexity = injection.get('complexity', 'unknown')
        match = match_injection_to_detection(injection, findings)
        detected = match is not None
        if detected:
            layer = classify_detection_layer(match)
            detected_by_layer = layer
            detail = match.get('rule_id') or match.get('id') or layer
            detection_details = 'matched by %s via %s' % (layer, detail)
            detected_count += 1
            if layer in per_layer:
                per_layer[layer]['detected'] += 1
        else:
            detected_by_layer = 'undetected'
            detection_details = ''
        per_injection.append({'id': injection.get('id'), 'cwe': cwe, 'complexity': complexity, 'detected': detected, 'detected_by_layer': detected_by_layer, 'detection_details': detection_details})
        cwe_entry = per_cwe.setdefault(cwe, {'injected': 0, 'detected': 0, 'evaded': 0})
        complexity_entry = per_complexity.setdefault(complexity, {'injected': 0, 'detected': 0, 'evaded': 0})
        cwe_entry['injected'] += 1
        complexity_entry['injected'] += 1
        if detected:
            cwe_entry['detected'] += 1
            complexity_entry['detected'] += 1
        else:
            cwe_entry['evaded'] += 1
            complexity_entry['evaded'] += 1
    evaded_count = total - detected_count
    denominator = total if total > 0 else 1
    detection_rate = round(detected_count / denominator, 3)
    evasion_rate = round(evaded_count / denominator, 3)
    return {'cycle': injection_log.get('cycle'), 'repo': injection_log.get('repo'), 'total_injections': total, 'detected_count': detected_count, 'evaded_count': evaded_count, 'detection_rate': detection_rate, 'evasion_rate': evasion_rate, 'per_injection': per_injection, 'per_layer_breakdown': per_layer, 'per_cwe_breakdown': per_cwe, 'per_complexity_breakdown': per_complexity}