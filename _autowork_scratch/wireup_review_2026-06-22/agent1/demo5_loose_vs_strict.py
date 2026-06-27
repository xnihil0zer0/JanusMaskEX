"""DEMO 5 — precision check on the fix: a LOOSE 'any live-root frame anywhere on
the stack' rule is NOT sufficient, because the gamed drive DOES put a live-root
frame on the stack (live_root_entrypoint called the mock wrapper). Only the
STRICT 'immediate caller's code object is in a live-root file' rule (combined with
forbidding the oracle from wrapping/calling the target) rejects the manufactured
call. This makes the fix recommendation precise.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from wire_up_phase1_primitive import observe_symbol_execution

LIVE_ROOT_FILE = os.path.join(os.path.dirname(__file__), "fake_live_root_module.py")
import importlib.util as _ilu
# rewrite clean live-root module
with open(LIVE_ROOT_FILE, "w") as f:
    f.write("def live_root_entrypoint(collab):\n    collab()\n    return 0\n")
_spec = _ilu.spec_from_file_location("flr5", LIVE_ROOT_FILE)
live_mod = _ilu.module_from_spec(_spec); _spec.loader.exec_module(live_mod)

def orphan_symbol():
    return 1

def make_observer(mode):
    live_files = {os.path.realpath(LIVE_ROOT_FILE)}
    class _Obs(observe_symbol_execution):
        def _trace(self, frame, event, arg):
            try:
                if event == 'call':
                    nm = frame.f_code.co_name
                    qn = getattr(frame.f_code, 'co_qualname', nm)
                    if nm in self._watched and qn == nm:
                        if mode == 'loose':
                            f = frame.f_back; ok = False
                            while f is not None:
                                if os.path.realpath(f.f_code.co_filename) in live_files:
                                    ok = True; break
                                f = f.f_back
                            if ok: self._executed.add(nm)
                        elif mode == 'strict':
                            c = frame.f_back
                            if c is not None and os.path.realpath(c.f_code.co_filename) in live_files:
                                self._executed.add(nm)
            except Exception:
                pass
            if self._prior is not None:
                try: return self._prior(frame, event, arg)
                except Exception: return self._trace
            return self._trace
    return _Obs

# gamed drive: test-module wrapper calls the orphan; live_root_entrypoint is on
# the stack but is NOT the immediate caller.
def wrapper():
    orphan_symbol()

for mode in ('loose', 'strict'):
    Obs = make_observer(mode)
    with Obs(['orphan_symbol']) as obs:
        live_mod.live_root_entrypoint(wrapper)   # gamed: orphan called by test wrapper
    print(f"[{mode:6}] gamed drive (immediate caller = test wrapper, live_root higher up): "
          f"executed={obs.executed('orphan_symbol')}")

print()
print("CONCLUSION: 'loose' (any live-root frame on the stack) is GAMEABLE -- it")
print("passes the manufactured call because live_root_entrypoint is above. The fix")
print("MUST be 'strict': the watched symbol's IMMEDIATE caller code object resides")
print("in a registered LIVE_ROOT module file, and the oracle is forbidden from")
print("calling or mock-wrapping the target. (Mocking a collaborator is fine; mocking")
print("it to a wrapper that calls the TARGET is the exact move that must be banned.)")
