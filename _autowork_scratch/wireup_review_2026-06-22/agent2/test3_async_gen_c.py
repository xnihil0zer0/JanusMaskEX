"""LIMITATION 3 — ASYNC / GENERATORS / C-level callbacks.
Symbols reached only inside an async task, a generator body, or via a C callback.
Brief Non-Goals explicitly carves out C-extension / generator-internal / exec.
Test which actually fire and which are blind.
"""
import sys, os, asyncio
sys.path.insert(0, os.path.dirname(__file__))
from faithful_primitive import observe_symbol_execution


# --- ASYNC: a top-level async def reached only inside an event loop task ---
async def async_symbol():
    return "async ran"


async def async_driver():
    return await async_symbol()


with observe_symbol_execution(['async_symbol']) as obs_a:
    out_a = asyncio.run(async_driver())
print("async_symbol output:", repr(out_a))
print("async_symbol observed (sound iff True):", obs_a.executed('async_symbol'))

# --- GENERATOR: a top-level def that is a generator, body runs only on iteration ---
def gen_symbol():
    yield 1
    yield 2


def gen_driver():
    return list(gen_symbol())  # forces the generator body to execute


with observe_symbol_execution(['gen_symbol']) as obs_g:
    out_g = gen_driver()
print("gen_symbol output:", out_g)
print("gen_symbol observed (sound iff True):", obs_g.executed('gen_symbol'))

# --- GENERATOR reached but NEVER iterated (created, not driven) ---
def gen_symbol2():
    yield 1


def lazy_driver():
    g = gen_symbol2()   # created, body NOT entered
    return g


with observe_symbol_execution(['gen_symbol2']) as obs_g2:
    _ = lazy_driver()
print("gen_symbol2 created-but-not-iterated observed (note: body did NOT run):",
      obs_g2.executed('gen_symbol2'))

# --- C-LEVEL CALLBACK: a top-level fn used as key= to sorted() (called from C) ---
def c_callback_symbol(x):
    return -x


def c_driver():
    return sorted([3, 1, 2], key=c_callback_symbol)


with observe_symbol_execution(['c_callback_symbol']) as obs_c:
    out_c = c_driver()
print("c_callback output (proves it REALLY ran %d times):" % len(out_c), out_c)
print("c_callback_symbol observed (Python frame entered per-call -> ?):",
      obs_c.executed('c_callback_symbol'))
