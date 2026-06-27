"""LIMITATION 2 FIX PROOF — installing threading.settrace ALSO closes the
worker-thread blind spot. This grounds the proposed minimal brief change
(Impl Note 3 must additionally install threading.settrace(self._trace) on
__enter__ and threading.settrace(None or prior) on __exit__).
"""
import sys, os, threading
sys.path.insert(0, os.path.dirname(__file__))


class observe_with_thread_trace:
    """Faithful primitive PLUS threading.settrace — the proposed fix."""
    def __init__(self, qualnames):
        self._watch = set(qualnames or [])
        self._reached = set()
        self._prior = None
        self._prior_thread = None

    def _trace(self, frame, event, arg):
        try:
            if event == 'call' and frame.f_code.co_name in self._watch:
                qn = getattr(frame.f_code, 'co_qualname', None)
                if qn is None or qn == frame.f_code.co_name:
                    self._reached.add(frame.f_code.co_name)
        except Exception:
            pass
        return self._trace

    def __enter__(self):
        self._prior = sys.gettrace()
        sys.settrace(self._trace)
        threading.settrace(self._trace)   # <-- THE FIX
        return self

    def __exit__(self, *exc):
        try:
            sys.settrace(self._prior)
        finally:
            threading.settrace(None)      # restore (no chain API; None is the default)
        return False

    def executed(self, name):
        return name in self._reached


def worker_thread_symbol():
    return "ran on worker thread"


_result = {}
def live_entrypoint_uses_thread_pool():
    t = threading.Thread(target=lambda: _result.setdefault('v', worker_thread_symbol()))
    t.start(); t.join()
    return _result.get('v')


with observe_with_thread_trace(['worker_thread_symbol']) as obs:
    out = live_entrypoint_uses_thread_pool()

print("worker thread result:", repr(out))
print("WITH threading.settrace -> observed (want True):", obs.executed('worker_thread_symbol'))
print("FIX WORKS" if obs.executed('worker_thread_symbol') else "FIX FAILED")
