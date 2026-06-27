"""DEMO 2 — two further facts about the Phase 1 primitive:

(2a) THE PRIMITIVE IS SOUND in isolation: a dead symbol that is genuinely not
     called is observed NOT-executed (so the brief's own oracle assertions B/C
     pass). The primitive is honest about EXECUTION.

(2b) BUT observe_symbol_execution has NO notion of a 'live-root call stack'.
     It marks a name reached on ANY 'call' frame event for that co_name,
     regardless of WHO called it. So the most trivial gaming oracle -- just
     `orphan_symbol()` typed directly in the test body, with NO entrypoint
     driven at all -- also reports REACHED. There is no requirement in the
     primitive that the symbol appear ON the stack BELOW a registered LIVE_ROOT
     frame.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from wire_up_phase1_primitive import observe_symbol_execution


def orphan_symbol():
    return 1


def never_called_symbol():
    return 2


def dead_caller():
    # a static reference / call site that is itself never invoked
    return never_called_symbol()


print("=== DEMO 2a: primitive is SOUND for genuinely-dead symbols ===")
with observe_symbol_execution(['orphan_symbol', 'never_called_symbol']) as obs:
    pass  # drive NOTHING
print(f"nothing driven -> executed(orphan_symbol)={obs.executed('orphan_symbol')}, "
      f"executed(never_called_symbol)={obs.executed('never_called_symbol')}")
print("  (both False -- the primitive genuinely observes execution, not reference)")

print()
print("=== DEMO 2b: but a DIRECT call in the test body is enough -- no stack check ===")
with observe_symbol_execution(['orphan_symbol']) as obs:
    orphan_symbol()          # the gaming oracle just calls it. No LIVE_ROOT involved.
print(f"oracle directly called orphan_symbol() -> executed(orphan_symbol)={obs.executed('orphan_symbol')}")

print()
print("=== DEMO 2c: dead_caller's static ref does NOT count (brief assertion C holds) ===")
with observe_symbol_execution(['never_called_symbol']) as obs:
    # dead_caller contains a call to never_called_symbol but is itself never invoked
    _ = dead_caller  # reference the name but do not call it
print(f"dead_caller referenced-not-invoked -> executed(never_called_symbol)={obs.executed('never_called_symbol')}")

print()
print("VERDICT: The primitive correctly observes EXECUTION (2a, 2c hold), which the")
print("         brief touts as superior to static name-reference. BUT 'executed' is")
print("         attributed to ANY caller frame (2b): the primitive has no concept of")
print("         'reached FROM a registered LIVE_ROOT'. The oracle author chooses the")
print("         caller, so the author can always make a dead symbol 'execute'.")
