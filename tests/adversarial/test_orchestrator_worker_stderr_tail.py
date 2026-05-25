"""Adversarial regression bar for ORCHESTRATOR_WORKER_STDERR_TAIL (D7).

Bug: ``harness.orchestrator_worker.main`` emits a ``worker_exit`` lifecycle
row in its ``finally:`` block with only ``phase``, ``task_id``, ``event``,
and ``exit_code`` -- no stderr context. When ``exit_code != 0`` (the
``except Exception`` arm at lines 338-343 set ``exit_code=2``, or the
rejected/decomposed paths set ``exit_code=1``) operators and the
``compute_brief_status`` consumer see a bare exit code with zero
diagnostic. RP3 solved the analogous opacity for the planner subprocess
in ``harness/autowork_daemon.py:301-328``; this brief dogfoods the same
pattern one layer down.

Fix shape (this brief):
- Wrap ``main()``'s ``try:`` body in ``contextlib.redirect_stderr(io.StringIO())``
  so the pipeline's stderr writes (including the explicit
  ``sys.stderr.write`` + ``traceback.print_exc`` in the except arm) land
  in a buffer.
- In the ``finally:`` block, compute
  ``stderr_tail = _stderr_buf.getvalue()[-256:].encode('unicode_escape').decode('ascii', errors='replace')``
  and pass it as a new ``stderr_tail=`` kwarg to
  ``_emit_lifecycle_safe(..., event='worker_exit', ...)``.

The two xfail markers in this file are dropped in a follow-up META commit
once the fix lands (same lifecycle as RP3 / RP7 / ROLLBACK_WORKTREE_CHECKOUT).
"""
from __future__ import annotations

import ast
import pathlib

import pytest


_MODULE_PATH = pathlib.Path(__file__).resolve().parent.parent.parent / "harness" / "orchestrator_worker.py"


def _load_source() -> str:
    return _MODULE_PATH.read_text(encoding="utf-8")


def _find_worker_exit_call(tree: ast.AST) -> ast.Call:
    """Locate the ``_emit_lifecycle_safe(..., event='worker_exit', ...)``
    Call node inside ``main()``. Returns the Call AST node or raises
    AssertionError if none found.
    """
    main_fn = next(
        (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "main"),
        None,
    )
    assert main_fn is not None, "main() function not found in harness/orchestrator_worker.py"
    candidates: list[ast.Call] = []
    for node in ast.walk(main_fn):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # Match bare-name call (_emit_lifecycle_safe) -- the file uses the local helper.
        if isinstance(func, ast.Name) and func.id == "_emit_lifecycle_safe":
            for kw in node.keywords:
                if (
                    kw.arg == "event"
                    and isinstance(kw.value, ast.Constant)
                    and kw.value.value == "worker_exit"
                ):
                    candidates.append(node)
                    break
    assert candidates, (
        "no _emit_lifecycle_safe(..., event='worker_exit', ...) call found in main(); "
        "did the post-RP7 layout shift the worker_exit emit out of main()?"
    )
    assert len(candidates) == 1, (
        f"expected exactly one worker_exit emit in main(); found {len(candidates)}. "
        "If the brief intentionally added a second emit site, update this test."
    )
    return candidates[0]


def test_worker_exit_emit_includes_stderr_tail_field() -> None:
    """The ``worker_exit`` lifecycle emit in ``harness/orchestrator_worker.py``
    must carry a ``stderr_tail`` kwarg so operators can correlate non-zero
    exit codes with the failure cause.
    """
    src = _load_source()
    tree = ast.parse(src)
    call = _find_worker_exit_call(tree)
    kwarg_names = {kw.arg for kw in call.keywords}
    assert "stderr_tail" in kwarg_names, (
        f"worker_exit emit missing required 'stderr_tail' kwarg; "
        f"got kwargs={sorted(k for k in kwarg_names if k is not None)!r}. "
        "Mirror RP3's pattern from harness/autowork_daemon.py:301-328."
    )
    # Sanity: existing kwargs are preserved (telemetry stability is load-bearing).
    for required in ("phase", "task_id", "event", "exit_code"):
        assert required in kwarg_names, (
            f"worker_exit emit dropped existing kwarg {required!r}; "
            f"got kwargs={sorted(k for k in kwarg_names if k is not None)!r}"
        )


def test_stderr_tail_is_truncated_to_256_chars_and_escaped() -> None:
    """The ``stderr_tail`` value must be the last 256 chars of the captured
    stderr buffer, encoded via ``unicode_escape`` to ASCII (preventing
    control characters or non-UTF-8 bytes from breaking the JSONL ledger).

    Source-grep enforces co-occurrence of the ``[-256:]`` slice operator
    AND the ``unicode_escape`` literal within ~10 source lines of the
    ``worker_exit`` emit, mirroring RP3's pattern in
    ``harness/autowork_daemon.py``.
    """
    src = _load_source()
    lines = src.splitlines()
    tree = ast.parse(src)
    call = _find_worker_exit_call(tree)
    emit_lineno = call.lineno  # 1-indexed

    # Window: 10 lines before, 5 lines after the emit (the redirect setup
    # happens before the try: block and the truncation happens in finally:
    # just before the emit -- both are above the emit lineno).
    lo = max(1, emit_lineno - 12)
    hi = min(len(lines), emit_lineno + 5)
    window = "\n".join(lines[lo - 1 : hi])

    assert "[-256:]" in window, (
        f"expected '[-256:]' slice operation within ~10 lines of the worker_exit emit "
        f"(line {emit_lineno}); window lines {lo}-{hi} contained no [-256:] slice. "
        f"Window:\n{window!r}"
    )
    assert "unicode_escape" in window, (
        f"expected 'unicode_escape' literal within ~10 lines of the worker_exit emit "
        f"(line {emit_lineno}); window lines {lo}-{hi} contained no 'unicode_escape'. "
        f"Window:\n{window!r}"
    )
