"""FAITHFUL model of the REVISED Phase-2 contract/coverage rule + the Phase-3
enforce action, transcribed DIRECTLY from the two briefs (Phase-2 Impl Note 2 /
the `uncovered` computation; Phase-3 Impl Note 2 / the gated reject arm).

This is the EXACT logic the wiring task would add inside _run_wire_up_gate's
already-tracked-file branch. It does NOT re-implement the AST diff or the git
plumbing; it imports the revised primitive's new_top_level_callables and accepts
parent/child source so we can drive it deterministically. The git-level
end-to-end driver (item4_phase3_enforce_real_gate / item2 self-cert) layers the
real _run_wire_up_gate on top where needed.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, "/home/xnihil0zer0/JanusMaskJR")

from revised_primitive import new_top_level_callables
from harness.wire_up import LIVE_ROOTS


def compute_uncovered(task, parent_src, child_src):
    """The REVISED per-symbol, LIVE_ROOT-validated coverage rule (Phase-2 Impl
    Note 2 / Phase-3 'consumed unchanged'). Returns (new_syms, uncovered,
    contract_valid)."""
    new_syms = new_top_level_callables(parent_src, child_src)

    _live = set(LIVE_ROOTS)
    _c = task.get('constraints') if isinstance(task.get('constraints'), dict) else {}
    _contract = _c.get('integration_contract') if isinstance(_c.get('integration_contract'), dict) else {}
    _entrypoints = _contract.get('entrypoints') if isinstance(_contract.get('entrypoints'), list) else []
    _csymbols = set(_contract.get('symbols')) if isinstance(_contract.get('symbols'), list) else set()
    _oracle = _contract.get('runtime_oracle') if isinstance(_contract.get('runtime_oracle'), str) else ''
    _contract_valid = bool(_entrypoints) and all(ep in _live for ep in _entrypoints) and bool(_oracle)
    _exempt_raw = task.get('wire_exempt') or _c.get('wire_exempt') or []
    _exempt = set(_exempt_raw) if isinstance(_exempt_raw, (list, tuple, set)) else set()

    uncovered = sorted(
        s for s in new_syms
        if s not in _exempt and not (_contract_valid and s in _csymbols)
    )
    return new_syms, uncovered, _contract_valid


def gate_action(task, parent_src, child_src, *, shadow_enabled, enforce_enabled):
    """Model the FULL knob matrix for the symbol-addition branch.
    Returns a dict describing what the branch would do."""
    if not shadow_enabled:
        # branch not entered at all (both-off / shadow-off strict no-op)
        return {'entered': False, 'row': None, 'rejected': False, 'uncovered': []}

    new_syms, uncovered, contract_valid = compute_uncovered(task, parent_src, child_src)
    if not uncovered:
        return {'entered': True, 'row': None, 'rejected': False, 'uncovered': []}

    if enforce_enabled:
        return {'entered': True, 'row': 'rejected', 'rejected': True, 'uncovered': uncovered,
                'event': 'orphan_symbol_unwired'}
    return {'entered': True, 'row': 'report', 'rejected': False, 'uncovered': uncovered,
            'event': 'orphan_symbol_unwired'}
