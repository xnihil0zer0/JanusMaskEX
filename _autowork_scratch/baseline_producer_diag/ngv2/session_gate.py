"""Pure transition-gate validation rules for the pipeline phases.

Agentic Spine Epic B, LEAF B1.

This module is intentionally *pure*: it performs no database access and no file
I/O.  It operates over an injected, already-deserialized artifact set (``rows``)
and decides whether a phase transition is allowed.

``rows`` is a dict keyed by artifact type, each value a list of artifact dicts
(the ``to_dict()`` forms of the contract dataclasses)::

    {
        'findings': [Finding.to_dict(), ...],
        'pocs':     [PoC.to_dict(), ...],
        'reports':  [LiveTestReport.to_dict(), ...],
    }

Missing keys are treated as empty lists.

Gate rules (the four pipeline edges):

- ``hunt -> triage``    : ok iff there is >= 1 valid ``Finding``.
- ``triage -> poc``     : ok iff the findings are deduped (no duplicate
                          ``Finding.id``) and >= 1 finding exists.
- ``poc -> detonate``   : ok iff every ``PoC.finding_id`` maps to a registered
                          finding id (no orphan PoC).
- ``detonate -> report``: ok iff every PoC has a matching ``LiveTestReport``.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from ngv2.contracts import Finding
from ngv2.contracts import PoC
from ngv2.contracts import LiveTestReport

from dataclasses import field
@dataclass
class GateResult:
    """Outcome of a single FSM gate evaluation."""

    ok: bool
    payload: Dict[str, Any] = field(default_factory=dict)
    phase_from: str = ""
    phase_to: str = ""
    error: Optional[str] = None

def _rows_for(rows: Dict[str, List[dict]], bucket: str) -> List[dict]:
    """Return the list of artifact dicts for ``bucket``; absent -> empty."""
    if not rows:
        return []
    value = rows.get(bucket)
    if not value:
        return []
    return list(value)

def _deserialize(contract: Any, raw: dict) -> Any:
    """Rebuild a contract instance from its dict form, preferring from_dict."""
    builder = getattr(contract, 'from_dict', None)
    if callable(builder):
        return builder(raw)
    return contract(**raw)

def _validate(instance: Any) -> None:
    """Run the artifact's own ``validate()`` if it exposes one."""
    validator = getattr(instance, 'validate', None)
    if callable(validator):
        validator()

def _load_findings(rows: Dict[str, List[dict]]) -> List[Any]:
    """Deserialize and validate every finding; may raise ValueError."""
    findings: List[Any] = []
    for raw in _rows_for(rows, 'findings'):
        finding = _deserialize(Finding, raw)
        _validate(finding)
        findings.append(finding)
    return findings

def _load_pocs(rows: Dict[str, List[dict]]) -> List[Any]:
    pocs: List[Any] = []
    for raw in _rows_for(rows, 'pocs'):
        poc = _deserialize(PoC, raw)
        _validate(poc)
        pocs.append(poc)
    return pocs

def _load_reports(rows: Dict[str, List[dict]]) -> List[Any]:
    reports: List[Any] = []
    for raw in _rows_for(rows, 'reports'):
        report = _deserialize(LiveTestReport, raw)
        _validate(report)
        reports.append(report)
    return reports

def _gate_hunt_to_triage(rows: Dict[str, List[dict]]) -> GateResult:
    try:
        findings = _load_findings(rows)
    except (ValueError, TypeError, KeyError) as exc:
        return GateResult(ok=False, error='Invalid finding: ' + str(exc))
    if not findings:
        return GateResult(ok=False, error='No artifacts found')
    return GateResult(ok=True, error=None)

def _gate_triage_to_poc(rows: Dict[str, List[dict]]) -> GateResult:
    try:
        findings = _load_findings(rows)
    except (ValueError, TypeError, KeyError) as exc:
        return GateResult(ok=False, error='Invalid finding: ' + str(exc))
    if not findings:
        return GateResult(ok=False, error='No artifacts found')
    ids = [f.id for f in findings]
    if len(set(ids)) != len(ids):
        return GateResult(ok=False, error='Duplicate findings detected')
    return GateResult(ok=True, error=None)

def _gate_poc_to_detonate(pf: str, pt: str, ev: Any) -> GateResult:
    report = _first(ev, ('live_report', 'report', 'detonation', 'live'), ev)
    verdict = semantic_verdict(report, ev)
    if verdict == 'confirmed':
        return GateResult(ok=True, phase_from=pf, phase_to=pt, payload={'semantic_verdict': verdict})
    return GateResult(ok=False, phase_from=pf, phase_to=pt, error='unconfirmed', payload={'semantic_verdict': verdict})

def _gate_detonate_to_report(rows: Dict[str, List[dict]]) -> GateResult:
    try:
        pocs = _load_pocs(rows)
        reports = _load_reports(rows)
    except (ValueError, TypeError, KeyError) as exc:
        return GateResult(ok=False, error='Invalid artifact: ' + str(exc))
    if not pocs:
        return GateResult(ok=False, error='No artifacts found')
    reported = {r.poc_finding_id for r in reports}
    missing = [p.finding_id for p in pocs if p.finding_id not in reported]
    if missing:
        return GateResult(ok=False, error='PoC(s) without a LiveTestReport: ' + ', '.join(sorted(set(missing))))
    return GateResult(ok=True, error=None)
_TRANSITIONS = {('hunt', 'triage'): _gate_hunt_to_triage, ('triage', 'poc'): _gate_triage_to_poc, ('poc', 'detonate'): _gate_poc_to_detonate, ('detonate', 'report'): _gate_detonate_to_report}

def gate_transition(phase_from: Any, phase_to: Any, evidence: Any=None) -> GateResult:
    """Dispatch a lifecycle gate; accepts BOTH calling conventions.

    New (lifecycle): ``gate_transition(phase_from: str, phase_to: str, evidence)``
    dispatches over ``_HANDLERS``.  Legacy (rows): ``gate_transition(rows: dict,
    from_phase, to_phase)`` evaluates the four artifact gates plus the
    every-phase -> 'done' early-abort, exactly as before the lifecycle epic.
    """
    if isinstance(phase_from, str):
        handler = _HANDLERS.get((phase_from, phase_to))
        if handler is None:
            return GateResult(ok=False, phase_from=phase_from, phase_to=phase_to, error='no_gate')
        return handler(phase_from, phase_to, evidence)
    rows, from_phase, to_phase = (phase_from, phase_to, evidence)
    if to_phase == 'done':
        return GateResult(ok=True, error=None)
    if not rows:
        return GateResult(ok=False, error='No artifacts found')
    if (from_phase, to_phase) == ('poc', 'detonate'):
        try:
            findings = _load_findings(rows)
            pocs = _load_pocs(rows)
        except (ValueError, TypeError, KeyError) as exc:
            return GateResult(ok=False, error='Invalid artifact: ' + str(exc))
        if not pocs:
            return GateResult(ok=False, error='No artifacts found')
        registered = {f.id for f in findings}
        orphans = [p.finding_id for p in pocs if p.finding_id not in registered]
        if orphans:
            return GateResult(ok=False, error='Orphan PoC(s) with no registered finding: ' + ', '.join(sorted(set(orphans))))
        return GateResult(ok=True, error=None)
    legacy_handlers = {('hunt', 'triage'): _gate_hunt_to_triage, ('triage', 'poc'): _gate_triage_to_poc, ('detonate', 'report'): _gate_detonate_to_report}
    handler = legacy_handlers.get((from_phase, to_phase))
    if handler is None:
        return GateResult(ok=False, error='Unknown transition: ' + str(from_phase) + ' -> ' + str(to_phase))
    return handler(rows)
import importlib
from dataclasses import field
from typing import Callable
from typing import Tuple

def _bind(attr: str, *module_names: str) -> Optional[Callable[..., Any]]:
    """Resolve ``attr`` from the first importable module among ``module_names``."""
    for module_name in module_names:
        try:
            module = importlib.import_module(module_name)
        except Exception:
            continue
        candidate = getattr(module, attr, None)
        if candidate is not None:
            return candidate
    return None
qualify = _bind('qualify', 'ngv2_source_qualify_gate', 'ngv2.ngv2_source_qualify_gate', 'ngv2.source_qualify_gate')
compute_confidence = _bind('compute_confidence', 'ngv2_grounding_confidence_gate', 'ngv2.ngv2_grounding_confidence_gate', 'ngv2.grounding_confidence_gate')
route_confidence = _bind('route_confidence', 'ngv2_grounding_confidence_gate', 'ngv2.ngv2_grounding_confidence_gate', 'ngv2.grounding_confidence_gate')
classify_novelty = _bind('classify_novelty', 'ngv2_novelty_gate', 'ngv2.ngv2_novelty_gate', 'ngv2.novelty_gate')
route_novelty = _bind('route_novelty', 'ngv2_novelty_gate', 'ngv2.ngv2_novelty_gate', 'ngv2.novelty_gate')
build_submission_package = _bind('build_submission_package', 'ngv2_submission_package_builder', 'ngv2.ngv2_submission_package_builder', 'ngv2.submission_package_builder', 'ngv2.submission_package')
readiness = _bind('readiness', 'ngv2_submission_readiness_gate', 'ngv2.ngv2_submission_readiness_gate', 'ngv2.submission_readiness_gate')
approve_submission = _bind('check_human_approval', 'ngv2.human_checkpoint_gate', 'ngv2_human_checkpoint_gate', 'ngv2.ngv2_human_checkpoint_gate')
record_submission = _bind('persist_submission', 'ngv2.human_checkpoint_gate', 'ngv2_human_checkpoint_gate', 'ngv2.ngv2_human_checkpoint_gate')
_imported_semantic_verdict = _bind('semantic_verdict', 'ngv2_detonation_gate', 'ngv2.ngv2_detonation_gate', 'ngv2.detonation_gate', 'ngv2_live_detonation_gate', 'ngv2.ngv2_live_detonation_gate')

def _get(obj: Any, name: str, default: Any=None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)

def _first(obj: Any, names: Tuple[str, ...], default: Any=None) -> Any:
    for name in names:
        value = _get(obj, name, None)
        if value is not None:
            return value
    return default

def _call(fn: Optional[Callable[..., Any]], *args: Any) -> Any:
    """Invoke ``fn`` tolerantly, trying a few arities before giving up."""
    if fn is None:
        return None
    attempts = []
    if args:
        attempts.append(args)
        attempts.append(args[:1])
    attempts.append(())
    for call_args in attempts:
        try:
            return fn(*call_args)
        except TypeError:
            continue
        except Exception:
            return None
    return None

def _decision(value: Any) -> str:
    """Normalize a gate return value into a single decision string."""
    if value is None:
        return ''
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return 'true' if value else 'false'
    label_fields = ('route', 'decision', 'action', 'verdict', 'outcome', 'status', 'disposition', 'band', 'label')
    if isinstance(value, dict):
        for name in label_fields:
            if name in value and value[name] is not None:
                return str(value[name])
        return str(value)
    for name in label_fields:
        attr = getattr(value, name, None)
        if attr is not None:
            return str(attr)
    return str(value)

def _is_go(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    token = _decision(value).strip().lower()
    if token in ('go', 'qualified', 'admit', 'pass', 'yes', 'true', 'ok', 'accept', 'accepted', 'eligible', 'in_scope'):
        return True
    if _get(value, 'qualified', None) is True:
        return True
    if _get(value, 'go', None) is True:
        return True
    if _get(value, 'ok', None) is True:
        return True
    return False

def _confidence_band(value: Any) -> str:
    token = _decision(value).strip().upper()
    if 'CONFIRM' in token or 'HIGH' in token or token == 'ADMIT' or (token == 'ADMITTED'):
        return 'ADMIT'
    if 'MEDIUM' in token or 'MANUAL' in token or 'HOLD' in token or ('REVIEW' in token):
        return 'MANUAL'
    if 'LOW' in token or 'DROP' in token or 'REJECT' in token:
        return 'DROP'
    return token

def _signature_in_diff(signature: Any, diff: Any) -> bool:
    """True iff ``signature`` is present anywhere in a live fs ``diff``."""
    if signature is None:
        return False
    if isinstance(diff, dict):
        if signature in diff:
            return True
        for value in diff.values():
            if value == signature:
                return True
            if isinstance(value, (list, tuple, set)) and signature in value:
                return True
        return False
    if isinstance(diff, (list, tuple, set)):
        if signature in diff:
            return True
        for item in diff:
            if item == signature:
                return True
            if isinstance(item, dict) and (signature in item.keys() or signature in item.values()):
                return True
            if isinstance(item, str) and isinstance(signature, str) and (signature in item):
                return True
        return False
    if isinstance(diff, str) and isinstance(signature, str):
        return signature in diff
    return diff == signature

def semantic_verdict(report: Any, evidence: Any=None) -> str:
    """Return 'confirmed' only when exit 0 AND success marker AND the expected
    filesystem-signature are all present in the live detonation report.

    A success marker on its own (marker-spoofing) never confirms.
    """
    if _imported_semantic_verdict is not None:
        verdict = _call(_imported_semantic_verdict, report, evidence)
        if verdict is None:
            verdict = _call(_imported_semantic_verdict, report)
        if isinstance(verdict, str) and verdict:
            return verdict
    exit_code = _first(report, ('exit_code', 'exit', 'exit_status', 'returncode'))
    exit_ok = exit_code == 0
    if exit_code is None and _get(report, 'exit_ok', None) is True:
        exit_ok = True
    success_marker = _first(report, ('success_marker', 'marker'))
    markers = _get(report, 'markers', None)
    stdout = _get(report, 'stdout', '') or ''
    marker_present = False
    if success_marker is not None:
        if isinstance(markers, (list, tuple, set)) and success_marker in markers:
            marker_present = True
        elif isinstance(stdout, str) and success_marker and (success_marker in stdout):
            marker_present = True
        elif _get(report, 'marker_present', None) is True:
            marker_present = True
    elif _get(report, 'marker_present', None) is True:
        marker_present = True
    expected_signature = _first(report, ('expected_signature', 'expected_fs_signature'))
    if expected_signature is None:
        expected_signature = _first(evidence, ('expected_signature', 'expected_fs_signature'))
    fs_diff = _first(report, ('fs_diff', 'live_fs_diff', 'filesystem_diff'), [])
    signature_present = _signature_in_diff(expected_signature, fs_diff)
    if exit_ok and marker_present and signature_present:
        return 'confirmed'
    return 'unconfirmed'

def _gate_source_to_hunt(pf: str, pt: str, ev: Any) -> GateResult:
    target = _first(ev, ('target', 'targets', 'candidate'), ev)
    oracle_result = _first(ev, ('oracle_result', 'oracle', 'qualification_inputs'), None)
    result = _call(qualify, target, oracle_result)
    if result is None:
        result = _call(qualify, ev, oracle_result)
    if _is_go(result):
        return GateResult(ok=True, phase_from=pf, phase_to=pt, payload={'qualification': result})
    return GateResult(ok=False, phase_from=pf, phase_to=pt, error='unqualified', payload={'qualification': result})

def _reachability_triage_band(ev: Any) -> Optional[str]:
    """Consult the Stage-3 LLM scope/auth triage when an LLM seam is supplied.

    Returns 'ADMIT'/'MANUAL'/'DROP', or None to skip triage (no seam present, so
    legacy callers are unaffected). Any error fail-safes to 'MANUAL'.
    """
    if not isinstance(ev, dict):
        return None
    complete = ev.get('llm_complete')
    client = ev.get('llm_client')
    if complete is None and client is None:
        return None
    finding = _first(ev, ('finding', 'findings'), {})
    path = ev.get('taint_path') or ev.get('path')
    snippets = ev.get('snippets')
    try:
        from ngv2.reachability_triage import judge
        return judge(finding, path, snippets, client=client, complete=complete).get('band')
    except Exception:
        return 'MANUAL'
def _gate_triage_to_verify(pf: str, pt: str, ev: Any) -> GateResult:
    finding = _first(ev, ('finding', 'findings'), ev)
    triage_band = _reachability_triage_band(ev)
    if triage_band == 'DROP':
        return GateResult(ok=False, phase_from=pf, phase_to=pt, error='out_of_scope', payload={'triage': 'DROP'})
    if triage_band == 'MANUAL':
        return GateResult(ok=False, phase_from=pf, phase_to=pt, error='manual_review_scope', payload={'triage': 'MANUAL'})
    try:
        from ngv2.confidence_signals import resolve_signals
        signals = resolve_signals(ev, finding)
    except Exception:
        signals = None
    confidence = _call(compute_confidence, finding, signals)
    route = _call(route_confidence, confidence)
    if route is None:
        route = confidence
    band = _confidence_band(route)
    if band == 'ADMIT':
        return GateResult(ok=True, phase_from=pf, phase_to=pt, payload={'confidence': confidence, 'route': route})
    if band == 'MANUAL':
        return GateResult(ok=False, phase_from=pf, phase_to=pt, error='manual_review', payload={'confidence': confidence, 'route': route})
    if band == 'DROP':
        return GateResult(ok=False, phase_from=pf, phase_to=pt, error='dropped', payload={'confidence': confidence, 'route': route})
    return GateResult(ok=False, phase_from=pf, phase_to=pt, error='unrouted', payload={'confidence': confidence, 'route': route})

def _gate_verify_to_poc(pf: str, pt: str, ev: Any) -> GateResult:
    poc = _first(ev, ('poc', 'proof_of_concept', 'build'), ev)
    exit_code = _first(poc, ('build_exit', 'exit_code', 'exit', 'returncode'))
    built = _first(poc, ('built', 'build_ok', 'ok'))
    is_built = built is True or exit_code == 0
    if is_built:
        return GateResult(ok=True, phase_from=pf, phase_to=pt, payload={'poc': poc})
    return GateResult(ok=False, phase_from=pf, phase_to=pt, error='poc_build_failed', payload={'poc': poc})

def _gate_detonate_to_novelty(pf: str, pt: str, ev: Any) -> GateResult:
    finding = _first(ev, ('finding', 'findings'), ev)
    corpus = _first(ev, ('corpus', 'known_corpus', 'known'), None)
    classification = _call(classify_novelty, finding, corpus)
    if classification is None:
        classification = _call(classify_novelty, finding)
    route = _call(route_novelty, classification)
    if route is None:
        route = classification
    token = _decision(route).strip().upper().replace('-', '_')
    is_novel = token in ('NOVEL', 'ADMIT', 'NEW', 'UNIQUE') or ('NOVEL' in token and (not any((neg in token for neg in ('NOT', 'NON', 'KNOWN', 'DUP')))))
    if is_novel:
        return GateResult(ok=True, phase_from=pf, phase_to=pt, payload={'novelty': classification, 'route': route})
    return GateResult(ok=False, phase_from=pf, phase_to=pt, error='not_novel', payload={'novelty': classification, 'route': route})

def _gate_novelty_to_report(pf: str, pt: str, ev: Any) -> GateResult:
    package = _call(build_submission_package, ev)
    if package is None:
        finding = _first(ev, ('finding', 'findings'), ev)
        package = _call(build_submission_package, finding)
    if package is None:
        return GateResult(ok=False, phase_from=pf, phase_to=pt, error='no_package')
    if _get(package, 'ok', True) is False:
        return GateResult(ok=False, phase_from=pf, phase_to=pt, error='package_failed', payload={'package': package})
    return GateResult(ok=True, phase_from=pf, phase_to=pt, payload={'package': package})

def _gate_report_to_awaiting(pf: str, pt: str, ev: Any) -> GateResult:
    package = _first(ev, ('package', 'submission_package'), ev)
    result = _call(readiness, package)
    if result is None:
        result = _call(readiness, ev)
    ready = _get(result, 'ready', None)
    if ready is None:
        ready = _is_go(result)
    if ready is True:
        return GateResult(ok=True, phase_from=pf, phase_to=pt, payload={'readiness': result})
    return GateResult(ok=False, phase_from=pf, phase_to=pt, error='not_ready', payload={'readiness': result})

def _gate_awaiting_to_submitted(pf: str, pt: str, ev: Any) -> GateResult:
    decision = _call(approve_submission, ev)
    outcome = _first(decision, ('outcome', 'decision', 'status'), _decision(decision))
    token = str(outcome).strip().lower()
    approved = _get(decision, 'approved', None) is True or token in ('approved', 'approve', 'go', 'admit', 'accepted', 'accept')
    if approved:
        return GateResult(ok=True, phase_from=pf, phase_to=pt, payload={'approval': decision})
    if token == 'parked':
        return GateResult(ok=False, phase_from=pf, phase_to=pt, error='parked', payload={'approval': decision})
    return GateResult(ok=False, phase_from=pf, phase_to=pt, error=token or 'not_approved', payload={'approval': decision})

def _gate_submitted_to_done(pf: str, pt: str, ev: Any) -> GateResult:
    record = _call(record_submission, ev)
    if record is None:
        return GateResult(ok=False, phase_from=pf, phase_to=pt, error='no_record')
    return GateResult(ok=True, phase_from=pf, phase_to=pt, payload={'record': record})
_HANDLERS: Dict[Tuple[str, str], Callable[[str, str, Any], GateResult]] = {('source', 'hunt'): _gate_source_to_hunt, ('triage', 'verify'): _gate_triage_to_verify, ('verify', 'poc'): _gate_verify_to_poc, ('poc', 'detonate'): _gate_poc_to_detonate, ('detonate', 'novelty'): _gate_detonate_to_novelty, ('novelty', 'report'): _gate_novelty_to_report, ('report', 'awaiting_submission'): _gate_report_to_awaiting, ('awaiting_submission', 'submitted'): _gate_awaiting_to_submitted, ('submitted', 'done'): _gate_submitted_to_done}
"ngv2.session_gate -- evidence-gated lifecycle transition dispatch.\n\n``gate_transition(phase_from, phase_to, evidence) -> GateResult`` wires each\nlifecycle edge to its corresponding *pure* sibling gate:\n\n    source -> hunt                 : qualify()\n    triage -> verify               : compute_confidence() + route_confidence()\n    verify -> poc                  : PoC build check\n    poc -> detonate                : semantic_verdict() == 'confirmed'\n    detonate -> novelty            : classify_novelty() + route_novelty()\n    novelty -> report              : build_submission_package()\n    report -> awaiting_submission  : readiness()\n    awaiting_submission -> submitted : approve_submission()\n    submitted -> done              : record_submission()\n\nAll sibling gates are imported (never re-implemented) and invoked here.  The\ndetonation verdict is intentionally strict: a success marker alone never\nconfirms -- the expected filesystem-signature must also appear in the live fs\ndiff, so marker-spoofing fails.\n\nPure and deterministic: no clock, randomness, network, or subprocess in this\nmodule.  Every seam (oracle, scanners, hunt worker, live runner, approval) is\ninjected via the ``evidence`` payload.\n"