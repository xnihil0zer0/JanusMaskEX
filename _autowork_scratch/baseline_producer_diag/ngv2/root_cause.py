"""ngv2.root_cause -- deterministic adversarial root-cause analyzer.

When an injected vulnerability evades every detection layer, this module
classifies WHY (which detection layer has the gap) and recommends the concrete
corrective artifact to build.

The analysis is PURE and deterministic: no disk, no network, no clock, no
randomness, and only the standard library is used. Detection-tool availability
and per-injection coverage are supplied through an INJECTED-SEAM ``config``
mapping carrying explicit boolean flags (see ``DEFAULT_CONFIG``).
"""
from __future__ import annotations
from typing import Any, Dict, Mapping, Optional, Tuple
ROOT_CAUSE_CATEGORIES: Tuple[str, ...] = ('semgrep_gap', 'scanner_gap', 'taint_spec_missing', 'claude_limitation', 'system_limitation')
DEFAULT_CONFIG: Dict[str, bool] = {'semgrep_available': True, 'scanner_available': True, 'joern_available': False, 'codeql_available': False, 'semgrep_coverage': False, 'scanner_coverage': False, 'taint_spec_coverage': False}
ACTION_MAP: Dict[str, Dict[str, str]] = {'semgrep_gap': {'action': 'write_semgrep_rule', 'artifact_type': 'semgrep_rule', 'target_dir': 'artifacts/semgrep_rules/', 'details_template': 'Add a Semgrep rule covering {cwe} in {file}: match sink {expected_sink} reached from source {expected_source}. Injected code: {injected_code}'}, 'scanner_gap': {'action': 'write_scanner_pattern', 'artifact_type': 'scanner_pattern', 'target_dir': 'artifacts/scanner_patterns/', 'details_template': 'Add a scanner pattern for {cwe} in {file}: flag sink {expected_sink} tainted by {expected_source}. Injected code: {injected_code}'}, 'taint_spec_missing': {'action': 'write_taint_spec', 'artifact_type': 'taint_spec', 'target_dir': 'artifacts/taint_specs/', 'details_template': 'Add a taint specification for {cwe} in {file}: declare {expected_source} as a source and {expected_sink} as a sink. Injected code: {injected_code}'}, 'claude_limitation': {'action': 'document_detection_gap', 'artifact_type': 'fp_pattern', 'target_dir': 'artifacts/fp_patterns/', 'details_template': 'Document the manual-review miss for {cwe} in {file}: {expected_source} -> {expected_sink}. Injected code: {injected_code}'}, 'system_limitation': {'action': 'log_capability_gap', 'artifact_type': 'capability_log', 'target_dir': 'artifacts/capability_logs/', 'details_template': 'Log a system capability gap for {cwe} in {file}: no layer can currently distinguish {expected_source} -> {expected_sink}. Injected code: {injected_code}'}}

def _resolve_config(config: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Return a fresh config dict: DEFAULT_CONFIG overlaid with ``config``.

    Never mutates the caller's mapping or the module-level default.
    """
    resolved: Dict[str, Any] = dict(DEFAULT_CONFIG)
    if config:
        resolved.update(config)
    return resolved

def _render_context(injection: Mapping[str, Any]) -> Dict[str, str]:
    """Build a safe, fully-populated formatting context from an injection."""
    return {'id': str(injection.get('id', 'UNKNOWN')), 'cwe': str(injection.get('cwe', 'CWE-UNKNOWN')), 'file': str(injection.get('file', '<unknown>')), 'complexity': str(injection.get('complexity', 'unknown')), 'injected_code': str(injection.get('injected_code', '')), 'expected_source': str(injection.get('expected_source', '')), 'expected_sink': str(injection.get('expected_sink', ''))}

def classify_root_cause(injection: Mapping[str, Any], scan_layers: Mapping[str, Mapping[str, Any]], config: Optional[Mapping[str, Any]]=None) -> str:
    """Classify why an evaded injection slipped through every detection layer.

    Walks the detection layers in priority order and returns the first
    category whose coverage gap explains the miss. ``config`` carries the
    injected coverage/availability seam flags (defaults to ``DEFAULT_CONFIG``).
    """
    cfg = _resolve_config(config)
    if cfg.get('semgrep_available') and (not cfg.get('semgrep_coverage')):
        return 'semgrep_gap'
    if cfg.get('scanner_available') and (not cfg.get('scanner_coverage')):
        return 'scanner_gap'
    formal_available = cfg.get('joern_available') or cfg.get('codeql_available')
    if formal_available and (not cfg.get('taint_spec_coverage')):
        return 'taint_spec_missing'
    claude_layer = scan_layers.get('claude_code', {}) if scan_layers else {}
    if not claude_layer.get('detected'):
        return 'claude_limitation'
    return 'system_limitation'

def recommend_action(category: str, injection: Mapping[str, Any]) -> Dict[str, str]:
    """Map a root-cause category to its concrete corrective action.

    Unknown categories fall back to the ``system_limitation`` action. The
    returned ``details`` field is the rendered template referencing the
    injection content.
    """
    entry = ACTION_MAP.get(category, ACTION_MAP['system_limitation'])
    context = _render_context(injection)
    return {'action': entry['action'], 'artifact_type': entry['artifact_type'], 'target_dir': entry['target_dir'], 'details': entry['details_template'].format(**context)}

def analyze_failure(injection: Mapping[str, Any], scan_layers: Mapping[str, Mapping[str, Any]], config: Optional[Mapping[str, Any]]=None) -> Dict[str, Any]:
    """Produce a structured root-cause verdict for an evaded injection."""
    category = classify_root_cause(injection, scan_layers, config)
    action = recommend_action(category, injection)
    injection_id = str(injection.get('id', 'UNKNOWN'))
    cwe = str(injection.get('cwe', 'CWE-UNKNOWN'))
    analysis_notes = f"Injection {injection_id} ({cwe}) evaded all detection layers; root cause attributed to '{category}'. Recommended corrective action: {action['action']} -> {action['artifact_type']} in {action['target_dir']}."
    return {'injection_id': injection_id, 'cwe': cwe, 'root_cause_category': category, 'recommended_action': action, 'corrective_artifact_type': action['artifact_type'], 'analysis_notes': analysis_notes}
__all__ = ['classify_root_cause', 'recommend_action', 'analyze_failure', 'ROOT_CAUSE_CATEGORIES', 'ACTION_MAP', 'DEFAULT_CONFIG']