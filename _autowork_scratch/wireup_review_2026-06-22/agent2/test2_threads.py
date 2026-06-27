"""LIMITATION 2 — THREADS.
sys.settrace only traces the thread it was set on. A symbol reached ONLY on a
worker thread is invisible unless threading.settrace is ALSO installed.

The brief's primitive uses sys.settrace ONLY (Implementation Note 3 says nothing
about threading.settrace). So a genuinely-wired symbol that runs on a worker
thread -> FALSE REJECT.
"""
import sys, os, threading
sys.path.insert(0, os.path.dirname(__file__))
from faithful_primitive import observe_symbol_execution


def worker_thread_symbol():
    # genuinely wired: the live entrypoint dispatches it onto a thread
    return "ran on worker thread"


_result = {}


def live_entrypoint_uses_thread_pool():
    # mirrors orchestrator running workers concurrently on threads
    t = threading.Thread(target=lambda: _result.setdefault('v', worker_thread_symbol()))
    t.start()
    t.join()
    return _result.get('v')


with observe_symbol_execution(['worker_thread_symbol']) as obs:
    out = live_entrypoint_uses_thread_pool()

print("worker thread result (proves it REALLY ran):", repr(out))
print("observer says executed (want True if sound; FALSE = blind spot):",
      obs.executed('worker_thread_symbol'))
print("VERDICT: FALSE REJECT" if (out == "ran on worker thread" and not obs.executed('worker_thread_symbol'))
      else "VERDICT: observed")

# Control: same symbol called on the MAIN thread IS observed (proves it's the
# thread boundary, not a broken primitive).
_result.clear()
with observe_symbol_execution(['worker_thread_symbol']) as obs2:
    worker_thread_symbol()
print("control: same symbol on MAIN thread observed (want True):",
      obs2.executed('worker_thread_symbol'))
