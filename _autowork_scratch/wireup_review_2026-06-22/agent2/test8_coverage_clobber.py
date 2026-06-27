"""ROOT-CAUSE for the under-coverage FALSE REJECT.
coverage.py 7.x uses sys.monitoring (PEP 669) on 3.12+, NOT sys.settrace.
When our observer calls sys.settrace, what is sys.gettrace()? Is coverage's
tracer even visible? And does installing settrace get OVERRIDDEN by coverage's
C-level monitoring such that our 'call' events never fire?"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

print("python:", sys.version.split()[0])
print("has sys.monitoring (PEP 669):", hasattr(sys, 'monitoring'))

# What does coverage register? Check current monitoring tool when run under coverage.
if hasattr(sys, 'monitoring'):
    mon = sys.monitoring
    for tid in range(6):
        try:
            name = mon.get_tool(tid)
        except Exception:
            name = '<err>'
        if name:
            print(f"  monitoring tool id {tid}: {name!r}")

print("sys.gettrace() at import time:", sys.gettrace())

from faithful_primitive import observe_symbol_execution

def reached_probe():
    return 42

def driver():
    return reached_probe()

print("sys.gettrace() before with:", sys.gettrace())
with observe_symbol_execution(['reached_probe']) as obs:
    print("  sys.gettrace() inside with:", sys.gettrace())
    driver()
print("reached_probe observed:", obs.executed('reached_probe'))
print()
print("DIAGNOSIS: coverage 7.x on py3.12+ traces via sys.monitoring, not")
print("sys.settrace. sys.settrace and sys.monitoring can COEXIST, but installing")
print("a settrace fn does NOT guarantee 'call' events when monitoring is the")
print("active local-events mechanism for already-compiled frames -- print above")
print("shows whether our settrace 'call' fired (obs True) or was suppressed.")
