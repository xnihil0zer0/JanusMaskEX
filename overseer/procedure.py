"""overseer/procedure.py — per-mode phase reducer.

A *procedure* is the ordered recipe a mode walks through, one phase at a time.
Each :class:`Phase` binds a gate NAME (a string resolved elsewhere against
``overseer.gates``) plus a single human-readable next-action string.

:data:`PROCEDURE_REGISTRY` maps the four procedure-bearing modes
(``brief-author``, ``oracle-author``, ``dispatch``, ``push``) to their ordered
phase lists.

:func:`advance` is the PURE reducer over a phase + a :class:`GateResult`:

* a failed gate yields ``Blocked(reason, fix_hint)``;
* a passing gate yields the NEXT phase's name (a ``str``);
* a passing gate on the LAST phase yields the :data:`Complete` singleton.

No I/O, no spawning — pure data plus logic. Only stdlib and ``overseer.gates``
are imported.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Union
from overseer.gates import GateResult
__all__ = ['Phase', 'Procedure', 'PROCEDURE_REGISTRY', 'advance', 'Blocked', 'Complete', 'Decision']

@dataclass(frozen=True)
class Phase:
    """One step of a procedure.

    ``name`` is the phase label (e.g. ``'SCOPE'``); ``gate`` is the NAME of the
    gate that must pass before the phase can be left; ``next_action`` is a short
    human-readable description of what to do while in this phase.
    """
    name: str
    gate: str
    next_action: str

@dataclass(frozen=True)
class Procedure:
    """An ordered recipe for a single mode."""
    mode: str
    phases: List[Phase]

@dataclass(frozen=True)
class Blocked:
    """Terminal-for-now decision: the current phase's gate failed."""
    reason: str
    fix_hint: str

class _Complete:
    """Type of the :data:`Complete` sentinel (a singleton)."""
    _instance: '_Complete | None' = None

    def __new__(cls) -> '_Complete':
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return 'Complete'

    def __bool__(self) -> bool:
        return True
Complete = _Complete()
Decision = Union[str, Blocked, _Complete]
PROCEDURE_REGISTRY: Dict[str, Procedure] = {'brief-author': Procedure(mode='brief-author', phases=[Phase('SCOPE', 'scope_locked', 'Pin the task scope and constraints.'), Phase('ORACLE', 'oracle_present', 'Draft the oracle tests for the task.'), Phase('COMMIT', 'oracle_committed', 'Commit the oracle so it is authoritative.'), Phase('BRIEF', 'brief_written', 'Write the implementation brief.'), Phase('PLAN', 'plan_ready', 'Produce the executable plan.')]), 'oracle-author': Procedure(mode='oracle-author', phases=[Phase('SCOPE', 'scope_locked', 'Pin the contract under test.'), Phase('ORACLE', 'oracle_drafted', 'Draft the oracle assertions.'), Phase('COMMIT', 'oracle_committed', 'Commit the oracle as the source of truth.'), Phase('REVIEW', 'oracle_reviewed', 'Review the committed oracle for gaps.')]), 'dispatch': Procedure(mode='dispatch', phases=[Phase('PREFLIGHT', 'preflight_clean', 'Confirm the workspace is preflight-clean.'), Phase('STAGE', 'staged', 'Stage the target files for the worker.'), Phase('BUILD', 'built', 'Synthesize the implementation.'), Phase('VERIFY', 'verified', 'Verify the build against the oracle.'), Phase('RESTORE', 'restored', 'Restore the workspace to a clean state.')]), 'push': Procedure(mode='push', phases=[Phase('SWEEP', 'swept', 'Sweep for uncommitted or stray changes.'), Phase('ZERO_REG', 'registry_zeroed', 'Zero out the in-flight task registry.'), Phase('POSTURE', 'posture_ok', 'Check the security/posture preconditions.'), Phase('PUSH', 'pushed', 'Push the result to the upstream.')])}

def advance(procedure: Procedure, phase: str, gate_result: GateResult) -> Decision:
    """Pure reducer: decide the next step for ``phase`` given ``gate_result``.

    * If the gate failed, return ``Blocked(reason, fix_hint)`` carrying the
      gate's diagnostics.
    * If the gate passed and ``phase`` is not the last, return the NEXT phase's
      name (a ``str``).
    * If the gate passed and ``phase`` is the last phase, return the
      :data:`Complete` singleton.

    Raises ``ValueError`` if ``phase`` is not part of ``procedure``.
    """
    if not gate_result.ok:
        return Blocked(reason=gate_result.reason, fix_hint=gate_result.fix_hint)
    names = [p.name for p in procedure.phases]
    try:
        idx = names.index(phase)
    except ValueError:
        raise ValueError(f'phase {phase!r} is not part of procedure {procedure.mode!r}')
    if idx == len(names) - 1:
        return Complete
    return names[idx + 1]