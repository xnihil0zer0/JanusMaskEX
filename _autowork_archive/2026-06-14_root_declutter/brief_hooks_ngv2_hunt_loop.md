---
interfaces: "NEW orchestration module ngv2/hunt_loop.py exposing run_hunt_loop(candidates, *, ranker, cloner, create_session, advance, admit=None, session_id_for=None, cwe='CWE-94', severity='HIGH', purpose='hunt') -> dict (the Phase-8.1 production hunt loop: rank -> [admit] -> clone -> create_session -> advance, parking each target at awaiting_submission and NEVER auto-submitting); module constants PARK_PHASES (frozenset incl 'awaiting_submission','manual_review','done') and AWAITING_SUBMISSION='awaiting_submission'"
working_dir: "/home/xnihil0zer0/NobleGreedv2"
meta_task_type: io_adapter
---

# Title

ngv2/hunt_loop.py — NEW Phase-8.1 production hunt loop (rank -> clone -> create_session -> advance; PARKS at awaiting_submission, never auto-submits)

# Scope

Build a NEW orchestration module ngv2/hunt_loop.py in the external NobleGreedv2 repo (working_dir /home/xnihil0zer0/NobleGreedv2). This is the Phase-8.1 production entrypoint the FSM lacked: it pulls the ranked work queue, then for each candidate optionally checks the concurrency scheduler, clones the target, creates an FSM session, and advances it through the lifecycle. Every effectful dependency is an INJECTED SEAM — ranker (ngv2.selection_ranker.rank_candidates), cloner (ngv2.acquisition.cloner.clone_target), create_session and advance (ngv2.session_api.SessionApi.create_session / .advance), and an optional admit gate (the concurrency scheduler) — so the module itself is pure, total, deterministic, and stdlib-only; the e2e/CLI harness wires the real ones. SAFETY (hard, baked-in): the loop calls advance(sid) with EXACTLY ONE positional argument and NEVER passes an approval decision, so the FSM fail-closes and PARKS at awaiting_submission — the loop NEVER auto-submits to any platform. Per candidate the loop records a result dict with status: 'parked' (reached awaiting_submission — the success case), 'deferred' (scheduler did not admit), 'clone_failed' (clone raised — isolated, loop continues), 'halted' (reached another PARK_PHASE like manual_review/done), 'incomplete' (stuck mid-lifecycle), or 'error' (session/advance raised). Returns {'considered': int, 'parked': int, 'results': [...]}. Emit the whole file VERBATIM from Deliverables. Name the committed oracle tests/test_hunt_loop_wired.py in the verification_command. Required plan shape: EXACTLY ONE impl task building this one new single file.

# Non-Goals

This is a NEW single-file module, not an edit; integration is out of scope — do NOT author or modify any test (the oracle tests/test_hunt_loop_wired.py is committed and authoritative) and do NOT add integration/e2e tests. Do NOT import ngv2.selection_ranker, ngv2.acquisition.cloner, ngv2.session_api, ngv2.concurrency_scheduler, or ANY ngv2 sibling at module scope — they arrive ONLY as injected callables (this keeps the oracle hermetic and avoids a sibling-import smoke failure). Do NOT call the network, a real clock, randomness, threading, multiprocessing, subprocess, sqlite, or the filesystem in any path. Do NOT pass an approval decision to advance under any circumstance (auto-submit is forbidden). No LLM, no third-party imports (stdlib only). Touch exactly the one new file ngv2/hunt_loop.py.

# Inputs

run_hunt_loop(candidates, *, ranker, cloner, create_session, advance, admit=None, session_id_for=None, cwe='CWE-94', severity='HIGH', purpose='hunt'). ``ranker(candidates, *, cwe, severity, purpose)`` returns an ordered queue of entries whose first element (entry[0] for a tuple/list, else str(entry)) is the repo. For each repo: if ``admit`` is given, call admit(repo) -> mapping; only proceed when .get('admit') is truthy, else record status 'deferred' with the verdict's reason. ``cloner(repo)`` returns a Target (or mapping); a raised exception -> status 'clone_failed' (loop continues). ``session_id_for(repo)`` (default 'hunt-' + repo with '/'->'-') yields the session id. ``create_session(sid, target_info)`` then ``advance(sid)`` (ONE arg, no approval) are called; the resulting mapping's 'phase' decides the status. target_info is the Target's repo_url/repo_root/pinned_commit/language/loc (or the mapping itself), always including 'repo'.

# Deliverables

ngv2/hunt_loop.py with EXACTLY this content:

```python
"""ngv2.hunt_loop — Phase-8.1 production hunt loop (autonomous orchestration).

Pulls the ranked work queue and drives each qualified target through
clone -> create_session -> advance, PARKING at awaiting_submission. The
production entrypoint the FSM lacked. Every effectful dependency is an INJECTED
SEAM (ranker, cloner, create_session, advance, optional admit gate), so this
module is pure, total, deterministic, and stdlib-only; the e2e/CLI harness wires
the real ngv2 producers.

SAFETY (hard constraint): advance is ALWAYS called with exactly one positional
argument and NEVER an approval decision, so the FSM fail-closes at
awaiting_submission. The loop NEVER auto-submits to a real platform — submission
stays human-gated at the park.
"""
from __future__ import annotations
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

# FSM phases at which the loop STOPS and hands off to a human. The success case
# is awaiting_submission (the human-gated park); the loop never advances past it.
PARK_PHASES = frozenset({'awaiting_submission', 'manual_review', 'done'})
AWAITING_SUBMISSION = 'awaiting_submission'


def _result(repo: str, *, status: str, phase: Optional[str] = None,
            session_id: Optional[str] = None, reason: Optional[str] = None,
            error: Optional[str] = None) -> Dict[str, Any]:
    return {'repo': repo, 'status': status, 'phase': phase,
            'session_id': session_id, 'reason': reason, 'error': error}


def _target_info(target: Any, repo: str) -> Dict[str, Any]:
    if isinstance(target, Mapping):
        info = dict(target)
        info.setdefault('repo', repo)
        return info
    info: Dict[str, Any] = {'repo': repo}
    for field in ('repo_url', 'repo_root', 'pinned_commit', 'language', 'loc'):
        val = getattr(target, field, None)
        if val is not None:
            info[field] = val
    return info


def run_hunt_loop(
    candidates: Sequence[Mapping[str, Any]],
    *,
    ranker: Callable[..., Sequence],
    cloner: Callable[[str], Any],
    create_session: Callable[[str, Mapping[str, Any]], Any],
    advance: Callable[[str], Mapping[str, Any]],
    admit: Optional[Callable[[str], Mapping[str, Any]]] = None,
    session_id_for: Optional[Callable[[str], str]] = None,
    cwe: str = 'CWE-94',
    severity: str = 'HIGH',
    purpose: str = 'hunt',
) -> Dict[str, Any]:
    """Drive ranked candidates through clone -> session -> advance, parking at
    awaiting_submission. Pure orchestration over injected seams. NEVER passes an
    approval decision to advance, so the FSM cannot auto-submit.
    """
    queue = list(ranker(candidates, cwe=cwe, severity=severity, purpose=purpose))
    results: List[Dict[str, Any]] = []
    sid_fn = session_id_for or (lambda repo: 'hunt-%s' % str(repo).replace('/', '-'))
    parked = 0
    for entry in queue:
        repo = entry[0] if isinstance(entry, (tuple, list)) else str(entry)
        if admit is not None:
            verdict = admit(repo)
            if not (isinstance(verdict, Mapping) and verdict.get('admit')):
                reason = verdict.get('reason') if isinstance(verdict, Mapping) else None
                results.append(_result(repo, status='deferred', reason=reason))
                continue
        try:
            target = cloner(repo)
        except Exception as exc:  # clone failures must not kill the loop
            results.append(_result(repo, status='clone_failed', error=str(exc)))
            continue
        sid = sid_fn(repo)
        target_info = _target_info(target, repo)
        try:
            create_session(sid, target_info)
            # SAFETY: advance with NO approval decision -> FSM parks, no submit.
            adv = advance(sid)
        except Exception as exc:
            results.append(_result(repo, status='error', session_id=sid, error=str(exc)))
            continue
        phase = adv.get('phase') if isinstance(adv, Mapping) else None
        reason = adv.get('reason') if isinstance(adv, Mapping) else None
        if phase == AWAITING_SUBMISSION:
            parked += 1
            results.append(_result(repo, status='parked', phase=phase,
                                   session_id=sid, reason=reason))
        elif phase in PARK_PHASES:
            results.append(_result(repo, status='halted', phase=phase,
                                   session_id=sid, reason=reason))
        else:
            results.append(_result(repo, status='incomplete', phase=phase,
                                   session_id=sid, reason=reason))
    return {'considered': len(queue), 'parked': parked, 'results': results}
```

DISPATCH DIRECTIVE — this is a NEW single-file module. Emit it as a single whole-file deliverable for ngv2/hunt_loop.py reproducing the Deliverables content BYTE-FOR-BYTE (it already imports everything it needs from the stdlib; no ngv2 sibling imports — all producers arrive as injected callables). Do NOT emit a `__JANUSMASK_PATCHES__` list — this is a new file, not a symbol patch. meta_task_type=io_adapter (external NGv2 target; the diff-fuzzer cannot resolve external imports, so use the fuzzer-bypassed, smoke-gated io_adapter meta-type). Use this task_id VERBATIM: `ngv2-hunt-loop`. priority: high. dependencies: []. files_touched: `["ngv2/hunt_loop.py"]` ONLY. verification_command (CWD-relative, NO `cd`): `.venv/bin/python -m pytest tests/test_hunt_loop_wired.py -q`. The committed oracle tests/test_hunt_loop_wired.py is the authoritative acceptance contract; do NOT author new tests. `spec.functional_requirements` MUST be CONSOLIDATED to at most 5 entries, and `test_spec.unit_tests` MUST enumerate AT LEAST as many entries as `spec.functional_requirements` (validator floor: len(unit_tests) >= len(functional_requirements)); unit_tests entries are descriptors NAMING committed-oracle test cases (this does NOT authorize authoring new tests). `test_spec.regression_tests` MUST list at least two entries that NAME existing test cases from this brief's committed oracle (plan descriptors referencing the committed oracle — this does NOT authorize authoring tests), e.g. `test_happy_path_parks_at_awaiting_submission` and `test_advance_never_passed_approval` (also good: `test_clone_failure_isolated`, `test_scheduler_defers_blocked_candidate`).
