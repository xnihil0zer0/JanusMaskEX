"""pytest form of ITEM 3 so it can be run under `pytest --cov`. The critical
case (agent2/finding1) is that under coverage.py's C-level CTracer the observer
must STILL observe executed=True (chaining suppressed it; clobber-then-restore
fixes it) AND must restore coverage's tracer exactly so the rest of the suite is
still measured."""
import os
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from revised_primitive import observe_symbol_execution


def reached_probe():
    return 42


def driver():
    return reached_probe()


def worker_thread_symbol():
    return "ran on worker thread"


def test_observed_under_active_tracer():
    prior_before = sys.gettrace()
    with observe_symbol_execution(['reached_probe']) as obs:
        driver()
    prior_after = sys.gettrace()
    assert obs.executed('reached_probe') is True, "clobber-then-restore must OBSERVE the symbol even under coverage's CTracer"
    assert prior_after is prior_before, "the EXACT prior tracer (coverage's) must be restored after the with-block"


def test_worker_thread_observed():
    res = {}
    with observe_symbol_execution(['worker_thread_symbol']) as obs:
        t = threading.Thread(target=lambda: res.setdefault('v', worker_thread_symbol()))
        t.start()
        t.join()
    assert obs.executed('worker_thread_symbol') is True, "threading.settrace must observe a worker-thread symbol"
