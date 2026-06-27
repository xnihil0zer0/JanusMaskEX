"""ITEM 3 -- SETTRACE FIXES HOLD against the REVISED primitive.

3a. clobber-then-restore observes executed=True under coverage's C-tracer
    (agent2/finding1 showed CHAINING gave False). This file is RUN under both
    `python -m coverage run` and `pytest --cov` by the driver script; here we
    only need to (i) observe a symbol reached via a NORMAL call, (ii) assert the
    prior tracer object is restored EXACTLY after the with-block.
3b. worker-thread reach observed True via threading.settrace (agent2/test2).
3c. new_top_level_callables enumerates a def inside a module-level try AND if AND
    with (agent2/test4/test5 widening).
"""
import os
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from revised_primitive import observe_symbol_execution, new_top_level_callables


def reached_probe():
    return 42


def driver():
    return reached_probe()


def worker_thread_symbol():
    return "ran on worker thread"


_result = {}
def threaded_entrypoint():
    t = threading.Thread(target=lambda: _result.setdefault('v', worker_thread_symbol()))
    t.start()
    t.join()
    return _result.get('v')


def run():
    results = {}

    # --- 3a: observe under whatever tracer is active (coverage when run under
    #         `coverage run` / `pytest --cov`); assert exact prior-tracer restore.
    prior_before = sys.gettrace()
    with observe_symbol_execution(['reached_probe']) as obs:
        driver()
    prior_after = sys.gettrace()
    observed = obs.executed('reached_probe')
    restored_exact = prior_after is prior_before
    results['3a_observed'] = observed
    results['3a_prior_restored_exact'] = restored_exact
    results['3a_prior_type'] = type(prior_before).__name__ if prior_before is not None else 'None'

    # --- 3b: worker-thread observation via threading.settrace
    _result.clear()
    with observe_symbol_execution(['worker_thread_symbol']) as obs2:
        out = threaded_entrypoint()
    results['3b_thread_observed'] = obs2.executed('worker_thread_symbol')
    results['3b_thread_out'] = out

    # --- 3c: AST diff widening into module-scope If / Try / With
    parent_src = "def already():\n    return 0\n"
    child_src = (
        "def already():\n    return 0\n"
        "def brand_new():\n    return 1\n"
        "async def brand_new_async():\n    return 2\n"
        "lam = lambda x: x\n"
        "import sys\n"
        "try:\n"
        "    import nonexist_xyz\n"
        "except ImportError:\n"
        "    def try_nested():\n"
        "        return 3\n"
        "if True:\n"
        "    def if_nested():\n"
        "        return 4\n"
        "with open(__file__) as _f:\n"
        "    def with_nested():\n"
        "        return 5\n"
    )
    got = new_top_level_callables(parent_src, child_src)
    results['3c_new_callables'] = got

    return results


if __name__ == "__main__":
    r = run()
    print("=== ITEM 3: settrace fixes (run standalone -- see driver for coverage runs) ===")
    print(f"3a observed reached_probe (clobber observes)  = {r['3a_observed']}")
    print(f"3a prior tracer ({r['3a_prior_type']}) restored EXACTLY = {r['3a_prior_restored_exact']}")
    ok_3a = (r['3a_observed'] is True) and (r['3a_prior_restored_exact'] is True)
    print(f"   3a: {'PASS' if ok_3a else 'FAIL'}")
    print()
    print(f"3b worker_thread_symbol observed via threading.settrace = {r['3b_thread_observed']}  (out={r['3b_thread_out']!r})")
    ok_3b = r['3b_thread_observed'] is True
    print(f"   3b: {'PASS' if ok_3b else 'FAIL'}")
    print()
    print(f"3c new_top_level_callables (try/if/with-nested) = {r['3c_new_callables']}")
    want = {'brand_new', 'brand_new_async', 'lam', 'try_nested', 'if_nested', 'with_nested'}
    got = set(r['3c_new_callables'])
    ok_3c = want.issubset(got) and ('already' not in got)
    print(f"   want >= {sorted(want)} and 'already' NOT present")
    print(f"   3c: {'PASS' if ok_3c else 'FAIL'}  (missing={sorted(want - got)}, extra={sorted(got - want)})")
    print()
    allok = ok_3a and ok_3b and ok_3c
    print(f"ITEM 3 (standalone) OVERALL: {'PASS' if allok else 'FAIL'}")
    sys.exit(0 if allok else 1)
