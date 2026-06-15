---
interfaces: "creates NEW ngv2/reachability_triage.py exposing build_triage_prompt(finding, path, snippets)->str, judge(finding, path, snippets, client, complete)->dict, classify_to_band, CLASS_TO_BAND, CLASSIFICATIONS — the Stage-3 LLM scope/auth triage over the injected LLMClient complete seam"
dependencies: []
meta_task_type: data_model
spec_author: "Phase-III BUILD-PREP agent (JanusMask)"
spec_reviewed_by: "owner (CodeQL CLI use APPROVED 2026-06-12)"
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

ngv2/reachability_triage.py — NEW Stage-3 LLM scope/auth triage: given a proven CodeQL path + code context, classify reachable_unauth|auth_gated|internal_only|out_of_scope and map to ADMIT/MANUAL/DROP; fail-safe to MANUAL on malformed/erroring output (never a silent DROP).

# Scope

CREATE the NEW single-file module `ngv2/reachability_triage.py`. A CodeQL path proves a flow EXISTS but cannot judge whether the source is an unauthenticated public entry point or admin-gated/internal plumbing — the semantic judgment that killed all 37 prior false positives. `build_triage_prompt` is deterministic and names the sink, source, proven path, and code context, demanding a strict JSON verdict. `judge` runs the prompt through the injected `ngv2.llm_client.LLMClient` complete seam (live path: `_e2e_run/claude_cli_client.py`), parses the verdict, and maps it to a band. FAIL-SAFE: any malformed or erroring output → band='MANUAL' (human review), NEVER a silent DROP.

DISPATCH DIRECTIVE — PATCH FORMAT (MANDATORY — WHOLE-FILE): this is a NEW single-file module, so emit the COMPLETE file for `ngv2/reachability_triage.py` (whole-file emission — NEVER a `__JANUSMASK_PATCHES__` symbol patch, never a manifest, never a dotted qualname). Reproduce it BYTE-FOR-BYTE exactly as follows:

```python
"""ngv2.reachability_triage -- Stage-3 LLM scope/auth triage (ADMIT/MANUAL/DROP).

A CodeQL taint path proves a source->sink flow *exists*; it cannot judge whether
the source is an unauthenticated public entry point or admin-gated/internal
plumbing -- the exact semantic judgment that killed all 37 prior false positives.
This stage asks the model, given the proven path + code context, to classify the
finding, and maps the verdict onto the gate's ADMIT/MANUAL/DROP bands.

The model edge is the injected ``ngv2.llm_client.LLMClient`` ``complete`` seam
(the live path is ``_e2e_run/claude_cli_client.py``, already proven). This module
is otherwise pure: ``build_triage_prompt`` is deterministic, and ``judge``
fail-safes to MANUAL (human review) on any malformed/unparseable output -- it
NEVER silently DROPs a finding the model did not clearly reject.
"""
from __future__ import annotations
import json
import re
from typing import Any, Callable, Dict, List, Optional

__all__ = ['build_triage_prompt', 'judge', 'classify_to_band', 'CLASS_TO_BAND',
           'CLASSIFICATIONS']

CLASSIFICATIONS = ('reachable_unauth', 'auth_gated', 'internal_only', 'out_of_scope')
CLASS_TO_BAND = {
    'reachable_unauth': 'ADMIT',
    'auth_gated': 'MANUAL',
    'internal_only': 'DROP',
    'out_of_scope': 'DROP',
}
_JSON_OBJ_RE = re.compile(r'\{.*\}', re.DOTALL)


def classify_to_band(classification: Any) -> str:
    """Map a classification string to ADMIT/MANUAL/DROP; unknown -> MANUAL."""
    if isinstance(classification, str):
        return CLASS_TO_BAND.get(classification.strip().lower(), 'MANUAL')
    return 'MANUAL'


def build_triage_prompt(finding: Dict[str, Any], path: Optional[List[Any]] = None,
                        snippets: Optional[List[str]] = None) -> str:
    """Build the deterministic scope/auth triage prompt.

    The prompt names the sink, the source, the proven path, and the code
    context, and demands a strict JSON verdict over :data:`CLASSIFICATIONS`.
    """
    finding = finding if isinstance(finding, dict) else {}
    cwe = finding.get('cwe') or finding.get('rule') or 'unknown'
    sink = '%s:%s' % (finding.get('file', '?'), finding.get('line', '?'))
    path_steps = path if isinstance(path, (list, tuple)) else (finding.get('path') or [])
    source = str(path_steps[0]) if path_steps else '(unknown source)'
    sink_step = str(path_steps[-1]) if path_steps else sink
    path_block = '\n'.join('  %d. %s' % (i + 1, s) for i, s in enumerate(path_steps)) or '  (no path steps)'
    snippet_block = '\n\n'.join(snippets or []) or '(no code context provided)'
    return (
        'You are triaging a static-analysis finding for an external bug-bounty.\n'
        'A CodeQL interprocedural taint path proves data flows from a SOURCE to a\n'
        'dangerous SINK. Your ONLY job is to judge attacker-reachability and scope.\n\n'
        'CWE: %s\n'
        'SOURCE: %s\n'
        'SINK: %s (%s)\n'
        'PROVEN TAINT PATH:\n%s\n\n'
        'CODE CONTEXT:\n%s\n\n'
        'Classify into exactly one of:\n'
        '  - reachable_unauth : reachable from an UNAUTHENTICATED public entry point, in scope\n'
        '  - auth_gated       : reachable only behind authentication/authorization\n'
        '  - internal_only    : only internal callers / hardcoded args / dev tooling\n'
        '  - out_of_scope     : not attacker-influenced, or out of program scope\n\n'
        'Respond with ONLY a JSON object: '
        '{"classification": "<one of the above>", "justification": "<one line>"}\n'
        % (cwe, source, sink_step, sink, path_block, snippet_block)
    )


def _parse_verdict(text: Any) -> Optional[Dict[str, str]]:
    """Extract ``{classification, justification}`` from the model output, or None."""
    if not isinstance(text, str) or not text.strip():
        return None
    match = _JSON_OBJ_RE.search(text)
    if not match:
        return None
    try:
        obj = json.loads(match.group(0))
    except ValueError:
        return None
    if not isinstance(obj, dict):
        return None
    classification = obj.get('classification')
    if not isinstance(classification, str):
        return None
    return {'classification': classification.strip().lower(),
            'justification': str(obj.get('justification', ''))}


def judge(finding: Dict[str, Any], path: Optional[List[Any]] = None,
          snippets: Optional[List[str]] = None, *,
          client: Any = None, complete: Optional[Callable[..., str]] = None
          ) -> Dict[str, Any]:
    """Classify a finding's scope/auth and return a band decision.

    Provide either an ``ngv2.llm_client.LLMClient`` via ``client`` or a raw
    ``complete`` seam (wrapped into an LLMClient). Returns
    ``{band, classification, justification, raw}``. Any failure to obtain or
    parse a clear verdict fail-safes to ``band='MANUAL'`` -- never a silent DROP.
    """
    prompt = build_triage_prompt(finding, path, snippets)
    if client is None:
        from ngv2.llm_client import LLMClient
        client = LLMClient(complete)
    try:
        raw = client.complete_text(prompt)
    except Exception as exc:
        return {'band': 'MANUAL', 'classification': 'error',
                'justification': 'llm error: %s' % exc, 'raw': None}
    verdict = _parse_verdict(raw)
    if verdict is None:
        return {'band': 'MANUAL', 'classification': 'unparseable',
                'justification': 'could not parse model verdict', 'raw': raw}
    band = classify_to_band(verdict['classification'])
    return {'band': band, 'classification': verdict['classification'],
            'justification': verdict['justification'], 'raw': raw}
```

POST-EMIT SELF-CHECK (mandatory): the module imports only `json`/`re`/`typing` plus a lazy `ngv2.llm_client.LLMClient`; every parse/LLM failure path returns band='MANUAL'; no classification ever returns a silent DROP without a model verdict; no network/clock/subprocess at module scope.

# Required plan shape

EXACTLY ONE impl task. Use this task_id VERBATIM (the committed oracle is keyed to it): `task_id`: `ngv2_reachability_triage`. meta_task_type=`data_model` (NEW pure module — single-file whole-file emission, no production-harness edit). priority: high. dependencies: []. working_dir: "/home/xnihil0zer0/NobleGreedv2". files_touched: `["ngv2/reachability_triage.py"]` ONLY. partial_edit semantics: WHOLE-FILE single-file emission per the DISPATCH DIRECTIVE — the DISPATCH DIRECTIVE block above (including the full pinned file content) MUST be copied VERBATIM into the task's `implementation_notes` so the blind worker sees it. verification_command: `python3 -m pytest -q tests/ngv2/test_reachability_triage_wired.py` (CWD-relative — NO `cd`). The committed RED oracle tests/ngv2/test_reachability_triage_wired.py is the authoritative acceptance contract — make it GREEN (8 tests); do NOT author new tests. `spec.functional_requirements` MUST be CONSOLIDATED to at most 5 entries, and `test_spec.unit_tests` MUST enumerate AT LEAST as many entries as `spec.functional_requirements` (validator floor: len(unit_tests) >= len(functional_requirements)); unit_tests entries are descriptors NAMING committed-oracle test cases (this does NOT authorize authoring new tests). `test_spec.regression_tests` MUST list at least two entries naming committed oracle cases: `test_reachable_unauth_maps_to_admit`, `test_internal_only_and_out_of_scope_map_to_drop`. `test_spec.edge_cases` (≥2, reflected in those test names): `test_malformed_output_failsafe_manual_never_silent_drop`, `test_llm_error_failsafe_manual`, `test_auth_gated_maps_to_manual` — including the integration-style case `test_reachable_unauth_maps_to_admit`.

# Non-Goals

Do NOT make the model DISCOVER a path — it only triages a path Stage 2 proved (an LLM asked to find the path hallucinates and yields no submission artifact). Do NOT perform the real network call — the complete seam is injected. Do NOT touch session_gate, llm_client, or any other module. Do NOT add clock, randomness, or subprocess. Gate INTEGRATION (consulting this band in session_gate) is a separate EDIT leaf.

# Inputs

The committed oracle tests/ngv2/test_reachability_triage_wired.py (RED — module absent). It pins: the prompt contains source, sink, path, the JSON instruction, and all four classifications; prompt determinism; reachable_unauth→ADMIT (the integration case, exercising the full prompt→seam→band path); internal_only/out_of_scope→DROP; auth_gated→MANUAL; malformed output and LLM error both fail-safe to MANUAL; and classify_to_band unknown→MANUAL.

# Deliverables

The NEW file `ngv2/reachability_triage.py` exactly as pinned in the DISPATCH DIRECTIVE, verified GREEN by `python3 -m pytest -q tests/ngv2/test_reachability_triage_wired.py` (8 passed).
