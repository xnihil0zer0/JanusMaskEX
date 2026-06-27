"""Deterministic hunt-phase state machine over Finding."""
from __future__ import annotations
from dataclasses import dataclass
from dataclasses import field
from ngv2.contracts import Finding

def transition_with_gate(machine, to, gate_result):
    """Advance ``machine`` to ``to`` only when the gate passes and the move is allowed.

    The move proceeds only if ``gate_result.ok`` is truthy AND the FSM permits the
    transition (reusing ``machine.can_transition``). A passing gate never bypasses
    the allow-map. On a failing gate or a disallowed move, raise ``ValueError``
    carrying ``gate_result.error`` and leave ``machine.state.phase`` unchanged.

    ``gate_result`` is duck-typed via ``.ok``/``.error``; ``session_gate`` is not
    imported.
    """
    if getattr(gate_result, 'ok', False) and machine.can_transition(to):
        machine.transition(to)
        return machine
    raise ValueError(getattr(gate_result, 'error', None))
from typing import Tuple
PHASES: Tuple[str, ...] = ('hunt', 'triage', 'poc', 'detonate', 'report', 'done')
from typing import Dict
ALLOWED_TRANSITIONS: Dict[str, Tuple[str, ...]] = {'hunt': ('triage', 'done'), 'triage': ('poc', 'done'), 'poc': ('detonate', 'done'), 'detonate': ('report', 'done'), 'report': ('done',), 'done': ()}

@dataclass
class HuntState:
    phase: str = 'hunt'
    findings: List[Any] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {'phase': self.phase, 'findings': [_finding_to_dict(f) for f in self.findings]}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'HuntState':
        phase = data.get('phase', 'hunt')
        raw = data.get('findings') or []
        return cls(phase=phase, findings=[_finding_from_dict(f) for f in raw])
    'Serializable hunt state: current phase plus accumulated findings.'

class HuntStateMachine:

    def __init__(self, state: Optional[HuntState]=None) -> None:
        self.state = state if state is not None else HuntState()

    def can_transition(self, phase_to: str) -> bool:
        return phase_to in ALLOWED_TRANSITIONS.get(self.state.phase, ())

    def transition(self, phase_to: str) -> None:
        if not self.can_transition(phase_to):
            raise ValueError('illegal transition: %r -> %r' % (self.state.phase, phase_to))
        self.state.phase = phase_to

    def add_finding(self, finding: Any) -> None:
        self.state.findings.append(finding)

    def to_dict(self) -> Dict[str, Any]:
        return self.state.to_dict()

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'HuntStateMachine':
        return cls(state=HuntState.from_dict(data))
    'Phase state machine governing legal transitions over :data:`PHASES`.'
import dataclasses
from typing import Any
from typing import List
from typing import Optional
LIFECYCLE_PHASES: Tuple[str, ...] = ('source', 'hunt', 'triage', 'verify', 'poc', 'detonate', 'novelty', 'report', 'awaiting_submission', 'submitted', 'done')

def _ordered_one_step(phases: Tuple[str, ...]) -> Dict[str, Tuple[str, ...]]:
    """Build a strictly one-step-ordered transition map for ``phases``."""
    transitions: Dict[str, Tuple[str, ...]] = {}
    for index, name in enumerate(phases):
        if index + 1 < len(phases):
            transitions[name] = (phases[index + 1],)
        else:
            transitions[name] = ()
    return transitions
LIFECYCLE_TRANSITIONS: Dict[str, Tuple[str, ...]] = _ordered_one_step(LIFECYCLE_PHASES)

def _finding_to_dict(finding: Any) -> Any:
    """Best-effort serialization of a Finding into a plain dict."""
    if dataclasses.is_dataclass(finding) and (not isinstance(finding, type)):
        return dataclasses.asdict(finding)
    if hasattr(finding, 'to_dict'):
        return finding.to_dict()
    if hasattr(finding, '__dict__'):
        return dict(vars(finding))
    return finding

def _finding_from_dict(data: Any) -> Any:
    """Best-effort reconstruction of a Finding from a plain dict."""
    if isinstance(data, Finding):
        return data
    if isinstance(data, dict):
        from_dict = getattr(Finding, 'from_dict', None)
        if callable(from_dict):
            return from_dict(data)
        return Finding(**data)
    return data
'ngv2.state_machine -- Hunt lifecycle phase model and serializable state.\n\nPins the canonical ``hunt -> triage -> poc -> detonate -> report -> done`` phase\nmodel (with early-abort to ``done`` available from every non-terminal phase) and\na small, JSON-serializable :class:`HuntState` that carries accumulated Findings.\n\nThis module is *additively* extended with an optional full-lifecycle view\n(:data:`LIFECYCLE_PHASES` / :data:`LIFECYCLE_TRANSITIONS`) describing the\nautonomous lifecycle wired by :mod:`ngv2.session_gate`.  The canonical\n:data:`PHASES` / :data:`ALLOWED_TRANSITIONS` contract is preserved unchanged for\nbackward compatibility -- existing callers and oracles keep working.\n\nPure and deterministic: no clock, randomness, network, or subprocess.\n'