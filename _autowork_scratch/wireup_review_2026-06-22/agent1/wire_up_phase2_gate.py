"""Faithful re-implementation of the PHASE 2 accept-gate branch exactly as
`brief_hooks_wire_up_runtime_reachability_gate.md` (TASK 2, Implementation
Notes 2) describes it. Verbatim semantics:

  _c        = task['constraints'] if dict else {}
  _contract = _c['integration_contract'] if dict else {}
  _entrypoints = _contract['entrypoints'] if list else []
  _exempt_raw = task['wire_exempt'] or _c['wire_exempt'] or []
  _exempt   = set(_exempt_raw) if list/tuple/set else set()

  new_syms  = new_top_level_callables(parent_src, child_src)
  uncovered = sorted(s for s in new_syms if s not in _exempt and not _entrypoints)
  if uncovered: write report row; else: no row.

A new callable is CONTRACT-COVERED iff it is in _exempt OR _entrypoints is
non-empty (brief: 'a declared contract covers this task's new callables').

This faithfully reflects the brief: the accept gate NEVER re-drives a LIVE_ROOT.
It checks ONLY that the task declared a non-empty entrypoints list (or exempt).
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from wire_up_phase1_primitive import new_top_level_callables


def run_phase2_symbol_branch(task, parent_src, child_src):
    """Returns the list of 'uncovered' symbols that WOULD produce an
    orphan_symbol_unwired report row (empty list => no row => gate accepts the
    addition as 'wired')."""
    _c = task.get('constraints') if isinstance(task.get('constraints'), dict) else {}
    _contract = _c.get('integration_contract') if isinstance(_c.get('integration_contract'), dict) else {}
    _entrypoints = _contract.get('entrypoints') if isinstance(_contract.get('entrypoints'), list) else []
    _exempt_raw = task.get('wire_exempt') or _c.get('wire_exempt') or []
    _exempt = set(_exempt_raw) if isinstance(_exempt_raw, (list, tuple, set)) else set()

    new_syms = new_top_level_callables(parent_src, child_src)
    uncovered = sorted(s for s in new_syms if s not in _exempt and not _entrypoints)
    return new_syms, uncovered
