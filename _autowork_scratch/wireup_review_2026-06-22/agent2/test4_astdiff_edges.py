"""LIMITATION 4 — AST-diff `new_top_level_callables` edge cases.
For each: print what the primitive returns, and judge against the brief's
DECLARED scope (Non-Goals: "Detecting NEW METHODS on a class or nested defs"
is OUT of scope; scope = module-scope def/async def + top-level name=lambda).

A miss is a DEFECT only if it is IN scope per the brief.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from faithful_primitive import new_top_level_callables


def show(label, parent, child, in_scope_note):
    got = new_top_level_callables(parent, child)
    print(f"--- {label} ---")
    print("  returns:", got)
    print("  brief-scope:", in_scope_note)
    print()


# (a) METHOD added to an existing class — OUT of scope per brief Non-Goals.
show("methods added to existing class",
     "class C:\n    def a(self): ...\n",
     "class C:\n    def a(self): ...\n    def brand_new_method(self): ...\n",
     "OUT of scope (class methods are the enclosing symbol's concern) -> empty expected")

# (b) DECORATED top-level function — IN scope (still a module-scope FunctionDef).
show("decorated top-level function",
     "def already(): ...\n",
     "import functools\n@functools.lru_cache\ndef decorated_new():\n    return 1\n",
     "IN scope: a decorated def is still a top-level FunctionDef -> should include 'decorated_new'")

# (c) CONDITIONALLY-defined top-level function (def inside if/try at module scope).
show("conditionally-defined function (if-guarded)",
     "x = 1\n",
     "x = 1\nif True:\n    def cond_new():\n        return 1\n",
     "AMBIGUOUS: module-executes-to-define but NOT a direct module.body node -> primitive likely MISSES it")

show("conditionally-defined function (try/except import fallback)",
     "x = 1\n",
     "try:\n    import nonexist\nexcept ImportError:\n    def fallback_impl():\n        return 1\n",
     "Common real pattern (backport/fallback). Body node nested in Try -> primitive likely MISSES")

# (d) RE-EXPORT / ALIAS of a function (assignment of a Name, not a Lambda).
show("alias / re-export (name = existing_fn)",
     "def real_impl(): ...\n",
     "def real_impl(): ...\npublic_alias = real_impl\n",
     "Alias is `name = Name` (not Lambda) -> primitive does NOT count it; "
     "but is `public_alias` a NEW callable that PHASE 2 should require wiring for? "
     "Brief scope = lambda-assignment only, so alias is silently excluded.")

# (e) functools.partial / wrapper assignment (name = call) -- a callable bound at top level
show("name = functools.partial(...) (a callable, not a lambda)",
     "import functools\ndef base(a,b): ...\n",
     "import functools\ndef base(a,b): ...\nbound = functools.partial(base, 1)\n",
     "A genuinely-callable top-level name, NOT a Lambda -> primitive excludes it (out of declared scope)")

# (f) rename reads as new (brief explicitly accepts this)
show("rename (old->new) reads as new",
     "def old_name():\n    return 1\n",
     "def new_name():\n    return 1\n",
     "Brief explicitly: 'A rename reads as new -- acceptable.' -> expects ['new_name']")
