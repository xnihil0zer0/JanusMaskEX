"""Non-invasive check: does the EXACT carve-out fix make ALL committed oracle tests green?
Monkeypatches a fixed _enforce_module_first into the plan_normalizer namespace (no repo edit),
then runs every test function in the committed oracle file and reports pass/fail."""
import inspect, tempfile, traceback
from pathlib import Path
import harness.planner.plan_normalizer as pn

src = inspect.getsource(pn._enforce_module_first)
old = ("        if repo_root is not None and isinstance(_vc, str) and _vc:\n"
       "            from pathlib import Path as _Path\n"
       "            if (_Path(repo_root) / _module_path(target)).is_file():\n"
       "                _ofiles = [f for f in _files_touched(oracle) if isinstance(f, str) and f]\n"
       "                if any(of in _vc for of in _ofiles):\n"
       "                    continue")
new = ("        if isinstance(_vc, str) and _vc:\n"
       "            _ofiles = [f for f in _files_touched(oracle) if isinstance(f, str) and f]\n"
       "            if any(of in _vc for of in _ofiles):\n"
       "                continue")
assert old in src, "FIX ANCHOR NOT FOUND — current carve-out text differs from expected"
fixed = src.replace(old, new)
exec(compile(fixed, pn.__file__, "exec"), pn.__dict__)   # redefine _enforce_module_first (fixed) in pn globals
print("monkeypatch applied: fixed _enforce_module_first installed in pn namespace\n")

import tests.harness.test_redpair_newmodule_order as T  # binds normalize_plan = pn.normalize_plan
fns = [n for n in dir(T) if n.startswith("test_")]
results = {}
for n in sorted(fns):
    fn = getattr(T, n)
    needs_tmp = "tmp_path" in inspect.signature(fn).parameters
    try:
        if needs_tmp:
            with tempfile.TemporaryDirectory() as d:
                fn(Path(d))
        else:
            fn()
        results[n] = "PASS"
    except Exception as e:
        results[n] = f"FAIL: {type(e).__name__}: {e}"
for n in sorted(results):
    print(f"  {results[n][:60]:62}  {n}")
npass = sum(1 for v in results.values() if v == "PASS")
print(f"\n{npass}/{len(results)} GREEN after fix")
print("VERDICT:", "ORACLE SATISFIABLE (re-drive impl)" if npass == len(results) else "ORACLE FLAWED (some tests not fixable by carve-out)")
