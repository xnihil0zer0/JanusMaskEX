"""Adversarial oracle for PHASE_AGY2D_WATCHDOG_BUDGET.

This test asserts that the sequential worker watchdog timeout in harness/autowork_daemon.py
is properly widened to match or exceed the worker's hard budget (synthesis_timeout * 2 + 300)
defined in harness/orchestrator_worker.py.

RED on HEAD:
For synthesis_timeout = 1200 (the standard synthesis window):
- Watchdog timeout is max(1800.0, 1200.0 + 300.0) = 1800s.
- Worker hard budget is 1200 * 2 + 300 = 2700s.
- The watchdog is 1800s < 2700s, causing the watchdog to prematurely kill the worker
  while it is still within its legitimate budget. The assertion fails.

GREEN after fix:
- Watchdog timeout is max(1800.0, 2.0 * 1200.0 + 600.0) = 3000s.
- Worker hard budget is 2700s.
- The watchdog is 3000s >= 2700s. The assertion passes.
"""

from pathlib import Path
import ast
import pytest


def _find_autowork_daemon() -> Path:
    # Try finding relative to this test file
    path1 = Path(__file__).parents[2] / "harness" / "autowork_daemon.py"
    if path1.exists():
        return path1
    # Fallback to current working directory
    path2 = Path("harness/autowork_daemon.py")
    if path2.exists():
        return path2
    raise FileNotFoundError("Could not find harness/autowork_daemon.py")


def _get_watchdog_timeout(timeout_val: float) -> float:
    path = _find_autowork_daemon()
    tree = ast.parse(path.read_text(encoding="utf-8"))

    class WatchdogFinder(ast.NodeVisitor):
        def __init__(self):
            self.exprs = []

        def visit_Assign(self, node):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "watchdog_timeout":
                    self.exprs.append(node.value)
            self.generic_visit(node)

    finder = WatchdogFinder()
    finder.visit(tree)

    formula_expr = None
    for e in finder.exprs:
        if isinstance(e, ast.Call) and isinstance(e.func, ast.Name) and e.func.id == "max":
            formula_expr = e
            break

    if formula_expr is None:
        raise ValueError("Could not find watchdog_timeout assignment with max() in autowork_daemon.py")

    func_node = ast.FunctionDef(
        name="eval_timeout",
        args=ast.arguments(
            posonlyargs=[],
            args=[ast.arg(arg="timeout_val", annotation=None)],
            kwonlyargs=[],
            kw_defaults=[],
            defaults=[],
            kwarg=None,
            vararg=None
        ),
        body=[ast.Return(value=formula_expr)],
        decorator_list=[]
    )
    ast.fix_missing_locations(func_node)
    mod = ast.Module(body=[func_node], type_ignores=[])
    code = compile(mod, filename="<ast>", mode="exec")
    namespace = {"max": max, "float": float}
    exec(code, namespace)
    return namespace["eval_timeout"](timeout_val)


@pytest.mark.parametrize("timeout", [900, 1200, 1800])
def test_watchdog_timeout_exceeds_worker_hard_budget(timeout):
    """Assert that for any given synthesis timeout, the watchdog budget is
    consistently >= the worker's hard timeout budget (timeout * 2 + 300).
    """
    watchdog = _get_watchdog_timeout(timeout)
    worker_hard_budget = float(timeout) * 2.0 + 300.0
    assert watchdog >= worker_hard_budget, (
        f"watchdog timeout ({watchdog}s) is smaller than the worker hard budget ({worker_hard_budget}s) "
        f"for synthesis timeout {timeout}s"
    )
