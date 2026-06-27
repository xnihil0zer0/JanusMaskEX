"""Pin the EXACT root cause of the under-coverage miss.
Hypothesis A: returning coverage's local tracer (non-None) for the driver frame
  means OUR _trace is not the local tracer, so when 'call' for reached_probe is
  dispatched it goes... where? Test by returning self._trace ALWAYS (ignore chain
  for local) and see if observation recovers.
Hypothesis B: coverage's CTracer, once settrace is swapped, stops generating
  events for frames that were already set up, OR the swap itself is the issue.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))


def reached_probe():
    return 42

def driver():
    return reached_probe()


# Variant 1: chain but ALWAYS return self._trace as the local (don't defer to coverage's local)
class obs_self_local:
    def __init__(self, w):
        self.w=set(w); self.r=set(); self.p=None
    def _t(self, frame, event, arg):
        if event=='call' and frame.f_code.co_name in self.w:
            qn=getattr(frame.f_code,'co_qualname',None)
            if qn is None or qn==frame.f_code.co_name:
                self.r.add(frame.f_code.co_name)
        if self.p is not None:
            try: self.p(frame,event,arg)
            except Exception: pass
        return self._t  # ALWAYS our local
    def __enter__(self):
        self.p=sys.gettrace(); sys.settrace(self._t); return self
    def __exit__(self,*a):
        sys.settrace(self.p); return False
    def ex(self,n): return n in self.r


# Variant 2: do NOT chain at all -- pure observer, ignore coverage (clobber)
class obs_no_chain:
    def __init__(self, w):
        self.w=set(w); self.r=set(); self.p=None
    def _t(self, frame, event, arg):
        if event=='call' and frame.f_code.co_name in self.w:
            self.r.add(frame.f_code.co_name)
        return self._t
    def __enter__(self):
        self.p=sys.gettrace(); sys.settrace(self._t); return self
    def __exit__(self,*a):
        sys.settrace(self.p); return False
    def ex(self,n): return n in self.r


for name, cls in [("self-local-chain", obs_self_local), ("no-chain-clobber", obs_no_chain)]:
    o = cls(['reached_probe'])
    with o:
        driver()
    print(f"{name}: reached_probe observed = {o.ex('reached_probe')}  (gettrace inside-check below)")

# Also: does manually re-running settrace mid-frame help? Show what gettrace is.
print("outer sys.gettrace():", type(sys.gettrace()).__name__)
