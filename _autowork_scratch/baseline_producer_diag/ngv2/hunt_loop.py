"""ngv2/hunt_loop.py -- Phase-8.1 production hunt loop.

Pulls the ranked work queue and drives each qualified target through
clone -> create_session -> advance, PARKING at ``awaiting_submission`` and
NEVER auto-submitting. Every effectful dependency is an injected seam, so the
module stays pure, total, deterministic, and stdlib-only.
"""
from __future__ import annotations
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple
PARK_PHASES = frozenset({'awaiting_submission', 'manual_review', 'done'})
AWAITING_SUBMISSION = 'awaiting_submission'

def _is_mapping(obj: Any) -> bool:
    """Duck-typed mapping check (stdlib-only, no isinstance on typing.Mapping)."""
    return isinstance(obj, dict) or (hasattr(obj, 'get') and hasattr(obj, 'keys') and hasattr(obj, '__getitem__'))

def _result(repo: str, status: str, *, phase: Optional[str]=None, reason: Optional[str]=None, error: Optional[str]=None) -> Dict[str, Any]:
    """Build a single per-candidate result record."""
    return {'repo': repo, 'status': status, 'phase': phase, 'reason': reason, 'error': error}

def _target_info(target: Any, repo: str) -> Dict[str, Any]:
    """Derive the ``target_info`` mapping handed to ``create_session``.

    If ``target`` is itself a mapping, copy it; otherwise read the well-known
    attributes (only present, non-None fields are included). ``repo`` is always
    present.
    """
    if _is_mapping(target):
        info: Dict[str, Any] = dict(target)
        info.setdefault('repo', repo)
        return info
    info = {'repo': repo}
    field_names = ('repo_url', 'repo_root', 'pinned_commit', 'language', 'loc')
    for field_name in field_names:
        value = getattr(target, field_name, None)
        if value is not None:
            info[field_name] = value
    return info

def run_hunt_loop(candidates: Any, *, ranker: Callable[..., Any], cloner: Callable[[str], Any], create_session: Callable[[str, Mapping[str, Any]], Any], advance: Callable[[str], Any], admit: Optional[Callable[[str], Any]]=None, session_id_for: Optional[Callable[[str], str]]=None, cwe: str='CWE-94', severity: str='HIGH', purpose: str='hunt') -> Dict[str, Any]:
    """Drive the ranked queue through clone -> create_session -> advance.

    PARKS at ``awaiting_submission`` and NEVER auto-submits: ``advance`` is
    always called with exactly one positional argument.
    """
    queue = ranker(candidates, cwe=cwe, severity=severity, purpose=purpose)
    results: List[Dict[str, Any]] = []
    parked = 0
    for entry in queue:
        if isinstance(entry, (tuple, list)):
            repo = entry[0]
        else:
            repo = str(entry)
        if admit is not None:
            verdict = admit(repo)
            if _is_mapping(verdict):
                ok = verdict.get('admit')
                reason = verdict.get('reason')
            else:
                ok = None
                reason = None
            if not ok:
                results.append(_result(repo, 'deferred', reason=reason))
                continue
        try:
            target = cloner(repo)
        except Exception as exc:
            results.append(_result(repo, 'clone_failed', error=str(exc)))
            continue
        if session_id_for is not None:
            sid = session_id_for(repo)
        else:
            sid = 'hunt-' + repo.replace('/', '-')
        try:
            target_info = _target_info(target, repo)
            create_session(sid, target_info)
            outcome = advance(sid)
        except Exception as exc:
            results.append(_result(repo, 'error', error=str(exc)))
            continue
        if _is_mapping(outcome):
            phase = outcome.get('phase')
            reason = outcome.get('reason')
        else:
            phase = None
            reason = None
        if phase == AWAITING_SUBMISSION:
            parked += 1
            results.append(_result(repo, 'parked', phase=phase, reason=reason))
        elif phase in PARK_PHASES:
            results.append(_result(repo, 'halted', phase=phase, reason=reason))
        else:
            results.append(_result(repo, 'incomplete', phase=phase, reason=reason))
    return {'considered': len(queue), 'parked': parked, 'results': results}