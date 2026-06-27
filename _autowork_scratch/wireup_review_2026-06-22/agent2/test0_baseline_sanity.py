"""Sanity: the faithful primitive does the brief's CORE case right.
Reached symbol observed True; dead symbol observed False; AST diff correct.
If THIS fails, my limitation findings would be strawmen. It must pass."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from faithful_primitive import observe_symbol_execution, new_top_level_callables


def reached_probe():
    return 42


def never_reached_probe():
    return 7


def dead_caller():
    # static reference (and call) in code that is never invoked
    return never_reached_probe()


def driver():
    # the "live entrypoint" that actually reaches reached_probe
    return reached_probe()


# A: reached symbol observed executed
with observe_symbol_execution(['reached_probe', 'never_reached_probe']) as obs:
    driver()
print("A reached_probe executed (want True):", obs.executed('reached_probe'))
print("B never_reached_probe executed (want False):", obs.executed('never_reached_probe'))

# C: static-ref-in-dead-code does NOT count (dead_caller never invoked)
with observe_symbol_execution(['never_reached_probe']) as obs2:
    driver()  # does not call dead_caller
print("C never_reached executed despite dead static ref (want False):", obs2.executed('never_reached_probe'))

# D: AST diff
parent = "def already():\n    return 1\n"
child = ("def already():\n    return 1\n"
         "def brand_new():\n    return 1\n"
         "async def brand_new_async():\n    return 2\n"
         "lam = lambda x: x\n")
got = new_top_level_callables(parent, child)
print("D new_top_level_callables (want ['brand_new','brand_new_async','lam']):", got)

# F: unparseable child fail-soft
print("F unparseable child (want []):", new_top_level_callables(parent, "def (:::"))

# F: tracer restored
before = sys.gettrace()
with observe_symbol_execution(['x']):
    pass
print("F tracer restored (want True):", sys.gettrace() is before)
