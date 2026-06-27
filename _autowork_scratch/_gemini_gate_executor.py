"""Transition gate executor for the NobleGreed phase state machine.

This module wires a *fail-closed* gate table across the ordered phases of the
pipeline.  Advancing from one phase to the next is only permitted when the
structural evidence required by the transition is present; otherwise the
executor refuses to advance and routes the run to a typed terminal symbol.

Only the Python standard library is used.  All behaviour is deterministic --
no wall-clock, randomness, or identifier generation is performed here.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Callable, Dict, List, Optional, Tuple

# Canonical phase order of the pipeline.  Consecutive pairs in this list are the
# transitions that must be gated; every other (non-consecutive) transition is
# left ungated and simply advances.
PHASE_ORDER: List[str] = [
    "hunt",
    "source",
    "findings",
    "triage",
    "poc",
    "detonate",
    "novelty",
    "verify",
    "report",
    "approval",
    "submission",
]


class TypedTerminal:
    """Container of typed terminal routing symbols.

    Each constant is a stable string label used to route a halted run.  They
    are plain strings (not generated) so the routing remains deterministic and
    comparable across processes.
    """

    EMPTY_HUNT: str = "empty_hunt"
    NO_TEMPLATE: str = "no_template"
    REFUTED: str = "refuted"
    MISSING_EVIDENCE: str = "missing_evidence"
    SERVICE_NO_BIND: str = "service_no_bind"
    NO_SOURCE: str = "no_source"
    NO_FINDINGS: str = "no_findings"
    NO_TRIAGE: str = "no_triage"
    NO_VERIFY: str = "no_verify"
    NO_NOVELTY: str = "no_novelty"
    NO_REPORT: str = "no_report"
    NO_APPROVAL: str = "no_approval"
    NO_SUBMISSION: str = "no_submission"


_CWE_DIGITS = re.compile(r"(\d+)")


def no_template_terminal(cwe: Any) -> str:
    """Return the ``no_template:CWE-<n>`` terminal label for a CWE reference.

    Accepts integer CWE inputs, case-insensitive CWE strings (``"CWE-89"``,
    ``"cwe89"``, ``"Cwe-0089"``), and falls back to ``no_template:CWE-unknown``
    for unparseable formats.
    """

    number: Optional[int] = None
    if isinstance(cwe, bool):
        number = None
    elif isinstance(cwe, int):
        number = cwe
    elif isinstance(cwe, str):
        match = _CWE_DIGITS.search(cwe)
        if match is not None:
            number = int(match.group(1))

    if number is None or number < 0:
        return "{0}:CWE-unknown".format(TypedTerminal.NO_TEMPLATE)
    return "{0}:CWE-{1}".format(TypedTerminal.NO_TEMPLATE, number)


# A gate function consumes an evidence mapping and reports whether confirmation
# (advancing) is permitted via the ``may_confirm`` flag.
GateResult = Dict[str, Any]
GateFn = Callable[[Any], GateResult]


def _lookup(evidence: Any, name: str) -> Any:
    """Safely fetch ``name`` from an evidence mapping, else ``None``."""

    if isinstance(evidence, Mapping):
        return evidence.get(name)
    return None


def _structural_gate(name: str) -> GateFn:
    """Build a fail-closed structural gate keyed on the next phase artifact.

    The returned gate confirms the transition only when evidence for ``name``
    is present and truthy; otherwise it reports ``<name>:missing_evidence`` and
    refuses confirmation.
    """

    def _gate(evidence: Any) -> GateResult:
        if _lookup(evidence, name):
            return {"may_confirm": True, "reason": "{0}:confirmed".format(name)}
        return {"may_confirm": False, "reason": "{0}:missing_evidence".format(name)}

    _gate.__name__ = "gate_{0}".format(name)
    _gate.gate_name = name  # type: ignore[attr-defined]
    return _gate


def _gate_poc_detonate(evidence: Any) -> GateResult:
    """Pre-existing gate: a real PoC with source is required to detonate."""

    poc = _lookup(evidence, "poc")
    if not isinstance(poc, Mapping):
        return {"may_confirm": False, "reason": "detonate:missing_evidence"}
    if not poc.get("source"):
        return {"may_confirm": False, "reason": "detonate:missing_poc_source"}
    if poc.get("mock") or poc.get("kind") == "mock":
        return {"may_confirm": False, "reason": "detonate:mock_poc"}
    return {"may_confirm": True, "reason": "detonate:real_poc"}


def _gate_detonate_novelty(evidence: Any) -> GateResult:
    """Pre-existing gate: a genuine dynamic detonation is required for novelty."""

    detonation = _lookup(evidence, "detonation")
    if not isinstance(detonation, Mapping):
        return {"may_confirm": False, "reason": "novelty:missing_evidence"}

    callsites = detonation.get("callsites") or []
    if callsites and all(
        isinstance(site, Mapping) and site.get("constant") for site in callsites
    ):
        return {"may_confirm": False, "reason": "novelty:constant_only_callsites"}

    if detonation.get("kind") == "static_assertion" or detonation.get(
        "static_assertion"
    ):
        return {"may_confirm": False, "reason": "novelty:static_assertion_detonation"}

    if not detonation.get("dynamic"):
        return {"may_confirm": False, "reason": "novelty:missing_evidence"}

    return {"may_confirm": True, "reason": "novelty:detonated"}


# The 8 remaining consecutive transitions that need structural, fail-closed
# gates.  Each entry is (from_phase, to_phase); the gate keys on the next-phase
# artifact so a missing artifact routes to the matching NO_* terminal.
_STRUCTURAL_TRANSITIONS: List[Tuple[str, str]] = [
    ("hunt", "source"),
    ("source", "findings"),
    ("findings", "triage"),
    ("triage", "poc"),
    ("novelty", "verify"),
    ("verify", "report"),
    ("report", "approval"),
    ("approval", "submission"),
]


def _build_transition_gates() -> Dict[Tuple[str, str], GateFn]:
    table: Dict[Tuple[str, str], GateFn] = {}
    for from_phase, to_phase in _STRUCTURAL_TRANSITIONS:
        table[(from_phase, to_phase)] = _structural_gate(to_phase)
    # Preserve the pre-existing gates verbatim.
    table[("poc", "detonate")] = _gate_poc_detonate
    table[("detonate", "novelty")] = _gate_detonate_novelty
    return table


_TRANSITION_GATES: Dict[Tuple[str, str], GateFn] = _build_transition_gates()


def run_gates(
    from_phase: str,
    to_phase: str,
    evidence: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Evaluate the gate (if any) guarding ``from_phase -> to_phase``.

    Returns a result mapping with a stable shape:

    - ``from_phase`` / ``to_phase``: the requested transition.
    - ``gated``: whether a gate guards this transition.
    - ``advance``: whether the run may advance.
    - ``may_confirm``: alias of ``advance`` for gate-level callers.
    - ``reason``: a human/machine readable explanation.

    Ungated (non-consecutive / unknown) transitions always advance.  Gated
    transitions fail closed: a missing-evidence gate yields ``advance=False``.
    """

    gate = _TRANSITION_GATES.get((from_phase, to_phase))
    if gate is None:
        return {
            "from_phase": from_phase,
            "to_phase": to_phase,
            "gated": False,
            "advance": True,
            "may_confirm": True,
            "reason": "{0}->{1}:no_gate".format(from_phase, to_phase),
        }

    outcome = gate(evidence if evidence is not None else {})
    may_confirm = bool(outcome.get("may_confirm"))
    return {
        "from_phase": from_phase,
        "to_phase": to_phase,
        "gated": True,
        "advance": may_confirm,
        "may_confirm": may_confirm,
        "reason": outcome.get("reason"),
    }
