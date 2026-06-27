"""Hunt-phase stage worker for ngv2.

This module exposes :func:`run_stage`, the hunt-phase ``stage_fn`` consumed by
``base_worker.StageWorker``.  It composes two injected seams -- an llm-client
seam that surfaces candidate leads for a target and the hunt-phase
``may_confirm`` gate that decides which candidates are allowed to graduate into
findings -- and emits confirmed candidates as artifact dicts.

The module is deliberately pure: it performs no network or process side
effects, reads no clock / randomness, and never imports the committed seam
modules (``llm_client``, ``contracts``, the gate modules,
``artifact_harvester``, ``session_get_task``, ``base_worker``).  All
collaborators arrive through the ``seams`` argument so the worker stays
testable with stubs.

Returned dicts are shaped so that
``artifact_harvester.parse_stage_artifact(filename, content, phase)`` can parse
them, with ``content`` carrying a JSON payload whose fields align with the
``contracts.Finding`` dataclass.
"""
from __future__ import annotations
import inspect
import json
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
__all__ = ['run_stage']
_LLM_CLIENT_ALIASES: Tuple[str, ...] = ('llm_client', 'llm', 'llm_client_seam', 'client', 'leads')
_GATE_ALIASES: Tuple[str, ...] = ('may_confirm', 'hunt_may_confirm', 'may_confirm_gate', 'gate', 'confirm')
_WRITE_ALIASES: Tuple[str, ...] = ('write', 'write_seam', 'writer')
_PHASE_ALIASES: Tuple[str, ...] = ('phase', 'stage')
_TARGET_ALIASES: Tuple[str, ...] = ('target', 'subject')
_PRIOR_ALIASES: Tuple[str, ...] = ('prior_findings', 'prior', 'findings')
_PARKED_ALIASES: Tuple[str, ...] = ('parked_package', 'parked', 'package')
_VERDICT_KEYS: Tuple[str, ...] = ('may_confirm', 'confirmed', 'confirm', 'allowed', 'allow', 'ok', 'passed', 'accept', 'accepted')
_CANDIDATE_CONTAINER_KEYS: Tuple[str, ...] = ('candidates', 'leads', 'findings', 'results', 'items')
_DEFAULT_PHASE = 'hunt'

def run_stage(context: Any, seams: Any) -> List[Dict[str, Any]]:
    """Run the hunt-phase stage.

    Resolves the task fields from ``context`` (the shape returned by
    ``session_get_task.get_task``), asks the injected llm-client seam for
    candidate leads against the target, applies the injected hunt-phase
    ``may_confirm`` gate to each candidate, and returns the gate-confirmed
    candidates shaped as artifact dicts.

    Neither ``context`` nor ``seams`` is mutated.  Any malformed candidate or
    seam hiccup is skipped rather than raised, and an empty / no-lead response
    yields ``[]``.
    """
    phase = _resolve_field(context, _PHASE_ALIASES, default=_DEFAULT_PHASE)
    target = _resolve_field(context, _TARGET_ALIASES, default=None)
    prior_findings = _resolve_field(context, _PRIOR_ALIASES, default=None)
    parked_package = _resolve_field(context, _PARKED_ALIASES, default=None)
    llm_client = _resolve_seam(seams, _LLM_CLIENT_ALIASES)
    may_confirm = _resolve_seam(seams, _GATE_ALIASES)
    if not callable(llm_client) or not callable(may_confirm):
        return []
    pool: Dict[str, Any] = {'context': context, 'ctx': context, 'seams': seams, 'phase': phase, 'stage': phase, 'target': target, 'subject': target, 'prior_findings': prior_findings, 'prior': prior_findings, 'parked_package': parked_package, 'parked': parked_package}
    try:
        raw_response = _invoke(llm_client, pool)
    except Exception:
        return []
    candidates = _extract_candidates(raw_response)
    if not candidates:
        return []
    artifacts: List[Dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        try:
            artifact = _process_candidate(candidate=candidate, index=index, phase=phase, target=target, may_confirm=may_confirm, pool=pool)
        except Exception:
            continue
        if artifact is not None:
            artifacts.append(artifact)
    return artifacts

def _process_candidate(candidate: Any, index: int, phase: Any, target: Any, may_confirm: Callable[..., Any], pool: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Gate a single candidate and, if confirmed, shape it as an artifact."""
    payload = _normalize_candidate(candidate)
    if payload is None:
        return None
    gate_pool = dict(pool)
    gate_pool.update({'candidate': payload, 'finding': payload, 'lead': payload})
    verdict = _invoke(may_confirm, gate_pool)
    confirmed, source = _interpret_verdict(verdict, payload)
    if not confirmed:
        return None
    finding = _build_finding(source, phase=phase, target=target)
    return _build_artifact(finding, index=index, phase=phase, target=target)

def _resolve_field(container: Any, aliases: Sequence[str], default: Any) -> Any:
    """Read a field from a mapping- or attribute-style container, read-only."""
    if container is None:
        return default
    if isinstance(container, dict):
        for alias in aliases:
            if alias in container:
                return container[alias]
        return default
    for alias in aliases:
        if hasattr(container, alias):
            return getattr(container, alias)
    return default

def _resolve_seam(seams: Any, aliases: Sequence[str]) -> Any:
    """Pull a collaborator out of the injected seams bundle."""
    if seams is None:
        return None
    if isinstance(seams, dict):
        for alias in aliases:
            if alias in seams:
                return seams[alias]
        return None
    for alias in aliases:
        if hasattr(seams, alias):
            return getattr(seams, alias)
    return None

def _invoke(fn: Callable[..., Any], pool: Dict[str, Any]) -> Any:
    """Call ``fn`` passing whichever pooled values match its parameters.

    Inspecting the signature lets the worker cooperate with the real seam
    signatures as well as arbitrarily-shaped test stubs without guessing a
    single fixed calling convention.
    """
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return fn()
    kwargs: Dict[str, Any] = {}
    accepts_var_keyword = False
    for name, param in sig.parameters.items():
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            accepts_var_keyword = True
        elif param.kind == inspect.Parameter.VAR_POSITIONAL:
            continue
        elif param.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY):
            if name in pool:
                kwargs[name] = pool[name]
    if accepts_var_keyword:
        for name, value in pool.items():
            kwargs.setdefault(name, value)
    return fn(**kwargs)

def _extract_candidates(response: Any) -> List[Any]:
    """Coerce an llm-client response into a flat list of candidates."""
    if not response:
        return []
    if isinstance(response, (list, tuple)):
        return [item for item in response if item]
    if isinstance(response, dict):
        for key in _CANDIDATE_CONTAINER_KEYS:
            if key in response:
                nested = response[key]
                return _extract_candidates(nested)
        return [response]
    return [response]

def _normalize_candidate(candidate: Any) -> Optional[Dict[str, Any]]:
    """Return a plain dict view of a candidate, or ``None`` if unusable."""
    if candidate is None:
        return None
    if isinstance(candidate, dict):
        return dict(candidate)
    data = getattr(candidate, '__dict__', None)
    if isinstance(data, dict) and data:
        return {k: v for k, v in data.items() if not k.startswith('_')}
    return None

def _interpret_verdict(verdict: Any, candidate: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """Decode a gate reply into ``(confirmed, source_payload)``.

    The gate may answer with a bool, a dict carrying an explicit verdict key,
    a (possibly enriched) candidate dict, or a tuple whose head is the verdict.
    """
    if verdict is None or verdict is False:
        return (False, candidate)
    if verdict is True:
        return (True, candidate)
    if isinstance(verdict, dict):
        for key in _VERDICT_KEYS:
            if key in verdict:
                return (bool(verdict[key]), candidate)
        return (True, dict(verdict))
    if isinstance(verdict, (tuple, list)):
        if not verdict:
            return (False, candidate)
        confirmed = bool(verdict[0])
        source = candidate
        if len(verdict) > 1 and isinstance(verdict[1], dict):
            source = dict(verdict[1])
        return (confirmed, source)
    return (bool(verdict), candidate)

def _build_finding(source: Dict[str, Any], phase: Any, target: Any) -> Dict[str, Any]:
    """Shape a confirmed candidate into a contracts.Finding-aligned payload."""
    finding: Dict[str, Any] = dict(source)
    finding.setdefault('phase', phase)
    if target is not None:
        finding.setdefault('target', target)
    return finding

def _build_artifact(finding: Dict[str, Any], index: int, phase: Any, target: Any) -> Dict[str, Any]:
    """Wrap a finding payload as a parse_stage_artifact-compatible dict."""
    filename = _make_filename(finding, index=index, phase=phase, target=target)
    content = json.dumps(finding, default=str, sort_keys=True)
    return {'filename': filename, 'content': content, 'phase': phase}

def _make_filename(finding: Dict[str, Any], index: int, phase: Any, target: Any) -> str:
    """Build a deterministic artifact filename for a finding."""
    label = finding.get('id') or finding.get('ident') or finding.get('title') or finding.get('name')
    slug = _slugify(label) if label else ''
    if not slug:
        slug = '{0}'.format(index)
    phase_part = _slugify(phase) or _DEFAULT_PHASE
    return '{0}_{1}.json'.format(phase_part, slug)

def _slugify(value: Any) -> str:
    """Reduce a value to a filesystem-safe lowercase slug (deterministic)."""
    text = str(value).strip().lower()
    out_chars = []
    for char in text:
        if char.isalnum():
            out_chars.append(char)
        elif char in (' ', '-', '_', '/', '.'):
            out_chars.append('_')
    slug = ''.join(out_chars).strip('_')
    while '__' in slug:
        slug = slug.replace('__', '_')
    return slug

if __name__ == "__main__":
    import sys as _sys
    from ngv2.workers._runner import main as _main

    _sys.exit(_main("hunt"))
