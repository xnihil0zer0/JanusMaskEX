"""Semantic signals: wire the orphaned structural verifiers onto the hunt path.

This module converts ``Violation`` objects produced by the structural
verifiers (:class:`ngv2.ast_verifier.ASTVerifier` and
:class:`ngv2.treesitter_verifier.TreeSitterVerifier`) into the lightweight
``{tool, kind, result}`` signal dicts consumed by
:func:`ngv2.grounding_confidence_gate.compute_confidence`.

A signal with ``kind`` in ``{'taint_flow', 'formal_path', 'live_poc'}`` and
``result == 'proof'`` is treated by the confidence gate as a structural proof
that drives a finding to ``CONFIRMED``.  Here we emit such a proof only when an
execution-sink violation corroborates an exec-class finding; every other
ERROR-severity violation degrades to a plain structural ``'match'`` signal.

Design constraints:

* Pure / deterministic -- no network, clock, randomness, or subprocess.
* Never raises on malformed input; degenerate inputs yield ``[]``.
* The verifier classes (and their optional tree-sitter / z3 dependencies) are
  imported lazily inside the function body, so this module stays importable
  even when those grammar wheels are absent.
"""
from typing import Optional
_EXEC_RULES = frozenset({'os_system', 'process_exec', 'subprocess_no_check'})
_EXEC_FINDING = ('command_injection', 'cwe-78', 'eval', 'cwe-95')
_LANG_BY_SUFFIX = (('.jsx', 'javascript'), ('.tsx', 'javascript'), ('.py', 'python'), ('.js', 'javascript'), ('.ts', 'javascript'), ('.java', 'java'), ('.c', 'c'), ('.h', 'c'))

def _language_for(finding: dict) -> str:
    """Infer the source language from a finding's evidence/file path suffix.

    Degrades gracefully to ``"python"`` for missing/unknown inputs.
    """
    path = ''
    if isinstance(finding, dict):
        evidence = finding.get('evidence')
        if isinstance(evidence, (list, tuple)) and evidence:
            path = str(evidence[0])
        elif isinstance(evidence, str):
            path = evidence
        if not path:
            located = finding.get('file')
            if isinstance(located, str):
                path = located
    path = path.split(':', 1)[0].lower()
    for suffix, lang in _LANG_BY_SUFFIX:
        if path.endswith(suffix):
            return lang
    return 'python'

def _is_exec_finding(finding: dict) -> bool:
    """Return True when the finding is command/code-execution flavoured."""
    if not isinstance(finding, dict):
        return False
    parts = []
    for field_name in ('category', 'id', 'cwe'):
        value = finding.get(field_name)
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, (list, tuple)):
            parts.extend((str(item) for item in value))
    blob = ' '.join(parts).lower()
    return any((token in blob for token in _EXEC_FINDING))

def produce_semantic_signals(finding: dict, source_code: str, language: Optional[str]=None) -> list[dict]:
    """Run the structural verifiers and emit compute_confidence-shaped signals.

    Returns a list of ``{'tool', 'kind', 'result', 'rule'}`` dicts, proof
    signals sorted first then by rule.  Returns ``[]`` on any malformed,
    empty, or non-string source, on a failed lazy import, or when both
    verifiers fail.
    """
    if not isinstance(source_code, str) or not source_code.strip():
        return []
    lang = language if isinstance(language, str) and language else _language_for(finding)
    try:
        from ngv2.ast_verifier import ASTVerifier, SEVERITY_ERROR
        from ngv2.treesitter_verifier import TreeSitterVerifier
    except Exception:
        return []
    result = None
    try:
        result = TreeSitterVerifier().verify(source_code, lang)
    except Exception:
        try:
            result = ASTVerifier().verify(source_code)
        except Exception:
            return []
    if result is None:
        return []
    violations = getattr(result, 'violations', None) or []
    exec_finding = _is_exec_finding(finding)
    signals: list[dict] = []
    for violation in violations:
        rule = getattr(violation, 'rule', None)
        if rule == 'tree_sitter_unavailable':
            continue
        severity = getattr(violation, 'severity', None)
        if rule in _EXEC_RULES and exec_finding:
            signals.append({'tool': 'ast_verifier', 'kind': 'taint_flow', 'result': 'proof', 'rule': rule})
        elif severity == SEVERITY_ERROR:
            signals.append({'tool': 'ast_verifier', 'kind': 'structural', 'result': 'match', 'rule': rule})
    signals.sort(key=lambda signal: (0 if signal['result'] == 'proof' else 1, str(signal['rule'])))
    return signals