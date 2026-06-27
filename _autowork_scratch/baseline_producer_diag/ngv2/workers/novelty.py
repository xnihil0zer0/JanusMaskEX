"""ngv2/workers/novelty.py -- novelty phase worker.

A thin, deterministic, seam-injected phase worker.  Its single public
entrypoint :func:`run_stage` judges whether a confirmed finding is *novel* by
composing the injected ``seams['novelty_gate']`` seam.  The gate is composed
only -- never weakened, bypassed, or auto-passed.  Every non-explicitly-novel
outcome (duplicate, failure, missing, malformed) is treated *fail-closed* as
non-novel.

The module performs no real model call, no network request and no subprocess:
all novelty behaviour arrives through the injected ``seams`` dict, so the same
inputs always yield the same output.  It imports only the Python standard
library, and it never imports ``ngv2.novelty_gate`` for in-place mutation.

Output is a list of artifact dicts shaped as ``{"filename", "content",
"phase"}`` so that ``artifact_harvester.parse_stage_artifact(filename, content,
phase)`` can consume them, with ``content`` carrying the field names of the
novelty-phase contracts dataclass (discovered at runtime from
``ngv2.contracts`` when available, with a canonical fallback otherwise).
"""
from __future__ import annotations
import json
from typing import Any, Callable, Dict, List, Optional, Tuple
__all__ = ['run_stage']
_UNSET = object()
_NOVEL = 'novel'
_DUPLICATE = 'duplicate'
_NON_NOVEL = 'non_novel'
_FAILURE = 'failure'
_NOVEL_TOKENS = frozenset({'novel', 'is_novel', 'isnovel', 'unique', 'new'})
_DUPLICATE_TOKENS = frozenset({'duplicate', 'dup', 'dupe', 'known', 'seen', 'existing', 'not_novel', 'non_novel'})
_FAILURE_TOKENS = frozenset({'failure', 'fail', 'failed', 'error', 'errored'})

def run_stage(context: Dict[str, Any], seams: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Judge novelty of the confirmed finding described by ``context``.

    Parameters
    ----------
    context:
        Phase context, typically ``{phase, target, prior_findings,
        parked_package}`` as produced by ``get_task(session_row)``.  Tolerant
        of ``None`` / missing keys / empty material.
    seams:
        Injected seam dict.  ``seams['novelty_gate']`` is the novelty gate
        (read-only, matching ``ngv2/novelty_gate.py``).  All gate behaviour is
        obtained from here -- no real model/network/subprocess is used.

    Returns
    -------
    list of dict
        One well-formed artifact dict ``{"filename", "content", "phase"}``
        parseable by ``artifact_harvester.parse_stage_artifact`` and shaped to
        build the novelty-phase contracts dataclass.  A duplicate/failure/
        malformed verdict is preserved and never upgraded to novel.
    """
    ctx = context if isinstance(context, dict) else {}
    phase = ctx.get('phase') or 'novelty'
    target = ctx.get('target')
    prior_findings = ctx.get('prior_findings')
    parked_package = ctx.get('parked_package')
    finding = {'phase': phase, 'target': target, 'prior_findings': prior_findings, 'parked_package': parked_package}
    if not _has_material(prior_findings) and (not _has_material(parked_package)):
        values = _make_values(novel=False, verdict=_NON_NOVEL, rationale='no confirmed finding material in context', target=target, phase=phase, duplicate_of=None, finding_id=_finding_id(prior_findings, parked_package), error=False, gate_result=None)
        return [_build_artifact(values, phase)]
    gate = seams.get('novelty_gate') if isinstance(seams, dict) else None
    if not callable(gate):
        values = _make_values(novel=False, verdict=_NON_NOVEL, rationale='novelty_gate seam missing or not callable', target=target, phase=phase, duplicate_of=None, finding_id=_finding_id(prior_findings, parked_package), error=True, gate_result=None)
        return [_build_artifact(values, phase)]
    try:
        gate_result: Any = _invoke_gate(gate, ctx, finding)
        raised: Optional[BaseException] = None
    except Exception as exc:
        gate_result = None
        raised = exc
    novel, verdict, rationale, duplicate_of, error = _interpret(gate_result, raised)
    values = _make_values(novel=novel, verdict=verdict, rationale=rationale, target=target, phase=phase, duplicate_of=duplicate_of, finding_id=_finding_id(prior_findings, parked_package), error=error, gate_result=gate_result)
    return [_build_artifact(values, phase)]

def _invoke_gate(gate: Callable[..., Any], ctx: Dict[str, Any], finding: Dict[str, Any]) -> Any:
    """Call ``gate`` with whatever argument shape its signature accepts.

    Signature resolution (via :mod:`inspect`) is done *before* the call so that
    an exception raised inside the gate is a genuine failure verdict and is
    never masked by retrying a different argument shape.
    """
    try:
        import inspect
        signature = inspect.signature(gate)
    except (ValueError, TypeError):
        return gate(finding)
    by_name = {'finding': finding, 'material': finding, 'candidate': finding, 'payload': finding, 'context': ctx, 'ctx': ctx, 'phase': finding.get('phase'), 'target': finding.get('target'), 'prior_findings': ctx.get('prior_findings'), 'parked_package': ctx.get('parked_package')}
    matched: Dict[str, Any] = {}
    has_var_keyword = False
    for pname, param in signature.parameters.items():
        if param.kind is param.VAR_KEYWORD:
            has_var_keyword = True
            continue
        if param.kind is param.VAR_POSITIONAL:
            continue
        if pname in by_name:
            matched[pname] = by_name[pname]
    candidates: List[Tuple[tuple, Dict[str, Any]]] = []
    if matched:
        candidates.append(((), matched))
    if has_var_keyword:
        candidates.append(((), by_name))
    candidates.append(((finding,), {}))
    candidates.append(((ctx,), {}))
    candidates.append(((), {}))
    for args, kwargs in candidates:
        try:
            signature.bind(*args, **kwargs)
        except TypeError:
            continue
        return gate(*args, **kwargs)
    return gate(finding)

def _interpret(result: Any, raised: Optional[BaseException]) -> Tuple[bool, str, str, Optional[Any]]:
    """Map a raw gate result into ``(novel, verdict, rationale, duplicate_of, error)``.

    The gate is never relaxed: only an *explicit* novel signal yields
    ``novel=True``.  Failures, duplicates, malformed output and missing
    verdicts all yield ``novel=False``.
    """
    if raised is not None:
        detail = '{0}: {1}'.format(type(raised).__name__, raised)
        return (False, _FAILURE, 'novelty_gate seam failed: ' + detail, None, True)
    if result is None:
        return (False, _NON_NOVEL, 'novelty_gate seam returned no verdict', None, False)
    if isinstance(result, bool):
        if result:
            return (True, _NOVEL, 'novelty_gate seam returned novel', None, False)
        return (False, _NON_NOVEL, 'novelty_gate seam returned non-novel', None, False)
    if isinstance(result, str):
        return _interpret_token(result, rationale_source=result, duplicate_of=None)
    if isinstance(result, dict):
        return _interpret_dict(result)
    return (False, _NON_NOVEL, 'novelty_gate seam returned malformed output', None, False)

def _interpret_dict(result: Dict[str, Any]) -> Tuple[bool, str, str, Optional[Any]]:
    rationale = _first_str(result, ('rationale', 'reason', 'reasons', 'explanation', 'detail', 'details', 'message', 'note'))
    duplicate_of = _first(result, ('duplicate_of', 'duplicateof', 'dup_of', 'original', 'original_id', 'report_id'))
    if _truthy(result, ('error', 'failed', 'failure', 'is_error', 'errored')):
        text = rationale or 'novelty_gate seam reported failure'
        return (False, _FAILURE, text, duplicate_of, True)
    for field_name in ('novel', 'is_novel', 'isnovel'):
        flag = result.get(field_name)
        if isinstance(flag, bool):
            if flag:
                return (True, _NOVEL, rationale or 'novelty_gate seam returned novel', None, False)
            verdict = _DUPLICATE if duplicate_of is not None else _NON_NOVEL
            return (False, verdict, rationale or 'novelty_gate seam returned non-novel', duplicate_of, False)
    verdict_raw = _first(result, ('verdict', 'status', 'result', 'decision', 'outcome'))
    if isinstance(verdict_raw, bool):
        if verdict_raw:
            return (True, _NOVEL, rationale or 'novelty_gate seam returned novel', None, False)
        return (False, _NON_NOVEL, rationale or 'novelty_gate seam returned non-novel', duplicate_of, False)
    if isinstance(verdict_raw, str):
        return _interpret_token(verdict_raw, rationale_source=rationale or verdict_raw, duplicate_of=duplicate_of)
    return (False, _NON_NOVEL, rationale or 'novelty_gate seam returned no verdict key', duplicate_of, False)

def _interpret_token(token: str, rationale_source: Optional[str], duplicate_of: Optional[Any]) -> Tuple[bool, str, str, Optional[Any]]:
    norm = token.strip().lower()
    rationale = rationale_source or token
    if norm in _NOVEL_TOKENS:
        return (True, _NOVEL, rationale, None, False)
    if norm in _FAILURE_TOKENS:
        return (False, _FAILURE, rationale, duplicate_of, True)
    if norm in _DUPLICATE_TOKENS:
        return (False, _DUPLICATE, rationale, duplicate_of, False)
    return (False, _NON_NOVEL, rationale, duplicate_of, False)

def _make_values(*, novel: bool, verdict: str, rationale: str, target: Any, phase: Any, duplicate_of: Any, finding_id: Any, error: bool, gate_result: Any) -> Dict[str, Any]:
    """Bundle the resolved novelty facts used to populate the artifact content."""
    return {'novel': novel, 'is_novel': novel, 'verdict': verdict, 'rationale': rationale, 'reason': rationale, 'target': target, 'phase': phase, 'duplicate_of': duplicate_of, 'finding_id': finding_id, 'error': error, 'gate_result': _safe(gate_result)}

def _build_artifact(values: Dict[str, Any], phase: Any) -> Dict[str, Any]:
    """Build a ``{filename, content, phase}`` artifact dict.

    ``content`` is a JSON string whose keys match the novelty-phase contracts
    dataclass (discovered at runtime) or a canonical fallback shape.
    """
    content_obj = _shape_content(values)
    content_text = json.dumps(content_obj, sort_keys=True, default=_safe)
    phase_label = phase if isinstance(phase, str) and phase else 'novelty'
    return {'filename': 'novelty.json', 'content': content_text, 'phase': phase_label}

def _shape_content(values: Dict[str, Any]) -> Dict[str, Any]:
    """Return a content dict keyed for the novelty contracts dataclass.

    When ``ngv2.contracts`` exposes a novelty dataclass, mirror its exact field
    names (so ``Dataclass(**content)`` succeeds).  Otherwise emit a canonical
    shape.  Either way, ``novel`` / ``verdict`` always reflect the gate's
    fail-closed judgement.
    """
    contract = _discover_contract()
    if contract is None:
        return _canonical_content(values)
    try:
        import dataclasses
        content: Dict[str, Any] = {}
        for field in dataclasses.fields(contract):
            resolved = _resolve_field(field.name, values)
            if resolved is _UNSET:
                if field.default is not dataclasses.MISSING:
                    resolved = field.default
                elif field.default_factory is not dataclasses.MISSING:
                    resolved = field.default_factory()
                else:
                    resolved = None
            content[field.name] = _safe(resolved)
        if not _names_cover_novelty(content):
            return _canonical_content(values)
        return content
    except Exception:
        return _canonical_content(values)

def _canonical_content(values: Dict[str, Any]) -> Dict[str, Any]:
    return {'phase': values.get('phase'), 'target': _safe(values.get('target')), 'novel': bool(values.get('novel')), 'verdict': values.get('verdict'), 'rationale': values.get('rationale'), 'duplicate_of': _safe(values.get('duplicate_of')), 'finding_id': _safe(values.get('finding_id')), 'error': bool(values.get('error'))}

def _resolve_field(field_name: str, values: Dict[str, Any]) -> Any:
    low = field_name.lower()
    synonyms = ((('novel', 'is_novel', 'isnovel', 'novelty', 'is_new'), 'novel'), (('verdict', 'status', 'result', 'decision', 'outcome', 'judgement', 'judgment'), 'verdict'), (('rationale', 'reason', 'reasons', 'explanation', 'detail', 'details', 'message', 'note', 'notes'), 'rationale'), (('duplicate_of', 'duplicateof', 'dup_of', 'original', 'original_id'), 'duplicate_of'), (('target', 'asset', 'subject'), 'target'), (('phase', 'stage', 'step'), 'phase'), (('finding_id', 'findingid', 'finding', 'id', 'report_id', 'reportid'), 'finding_id'), (('error', 'failed', 'failure', 'is_error', 'errored'), 'error'), (('gate_result', 'raw', 'raw_result', 'gate', 'verdict_raw'), 'gate_result'))
    for names, source in synonyms:
        if low in names:
            return values.get(source, _UNSET)
    return _UNSET

def _names_cover_novelty(content: Dict[str, Any]) -> bool:
    lowered = {name.lower() for name in content}
    novelty_names = {'novel', 'is_novel', 'isnovel', 'novelty', 'is_new'}
    verdict_names = {'verdict', 'status', 'result', 'decision', 'outcome', 'judgement', 'judgment'}
    return bool(lowered & novelty_names) or bool(lowered & verdict_names)

def _discover_contract() -> Any:
    """Best-effort lookup of the novelty contracts dataclass.

    Returns ``None`` when ``ngv2.contracts`` is unavailable or exposes no
    novelty-named dataclass, in which case the canonical shape is used.
    """
    try:
        import importlib
        import dataclasses
        module = importlib.import_module('ngv2.contracts')
    except Exception:
        return None
    best = None
    for name in dir(module):
        obj = getattr(module, name, None)
        if isinstance(obj, type) and dataclasses.is_dataclass(obj) and ('novel' in name.lower()):
            if best is None or len(name) > len(best.__name__):
                best = obj
    return best

def _has_material(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, (str, bytes, list, tuple, set, dict)):
        return len(value) > 0
    return True

def _finding_id(prior_findings: Any, parked_package: Any) -> Any:
    for source in (parked_package, prior_findings):
        ident = _extract_id(source)
        if ident is not None:
            return ident
    return None

def _extract_id(source: Any) -> Any:
    if isinstance(source, dict):
        for field_name in ('finding_id', 'id', 'report_id', 'ident'):
            if source.get(field_name) is not None:
                return source.get(field_name)
    if isinstance(source, (list, tuple)) and source:
        return _extract_id(source[0])
    return None

def _first(mapping: Dict[str, Any], names: Tuple[str, ...]) -> Any:
    for name in names:
        if name in mapping and mapping.get(name) is not None:
            return mapping.get(name)
    return None

def _first_str(mapping: Dict[str, Any], names: Tuple[str, ...]) -> Optional[str]:
    value = _first(mapping, names)
    if value is None:
        return None
    return value if isinstance(value, str) else str(value)

def _truthy(mapping: Dict[str, Any], names: Tuple[str, ...]) -> bool:
    for name in names:
        if mapping.get(name):
            return True
    return False

def _safe(value: Any) -> Any:
    """Return a JSON-serialisable representation of ``value``."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_safe(v) for v in value]
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)

if __name__ == "__main__":
    import sys as _sys
    from ngv2.workers._runner import main as _main

    _sys.exit(_main("novelty"))
