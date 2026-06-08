"""Agent-boundary PreToolUse hard-block hook for the overseer.

This module closes the gap where the jailed agent could bypass the structured
action seam (``dispatch_action`` / ``can_switch``) by issuing a *raw* tool call
-- e.g. ``Write`` a brief before the ORACLE + COMMIT phases have passed, or a
``git commit`` proxy before the oracle has gone RED.

The decision logic is **pure** and **stdlib-only**: it maps the triple
``(tool_name, tool_input, phase)`` -- where ``phase`` is the active
``ProcedureState.phase`` exported by ``procedure_substrate`` -- onto a
deterministic allow/deny verdict.  The hook never executes the tool, never
shells out, never spawns an agent, and performs no network / SSE / subprocess
I/O.  It only computes a verdict and returns it.

Two public entrypoints:

``evaluate(tool_name, tool_input, phase) -> (allow: bool, reason: str)``
    The pure phase/tool deny rule.

``decide(event: dict) -> dict``
    The PreToolUse hook entrypoint: maps a raw tool-call event dict to a
    machine-readable allow/deny decision (Claude Code PreToolUse hook shape),
    carrying a structured ``reason`` and ``fix_hint`` (the ``GateResult`` shape)
    on a deny.

The phase/gate ordering mirrors the reducer's ordering in
``procedure_substrate`` so the boundary block tracks the same progression the
gates enforce.  Anything not provably consistent with the active phase fails
*closed*.
"""
import json
import re
_PHASE_ORDER = ('SCOPE', 'ORACLE', 'RED', 'COMMIT', 'BRIEF', 'PLAN', 'BUILD', 'SUITE', 'GREEN', 'POSTURE', 'REVIEW')
_GATE_PHASE = {'oracle_is_red': 'RED', 'oracles_committed_at_head': 'COMMIT', 'brief_lint': 'BRIEF', 'plan_preflight': 'PLAN', 'suite_green_zero_reg': 'SUITE', 'posture_locked': 'POSTURE'}
_TERMINAL_PHASES = frozenset({'', 'NONE', 'COMPLETE', 'DONE', 'IDLE', 'CLOSED'})
_READ_ONLY_TOOLS = frozenset({'READ', 'GLOB', 'GREP', 'LS', 'NOTEBOOKREAD', 'TODOREAD', 'WEBFETCH', 'WEBSEARCH'})
_BRIEF_HOOKS_RE = re.compile('(?:^|[\\\\/])brief_hooks_', re.IGNORECASE)

def _phase_of(state):
    """Normalise an active phase out of a string or a ProcedureState-like object.

    Malformed / empty / missing state is treated as the most restrictive active
    phase (pre-BRIEF, oracle not RED) so the hook fails *closed* -- except for
    the explicit terminal sentinels, which mean "no procedure active".
    """
    if state is None:
        return None
    if not isinstance(state, (str, bytes)):
        phase = getattr(state, 'phase', None)
        return _phase_of(phase)
    raw = state.decode() if isinstance(state, bytes) else state
    norm = raw.strip().upper()
    if not norm or norm in _TERMINAL_PHASES:
        return None
    return norm

def _phase_index(phase):
    """Ordinal of an *active* phase; unknown active phases are most restrictive."""
    try:
        return _PHASE_ORDER.index(phase)
    except ValueError:
        return 0

def _before(phase, marker):
    """True iff the active ``phase`` is strictly before phase ``marker``."""
    return _phase_index(phase) < _PHASE_ORDER.index(marker)

def _oracle_is_red(phase):
    """True iff the oracle has gone RED for this active phase (gate satisfied)."""
    if phase == 'RED':
        return True
    return _phase_index(phase) >= _PHASE_ORDER.index(_GATE_PHASE['oracle_is_red'])

def _extract_path(tool_input):
    if not isinstance(tool_input, dict):
        return None
    for key in ('file_path', 'path', 'filename', 'notebook_path', 'target', 'file'):
        val = tool_input.get(key)
        if isinstance(val, str) and val:
            return val
    return None

def _is_brief_hooks_path(path):
    return bool(path) and bool(_BRIEF_HOOKS_RE.search(path))

def _is_git_commit_proxy(tool_name, tool_input):
    """Recognise a git-commit proxy tool call (by tool name or command string)."""
    name = (tool_name or '').strip().lower().replace('-', '_').replace(' ', '_')
    if 'commit' in name and ('git' in name or name in {'commit', 'commit_proxy'}):
        return True
    if isinstance(tool_input, dict):
        for key in ('command', 'cmd', 'args', 'argv', 'proxy', 'action'):
            val = tool_input.get(key)
            if isinstance(val, (list, tuple)):
                val = ' '.join((str(x) for x in val))
            if isinstance(val, str) and re.search('\\bgit\\b.*\\bcommit\\b', val, re.IGNORECASE):
                return True
    return False

def _verdict(tool_name, tool_input, phase):
    """Pure decision core: returns ``(allow, reason, fix_hint)``.

    ``fix_hint`` is empty on allow and a remediation string on deny so callers
    can surface a ``GateResult``-shaped block.
    """
    tool_input = tool_input if isinstance(tool_input, dict) else {}
    active = _phase_of(phase)
    if active is None:
        return (True, 'no active procedure phase; agent-boundary hook is inert', '')
    name_upper = (tool_name or '').strip().upper()
    if name_upper in _READ_ONLY_TOOLS:
        return (True, 'read-only tool is consistent with any active phase', '')
    if name_upper == 'WRITE':
        path = _extract_path(tool_input)
        if path is None:
            if _before(active, 'BRIEF'):
                return (False, 'Write with no inspectable target path is not provably consistent with the active phase {!r}; the brief seam is not yet open (before BRIEF) -- failing closed.'.format(active), 'Route the write through dispatch_action once the procedure reaches BRIEF, or supply an explicit file_path.')
        elif _is_brief_hooks_path(path) and _before(active, 'BRIEF'):
            return (False, 'Write to brief-hooks path {!r} is blocked before the BRIEF phase (active phase: {!r}); author the oracle and commit it at head first.'.format(path, active), 'Advance the procedure through the ORACLE and COMMIT phases (oracle_is_red, oracles_committed_at_head) before writing the brief; do not bypass dispatch_action with a raw Write.')
    if _is_git_commit_proxy(tool_name, tool_input):
        if not _oracle_is_red(active):
            return (False, 'git commit proxy is blocked before the oracle phase is RED (active phase: {!r}; gate oracle_is_red not yet satisfied).'.format(active), 'Author a failing (RED) oracle so oracle_is_red holds before committing; commits at head are gated on a red oracle.')
    return (True, 'tool {!r} is consistent with active phase {!r}'.format(tool_name, active), '')

def evaluate(tool_name, tool_input, phase=None):
    """Pure allow/deny rule for a raw tool call against the active phase.

    Parameters
    ----------
    tool_name:
        The raw tool name (e.g. ``"Write"``, ``"Read"``).
    tool_input:
        The raw tool input mapping (e.g. ``{"file_path": "brief_hooks_x.md"}``).
    phase:
        The active ``ProcedureState.phase`` (a string), a ProcedureState-like
        object exposing ``.phase``, or ``None`` / a terminal sentinel when no
        procedure is active.

    Returns
    -------
    (allow, reason):
        ``allow`` is ``True`` when the call is consistent with the active phase
        (or no procedure is active), ``False`` when it is blocked.  ``reason`` is
        a human-readable explanation.  Defaults fail *closed* for calls not
        provably consistent with the active phase.
    """
    allow, reason, _hint = _verdict(tool_name, tool_input, phase)
    return (allow, reason)

def decide(event):
    """Map a PreToolUse event dict to an allow/deny decision dict.

    The returned decision follows the Claude Code PreToolUse hook shape and is
    machine-readably a DENY (it serialises to contain ``deny``/``block``) when
    the call is blocked, carrying a structured ``reason`` and ``fix_hint``
    (the ``GateResult`` shape).  An allowed call serialises with neither
    ``deny`` nor ``block``.
    """
    event = event if isinstance(event, dict) else {}
    tool_name = event.get('tool_name') or event.get('tool') or ''
    tool_input = event.get('tool_input') or event.get('tool_args') or event.get('input') or {}
    phase = event.get('phase')
    if phase is None:
        phase = event.get('state') or event.get('procedure_state')
    allow, reason, fix_hint = _verdict(tool_name, tool_input, phase)
    if allow:
        return {'decision': 'allow', 'reason': reason, 'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'allow', 'permissionDecisionReason': reason}}
    return {'decision': 'block', 'reason': reason, 'fix_hint': fix_hint, 'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny', 'permissionDecisionReason': reason}}
SETTINGS_FRAGMENT = {'hooks': {'PreToolUse': [{'matcher': '*', 'hooks': [{'type': 'command', 'command': 'python -m overseer.procedure_hook'}]}]}}

def main():
    """CLI shim: read a PreToolUse event JSON on stdin, emit the decision JSON."""
    import sys
    try:
        event = json.load(sys.stdin)
    except (ValueError, OSError):
        event = {}
    decision = decide(event if isinstance(event, dict) else {})
    json.dump(decision, sys.stdout)
    sys.stdout.write('\n')
    if decision.get('decision') == 'block':
        return 2
    return 0
if __name__ == '__main__':
    raise SystemExit(main())