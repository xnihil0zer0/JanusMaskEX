"""ITEM 5 -- NO CONTRADICTION / NO OVER-STRICTNESS.

The revised Phase-1 brief BANS: "monkeypatch a COLLABORATOR to a wrapper that
calls the TARGET" (the gaming move -- immediate caller is the test wrapper).
It ALLOWS: "if the WATCHED symbol is itself a normally-mocked collaborator,
leave it UNMOCKED / wrap-and-delegate so the real body runs" (the immediate
caller is the LIVE_ROOT that calls the collaborator directly).

This script proves the immediate-caller rule DISTINGUISHES the two:

  LEGIT case  : the watched symbol IS a collaborator that the live root calls
                DIRECTLY on the production edge. The oracle leaves it unmocked
                (or wrap-and-delegates so the real body runs). The IMMEDIATE
                caller of the watched symbol is the LIVE_ROOT frame -> True.

  BANNED case : the watched symbol is the TARGET; a DIFFERENT collaborator is
                monkeypatched to a wrapper that CALLS the target. The IMMEDIATE
                caller of the watched symbol is the test wrapper frame -> False.

If the LEGIT case passed and the BANNED case failed, the rule is sound and NOT
so strict it blocks legitimate oracles.
"""
import os
import sys
import importlib.util as ilu

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, "/home/xnihil0zer0/JanusMaskJR")

from revised_primitive import observe_symbol_execution
from harness.wire_up import LIVE_ROOTS

# Build a live-root module on disk whose path ends with a real LIVE_ROOT rel.
LR_DIR = os.path.join(HERE, "fake_live_root_tree", "harness")
os.makedirs(LR_DIR, exist_ok=True)
LR_FILE = os.path.join(LR_DIR, "orchestrator.py")
with open(LR_FILE, "w") as f:
    f.write(
        "def real_collaborator():\n"
        "    # the WATCHED symbol -- a real top-level callable that the live root\n"
        "    # invokes directly on the production path. (Models e.g. smoke_import.)\n"
        "    return 'real work'\n"
        "\n"
        "def other_collaborator():\n"
        "    return None\n"
        "\n"
        "def live_root_iter(collab_real, collab_other):\n"
        "    # production body: it calls BOTH collaborators DIRECTLY.\n"
        "    collab_other()\n"
        "    return collab_real()\n"
    )
_spec = ilu.spec_from_file_location("flr_item5", LR_FILE)
lr = ilu.module_from_spec(_spec)
_spec.loader.exec_module(lr)

LR_SEED = list(LIVE_ROOTS)


def target_symbol():
    """The TARGET the BANNED case smuggles in via a wrapper. Nothing in the
    live root really calls it."""
    return 1


print("=== ITEM 5: rule distinguishes LEGIT collaborator from BANNED wrapper-smuggle ===\n")
allok = True

# --- LEGIT: watched symbol IS real_collaborator, left UNMOCKED; live root calls
#     it directly. We pass lr.real_collaborator (the real body) as collab_real,
#     so its immediate caller is live_root_iter (the LIVE_ROOT frame).
with observe_symbol_execution(['real_collaborator']) as obs:
    lr.live_root_iter(lr.real_collaborator, lr.other_collaborator)
legit_ex = obs.executed('real_collaborator')
legit_efr = obs.executed_from_live_root('real_collaborator', LR_SEED)
legit_rf = obs.reached_from('real_collaborator')
ok_legit = (legit_ex is True) and (legit_efr is True)
allok = allok and ok_legit
print(f"[{'PASS' if ok_legit else 'FAIL'}] LEGIT (watched collaborator left unmocked, called directly by live root)")
print(f"        executed={legit_ex} executed_from_live_root={legit_efr}")
print(f"        reached_from={legit_rf}")
print(f"        EXPECT executed_from_live_root==True (legitimate oracle NOT blocked)")
print()

# --- LEGIT-2: wrap-and-delegate -- the oracle wraps the collaborator in a
#     delegating shim BUT the brief's allowance is about leaving the REAL BODY
#     to run. Here we test the HONEST wrap-and-delegate where the live root calls
#     the WRAPPER which immediately delegates to the real body. The immediate
#     caller of real_collaborator is the wrapper (test frame), so strict
#     provenance is False for the watched name 'real_collaborator'. The honest
#     way to keep the proof is to leave it UNMOCKED (LEGIT above). This case
#     documents that even wrap-and-delegate must watch the symbol the LIVE_ROOT
#     calls DIRECTLY; we assert the unmocked form is the one that proves wiring.
def delegating_wrapper():
    return lr.real_collaborator()  # delegates to real body
with observe_symbol_execution(['real_collaborator']) as obs2:
    lr.live_root_iter(delegating_wrapper, lr.other_collaborator)
wrap_efr = obs2.executed_from_live_root('real_collaborator', LR_SEED)
print(f"[INFO] wrap-and-delegate (live root calls wrapper, wrapper calls real body):")
print(f"        executed_from_live_root('real_collaborator')={wrap_efr} reached_from={obs2.reached_from('real_collaborator')}")
print(f"        (documented: to PROVE wiring, watch the symbol the LIVE_ROOT calls DIRECTLY -- leave it unmocked, LEGIT above)")
print()

# --- BANNED: watched symbol is target_symbol; other_collaborator is monkeypatched
#     to a wrapper that CALLS target_symbol. The live root is on the stack but the
#     immediate caller of target_symbol is the test wrapper.
def other_collab_wrapper():
    target_symbol()      # the BANNED manufactured call
    return None
with observe_symbol_execution(['target_symbol']) as obs3:
    lr.live_root_iter(lr.real_collaborator, other_collab_wrapper)
banned_ex = obs3.executed('target_symbol')
banned_efr = obs3.executed_from_live_root('target_symbol', LR_SEED)
banned_rf = obs3.reached_from('target_symbol')
ok_banned = (banned_ex is True) and (banned_efr is False)
allok = allok and ok_banned
print(f"[{'PASS' if ok_banned else 'FAIL'}] BANNED (collaborator monkeypatched to a wrapper that CALLS the target)")
print(f"        executed={banned_ex} executed_from_live_root={banned_efr}")
print(f"        reached_from={banned_rf}")
print(f"        EXPECT executed_from_live_root==False (gaming move rejected)")
print()

print(f"ITEM 5 OVERALL: {'PASS -- rule distinguishes legit collaborator (True) from banned smuggle (False); not over-strict' if allok else 'FAIL'}")
sys.exit(0 if allok else 1)
