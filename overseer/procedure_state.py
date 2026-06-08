"""Durable per-conversation procedure state for the overseer.

The procedure machine's state is READ from disk, never reconstructed: a phase
pointer plus the last recorded :class:`~overseer.gates.GateResult`, keyed by
conversation id under an injected ``state_dir``. This survives a fresh load
(the ``--resume`` / daemon-restart case). Conversations are isolated by file
path, and an unknown conversation loads a fresh default state rather than
raising.

Stdlib-only.
"""
from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path
from overseer.gates import GateResult
DEFAULT_PHASE = 'BRIEF'

@dataclass
class ProcedureState:
    """The durable pointer into the procedure machine for one conversation."""
    phase: str
    last_gate: GateResult | None = None

def _state_path(conversation_id: str, state_dir: Path) -> Path:
    """Resolve the on-disk json file isolating one conversation's state."""
    return Path(state_dir) / 'state' / 'procedures' / f'{conversation_id}.json'

def _gate_to_dict(gate: GateResult | None) -> dict | None:
    """Serialize a GateResult to a plain json-friendly dict (or None)."""
    if gate is None:
        return None
    return {'ok': bool(gate.ok), 'reason': gate.reason, 'fix_hint': gate.fix_hint}

def _gate_from_dict(data: dict | None) -> GateResult | None:
    """Reconstruct a GateResult from its serialized dict (or None)."""
    if data is None:
        return None
    return GateResult(ok=data.get('ok', False), reason=data.get('reason'), fix_hint=data.get('fix_hint'))

def load_state(conversation_id: str, *, state_dir: Path) -> ProcedureState:
    """Load persistent state for ``conversation_id`` from ``state_dir``.

    Returns a fresh default :class:`ProcedureState` if the conversation has no
    persisted state on disk.
    """
    path = _state_path(conversation_id, state_dir)
    if not path.exists():
        return ProcedureState(phase=DEFAULT_PHASE, last_gate=None)
    with path.open('r', encoding='utf-8') as fh:
        data = json.load(fh)
    return ProcedureState(phase=data.get('phase', DEFAULT_PHASE), last_gate=_gate_from_dict(data.get('last_gate')))

def save_state(conversation_id: str, state: ProcedureState, *, state_dir: Path) -> None:
    """Serialize ``state`` and write it to disk, overwriting any prior state."""
    path = _state_path(conversation_id, state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {'phase': state.phase, 'last_gate': _gate_to_dict(state.last_gate)}
    with path.open('w', encoding='utf-8') as fh:
        json.dump(payload, fh)