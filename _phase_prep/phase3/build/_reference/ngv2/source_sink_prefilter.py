"""ngv2.source_sink_prefilter -- Stage-1 cheap necessary-condition gate.

Keep a repo for the expensive CodeQL stage only if it has BOTH a public attacker
entry point AND a dangerous sink class -- a sound, cheap *necessary* condition
that avoids building a CodeQL database (minutes, ~GB) for repos that cannot match.

It revives two orphaned scanners on a live path:

* ``ngv2.entrypoint_scan.scan_entrypoints`` -> public sources (web routes, CLIs,
  and -- Gap G6 -- MFF model-load boundaries), which in turn drives the revived
  ``ngv2.web_framework_detect``;
* ``ngv2.deser_detect.check_deserialization`` -> the CWE-502 sink class the legacy
  engine never scanned, plus ``ngv2.pattern_scanner`` for CWE-78/89/94/327.

Pure, stdlib-only, deterministic. No network, clock, randomness, or subprocess.
"""
from __future__ import annotations
import os
from typing import Any, Dict, List, Optional

from ngv2.deser_detect import check_deserialization
from ngv2.pattern_scanner import scan_directory
from ngv2.entrypoint_scan import scan_entrypoints

__all__ = ['prefilter', 'collect_sinks']

# Boundary precedence -> the cascade "mode" reported for the kept repo.
_BOUNDARY_TO_MODE = (('network', 'web'), ('model_file', 'mff'), ('cli', 'cli'))


def collect_sinks(clone_path: str) -> List[Dict[str, Any]]:
    """Aggregate dangerous sinks (deser CWE-502 + pattern_scanner) for a clone.

    Returns a deterministic list of ``{sink_class, cwe, file, line}`` dicts.
    Bare deser *imports* are excluded -- only usage sinks count.
    """
    sinks: List[Dict[str, Any]] = []
    deser = check_deserialization(clone_path)
    for rec in deser.get('patterns') or []:
        module = rec.get('module', '')
        if module.endswith('_import'):
            continue
        sinks.append({'sink_class': 'deserialization', 'cwe': 'CWE-502',
                      'file': rec.get('file'), 'line': rec.get('line')})
    report = scan_directory(clone_path)
    for finding in report.get('findings') or []:
        sinks.append({'sink_class': finding.get('id'), 'cwe': finding.get('cwe'),
                      'file': finding.get('file'), 'line': finding.get('line')})
    sinks.sort(key=lambda s: (str(s['file']), s['line'] or 0, str(s['sink_class'])))
    return sinks


def _mode_for(boundaries: set) -> str:
    for boundary, mode in _BOUNDARY_TO_MODE:
        if boundary in boundaries:
            return mode
    return 'none'


def prefilter(clone_path: str, rules_path: Optional[str] = None) -> Dict[str, Any]:
    """Decide whether ``clone_path`` is worth a CodeQL build.

    Returns ``{keep, mode, boundaries, entrypoints, sinks}`` where
    ``keep = bool(entrypoints) and bool(sinks)``. ``mode`` names the strongest
    attacker boundary present (``web`` > ``mff`` > ``cli``); a non-directory path
    yields ``keep=False`` with empty lists.
    """
    if not os.path.isdir(clone_path):
        return {'keep': False, 'mode': 'none', 'boundaries': [],
                'entrypoints': [], 'sinks': []}
    entrypoints = scan_entrypoints(clone_path, rules_path)
    sinks = collect_sinks(clone_path)
    boundaries = {e.get('attacker_boundary') for e in entrypoints if e.get('attacker_boundary')}
    keep = bool(entrypoints) and bool(sinks)
    return {'keep': keep, 'mode': _mode_for(boundaries),
            'boundaries': sorted(boundaries), 'entrypoints': entrypoints,
            'sinks': sinks}
