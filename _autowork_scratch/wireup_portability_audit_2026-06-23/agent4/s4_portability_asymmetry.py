"""S4: Portability asymmetry between the MODULE gate (check_wired, ENABLED) and the
RUNTIME SYMBOL floor (symbol_reachable_from_live_root, default-OFF) at JM HEAD fc8167a.

Finding: check_wired reconciles roots via discover_live_roots for external/rootless
trees; symbol_reachable_from_live_root does NOT — it seeds only from the passed roots
(default LIVE_ROOTS, JM-hardcoded) and has no discover_live_roots fallback, so on an
external tree where no LIVE_ROOTS file exists, the floor returns False for EVERY symbol
(would_be_orphan storm).
"""
import inspect
from harness import wire_up

cw = inspect.getsource(wire_up.check_wired)
floor = inspect.getsource(wire_up.symbol_reachable_from_live_root)

print("=== check_wired has discover_live_roots reconciliation fallback? ===")
print("  ", "discover_live_roots" in cw)
print("=== symbol_reachable_from_live_root has discover_live_roots fallback? ===")
print("  ", "discover_live_roots" in floor)
print()
print("=== check_wired rootless no-op clause present? ('external/rootless') ===")
print("  ", "external/rootless" in cw or "rootless" in cw.lower())
print("=== floor rootless no-op clause present? ===")
print("  ", "rootless" in floor.lower())
print()

# Empirical: run the floor on a synthetic external tree with NO LIVE_ROOTS files.
import tempfile, pathlib
with tempfile.TemporaryDirectory() as d:
    root = pathlib.Path(d)
    # an external package: main.py (entry, __main__ guard) imports lib.py:helper
    (root / "main.py").write_text(
        "from lib import helper\n"
        "def run():\n    return helper()\n"
        "if __name__ == '__main__':\n    run()\n"
    )
    (root / "lib.py").write_text("def helper():\n    return 1\n")
    # FLOOR with default JM LIVE_ROOTS (none exist in this tree):
    floor_default = wire_up.symbol_reachable_from_live_root(str(root), "lib.py", "helper")
    # MODULE gate (check_wired) on the same external lib.py:
    cw_res = wire_up.check_wired(str(root), "lib.py")
    # discover_live_roots on the external tree:
    droots = wire_up.discover_live_roots(str(root))
    print("=== Empirical external-tree probe (NO JM LIVE_ROOTS present) ===")
    print("  discover_live_roots(external) =", droots, " (finds main.py via __main__ guard)")
    print("  symbol_reachable_from_live_root('lib.py','helper', default roots) =", floor_default,
          " <- FLOOR is JM-hardcoded; returns False even though helper IS reachable")
    print("  check_wired('lib.py').wired =", getattr(cw_res, "wired", None),
          " <- MODULE gate reconciles roots, so it is portable")
    # And prove the floor WORKS if given the reconciled roots explicitly:
    floor_reconciled = wire_up.symbol_reachable_from_live_root(str(root), "lib.py", "helper", roots=droots)
    print("  symbol_reachable_from_live_root(..., roots=discover_live_roots(...)) =", floor_reconciled,
          " <- floor becomes correct ONLY when fed reconciled roots (the portability fix)")
