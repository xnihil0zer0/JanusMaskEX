---
interfaces: "creates NEW ngv2/source_sink_prefilter.py exposing prefilter(clone_path, rules_path)->dict and collect_sinks(clone_path)->list — the Stage-1 source×sink necessary-condition gate that REVIVES deser_detect AND (transitively) web_framework_detect on a live path"
dependencies: ["ngv2_entrypoint_scan", "ngv2_sink_classes_data"]
meta_task_type: data_model
spec_author: "Phase-III BUILD-PREP agent (JanusMask)"
spec_reviewed_by: "owner (CodeQL CLI use APPROVED 2026-06-12)"
---

# Title

ngv2/source_sink_prefilter.py — NEW Stage-1 cheap gate: keep a repo for the expensive CodeQL stage ONLY if it has BOTH a public attacker entry point AND a dangerous sink class (deser CWE-502 + pattern_scanner). Reports a cascade `mode` (web>mff>cli) folding in G6.

# Scope

CREATE the NEW single-file module `ngv2/source_sink_prefilter.py`. `prefilter(clone_path)` returns `{keep, mode, boundaries, entrypoints, sinks}` with `keep = bool(entrypoints) and bool(sinks)`. Entry points come from `ngv2.entrypoint_scan.scan_entrypoints` (dependency `ngv2_entrypoint_scan`); sinks from the REVIVED `ngv2.deser_detect.check_deserialization` (the CWE-502 class the legacy engine never scanned, usage sinks only — bare imports excluded) plus `ngv2.pattern_scanner.scan_directory`. This is the live import that un-orphans deser_detect; web_framework_detect is revived transitively via entrypoint_scan. `mode` names the strongest boundary present so the G6 MFF mode (model-file boundary + deser sink → keep) is explicit. Pure, stdlib-only, deterministic.

DISPATCH DIRECTIVE — PATCH FORMAT (MANDATORY — WHOLE-FILE): this is a NEW single-file module, so emit the COMPLETE file for `ngv2/source_sink_prefilter.py` (whole-file emission — NEVER a `__JANUSMASK_PATCHES__` symbol patch, never a manifest, never a dotted qualname). Reproduce it BYTE-FOR-BYTE exactly as follows:

```python
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
```

POST-EMIT SELF-CHECK (mandatory): the module imports check_deserialization, scan_directory, and scan_entrypoints at top level; `keep` is exactly `bool(entrypoints) and bool(sinks)`; bare deser imports are excluded from sinks; no network/clock/subprocess import.

# Required plan shape

EXACTLY ONE impl task. Use this task_id VERBATIM (the committed oracle is keyed to it): `task_id`: `ngv2_source_sink_prefilter`. meta_task_type=`data_model` (NEW pure module — single-file whole-file emission, no production-harness edit). priority: high. dependencies: ["ngv2_entrypoint_scan", "ngv2_sink_classes_data"]. working_dir: "/home/xnihil0zer0/NobleGreedv2". files_touched: `["ngv2/source_sink_prefilter.py"]` ONLY. partial_edit semantics: WHOLE-FILE single-file emission per the DISPATCH DIRECTIVE — the DISPATCH DIRECTIVE block above (including the full pinned file content) MUST be copied VERBATIM into the task's `implementation_notes` so the blind worker sees it. verification_command: `python3 -m pytest -q tests/ngv2/test_source_sink_prefilter_wired.py` (CWD-relative — NO `cd`). The committed RED oracle tests/ngv2/test_source_sink_prefilter_wired.py is the authoritative acceptance contract — make it GREEN (7 tests); do NOT author new tests. `test_spec.regression_tests` MUST list at least two entries naming committed oracle cases: `test_keep_true_for_web_route_plus_pickle_sink`, `test_g6_mff_mode_model_load_plus_deser`. `test_spec.edge_cases` (≥2, reflected in those test names): `test_keep_false_route_but_no_sink`, `test_keep_false_sink_but_no_entrypoint`, `test_live_path_revives_deser_and_web_framework_detect` — including the integration-style case `test_live_path_revives_deser_and_web_framework_detect`.

# Non-Goals

Do NOT add the interprocedural forward trace (that is CodeQL Stage 2 — this is only the cheap necessary-condition gate). Do NOT touch deser_detect, web_framework_detect, pattern_scanner, or entrypoint_scan. Do NOT add network, clock, randomness, subprocess, or logging. Driver INTEGRATION (feeding kept repos to CodeQL) is a separate downstream leaf.

# Inputs

The committed oracle tests/ngv2/test_source_sink_prefilter_wired.py (RED — module absent). It pins: web route + pickle sink → keep=True, mode='web', a CWE-502 sink present; route but no sink → keep=False; sink but no entry point → keep=False; the G6 MFF case (torch.load model-load + deser → keep=True, mode='mff', model_file boundary); non-dir safe; collect_sinks excludes bare imports; and the live-path case asserting both ngv2.deser_detect and ngv2.web_framework_detect are in sys.modules after prefilter.

# Deliverables

The NEW file `ngv2/source_sink_prefilter.py` exactly as pinned in the DISPATCH DIRECTIVE, verified GREEN by `python3 -m pytest -q tests/ngv2/test_source_sink_prefilter_wired.py` (7 passed).
