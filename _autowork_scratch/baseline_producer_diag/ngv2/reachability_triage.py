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
__all__ = ['build_triage_prompt', 'judge', 'classify_to_band', 'CLASS_TO_BAND', 'CLASSIFICATIONS']
CLASSIFICATIONS = ('reachable_unauth', 'auth_gated', 'internal_only', 'out_of_scope')
CLASS_TO_BAND = {'reachable_unauth': 'ADMIT', 'auth_gated': 'MANUAL', 'internal_only': 'DROP', 'out_of_scope': 'DROP'}
_JSON_OBJ_RE = re.compile('\\{.*\\}', re.DOTALL)

def classify_to_band(classification: Any) -> str:
    """Map a classification string to ADMIT/MANUAL/DROP; unknown -> MANUAL."""
    if isinstance(classification, str):
        return CLASS_TO_BAND.get(classification.strip().lower(), 'MANUAL')
    return 'MANUAL'

def build_triage_prompt(finding: Dict[str, Any], path: Optional[List[Any]]=None, snippets: Optional[List[str]]=None) -> str:
    """Build the deterministic scope/auth triage prompt.

    The prompt names the sink, the source, the proven path, and the code
    context, and demands a strict JSON verdict over :data:`CLASSIFICATIONS`.
    """
    finding = finding if isinstance(finding, dict) else {}
    cwe = finding.get('cwe') or finding.get('rule') or 'unknown'
    sink = '%s:%s' % (finding.get('file', '?'), finding.get('line', '?'))
    path_steps = path if isinstance(path, (list, tuple)) else finding.get('path') or []
    source = str(path_steps[0]) if path_steps else '(unknown source)'
    sink_step = str(path_steps[-1]) if path_steps else sink
    path_block = '\n'.join(('  %d. %s' % (i + 1, s) for i, s in enumerate(path_steps))) or '  (no path steps)'
    snippet_block = '\n\n'.join(snippets or []) or '(no code context provided)'
    return 'You are triaging a static-analysis finding for an external bug-bounty.\nA CodeQL interprocedural taint path proves data flows from a SOURCE to a\ndangerous SINK. Your ONLY job is to judge attacker-reachability and scope.\n\nCWE: %s\nSOURCE: %s\nSINK: %s (%s)\nPROVEN TAINT PATH:\n%s\n\nCODE CONTEXT:\n%s\n\nClassify into exactly one of:\n  - reachable_unauth : reachable from an UNAUTHENTICATED public entry point, in scope\n  - auth_gated       : reachable only behind authentication/authorization\n  - internal_only    : only internal callers / hardcoded args / dev tooling\n  - out_of_scope     : not attacker-influenced, or out of program scope\n\nRespond with ONLY a JSON object: {"classification": "<one of the above>", "justification": "<one line>"}\n' % (cwe, source, sink_step, sink, path_block, snippet_block)

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
    return {'classification': classification.strip().lower(), 'justification': str(obj.get('justification', ''))}

def judge(finding: Dict[str, Any], path: Optional[List[Any]]=None, snippets: Optional[List[str]]=None, *, client: Any=None, complete: Optional[Callable[..., str]]=None) -> Dict[str, Any]:
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
        return {'band': 'MANUAL', 'classification': 'error', 'justification': 'llm error: %s' % exc, 'raw': None}
    verdict = _parse_verdict(raw)
    if verdict is None:
        return {'band': 'MANUAL', 'classification': 'unparseable', 'justification': 'could not parse model verdict', 'raw': raw}
    band = classify_to_band(verdict['classification'])
    return {'band': band, 'classification': verdict['classification'], 'justification': verdict['justification'], 'raw': raw}