"""Deterministic phase-dispatch shell for the self-chaining hunt cron orchestrator.

Distilled from the legacy ``orchestrator/phase_runner.py``. The durable capability
is threefold:

1. selecting a markdown prompt template by phase name,
2. computing the next phase deterministically from the state-machine graph, and
3. composing a ``## Current State`` trigger prompt from an injected state dict.

This module is PURE and stdlib-only: no file reads, no network access, no clock,
and no randomness. State is passed in (an injected seam) rather than loaded from
disk, which keeps the whole module deterministic and trivially testable.
"""
from __future__ import annotations
from typing import Dict, Mapping, Optional
from ngv2.state_machine import ALLOWED_TRANSITIONS
DEFAULT_PHASE: str = 'hunt'
PHASE_PROMPTS: Dict[str, str] = {'hunt': '## Phase: hunt\nSurvey the target surface and enumerate candidate weaknesses. Record every lead so the triage phase has concrete material to work from.', 'triage': '## Phase: triage\nReview the hunt leads, discard noise, and rank the surviving candidates by plausibility and impact. Promote the strongest lead toward a proof of concept.', 'poc': '## Phase: poc\nBuild a minimal, reproducible proof of concept for the triaged candidate. Capture the exact steps so the detonate phase can execute deterministically.', 'detonate': '## Phase: detonate\nExecute the proof of concept against the target in a controlled manner and collect the resulting evidence for the report phase.', 'report': '## Phase: report\nSummarize the confirmed finding, its impact, and the reproduction steps into a final report. This closes out the current cycle.'}
WATCHDOG_PROMPT: str = '## Watchdog\nInspect the orchestrator state. If `last_phase_end` is stale or unset while a non-terminal phase is still pending, the previous tick did not chain forward. Re-issue the trigger prompt and call CronCreate to schedule the next tick so the hunt keeps advancing without manual intervention.'

def get_phase_prompt(phase: Optional[str]=None) -> str:
    """Return the prompt template for ``phase``.

    Unknown, terminal, or ``None`` phases fall back to the default phase prompt so
    the caller always receives a usable, non-empty template.
    """
    if phase is None or phase not in PHASE_PROMPTS:
        return PHASE_PROMPTS[DEFAULT_PHASE]
    return PHASE_PROMPTS[phase]

def get_next_phase(current_phase: Optional[str]) -> str:
    """Compute the successor of ``current_phase`` from the transition graph.

    The single non-``done`` successor is chosen; terminal or unknown phases yield
    ``'done'``. This mirrors the ``ngv2.state_machine`` graph exactly.
    """
    transitions = ALLOWED_TRANSITIONS.get(current_phase, ())
    return next((p for p in transitions if p != 'done'), 'done')

def build_trigger_prompt(state: Mapping[str, object], phase: Optional[str]=None) -> str:
    """Compose a ``## Current State`` trigger prompt without mutating ``state``.

    The resolved phase is, in order of precedence:

    * the explicit ``phase`` argument, when given;
    * the successor of ``state['current_phase']`` when ``state['last_phase_end']``
      is truthy (the previous phase has ended, so advance);
    * otherwise ``state['current_phase']`` (resume the in-flight phase).

    The phase-specific prompt is appended after a ``---`` separator.
    """
    if phase is None:
        current = state.get('current_phase')
        if state.get('last_phase_end'):
            resolved = get_next_phase(current)
        else:
            resolved = current
    else:
        resolved = phase
    header = '## Current State\n'
    header += f'Phase: {resolved}\n'
    header += f'Phase count: {state.get('phase_count')}\n'
    header += f'Cycle count: {state.get('cycle_count')}\n'
    return header + '\n---\n\n' + get_phase_prompt(resolved)