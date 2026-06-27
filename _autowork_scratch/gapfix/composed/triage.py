"""Triage phase worker for the ngv2 conductor pipeline.

This module exposes a single composing entry point, :func:`run_stage`, that
turns the ``prior_findings`` carried by a ``get_task``-shaped *context* into a
list of triaged, Finding-shaped artifact dicts.

The worker is intentionally a *composition* layer: it owns no policy of its
own.  It pulls the injected ``llm-client`` seam and the triage ``may_confirm``
gate out of the ``seams`` mapping, uses the llm-client to assess / prioritise
each prior finding, and uses the gate to decide which assessed findings are
allowed to advance.  Confirmed findings are rendered into artifact dicts whose
``filename`` / ``content`` pair is parseable by
``artifact_harvester.parse_stage_artifact(filename, content, phase='triage')``
and whose body is shaped for the ``contracts.Finding`` dataclass.

Design constraints honoured here:

* Standard library only -- no third-party imports.
* Deterministic -- ids are derived from the finding content via a stable hash;
  no wall-clock, uuid, or unseeded randomness is used.
* Seams are consumed purely by injection; no committed module is edited.
* No string literal is ever bound to a credential-shaped variable name.
"""
from __future__ import annotations
import dataclasses
import hashlib
import inspect
import json
from typing import Any, Callable, Dict, List, Optional, Sequence
PHASE = 'triage'
__all__ = ['run_stage']

def run_stage(context: Dict[str, Any], seams: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Run the triage phase over ``context['prior_findings']``.

    Parameters
    ----------
    context:
        A ``get_task``-shaped mapping following
        ``{phase, target, prior_findings, parked_package}``.  Only
        ``prior_findings`` and ``target`` are consumed here.
    seams:
        Injected collaborators.  Must surface an llm-client seam (used to
        assess / prioritise findings) and the triage ``may_confirm`` gate
        (used to decide which findings advance).

    Returns
    -------
    list[dict]
        Triaged artifact dicts (possibly empty).  Every dict carries a
        ``filename`` / ``content`` pair parseable by
        ``parse_stage_artifact(..., phase='triage')`` and a Finding-shaped
        body.
    """
    context = context if isinstance(context, dict) else {}
    seams = seams if isinstance(seams, dict) else {}
    prior_findings = _coerce_sequence(context.get('prior_findings'))
    if not prior_findings:
        return []
    target = context.get('target')
    llm_client = _resolve_llm_seam(seams)
    triage_gate = _resolve_triage_gate(seams)
    artifacts: List[Dict[str, Any]] = []
    for finding in prior_findings:
        record = _as_record(finding)
        assessment = _assess(llm_client, record, target, context)
        if not _confirm(triage_gate, record, assessment):
            continue
        artifacts.append(_build_artifact(record, assessment, target))
    return artifacts

def _normalize(name: Any) -> str:
    return str(name).strip().lower().replace('-', '_').replace(' ', '_')

def _resolve_llm_seam(seams: Dict[str, Any]) -> Optional[Any]:
    """Locate the injected llm-client seam within ``seams``."""
    primaries = ('llm_client', 'llm', 'client', 'model', 'assessor', 'assess', 'completion', 'chat')
    substrings = ('llm', 'client', 'model', 'assess', 'chat', 'complete')
    return _find_seam(seams, primaries, substrings)

def _resolve_triage_gate(seams: Dict[str, Any]) -> Optional[Any]:
    """Locate the triage ``may_confirm`` gate within ``seams``."""
    primaries = ('triage_may_confirm', 'triage_gate', 'may_confirm', 'triage', 'confirm_gate', 'confirm', 'gate')
    substrings = ('confirm', 'gate')
    return _find_seam(seams, primaries, substrings, prefer='triage')

def _find_seam(seams: Any, primaries: Sequence[str], substrings: Sequence[str], prefer: Optional[str]=None) -> Optional[Any]:
    if not isinstance(seams, dict):
        return None
    normalized = {_normalize(k): v for k, v in seams.items()}
    for name in primaries:
        candidate = normalized.get(name)
        if candidate is not None:
            return candidate
    for value in seams.values():
        if isinstance(value, dict):
            nested = _find_seam(value, primaries, substrings, prefer)
            if nested is not None:
                return nested
    fallback: Optional[Any] = None
    for name, value in normalized.items():
        if value is None:
            continue
        if any((token in name for token in substrings)):
            if prefer and prefer in name:
                return value
            if fallback is None:
                fallback = value
    return fallback

def _assess(llm_client: Optional[Any], record: Dict[str, Any], target: Any, context: Dict[str, Any]) -> Any:
    """Invoke the llm-client seam to assess / prioritise one finding."""
    if llm_client is None:
        return {'confidence': 0.5, 'priority': 'unknown'}
    named = {'finding': record, 'candidate': record, 'item': record, 'record': record, 'target': target, 'context': context, 'prompt': _assessment_prompt(record, target)}
    callable_seam = _as_callable(llm_client, ('assess', 'triage', 'evaluate', 'prioritize', 'complete', 'run'))
    if callable_seam is None:
        return {'confidence': 0.5, 'priority': 'unknown'}
    try:
        return _smart_invoke(callable_seam, named, positional=(record, target))
    except Exception:
        return {'confidence': 0.5, 'priority': 'unknown'}

def _confirm(gate: Optional[Any], record: Dict[str, Any], assessment: Any) -> bool:
    """Invoke the triage may_confirm gate to decide if a finding advances."""
    if gate is None:
        return True
    named = {'finding': record, 'candidate': record, 'item': record, 'assessment': assessment, 'result': assessment, 'score': _confidence_of(assessment), 'confidence': _confidence_of(assessment), 'context': None}
    callable_gate = _as_callable(gate, ('may_confirm', 'confirm', 'check', 'evaluate', 'decide', 'run'))
    if callable_gate is None:
        return True
    try:
        outcome = _smart_invoke(callable_gate, named, positional=(record, assessment))
    except Exception:
        return False
    return _is_confirmed(outcome)

def _as_callable(seam: Any, method_names: Sequence[str]) -> Optional[Callable[..., Any]]:
    """Return a callable view of *seam* (itself, or a well-known method)."""
    if callable(seam):
        return seam
    for method_name in method_names:
        attr = getattr(seam, method_name, None)
        if callable(attr):
            return attr
    return None

def _smart_invoke(fn: Callable[..., Any], named: Dict[str, Any], positional: Sequence[Any]) -> Any:
    """Call *fn*, mapping its declared parameters to ``named`` when possible.

    Falls back to positional invocation (trimming arguments to the accepted
    arity) when the signature cannot be introspected -- e.g. for mocks.
    """
    signature = None
    try:
        signature = inspect.signature(fn)
    except (TypeError, ValueError):
        signature = None
    if signature is not None:
        args: List[Any] = []
        usable = True
        for param in signature.parameters.values():
            if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
                continue
            if param.kind == inspect.Parameter.KEYWORD_ONLY:
                usable = False
                break
            args.append(_match_param(param.name, named))
        if usable:
            try:
                return fn(*args)
            except TypeError:
                pass
    return _invoke_trimmed(fn, list(positional))

def _match_param(param_name: str, named: Dict[str, Any]) -> Any:
    lowered = param_name.lower()
    if 'assess' in lowered or 'result' in lowered:
        return named.get('assessment')
    if 'conf' in lowered or 'score' in lowered or 'prio' in lowered:
        return named.get('score')
    if 'target' in lowered:
        return named.get('target')
    if 'prompt' in lowered or 'message' in lowered or 'text' in lowered:
        return named.get('prompt')
    if 'context' in lowered or 'ctx' in lowered:
        return named.get('context')
    if 'find' in lowered or 'cand' in lowered or 'item' in lowered or ('record' in lowered):
        return named.get('finding')
    return named.get('finding')

def _invoke_trimmed(fn: Callable[..., Any], args: List[Any]) -> Any:
    """Call *fn* with as many of *args* as it will accept."""
    last_error: Optional[TypeError] = None
    for count in range(len(args), -1, -1):
        try:
            return fn(*args[:count])
        except TypeError as error:
            last_error = error
            continue
    if last_error is not None:
        raise last_error
    return fn()

def _confidence_of(assessment: Any) -> float:
    if isinstance(assessment, dict):
        for field_name in ('confidence', 'score', 'priority_score', 'weight'):
            value = assessment.get(field_name)
            if isinstance(value, (int, float)):
                return float(value)
    if isinstance(assessment, (int, float)) and (not isinstance(assessment, bool)):
        return float(assessment)
    return 0.5

def _is_confirmed(outcome: Any) -> bool:
    if isinstance(outcome, bool):
        return outcome
    if isinstance(outcome, (int, float)):
        return outcome > 0
    if isinstance(outcome, dict):
        for field_name in ('confirm', 'confirmed', 'advance', 'advanced', 'passed', 'ok', 'accept', 'accepted', 'allow'):
            if field_name in outcome:
                return bool(outcome[field_name])
        return bool(outcome)
    if isinstance(outcome, (tuple, list)) and outcome:
        return bool(outcome[0])
    return bool(outcome)

def _enrich_sink(body: Dict[str, Any]) -> Dict[str, Any]:
    try:
        from ngv2 import sink_extract
    except Exception:
        return body
    try:
        return sink_extract.enrich_finding(body)
    except Exception:
        return body

def _build_artifact(record: Dict[str, Any], assessment: Any, target: Any) -> Dict[str, Any]:
    """Render a confirmed finding into a parseable, Finding-shaped artifact."""
    ident = _stable_id(record, target)
    triage_meta = _triage_metadata(assessment)
    body: Dict[str, Any] = {}
    body.update(record)
    body = _enrich_sink(body)
    body.setdefault('id', ident)
    body.setdefault('target', target)
    body['phase'] = PHASE
    body['status'] = 'triaged'
    body['confidence'] = _confidence_of(assessment)
    body['triage'] = triage_meta
    filename, content = _select_payload(ident, body, record, target)
    artifact: Dict[str, Any] = {}
    artifact.update(body)
    artifact['phase'] = PHASE
    artifact['filename'] = filename
    artifact['content'] = content
    artifact['finding'] = body
    return artifact

def _triage_metadata(assessment: Any) -> Dict[str, Any]:
    meta: Dict[str, Any] = {'confidence': _confidence_of(assessment)}
    if isinstance(assessment, dict):
        for field_name in ('priority', 'rationale', 'reason', 'label', 'category', 'severity'):
            if field_name in assessment:
                meta[field_name] = assessment[field_name]
    elif isinstance(assessment, str):
        meta['rationale'] = assessment
    return meta

def _select_payload(ident: str, body: Dict[str, Any], record: Dict[str, Any], target: Any) -> 'tuple[str, str]':
    """Pick a (filename, content) pair, validating against the real parser.

    Several candidate encodings are produced.  When
    ``artifact_harvester.parse_stage_artifact`` is importable, the first
    candidate it accepts is used, guaranteeing parseability.  Otherwise the
    primary candidate is returned unchanged.
    """
    candidates = _payload_candidates(ident, body, record, target)
    parser = _load_parser()
    if parser is not None:
        for filename, content in candidates:
            if _parses_cleanly(parser, filename, content):
                return (filename, content)
    return candidates[0]

def _payload_candidates(ident: str, body: Dict[str, Any], record: Dict[str, Any], target: Any) -> 'List[tuple[str, str]]':
    contract_body = _contract_shaped_body(body)
    primary = json.dumps(contract_body, sort_keys=True, default=str)
    rich = json.dumps(body, sort_keys=True, default=str)
    markdown = _render_markdown(contract_body)
    candidates: 'List[tuple[str, str]]' = [('triage_finding_{0}.json'.format(ident), primary), ('triage_{0}.json'.format(ident), rich), ('{0}.triage.json'.format(ident), primary), ('triage_finding_{0}.md'.format(ident), markdown)]
    return candidates

def _contract_shaped_body(body: Dict[str, Any]) -> Dict[str, Any]:
    """Project *body* onto the ``contracts.Finding`` field set when known."""
    field_specs = _finding_fields()
    if not field_specs:
        return dict(body)
    shaped: Dict[str, Any] = {}
    for field_name, field in field_specs:
        if field_name in body:
            shaped[field_name] = body[field_name]
        elif _has_default(field):
            continue
        else:
            shaped[field_name] = _default_for_field(field, field_name, body)
    return shaped

def _render_markdown(body: Dict[str, Any]) -> str:
    lines = ['# Triage Finding', '']
    title = body.get('title') or body.get('name') or body.get('id') or 'finding'
    lines.append('## {0}'.format(title))
    lines.append('')
    for field_name in sorted(body):
        lines.append('- {0}: {1}'.format(field_name, body[field_name]))
    lines.append('')
    return '\n'.join(lines)

def _finding_fields() -> 'Optional[List[tuple[str, Any]]]':
    try:
        from ngv2 import contracts
    except Exception:
        return None
    finding_cls = getattr(contracts, 'Finding', None)
    if finding_cls is None or not dataclasses.is_dataclass(finding_cls):
        return None
    try:
        return [(field.name, field) for field in dataclasses.fields(finding_cls)]
    except Exception:
        return None

def _has_default(field: Any) -> bool:
    return field.default is not dataclasses.MISSING or field.default_factory is not dataclasses.MISSING

def _default_for_field(field: Any, field_name: str, body: Dict[str, Any]) -> Any:
    annotation = getattr(field, 'type', None)
    text = str(annotation).lower() if annotation is not None else ''
    if 'list' in text or 'sequence' in text or 'tuple' in text:
        return []
    if 'dict' in text or 'mapping' in text:
        return {}
    if 'int' in text:
        return 0
    if 'float' in text:
        return 0.0
    if 'bool' in text:
        return False
    if 'str' in text:
        return str(body.get(field_name, ''))
    return body.get(field_name)

def _load_parser() -> Optional[Callable[..., Any]]:
    try:
        from ngv2 import artifact_harvester
    except Exception:
        return None
    parser = getattr(artifact_harvester, 'parse_stage_artifact', None)
    return parser if callable(parser) else None

def _parses_cleanly(parser: Callable[..., Any], filename: str, content: str) -> bool:
    for attempt in (lambda: parser(filename, content, phase=PHASE), lambda: parser(filename, content, PHASE), lambda: parser(filename, content)):
        try:
            result = attempt()
        except TypeError:
            continue
        except Exception:
            return False
        return result is not None and result != [] and (result != {})
    return False

def _coerce_sequence(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    if isinstance(value, dict):
        return [value]
    return [value]

def _as_record(finding: Any) -> Dict[str, Any]:
    """Normalise an arbitrary finding representation into a plain dict."""
    if isinstance(finding, dict):
        return dict(finding)
    if dataclasses.is_dataclass(finding) and (not isinstance(finding, type)):
        try:
            return dataclasses.asdict(finding)
        except Exception:
            pass
    for attr in ('to_dict', 'as_dict', 'dict', 'model_dump'):
        method = getattr(finding, attr, None)
        if callable(method):
            try:
                produced = method()
                if isinstance(produced, dict):
                    return dict(produced)
            except Exception:
                continue
    data = getattr(finding, '__dict__', None)
    if isinstance(data, dict) and data:
        return {k: v for k, v in data.items() if not k.startswith('_')}
    return {'value': finding}

def _assessment_prompt(record: Dict[str, Any], target: Any) -> str:
    title = record.get('title') or record.get('name') or record.get('id') or 'finding'
    return "Assess and prioritise triage candidate '{0}' for target '{1}'.".format(title, target)

def _stable_id(record: Dict[str, Any], target: Any) -> str:
    """Deterministic short identifier derived from the finding content."""
    existing = record.get('id')
    if isinstance(existing, str) and existing:
        return existing
    payload = json.dumps({'target': target, 'finding': record}, sort_keys=True, default=str)
    digest = hashlib.sha256(payload.encode('utf-8')).hexdigest()
    return digest[:12]

if __name__ == "__main__":
    import sys as _sys
    from ngv2.workers._runner import main as _main

    _sys.exit(_main("triage"))
