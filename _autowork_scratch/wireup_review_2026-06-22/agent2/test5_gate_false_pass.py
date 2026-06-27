"""Does an AST-diff MISS become a Phase-2 gate FALSE PASS?
Phase 2: uncovered = [s for s in new_syms if s not in exempt and not entrypoints].
If new_top_level_callables MISSES a symbol, it is never in new_syms -> never
'uncovered' -> NO report row -> the symbol lands with NO contract required.

That is the EXACT failure the gate exists to kill (a new callable landing dead
without a declared reachability contract), just via a different door than the
'already-tracked file skipped' door this brief closes.

Simulate the Phase-2 uncovered computation EXACTLY (per brief Impl Note 2)."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from faithful_primitive import new_top_level_callables


def phase2_uncovered(parent_src, child_src, task):
    """EXACT replica of brief's Impl Note 2 uncovered computation."""
    new_syms = new_top_level_callables(parent_src, child_src)
    _c = task.get('constraints') if isinstance(task.get('constraints'), dict) else {}
    _contract = _c.get('integration_contract') if isinstance(_c.get('integration_contract'), dict) else {}
    _entrypoints = _contract.get('entrypoints') if isinstance(_contract.get('entrypoints'), list) else []
    _exempt_raw = task.get('wire_exempt') or _c.get('wire_exempt') or []
    _exempt = set(_exempt_raw) if isinstance(_exempt_raw, (list, tuple, set)) else set()
    uncovered = sorted(s for s in new_syms if s not in _exempt and not _entrypoints)
    return new_syms, uncovered


NO_CONTRACT_TASK = {}  # no integration_contract, no wire_exempt

print("Scenario: a new callable lands with NO contract and NO exempt.")
print("If the gate is armed, it SHOULD report it as uncovered.\n")

cases = {
    "plain top-level def (control, should be CAUGHT)": (
        "x=1\n", "x=1\ndef genuinely_dead_new():\n    return 1\n"),
    "try/except import-fallback def (real backport pattern)": (
        "x=1\n",
        "x=1\ntry:\n    from fast import impl as worker\nexcept ImportError:\n"
        "    def worker():\n        return 'slow path'\n"),
    "if-guarded def (platform/flag branch)": (
        "x=1\n",
        "x=1\nimport sys\nif sys.platform=='linux':\n    def linux_only_handler():\n        return 1\n"),
    "alias re-export of a NEW impl": (
        "x=1\n",
        "x=1\ndef _impl():\n    return 1\nhandler = _impl\n"),
}

for label, (parent, child) in cases.items():
    new_syms, uncovered = phase2_uncovered(parent, child, NO_CONTRACT_TASK)
    caught = bool(uncovered)
    print(f"[{label}]")
    print(f"   new_syms={new_syms}  uncovered={uncovered}")
    print(f"   gate {'REPORTS (caught)' if caught else 'SILENT -> FALSE PASS: dead symbol lands unflagged'}\n")
