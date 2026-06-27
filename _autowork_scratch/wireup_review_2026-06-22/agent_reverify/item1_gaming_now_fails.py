"""ITEM 1 -- GAMING NOW FAILS (the headline) against the REVISED primitive.

Re-runs agent1's attacks (demo1 monkeypatched-wrapper, demo2 direct-call, demo5
loose-vs-strict) against the REVISED observe_symbol_execution (immediate-caller
provenance + executed_from_live_root), PLUS a positive control proving a genuine
LIVE_ROOT->orphan production edge passes.

A genuine LIVE_ROOT is modeled by writing a module whose ON-DISK PATH ends with a
real LIVE_ROOTS rel-path (harness/orchestrator.py), so the provenance matcher
recognizes its frames as living in a registered LIVE_ROOT file -- exactly the
real-world condition (orchestrator.py IS the file at that rel-path).
"""
import os
import sys
import importlib.util as ilu

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, "/home/xnihil0zer0/JanusMaskJR")

from revised_primitive import observe_symbol_execution
from harness.wire_up import LIVE_ROOTS   # ground-truth seed

# Build a synthetic LIVE_ROOT module on disk whose path ENDS WITH a real
# LIVE_ROOTS rel-path so executed_from_live_root() recognizes its frames.
LR_REL = "harness/orchestrator.py"
assert LR_REL in LIVE_ROOTS, "sanity: LR_REL must be a real LIVE_ROOT"
LR_DIR = os.path.join(HERE, "fake_live_root_tree", "harness")
os.makedirs(LR_DIR, exist_ok=True)
LR_FILE = os.path.join(LR_DIR, "orchestrator.py")
with open(LR_FILE, "w") as f:
    f.write(
        "def smoke_import(*a, **k):\n"
        "    return None\n"
        "\n"
        "def run_pipeline_iter(collab):\n"
        "    # a faithful stand-in for run_pipeline's one-iteration body:\n"
        "    # it calls a COLLABORATOR (smoke_import) the way run_pipeline does.\n"
        "    collab()\n"
        "    return 0\n"
        "\n"
        "def production_calls_orphan(orphan):\n"
        "    # a PRODUCTION call edge: this live-root function calls the target\n"
        "    # directly (the genuine-wiring positive control).\n"
        "    return orphan()\n"
    )
_spec = ilu.spec_from_file_location("fake_live_root_orch", LR_FILE)
live_mod = ilu.module_from_spec(_spec)
_spec.loader.exec_module(live_mod)

# The LIVE_ROOT seed the gate would pass (POSIX rel-paths). The matcher must
# resolve our absolute LR_FILE (which ends with harness/orchestrator.py) against
# this rel-path seed.
LR_SEED = list(LIVE_ROOTS)


def orphan_symbol():
    return "i ran but nobody real called me"


results = []


# ---------------------------------------------------------------------------
# 1a. demo1: oracle monkeypatches a COLLABORATOR to a wrapper that CALLS the
#     orphan. The live root drives the collaborator; the wrapper (a THIS-file
#     function) is the IMMEDIATE caller of the orphan.
# ---------------------------------------------------------------------------
def attack_1a():
    def smoke_import_wrapper(*a, **k):
        orphan_symbol()           # manufactured call; immediate caller = THIS test file
        return None
    with observe_symbol_execution(['orphan_symbol']) as obs:
        live_mod.run_pipeline_iter(smoke_import_wrapper)
    ex = obs.executed('orphan_symbol')
    efr = obs.executed_from_live_root('orphan_symbol', LR_SEED)
    rf = obs.reached_from('orphan_symbol')
    return ex, efr, rf


# ---------------------------------------------------------------------------
# 1b. demo2: oracle calls the orphan DIRECTLY in the test body.
# ---------------------------------------------------------------------------
def attack_1b():
    with observe_symbol_execution(['orphan_symbol']) as obs:
        orphan_symbol()
    return obs.executed('orphan_symbol'), obs.executed_from_live_root('orphan_symbol', LR_SEED), obs.reached_from('orphan_symbol')


# ---------------------------------------------------------------------------
# 1c. demo5: the loose "any live-root frame on the stack" variant -- the live
#     root is ON the stack (it called the wrapper) but the immediate caller is
#     the test wrapper. Strict immediate-caller rule must reject.
# ---------------------------------------------------------------------------
def attack_1c():
    def wrapper():
        orphan_symbol()           # immediate caller = THIS test file (wrapper)
    with observe_symbol_execution(['orphan_symbol']) as obs:
        live_mod.run_pipeline_iter(wrapper)   # live_root on stack, wrapper is immediate caller
    return obs.executed('orphan_symbol'), obs.executed_from_live_root('orphan_symbol', LR_SEED), obs.reached_from('orphan_symbol')


# ---------------------------------------------------------------------------
# 1d. POSITIVE CONTROL: a registered LIVE_ROOT calls the orphan through a
#     PRODUCTION edge (production_calls_orphan lives in the LIVE_ROOT file and
#     directly calls the target). Must be True, else the gate is over-strict.
# ---------------------------------------------------------------------------
def attack_1d():
    with observe_symbol_execution(['orphan_symbol']) as obs:
        live_mod.production_calls_orphan(orphan_symbol)
    return obs.executed('orphan_symbol'), obs.executed_from_live_root('orphan_symbol', LR_SEED), obs.reached_from('orphan_symbol')


print("=== ITEM 1: gaming now fails (revised immediate-caller provenance) ===")
print(f"LIVE_ROOTS seed = {LR_SEED}")
print(f"fake live-root file (path ends with {LR_REL}) = {LR_FILE}")
print()

ex, efr, rf = attack_1a()
ok_1a = (ex is True) and (efr is False)
print(f"[1a monkeypatch-wrapper-calls-orphan] executed={ex} executed_from_live_root={efr}")
print(f"    reached_from={rf}")
print(f"    EXPECT executed_from_live_root==False (attack defeated): {'PASS' if ok_1a else 'FAIL'}")
print()

ex, efr, rf = attack_1b()
ok_1b = (efr is False)
print(f"[1b direct-call-in-test-body]        executed={ex} executed_from_live_root={efr}")
print(f"    reached_from={rf}")
print(f"    EXPECT executed_from_live_root==False: {'PASS' if ok_1b else 'FAIL'}")
print()

ex, efr, rf = attack_1c()
ok_1c = (efr is False)
print(f"[1c loose-any-frame variant]         executed={ex} executed_from_live_root={efr}")
print(f"    reached_from={rf}")
print(f"    EXPECT executed_from_live_root==False under strict immediate-caller: {'PASS' if ok_1c else 'FAIL'}")
print()

ex, efr, rf = attack_1d()
ok_1d = (ex is True) and (efr is True)
print(f"[1d POSITIVE CONTROL prod-edge]      executed={ex} executed_from_live_root={efr}")
print(f"    reached_from={rf}")
print(f"    EXPECT executed_from_live_root==True (genuine wiring not over-rejected): {'PASS' if ok_1d else 'FAIL'}")
print()

allok = ok_1a and ok_1b and ok_1c and ok_1d
print(f"ITEM 1 OVERALL: {'PASS -- gaming defeated AND genuine wiring still passes' if allok else 'FAIL'}")
sys.exit(0 if allok else 1)
