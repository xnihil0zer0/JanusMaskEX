"""LIMITATION 6 — co_name / co_qualname collision FALSE PASS.
The watcher matches frame.f_code.co_name and accepts when co_qualname == name.
But the brief says 'OR fall back to matching co_name when qualname is
unavailable'. On <3.11 (or if co_qualname is absent) it would match ANY frame
with that bare name -- including a method or nested def of the same name on a
DIFFERENT, dead class -> FALSE PASS (reports the dead top-level symbol as
executed because a same-named method ran).

On 3.11+ co_qualname disambiguates, so test BOTH the real path (should be sound)
AND simulate the fallback path the brief mandates (should be UNSOUND)."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from faithful_primitive import observe_symbol_execution

print("Python:", sys.version.split()[0], "co_qualname present:",
      hasattr((lambda: 0).__code__, 'co_qualname'))


# The NEW top-level symbol we watch -- it is DEAD (never called on entrypoint).
def shared_name():
    return "TOP-LEVEL (dead)"


# A live, unrelated class with a method of the SAME bare name that DOES run.
class SomethingLive:
    def shared_name(self):     # co_name == 'shared_name', co_qualname == 'SomethingLive.shared_name'
        return "METHOD (live)"


def live_entrypoint():
    return SomethingLive().shared_name()   # calls the METHOD, never the top-level fn


with observe_symbol_execution(['shared_name']) as obs:
    out = live_entrypoint()

print("entrypoint ran the METHOD, output:", repr(out))
print("top-level shared_name observed (sound iff False, since only the method ran):",
      obs.executed('shared_name'))
print("On 3.11+ (real path): co_qualname guard ->",
      "SOUND (False)" if not obs.executed('shared_name') else "FALSE PASS (True)")

# --- Now simulate the brief's MANDATED fallback (match co_name when qualname
#     unavailable) to show that branch is UNSOUND. ---
class fallback_observer:
    def __init__(self, watch):
        self.watch = set(watch); self.reached = set(); self.prior = None
    def _t(self, frame, event, arg):
        if event == 'call':
            name = frame.f_code.co_name
            qn = getattr(frame.f_code, 'co_qualname', None)
            # brief: "fall back to matching co_name when qualname is unavailable"
            if name in self.watch and (qn is None):   # force the fallback branch
                self.reached.add(name)
            elif name in self.watch and qn is None:
                self.reached.add(name)
        return self._t
    def __enter__(self):
        self.prior = sys.gettrace(); sys.settrace(self._t); return self
    def __exit__(self, *a):
        sys.settrace(self.prior); return False
    def executed(self, n): return n in self.reached

# Demonstrate the principle directly: under the fallback rule (qn unavailable),
# a same-named method match would set reached. We can't remove co_qualname on
# 3.11+, so show the logic: if the guard is `qn is None or qn == name`, and on a
# hypothetical <3.11 qn is None for ALL frames, the method frame (co_name
# 'shared_name') WOULD match. Prove via a direct co_name check:
def method_frame_would_match():
    matched = {}
    def t(frame, event, arg):
        if event == 'call' and frame.f_code.co_name == 'shared_name':
            # the brief fallback `qn is None` path: count it
            matched['hit_qualname'] = getattr(frame.f_code, 'co_qualname', None)
        return t
    prior = sys.gettrace(); sys.settrace(t)
    try:
        SomethingLive().shared_name()
    finally:
        sys.settrace(prior)
    return matched

m = method_frame_would_match()
print("\nThe live frame the watcher sees has co_qualname =", repr(m.get('hit_qualname')))
print("Under the brief's `qn is None` fallback (pre-3.11), that frame matches by "
      "bare co_name -> FALSE PASS on the dead top-level symbol.")
