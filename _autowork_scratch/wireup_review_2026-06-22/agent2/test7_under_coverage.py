"""LIMITATION 7 — behaviour UNDER an existing tracer (coverage.py).
The brief mandates the observer CHAIN to the prior tracer and RESTORE it.
The faithful impl returns `local if local else self._trace`. When a prior tracer
returns a NON-None local tracer (coverage does), the observer returns coverage's
local tracer for that frame -> our own _trace is NOT the local tracer for that
frame, so NESTED 'call' events under that frame are routed to coverage's local,
not ours. For a TOP-LEVEL watched call this still fires (the 'call' is seen at
global dispatch), but a watched symbol reached only as a NESTED call under a
coverage-traced frame could be missed.

Test: install a stand-in 'prior' tracer that returns a local tracer (like
coverage), then drive a NESTED watched call, and see if the observer still sees
it. Also verify the prior tracer is RESTORED and still receives events."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from faithful_primitive import observe_symbol_execution

prior_events = []

def prior_tracer(frame, event, arg):
    # mimic coverage: record, and RETURN a local tracer (non-None)
    prior_events.append((frame.f_code.co_name, event))
    return prior_tracer   # returns a local tracer -> this is what coverage does


def nested_watched():
    return "nested ran"


def outer():
    return nested_watched()   # watched symbol reached as a NESTED call


# install the prior tracer first (simulating coverage already running)
sys.settrace(prior_tracer)
try:
    before = sys.gettrace()
    with observe_symbol_execution(['nested_watched']) as obs:
        outer()
    after = sys.gettrace()
finally:
    sys.settrace(None)

print("prior tracer restored after with-block (want True):", after is before is prior_tracer)
print("nested_watched observed despite coverage-style prior local tracer (want True):",
      obs.executed('nested_watched'))
print("prior tracer kept receiving events during the block (want >0):",
      len([e for e in prior_events if e[0] in ('outer', 'nested_watched')]))
print("VERDICT:", "SOUND under coverage" if obs.executed('nested_watched')
      else "MISS: nested watched call lost when prior tracer returns a local")
