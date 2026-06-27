"""DEMO 4 — End-to-end: the full Phase1+Phase2 sequence certifies an ORPHAN as
'wired', and a minimal stack-aware fix would catch it.

Story for a single leaf that adds `orphan_symbol` to an already-tracked module:
  * Phase 2 accept gate: leaf declares constraints.integration_contract.entrypoints
    = ['harness/orchestrator.py'] -> NO orphan report (Demo 3 case C).
  * Phase 1 runtime oracle (the leaf's verification_command, the ONLY actual
    execution proof): GREEN because the oracle author drives the LIVE_ROOT with a
    monkeypatched collaborator that manufactures the call (Demo 1).
  => Both layers green. orphan_symbol has ZERO real callers. Certified 'wired'.

Then we show the MINIMAL FIX: an observer that records the CALLER chain and an
oracle contract that the watched symbol must appear on the stack BELOW a frame
whose code object belongs to a registered LIVE_ROOT module file -- and that the
oracle must NOT itself be the direct caller. Under that rule the manufactured
mock-wrapper call is rejected because its caller chain is the TEST module, not a
LIVE_ROOT module.
"""
import sys, os, inspect
sys.path.insert(0, os.path.dirname(__file__))
from wire_up_phase1_primitive import observe_symbol_execution
from wire_up_phase2_gate import run_phase2_symbol_branch

# ---- shared fixture: a LIVE_ROOT + an orphan, modeled in two 'modules' ----
LIVE_ROOT_FILE = os.path.join(os.path.dirname(__file__), "fake_live_root_module.py")
with open(LIVE_ROOT_FILE, "w") as f:
    f.write(
        "def smoke_import(*a, **k):\n    return None\n\n"
        "def live_root_entrypoint(orphan_caller):\n"
        "    # models run_pipeline; calls collaborator only\n"
        "    orphan_caller()\n"
        "    return 0\n"
    )
import importlib.util as _ilu
_spec = _ilu.spec_from_file_location("fake_live_root_module", LIVE_ROOT_FILE)
live_mod = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(live_mod)

def orphan_symbol():           # the brand-new orphan; defined in THIS (test) module
    return "orphan body ran"

PARENT = "def already(): return 0\n"
CHILD = "def already(): return 0\ndef orphan_symbol(): return 1\n"

print("=== DEMO 4: end-to-end certification of an ORPHAN as 'wired' ===\n")

# ---- LAYER 1: Phase 2 accept gate, leaf declares a contract ----
leaf_task = {"constraints": {"integration_contract": {
    "entrypoints": ["harness/orchestrator.py"],
    "observable_effect": "claimed but false",
}}}
_new, uncovered = run_phase2_symbol_branch(leaf_task, PARENT, CHILD)
print(f"[Phase 2 accept gate] new symbols={_new}; uncovered(report)={uncovered}")
print(f"   => {'NO orphan report -> ACCEPTED' if not uncovered else 'reported'}\n")

# ---- LAYER 2: Phase 1 runtime oracle, gamed by manufactured call ----
def smoke_import_wrapper(*a, **k):
    orphan_symbol()           # manufactured call inside the mocked collaborator
    return None
with observe_symbol_execution(['orphan_symbol']) as obs:
    live_mod.live_root_entrypoint(smoke_import_wrapper)   # 'drive the LIVE_ROOT'
runtime_green = obs.executed('orphan_symbol')
print(f"[Phase 1 runtime oracle] obs.executed('orphan_symbol')={runtime_green}")
print(f"   => {'GREEN (passes vcmd gate)' if runtime_green else 'red'}\n")

both = (not uncovered) and runtime_green
print(f"COMPOSITE: Phase2 accepted AND Phase1 oracle green = {both}")
print("  orphan_symbol has ZERO real production callers, yet the full sequence")
print("  certifies it WIRED. The proposed sequence CAN be gamed.\n")

# ============================================================================
# THE MINIMAL FIX (control): a stack/origin-aware observer.
# A watched symbol counts as reached ONLY if, at the 'call' event, a frame
# higher on the stack belongs to a registered LIVE_ROOT module file -- AND the
# immediate caller is not the oracle/test module itself.
# ============================================================================
print("=== DEMO 4b: minimal fix -- require a registered-LIVE_ROOT frame on the stack ===")

class observe_from_live_root(observe_symbol_execution):
    def __init__(self, qualnames, live_root_files):
        super().__init__(qualnames)
        self._live_files = {os.path.realpath(p) for p in live_root_files}
    def _trace(self, frame, event, arg):
        try:
            if event == 'call':
                name = frame.f_code.co_name
                qn = getattr(frame.f_code, 'co_qualname', name)
                if name in self._watched and qn == name:
                    # walk up the caller chain; require a LIVE_ROOT-file frame
                    on_live_stack = False
                    f = frame.f_back
                    while f is not None:
                        if os.path.realpath(f.f_code.co_filename) in self._live_files:
                            on_live_stack = True
                            break
                        f = f.f_back
                    if on_live_stack:
                        self._executed.add(name)
        except Exception:
            pass
        if self._prior is not None:
            try:
                return self._prior(frame, event, arg)
            except Exception:
                return self._trace
        return self._trace

# Same gamed drive, but now require the LIVE_ROOT *module file* on the stack.
# The orphan is called by smoke_import_wrapper, which is defined in THIS test
# module -- NOT in the live-root module file. (live_root_entrypoint did call the
# wrapper, so a live-root frame IS on the stack here; tighten further: require
# the IMMEDIATE caller to be the live-root file.)
class observe_strict(observe_from_live_root):
    def _trace(self, frame, event, arg):
        try:
            if event == 'call':
                name = frame.f_code.co_name
                qn = getattr(frame.f_code, 'co_qualname', name)
                if name in self._watched and qn == name:
                    caller = frame.f_back
                    # STRICT: the immediate caller's code must live in a LIVE_ROOT file
                    if caller is not None and os.path.realpath(caller.f_code.co_filename) in self._live_files:
                        self._executed.add(name)
        except Exception:
            pass
        if self._prior is not None:
            try:
                return self._prior(frame, event, arg)
            except Exception:
                return self._trace
        return self._trace

with observe_strict(['orphan_symbol'], [LIVE_ROOT_FILE]) as obs2:
    live_mod.live_root_entrypoint(smoke_import_wrapper)
print(f"   strict observer, gamed drive (caller = test-module wrapper):")
print(f"   obs.executed('orphan_symbol') = {obs2.executed('orphan_symbol')}  (False = gaming rejected)")

# Positive control: a REAL wiring -- the live-root module itself calls the orphan.
with open(LIVE_ROOT_FILE, "a") as f:
    f.write("\nimport demo4_endtoend_and_fix as _t\n"
            "def really_wired_root():\n    return _t.orphan_symbol()\n")
_spec2 = _ilu.spec_from_file_location("fake_live_root_module2", LIVE_ROOT_FILE)
live_mod2 = _ilu.module_from_spec(_spec2)
_spec2.loader.exec_module(live_mod2)
with observe_strict(['orphan_symbol'], [LIVE_ROOT_FILE]) as obs3:
    live_mod2.really_wired_root()
print(f"   strict observer, REAL wiring (caller = live-root module file):")
print(f"   obs.executed('orphan_symbol') = {obs3.executed('orphan_symbol')}  (True = real wiring accepted)")
print()
print("VERDICT: a caller-origin check (immediate caller's code object must reside")
print("         in a registered LIVE_ROOT module file, and the oracle is forbidden")
print("         from calling/mock-wrapping the target itself) DISTINGUISHES real")
print("         wiring from a manufactured test call. The proposed briefs impose")
print("         no such check -- so the gap is real AND closable.")
