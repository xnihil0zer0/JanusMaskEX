"""ngv2.feedback_synth -- pure telemetry-to-diagnostic prompt formatter.

This module turns a previous PoC plus a detonation telemetry mapping into a
structured, deterministic diagnostic markdown prompt. It classifies the failure
into exactly one of three classes and bounds the size of captured streams.

The transform is pure: no I/O, no clock, no randomness. Calling
``build_diagnostic_prompt`` twice with identical inputs yields byte-identical
output.
"""
from __future__ import annotations
import re
from typing import Any, Dict, List, Optional
ENV_PATH_ERROR: str = 'ENV_PATH_ERROR'
SYNTAX_API_ERROR: str = 'SYNTAX_API_ERROR'
PAYLOAD_REFUTED: str = 'PAYLOAD_REFUTED'
_ENV_CATEGORIES = ('import_error', 'network_error')
_HEAD_LINES = 250
_TAIL_LINES = 750
_MAX_LINES = _HEAD_LINES + _TAIL_LINES
_DEPRECATION_RE = re.compile('(?:Pending)?DeprecationWarning|\\bwarnings?\\.warn\\b|is deprecated\\b', re.IGNORECASE)
_ENV_SIGNATURES = ('ModuleNotFoundError', 'ImportError', 'No module named', 'connection refused', 'ConnectionRefusedError', 'ConnectionError', 'Network is unreachable', 'Temporary failure in name resolution', 'Failed to establish a new connection', 'Name or service not known')
_SYNTAX_SIGNATURES = ('SyntaxError', 'IndentationError', 'TabError', 'TypeError', 'AttributeError')
try:
    from ngv2 import crash_analyzer as _crash_analyzer
except Exception:
    _crash_analyzer = None
try:
    from ngv2 import trace_parser as _trace_parser
except Exception:
    _trace_parser = None

def _error_patterns() -> Dict[str, List[str]]:
    """Return crash_analyzer.ERROR_PATTERNS, read live so patches are honored."""
    if _crash_analyzer is None:
        return {}
    patterns = getattr(_crash_analyzer, 'ERROR_PATTERNS', {})
    if isinstance(patterns, dict):
        return patterns
    return {}

def _infer_failure_mode(entry: Any) -> Optional[str]:
    """Call trace_parser.infer_failure_mode defensively, swallowing errors."""
    if _trace_parser is None:
        return None
    func = getattr(_trace_parser, 'infer_failure_mode', None)
    if func is None:
        return None
    try:
        result = func(entry)
    except Exception:
        return None
    if result is None:
        return None
    return str(result)

def _get_finding_id(prev_poc: Any) -> str:
    """Extract finding_id from an object attribute or a dict-style mapping."""
    if prev_poc is None:
        return 'unknown'
    if isinstance(prev_poc, dict):
        value = prev_poc.get('finding_id', 'unknown')
    else:
        value = getattr(prev_poc, 'finding_id', 'unknown')
    if value is None:
        return 'unknown'
    return str(value)

def _coerce_str(value: Any) -> str:
    if value is None:
        return ''
    if isinstance(value, str):
        return value
    return str(value)

def _matches_any(patterns: List[str], text: str) -> bool:
    lowered = text.lower()
    for pat in patterns:
        if not isinstance(pat, str):
            continue
        try:
            if re.search(pat, text, re.IGNORECASE):
                return True
        except re.error:
            if pat.lower() in lowered:
                return True
    return False

def _has_env_signature(text: str) -> bool:
    lowered = text.lower()
    for sig in _ENV_SIGNATURES:
        if sig.lower() in lowered:
            return True
    patterns = _error_patterns()
    for category in _ENV_CATEGORIES:
        if _matches_any(list(patterns.get(category, []) or []), text):
            return True
    return False

def _has_syntax_signature(text: str) -> bool:
    lowered = text.lower()
    for sig in _SYNTAX_SIGNATURES:
        if sig.lower() in lowered:
            return True
    return False

def _mode_is_env(mode: Optional[str]) -> bool:
    if not mode:
        return False
    m = mode.lower()
    return any((tok in m for tok in ('import', 'network', 'connection', 'module')))

def _mode_is_syntax(mode: Optional[str]) -> bool:
    if not mode:
        return False
    m = mode.lower()
    return any((tok in m for tok in ('syntax', 'attribute', 'type', 'api')))

def _strip_and_truncate(text: str) -> str:
    """Drop deprecation noise, then bound to first 250 + last 750 lines."""
    lines = [ln for ln in text.splitlines() if not _DEPRECATION_RE.search(ln)]
    if len(lines) > _MAX_LINES:
        omitted = len(lines) - _MAX_LINES
        marker = '... [%d line(s) elided; retaining first %d + last %d, tracebacks prioritized] ...' % (omitted, _HEAD_LINES, _TAIL_LINES)
        lines = lines[:_HEAD_LINES] + [marker] + lines[-_TAIL_LINES:]
    return '\n'.join(lines)

def _classify(exit_code: Optional[int], combined: str, marker_present: bool, mode: Optional[str]) -> str:
    """Pick exactly one class with precedence ENV > SYNTAX > REFUTED."""
    if _has_env_signature(combined) or _mode_is_env(mode):
        return ENV_PATH_ERROR
    if _has_syntax_signature(combined) or _mode_is_syntax(mode):
        return SYNTAX_API_ERROR
    return PAYLOAD_REFUTED
_GUIDANCE = {ENV_PATH_ERROR: 'The detonation environment could not import a dependency or reach the network. Repair the import path / environment provisioning before re-judging the payload; this is not evidence about the finding itself.', SYNTAX_API_ERROR: "The PoC raised a syntax or API-misuse error. Correct the script's syntax or its use of the target API and re-detonate; the payload was never exercised.", PAYLOAD_REFUTED: 'The PoC ran cleanly but the success marker was absent. Treat the current hypothesis as refuted and revise the exploitation approach.'}

def build_diagnostic_prompt(prev_poc: Any, telemetry: Dict[str, Any]) -> str:
    """Render a deterministic diagnostic markdown prompt.

    Args:
        prev_poc: Carries a ``finding_id`` attribute or mapping key.
        telemetry: Optional keys ``exit_code`` (int|None), ``stdout`` (str),
            ``stderr`` (str), ``marker_present`` (bool); each is optional and
            defaults safely when absent.

    Returns:
        Structured markdown referencing ``prev_poc.finding_id`` and containing
        exactly one classification token verbatim.
    """
    if not isinstance(telemetry, dict):
        telemetry = {}
    finding_id = _get_finding_id(prev_poc)
    raw_exit = telemetry.get('exit_code', None)
    exit_code: Optional[int]
    if raw_exit is None:
        exit_code = None
    else:
        try:
            exit_code = int(raw_exit)
        except (TypeError, ValueError):
            exit_code = None
    stdout = _coerce_str(telemetry.get('stdout', ''))
    stderr = _coerce_str(telemetry.get('stderr', ''))
    marker_present = bool(telemetry.get('marker_present', False))
    combined = stdout + '\n' + stderr
    mode = _infer_failure_mode({'exit_code': exit_code, 'stdout': stdout, 'stderr': stderr, 'marker_present': marker_present})
    classification = _classify(exit_code, combined, marker_present, mode)
    out_stdout = _strip_and_truncate(stdout)
    out_stderr = _strip_and_truncate(stderr)
    exit_display = 'None' if exit_code is None else str(exit_code)
    mode_display = mode if mode else 'n/a'
    sections: List[str] = []
    sections.append('# Diagnostic Prompt: %s' % finding_id)
    sections.append('')
    sections.append('## Classification')
    sections.append(classification)
    sections.append('')
    sections.append('## Finding')
    sections.append('finding_id: %s' % finding_id)
    sections.append('')
    sections.append('## Telemetry Summary')
    sections.append('- exit_code: %s' % exit_display)
    sections.append('- marker_present: %s' % ('true' if marker_present else 'false'))
    sections.append('- inferred_failure_mode: %s' % mode_display)
    sections.append('')
    sections.append('## STDOUT')
    sections.append('```')
    sections.append(out_stdout)
    sections.append('```')
    sections.append('')
    sections.append('## STDERR')
    sections.append('```')
    sections.append(out_stderr)
    sections.append('```')
    sections.append('')
    sections.append('## Guidance')
    sections.append(_GUIDANCE[classification])
    sections.append('')
    return '\n'.join(sections)
__all__ = ['build_diagnostic_prompt', 'ENV_PATH_ERROR', 'SYNTAX_API_ERROR', 'PAYLOAD_REFUTED']