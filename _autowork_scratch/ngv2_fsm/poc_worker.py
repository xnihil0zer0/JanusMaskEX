"""ngv2/workers/poc.py -- exploitation (PoC) phase worker.

This module is the ``poc`` phase leaf of the conductor pipeline.  It exposes a
single frozen phase-contract entry point::

    run_stage(context: dict, seams: dict) -> list[dict]

``run_stage`` reads the finding to exploit from ``context['prior_findings']``
and the target from ``context['target']`` (treating ``context`` as read-only
input), then composes three *injected* seams to draft and repair a PoC:

* ``llm_client``      -- produces raw model text for a prompt,
* ``poc_writer``      -- drafts PoC source/content from the finding/target,
* ``poc_repair_loop`` -- repairs the drafted PoC and reports success/failure.

Every externally-observable behaviour (model, network, subprocess) is obtained
*only* from the seams dict, so the module is fully deterministic under stub
seams: it never imports a model client, opens a socket, or spawns a process.

The function returns a list of artifact dicts with ``phase == "poc"`` whose
``filename`` / ``content`` shape is parseable by
``artifact_harvester.parse_stage_artifact(filename, content, phase)`` and whose
fields are sufficient to build a ``contracts.PoC``.  Empty or malformed writer
output, a missing finding, and a repair loop that reports failure are all
handled deterministically -- the failure is surfaced inside the returned
artifacts rather than raised.

Only the Python standard library is imported.  No wall-clock, randomness, or
id-generation source is used; the same inputs always produce the same output.
"""
from typing import Any, Iterable, Mapping, Optional, Sequence, Tuple
import inspect
_LLM_ALIASES: Tuple[str, ...] = ('llm_client', 'llm-client', 'llm', 'llmclient', 'model', 'client')
_WRITER_ALIASES: Tuple[str, ...] = ('poc_writer', 'poc-writer', 'pocwriter', 'writer', 'drafter')
_REPAIR_ALIASES: Tuple[str, ...] = ('poc_repair_loop', 'poc-repair-loop', 'poc_repair', 'repair_loop', 'poc_repairer', 'repairer', 'repair')
_CONTENT_FIELDS: Tuple[str, ...] = ('content', 'source', 'poc_source', 'poc_code', 'poc', 'code', 'exploit_code', 'exploit', 'script', 'body', 'text', 'draft', 'payload', 'output')
_SUCCESS_FIELDS: Tuple[str, ...] = ('success', 'ok', 'passed', 'succeeded', 'valid', 'is_valid', 'repaired')
_FAILURE_FLAGS: Tuple[str, ...] = ('failed', 'failure', 'is_failure', 'broken')
_ERROR_FIELDS: Tuple[str, ...] = ('error', 'errors', 'reason', 'message', 'detail', 'traceback')
_FAILED_STATUSES: Tuple[str, ...] = ('failed', 'failure', 'error', 'invalid', 'broken', 'rejected')
_ID_FIELDS: Tuple[str, ...] = ('finding_id', 'id', 'fid', 'vuln_id', 'vulnerability_id', 'identifier', 'cwe')
_NAME_FIELDS: Tuple[str, ...] = ('title', 'name', 'summary', 'headline')
_DESC_FIELDS: Tuple[str, ...] = ('description', 'details', 'rationale', 'explanation', 'summary')
_LANG_FIELDS: Tuple[str, ...] = ('language', 'lang', 'ecosystem')
_TARGET_FIELDS: Tuple[str, ...] = ('name', 'repo', 'repository', 'url', 'package', 'slug', 'identifier')
_LANG_EXTENSIONS: Tuple[Tuple[str, str], ...] = (('python', '.py'), ('py', '.py'), ('javascript', '.js'), ('js', '.js'), ('typescript', '.ts'), ('ts', '.ts'), ('ruby', '.rb'), ('go', '.go'), ('java', '.java'), ('php', '.php'), ('bash', '.sh'), ('shell', '.sh'), ('sh', '.sh'))
_DEFAULT_LANGUAGE = 'python'
_PHASE = 'poc'

def _err_text(exc: Optional[BaseException]) -> str:
    """Render an exception as a deterministic, message-only string."""
    if exc is None:
        return 'unknown error'
    return '{0}: {1}'.format(type(exc).__name__, exc)

def _get(obj: Any, names: Iterable[str]) -> Any:
    """Return the first present, non-callable value for ``names`` on ``obj``.

    Works for mappings (by membership) and for plain objects (by attribute).
    Returns ``None`` when nothing matches.
    """
    if obj is None:
        return None
    if isinstance(obj, Mapping):
        for ident in names:
            if ident in obj and obj[ident] is not None:
                return obj[ident]
        return None
    for ident in names:
        if hasattr(obj, ident):
            value = getattr(obj, ident)
            if value is not None and (not callable(value)):
                return value
    return None

def _stringify(value: Any) -> Optional[str]:
    """Coerce a value to text content, or ``None`` if it has no text form."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (bytes, bytearray)):
        try:
            return bytes(value).decode('utf-8', 'replace')
        except Exception:
            return None
    return None

def _content_of(obj: Any) -> Optional[str]:
    """Extract PoC text content from a seam output of unknown shape."""
    if obj is None:
        return None
    direct = _stringify(obj)
    if direct is not None:
        return direct
    if isinstance(obj, Mapping) or hasattr(obj, '__dict__') or _has_any_attr(obj, _CONTENT_FIELDS):
        candidate = _get(obj, _CONTENT_FIELDS)
        return _stringify(candidate)
    return None

def _has_any_attr(obj: Any, names: Iterable[str]) -> bool:
    return any((hasattr(obj, ident) for ident in names))

def _is_failure(result: Any) -> Tuple[bool, Optional[str]]:
    """Interpret a repair-loop result as ``(failed, reason)``.

    Recognises booleans, mappings with explicit success/failure flags or a
    ``status`` string, objects exposing the same, and a truthy error field.
    A bare string or content-only result is treated as success (the repaired
    PoC body itself).
    """
    if result is None:
        return (True, 'poc_repair_loop returned no result')
    if isinstance(result, bool):
        if result:
            return (False, None)
        return (True, 'poc_repair_loop reported failure')
    if isinstance(result, str):
        return (False, None)
    if isinstance(result, Mapping):
        for ident in _SUCCESS_FIELDS:
            if ident in result:
                if result[ident]:
                    return (False, None)
                return (True, _failure_reason(result))
        for ident in _FAILURE_FLAGS:
            if ident in result and result[ident]:
                return (True, _failure_reason(result))
        status = result.get('status')
        if isinstance(status, str) and status.strip().lower() in _FAILED_STATUSES:
            return (True, _failure_reason(result))
        existing_error = _get(result, _ERROR_FIELDS)
        if existing_error:
            return (True, _coerce_reason(existing_error))
        return (False, None)
    for ident in _SUCCESS_FIELDS:
        if hasattr(result, ident):
            if getattr(result, ident):
                return (False, None)
            return (True, _failure_reason(result))
    for ident in _FAILURE_FLAGS:
        if hasattr(result, ident) and getattr(result, ident):
            return (True, _failure_reason(result))
    existing_error = _get(result, _ERROR_FIELDS)
    if existing_error:
        return (True, _coerce_reason(existing_error))
    return (False, None)

def _coerce_reason(value: Any) -> str:
    if value is None:
        return 'poc_repair_loop reported failure'
    if isinstance(value, (list, tuple)):
        parts = [str(item) for item in value if item is not None]
        return '; '.join(parts) if parts else 'poc_repair_loop reported failure'
    text = str(value).strip()
    return text or 'poc_repair_loop reported failure'

def _failure_reason(result: Any) -> str:
    return _coerce_reason(_get(result, _ERROR_FIELDS))

def _extension_for(language: Optional[str]) -> str:
    if isinstance(language, str):
        normalized = language.strip().lower()
        for label, ext in _LANG_EXTENSIONS:
            if normalized == label:
                return ext
    return '.py'

def _supply(func: Any, pool: Mapping[str, Any]) -> dict:
    """Build a kwargs dict matching ``func``'s named parameters from ``pool``."""
    signature = inspect.signature(func)
    kwargs: dict = {}
    for name, parameter in signature.parameters.items():
        if parameter.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        if name in pool:
            kwargs[name] = pool[name]
    return kwargs

def _invoke(func: Any, pool: Mapping[str, Any], positional_orders: Sequence[Sequence[str]]) -> Tuple[Any, Optional[str]]:
    """Call ``func`` deterministically, returning ``(result, error_text)``.

    A signature-matched keyword call is attempted first (the natural path for
    well-formed seams); positional fallbacks cover positional-only stubs.  A
    signature mismatch (``TypeError``) is retried; any other raised exception is
    surfaced as an error string rather than propagated.
    """
    if func is None:
        return (None, 'seam not provided')
    if not callable(func):
        return (None, 'seam is not callable')
    attempts = []
    try:
        attempts.append(((), _supply(func, pool)))
    except (TypeError, ValueError):
        pass
    for order in positional_orders:
        args = tuple((pool[name] for name in order if name in pool))
        attempts.append((args, {}))
    attempts.append(((), {}))
    last_signature_error: Optional[BaseException] = None
    for args, kwargs in attempts:
        try:
            return (func(*args, **kwargs), None)
        except TypeError as exc:
            last_signature_error = exc
            continue
        except Exception as exc:
            return (None, _err_text(exc))
    return (None, _err_text(last_signature_error))

def _select_finding(context: Mapping[str, Any]) -> Any:
    """Pick the finding to exploit from ``context['prior_findings']``.

    Accepts a list/tuple (first element), a single finding mapping, or a
    mapping of findings (first value).  Returns ``None`` when no finding is
    available.  Does not mutate ``context``.
    """
    prior = context.get('prior_findings')
    if not prior:
        return None
    if isinstance(prior, (list, tuple)):
        return prior[0] if len(prior) > 0 else None
    if isinstance(prior, Mapping):
        looks_like_finding = any((ident in prior for ident in _ID_FIELDS + _NAME_FIELDS + _DESC_FIELDS))
        if looks_like_finding:
            return prior
        values = list(prior.values())
        return values[0] if values else None
    return prior

def _finding_identifier(finding: Any) -> str:
    value = _get(finding, _ID_FIELDS)
    if value is None:
        value = _get(finding, _NAME_FIELDS)
    if value is None:
        return 'unknown-finding'
    return str(value)

class _RepoTarget(object):
    """A target reference that carries both a display ``name`` (so artifact and
    prompt metadata stay the bare target slug) and a ``repo_root`` (so the
    poc_writer grounder can resolve repo-relative cited evidence paths)."""

    __slots__ = ('name', 'repo_root')

    def __init__(self, name: Any, repo_root: Any) -> None:
        self.name = name
        self.repo_root = repo_root

def _build_target(context: Mapping[str, Any]) -> Any:
    """Build a repo-root-bearing target from the worker context so PoC grounding
    can read the cited source. Falls back to the bare target reference when no
    repo root is available."""
    tgt = context.get('target') if isinstance(context, Mapping) else None
    repo = context.get('repo') if isinstance(context, Mapping) else None
    if repo:
        return _RepoTarget(name=tgt, repo_root=repo)
    return tgt

def _target_reference(target: Any) -> Any:
    if target is None:
        return None
    if isinstance(target, str):
        return target
    reference = _get(target, _TARGET_FIELDS)
    if reference is not None:
        return reference
    return target

def _build_prompt(finding: Any, target: Any) -> str:
    """Build a deterministic drafting prompt from the finding and target."""
    title = _get(finding, _NAME_FIELDS) or _finding_identifier(finding)
    description = _get(finding, _DESC_FIELDS) or ''
    target_ref = _target_reference(target)
    return 'Write a proof-of-concept exploit for the following finding.\ntarget: {0}\nfinding: {1}\ndetails: {2}\n'.format(target_ref, title, description)

def _build_artifact(finding: Any, target: Any, content: str, success: bool, repaired: bool, error: Optional[str]) -> dict:
    """Assemble a single ``phase='poc'`` artifact dict.

    The returned dict carries ``filename`` / ``content`` / ``phase`` (so it is
    parseable by ``parse_stage_artifact``) plus the metadata fields needed to
    build a ``contracts.PoC``.  Content is mirrored under a few common field
    names so downstream parsing is resilient to the exact contract layout.
    """
    finding_id = _finding_identifier(finding)
    title = _get(finding, _NAME_FIELDS)
    description = _get(finding, _DESC_FIELDS)
    language = _get(finding, _LANG_FIELDS) or _DEFAULT_LANGUAGE
    filename = 'poc' + _extension_for(language)
    target_ref = _target_reference(target)
    artifact = {'phase': _PHASE, 'filename': filename, 'content': content, 'source': content, 'code': content, 'poc_source': content, 'language': str(language), 'finding_id': finding_id, 'target': target_ref, 'name': title if title is not None else finding_id, 'title': title if title is not None else finding_id, 'description': description if description is not None else '', 'success': bool(success), 'status': 'success' if success else 'failed', 'repaired': bool(repaired), 'error': error}
    return artifact

def _failure_artifact(finding: Any, target: Any, reason: str, source: Optional[str]) -> dict:
    """Build a deterministic failure artifact (still parseable as a PoC)."""
    if source and source.strip():
        content = source
    else:
        content = '# poc generation failed\n# reason: {0}\n'.format(reason)
    return _build_artifact(finding=finding, target=target, content=content, success=False, repaired=False, error=reason)

def _seam(seams: Any, aliases: Iterable[str]) -> Any:
    if seams is None:
        return None
    if isinstance(seams, Mapping):
        for ident in aliases:
            if ident in seams and seams[ident] is not None:
                return seams[ident]
        return None
    for ident in aliases:
        if hasattr(seams, ident):
            candidate = getattr(seams, ident)
            if candidate is not None:
                return candidate
    return None

def run_stage(context: dict, seams: dict) -> list[dict]:
    """Run the PoC exploitation phase and return artifact dict(s).

    Signature is frozen as ``run_stage(context: dict, seams: dict) -> list[dict]``.

    ``context`` is treated as read-only input; the finding is read from
    ``context['prior_findings']`` and the target from ``context['target']``.
    All PoC drafting and repair behaviour comes from the injected ``seams``
    (``llm_client``, ``poc_writer``, ``poc_repair_loop``).  The function never
    raises for the documented edge cases -- empty/malformed writer output, a
    repair loop reporting failure, or a missing finding -- instead it surfaces
    the failure inside the returned artifacts.
    """
    safe_context: Mapping[str, Any] = context if isinstance(context, Mapping) else {}
    safe_seams: Any = seams if seams is not None else {}
    finding = _select_finding(safe_context)
    target = _build_target(safe_context)
    if finding is None:
        return [_failure_artifact(finding=None, target=target, reason="no finding to exploit in context['prior_findings']", source=None)]
    writer = _seam(safe_seams, _WRITER_ALIASES)
    if writer is None:
        return [_failure_artifact(finding=finding, target=target, reason='poc_writer seam not provided', source=None)]
    llm = _seam(safe_seams, _LLM_ALIASES)
    repair = _seam(safe_seams, _REPAIR_ALIASES)
    prompt = _build_prompt(finding, target)
    raw_text: Optional[str] = None
    if llm is not None:
        llm_pool = {'prompt': prompt, 'messages': prompt, 'finding': finding, 'target': target, 'context': safe_context}
        llm_orders = [('prompt',), ('finding', 'target'), ('finding',), ('context',)]
        llm_result, llm_error = _invoke(llm, llm_pool, llm_orders)
        if llm_error is None:
            raw_text = _content_of(llm_result)
    writer_pool = {'llm_client': llm, 'llm': llm, 'client': llm, 'finding': finding, 'target': target, 'context': safe_context, 'seams': safe_seams, 'prompt': prompt, 'raw': raw_text, 'draft': raw_text, 'text': raw_text}
    writer_orders = [('llm_client', 'finding', 'target'), ('finding', 'target', 'llm_client'), ('llm_client', 'finding'), ('finding', 'target'), ('raw', 'finding', 'target'), ('finding', 'raw'), ('llm_client',), ('finding',), ('raw',)]
    draft, writer_error = _invoke(writer, writer_pool, writer_orders)
    if writer_error is not None:
        return [_failure_artifact(finding=finding, target=target, reason='poc_writer error: {0}'.format(writer_error), source=None)]
    draft_content = _content_of(draft)
    if draft_content is None or not draft_content.strip():
        return [_failure_artifact(finding=finding, target=target, reason='poc_writer produced empty or malformed output', source=None)]
    if repair is None:
        return [_build_artifact(finding=finding, target=target, content=draft_content, success=True, repaired=False, error=None)]
    repair_pool = {'poc': draft, 'draft': draft, 'content': draft_content, 'source': draft_content, 'llm_client': llm, 'llm': llm, 'client': llm, 'finding': finding, 'target': target, 'context': safe_context, 'seams': safe_seams}
    repair_orders = [('draft', 'llm_client'), ('poc', 'llm_client'), ('content', 'llm_client'), ('draft',), ('poc',), ('content',), ('draft', 'finding', 'target')]
    repaired_result, repair_error = _invoke(repair, repair_pool, repair_orders)
    if repair_error is not None:
        return [_failure_artifact(finding=finding, target=target, reason='poc_repair_loop error: {0}'.format(repair_error), source=draft_content)]
    final_content = _content_of(repaired_result) or draft_content
    failed, reason = _is_failure(repaired_result)
    if failed:
        return [_failure_artifact(finding=finding, target=target, reason=reason or 'poc_repair_loop reported failure', source=final_content)]
    return [_build_artifact(finding=finding, target=target, content=final_content, success=True, repaired=True, error=None)]

if __name__ == "__main__":
    import sys as _sys
    from ngv2.workers._runner import main as _main

    _sys.exit(_main("poc"))
