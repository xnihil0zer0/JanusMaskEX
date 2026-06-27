"""ngv2/workers/detonate.py -- detonate exploitation phase worker.

This whole-file module implements the ``detonate`` phase of the ng v2 pipeline.
It composes an *injected* detonation seam to execute a proof-of-concept (PoC)
against a target and captures the result, mapping it into artifact dict(s)
from which ``contracts.LiveTestReport`` can be built.

Design constraints honored here:

* ``run_stage(context, seams) -> list[dict]`` is the frozen phase-contract
  signature shared by every phase worker.
* The module performs **no** real subprocess/detonation, network, or LLM call.
  All execution behavior is taken from ``seams['detonation']`` (the injected
  detonation callable), so the worker is deterministic under a stub seam.
* ``context`` is treated as read-only -- it is never mutated.
* Failures (seam raising, seam reporting failure, empty/malformed results,
  missing PoC) are surfaced deterministically in the returned artifacts rather
  than raising.
* Standard library only; no wall-clock / random / uuid sources (any timestamp
  is taken from an injected ``now_fn`` with a deterministic default).
"""
from __future__ import annotations
import dataclasses
import inspect
import json
from typing import Any
from typing import Callable
from typing import Iterable
from typing import Optional
PHASE = 'detonate'
_DEFAULT_TIMESTAMP = '1970-01-01T00:00:00Z'
_OUTCOME_SUCCESS = 'success'
_OUTCOME_FAILURE = 'failure'
_OUTCOME_ERROR = 'error'
_OUTCOME_NO_POC = 'no_poc'
_EXIT_CODE_FIELDS = ('exit_code', 'returncode', 'return_code', 'code', 'rc', 'status_code')
_STDOUT_FIELDS = ('stdout', 'out', 'output', 'log', 'logs')
_STDERR_FIELDS = ('stderr', 'err', 'error_output', 'stderr_text')
_CRASHED_FIELDS = ('crashed', 'crash', 'did_crash', 'segfault', 'sigsegv', 'asan')
_TIMEOUT_FIELDS = ('timed_out', 'timeout', 'did_timeout')
_SUCCESS_FIELDS = ('success', 'ok', 'passed', 'reproduced', 'vulnerable', 'exploited', 'triggered')
_FAILURE_FIELDS = ('failed', 'failure', 'errored')
_ERROR_MSG_FIELDS = ('error', 'error_message', 'message', 'reason', 'detail')
_DURATION_FIELDS = ('duration', 'elapsed', 'duration_s', 'runtime', 'wall_time')
_SIGNAL_FIELDS = ('signal', 'signum', 'term_signal')

def run_stage(context: dict, seams: dict) -> list[dict]:
    """Run the detonate phase.

    Args:
        context: Read-only stage context. Recognized keys include
            ``phase``, ``target``, ``prior_findings`` and ``parked_package``.
        seams: Injected dependency map. ``seams['detonation']`` MUST be the
            detonation callable used to execute the PoC. An optional
            ``seams['now_fn']`` (callable returning a timestamp) supplies a
            deterministic clock.

    Returns:
        A list of artifact dicts (typically one). Each dict carries
        ``phase='detonate'``, a ``filename`` and JSON ``content`` so it is
        parseable by ``artifact_harvester.parse_stage_artifact``, and the
        flattened LiveTestReport fields so the report can be built directly.
    """
    context = context if isinstance(context, dict) else {}
    seams = seams if isinstance(seams, dict) else {}
    target_label = _extract_target(context)
    poc_source, poc_value = _extract_poc(context)
    timestamp = _resolve_timestamp(seams, context)
    if poc_value is None:
        report = _build_report(target_label=target_label, poc_value=None, poc_source=poc_source, normalized=None, outcome=_OUTCOME_NO_POC, error_message='no PoC available in context to detonate', timestamp=timestamp, raw_result=None)
        return [_to_artifact(report)]
    detonation_seam = seams.get('detonation')
    if not callable(detonation_seam):
        report = _build_report(target_label=target_label, poc_value=poc_value, poc_source=poc_source, normalized=None, outcome=_OUTCOME_ERROR, error_message='no callable detonation seam injected', timestamp=timestamp, raw_result=None)
        return [_to_artifact(report)]
    raw_result: Any = None
    seam_error: Optional[str] = None
    try:
        raw_result = _invoke_detonation(detonation_seam, poc_value, target_label, poc_source, context)
    except Exception as exc:
        seam_error = 'detonation seam raised {0}: {1}'.format(type(exc).__name__, exc)
    if seam_error is not None:
        report = _build_report(target_label=target_label, poc_value=poc_value, poc_source=poc_source, normalized=None, outcome=_OUTCOME_ERROR, error_message=seam_error, timestamp=timestamp, raw_result=None)
        return [_to_artifact(report)]
    normalized = _normalize_result(raw_result)
    if normalized is None:
        is_empty = raw_result is None or raw_result == {} or raw_result == [] or (raw_result == '')
        message = 'detonation seam returned an empty result' if is_empty else 'detonation seam returned a malformed/unparseable result'
        report = _build_report(target_label=target_label, poc_value=poc_value, poc_source=poc_source, normalized=None, outcome=_OUTCOME_ERROR, error_message=message, timestamp=timestamp, raw_result=_safe_jsonable(raw_result))
        return [_to_artifact(report)]
    outcome, error_message = _classify(normalized)
    report = _build_report(target_label=target_label, poc_value=poc_value, poc_source=poc_source, normalized=normalized, outcome=outcome, error_message=error_message, timestamp=timestamp, raw_result=_safe_jsonable(raw_result))
    return [_to_artifact(report)]

def _extract_target(context: dict) -> Any:
    """Read the target from context without mutating it."""
    target = context.get('target')
    if isinstance(target, dict):
        for field_name in ('name', 'slug', 'repo', 'identifier', 'id', 'label'):
            value = target.get(field_name)
            if value:
                return value
        return target
    return target

def _extract_poc(context: dict) -> tuple[Any, Any]:
    """Locate the PoC to execute.

    Returns a ``(source, poc)`` tuple where ``source`` is the container the PoC
    was found in (for provenance) and ``poc`` is the PoC payload itself, or
    ``(source, None)`` when no PoC is present.
    """
    poc_fields = ('poc', 'poc_code', 'poc_path', 'poc_file', 'exploit', 'payload', 'script')
    package = context.get('parked_package')
    if isinstance(package, dict):
        for field_name in poc_fields:
            value = package.get(field_name)
            if value:
                return (package, value)
        nested = package.get('finding')
        if isinstance(nested, dict):
            for field_name in poc_fields:
                value = nested.get(field_name)
                if value:
                    return (package, value)
    elif isinstance(package, str) and package.strip():
        return (package, package)
    findings = context.get('prior_findings')
    if isinstance(findings, dict):
        findings = [findings]
    if isinstance(findings, (list, tuple)):
        for finding in findings:
            if isinstance(finding, dict):
                for field_name in poc_fields:
                    value = finding.get(field_name)
                    if value:
                        return (finding, value)
            elif isinstance(finding, str) and finding.strip():
                return (finding, finding)
    return (package, None)

def _resolve_timestamp(seams: dict, context: dict) -> Any:
    """Obtain a deterministic timestamp from an injected clock, if any."""
    for container in (seams, context):
        now_fn = container.get('now_fn') if isinstance(container, dict) else None
        if callable(now_fn):
            try:
                return now_fn()
            except Exception:
                return _DEFAULT_TIMESTAMP
        explicit = container.get('now') if isinstance(container, dict) else None
        if explicit is not None and (not callable(explicit)):
            return explicit
    return _DEFAULT_TIMESTAMP

def _invoke_detonation(seam: Callable[..., Any], poc_value: Any, target_label: Any, poc_source: Any, context: dict) -> Any:
    """Invoke the injected detonation seam, adapting to its signature.

    The seam contract is intentionally permissive: different stubs/real seams
    may accept ``(poc, target)``, ``(context)``, ``**kwargs``, etc. We inspect
    the signature and pass exactly the keyword arguments it accepts, falling
    back to positional conventions. No real process is ever spawned here.
    """
    kwargs_pool = {'poc': poc_value, 'target': target_label, 'package': poc_source, 'parked_package': poc_source, 'finding': poc_source, 'context': context}
    try:
        signature = inspect.signature(seam)
    except (TypeError, ValueError):
        signature = None
    if signature is not None:
        params = list(signature.parameters.values())
        accepts_var_kw = any((p.kind == inspect.Parameter.VAR_KEYWORD for p in params))
        if accepts_var_kw:
            return seam(**kwargs_pool)
        bindable = {p.name: kwargs_pool[p.name] for p in params if p.name in kwargs_pool and p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)}
        required = [p for p in params if p.default is inspect.Parameter.empty and p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)]
        if bindable and all((p.name in bindable for p in required)):
            try:
                return seam(**bindable)
            except TypeError:
                pass
    for args in ((poc_value, target_label), (poc_value,), (context,), (poc_source,)):
        try:
            return seam(*args)
        except TypeError:
            continue
    return seam()

def _normalize_result(result: Any) -> Optional[dict]:
    """Coerce a detonation result into a plain dict, or None if unparseable."""
    if result is None:
        return None
    if isinstance(result, dict):
        return dict(result)
    if dataclasses.is_dataclass(result) and (not isinstance(result, type)):
        try:
            return dataclasses.asdict(result)
        except Exception:
            return None
    as_dict = getattr(result, '_asdict', None)
    if callable(as_dict):
        try:
            return dict(as_dict())
        except Exception:
            return None
    instance_dict = getattr(result, '__dict__', None)
    if isinstance(instance_dict, dict) and instance_dict:
        return {name: value for name, value in instance_dict.items() if not name.startswith('_')}
    return None

def _lookup(data: dict, candidates: Iterable[str], default: Any=None) -> Any:
    for field_name in candidates:
        if field_name in data and data[field_name] is not None:
            return data[field_name]
    return default

def _has_field(data: dict, candidates: Iterable[str]) -> bool:
    return any((field_name in data and data[field_name] is not None for field_name in candidates))

def _classify(normalized: dict) -> tuple[str, Optional[str]]:
    """Determine the outcome label and an optional error message.

    A seam that explicitly reports success/failure wins; otherwise the outcome
    is derived from crash/exit-code signals (a detonation "succeeds" when the
    PoC triggers the vulnerability).
    """
    error_message = _lookup(normalized, _ERROR_MSG_FIELDS)
    error_message = None if error_message is None else str(error_message)
    if _has_field(normalized, _SUCCESS_FIELDS):
        reported = bool(_lookup(normalized, _SUCCESS_FIELDS))
        return (_OUTCOME_SUCCESS if reported else _OUTCOME_FAILURE, error_message)
    if _has_field(normalized, _FAILURE_FIELDS):
        failed = bool(_lookup(normalized, _FAILURE_FIELDS))
        return (_OUTCOME_FAILURE if failed else _OUTCOME_SUCCESS, error_message)
    exit_code = _lookup(normalized, _EXIT_CODE_FIELDS)
    fs_diff = _lookup(normalized, _FS_DIFF_FIELDS)
    stdout = _lookup(normalized, _STDOUT_FIELDS, '') or ''
    stderr = _lookup(normalized, _STDERR_FIELDS, '') or ''
    marker = _lookup(normalized, ('success_marker', 'marker'), _DEFAULT_MARKER)
    fs_sig = _lookup(normalized, ('expected_fs_signature', 'fs_signature'), _DEFAULT_FS_SIGNATURE)
    has_semantic_evidence = fs_diff is not None or (marker and (marker in stdout or marker in stderr))
    if has_semantic_evidence:
        try:
            from ngv2.detonation import semantic_verdict
        except Exception:
            semantic_verdict = None
        if semantic_verdict is not None:
            try:
                ec = int(exit_code) if exit_code is not None else None
            except (TypeError, ValueError):
                ec = None if exit_code is None else 1
            verdict = semantic_verdict(ec, str(stdout), str(stderr), str(fs_diff or ''), success_marker=str(marker), expected_fs_signature=str(fs_sig))
            return (_OUTCOME_SUCCESS if verdict == 'confirmed' else _OUTCOME_FAILURE, error_message)
    crashed = bool(_lookup(normalized, _CRASHED_FIELDS, False))
    if crashed:
        return (_OUTCOME_FAILURE, error_message)
    return (_OUTCOME_FAILURE, error_message)

def _build_report(*, target_label: Any, poc_value: Any, poc_source: Any, normalized: Optional[dict], outcome: str, error_message: Optional[str], timestamp: Any, raw_result: Any) -> dict:
    """Build a flat LiveTestReport-shaped mapping with synonym-rich fields."""
    data = normalized or {}
    exit_code = _lookup(data, _EXIT_CODE_FIELDS)
    stdout = _lookup(data, _STDOUT_FIELDS, '')
    stderr = _lookup(data, _STDERR_FIELDS, '')
    crashed = bool(_lookup(data, _CRASHED_FIELDS, False))
    timed_out = bool(_lookup(data, _TIMEOUT_FIELDS, False))
    duration = _lookup(data, _DURATION_FIELDS)
    term_signal = _lookup(data, _SIGNAL_FIELDS)
    detonated = outcome in (_OUTCOME_SUCCESS, _OUTCOME_FAILURE)
    passed = outcome == _OUTCOME_SUCCESS
    report = {'phase': PHASE, 'stage': PHASE, 'target': target_label, 'target_name': target_label, 'poc': _safe_jsonable(poc_value), 'poc_id': _poc_identity(poc_source, poc_value), 'poc_ref': _poc_identity(poc_source, poc_value), 'outcome': outcome, 'status': outcome, 'verdict': outcome, 'result': outcome, 'detonated': detonated, 'executed': detonated, 'success': passed, 'passed': passed, 'reproduced': passed, 'vulnerable': passed, 'exploited': passed, 'crashed': crashed, 'timed_out': timed_out, 'exit_code': exit_code, 'returncode': exit_code, 'signal': term_signal, 'stdout': stdout if stdout is not None else '', 'stderr': stderr if stderr is not None else '', 'duration': duration, 'error': error_message, 'error_message': error_message, 'timestamp': timestamp, 'raw_result': raw_result}
    return report

def _poc_identity(poc_source: Any, poc_value: Any) -> Optional[str]:
    if isinstance(poc_source, dict):
        for field_name in ('poc_id', 'id', 'finding_id', 'name', 'slug'):
            value = poc_source.get(field_name)
            if value:
                return str(value)
    if isinstance(poc_value, dict):
        for field_name in ('poc_id', 'id', 'name'):
            value = poc_value.get(field_name)
            if value:
                return str(value)
    if isinstance(poc_value, str):
        return poc_value if len(poc_value) <= 80 else poc_value[:80]
    return None

def _to_artifact(report: dict) -> dict:
    """Wrap a report mapping as an artifact dict for parse_stage_artifact.

    The artifact carries ``phase``, ``filename`` and JSON ``content`` (the
    arguments ``artifact_harvester.parse_stage_artifact(filename, content,
    phase)`` consumes) and also flattens the report fields at the top level so
    a ``contracts.LiveTestReport`` can be built directly from the artifact.
    """
    content = json.dumps(report, default=str, sort_keys=True)
    artifact = {'phase': PHASE, 'filename': 'detonate_live_test_report.json', 'content': content, 'report': report}
    for field_name, value in report.items():
        if field_name not in artifact:
            artifact[field_name] = value
    return artifact

def _safe_jsonable(value: Any) -> Any:
    """Return a JSON-serializable view of value (best effort, never raises)."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(k): _safe_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_jsonable(v) for v in value]
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)
_FS_DIFF_FIELDS = ('fs_snapshot_diff', 'fs_diff', 'fs_snapshot', 'snapshot_diff')
_DEFAULT_MARKER = 'VULNERABLE'
_DEFAULT_FS_SIGNATURE = 'pwned_marker'
if __name__ == '__main__':
    import sys as _sys
    from ngv2.workers._runner import main as _main
    _sys.exit(_main('detonate'))