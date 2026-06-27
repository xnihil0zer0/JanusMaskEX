"""Find a CORRECT chaining strategy that observes AND preserves coverage data.
Strategies to test under `coverage run` and assert coverage still records lines.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

def reached_probe(): return 42
def driver(): return reached_probe()


# STRATEGY X: chain, but make OUR local-trace wrap coverage's local-trace.
# On 'call', record our match, call prior global to get prior's local, then
# return a composed local that forwards to prior's local AND keeps watching 'call'.
class obs_compose:
    def __init__(self, w):
        self.w=set(w); self.r=set(); self.p=None
    def _global(self, frame, event, arg):
        self._match(frame, event)
        prior_local = None
        if self.p is not None:
            try: prior_local = self.p(frame, event, arg)
            except Exception: prior_local = None
        return self._make_local(prior_local)
    def _match(self, frame, event):
        if event=='call' and frame.f_code.co_name in self.w:
            qn=getattr(frame.f_code,'co_qualname',None)
            if qn is None or qn==frame.f_code.co_name:
                self.r.add(frame.f_code.co_name)
    def _make_local(self, prior_local):
        def local(frame, event, arg):
            self._match(frame, event)
            nxt = None
            if prior_local is not None:
                try: nxt = prior_local(frame, event, arg)
                except Exception: nxt = None
            return self._make_local(nxt) if nxt is not None else local
        return local
    def __enter__(self):
        self.p=sys.gettrace(); sys.settrace(self._global); return self
    def __exit__(self,*a):
        sys.settrace(self.p); return False
    def ex(self,n): return n in self.r


# STRATEGY Y (PRAGMATIC, what I'd actually recommend): the observer is used
# only inside the `with` block driving an entrypoint. Snapshot the prior tracer,
# CLOBBER during the block (return self._trace), then RESTORE on exit. Coverage
# loses line data ONLY for the few frames inside the with-block (acceptable:
# the gate-proof oracle doesn't need coverage of the driven body), and the
# prior tracer is reinstalled exactly. This is "restore", which item F allows
# as an alternative to "chain" ("chain-OR-restore").
class obs_clobber_restore:
    def __init__(self, w):
        self.w=set(w); self.r=set(); self.p=None
    def _t(self, frame, event, arg):
        try:
            if event=='call' and frame.f_code.co_name in self.w:
                qn=getattr(frame.f_code,'co_qualname',None)
                if qn is None or qn==frame.f_code.co_name:
                    self.r.add(frame.f_code.co_name)
        except Exception:
            pass
        return self._t
    def __enter__(self):
        self.p=sys.gettrace(); sys.settrace(self._t); return self
    def __exit__(self,*a):
        sys.settrace(self.p); return False  # EXACT restore
    def ex(self,n): return n in self.r


for name, cls in [("compose-chain", obs_compose), ("clobber-then-restore", obs_clobber_restore)]:
    o = cls(['reached_probe'])
    before = sys.gettrace()
    with o:
        driver()
    after = sys.gettrace()
    print(f"{name}: observed={o.ex('reached_probe')}  prior_restored={after is before}  prior_type={type(before).__name__}")
