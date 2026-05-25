"""Adversarial tests for AUTOWORK_SILENT_SKIP_TELEMETRY.

Pre-staged xfail-strict tests that flip to PASS once the dispatch lands.

Verifies that the three silent `except` blocks in
``harness/autowork_daemon.py:_auto_promote`` (lines ~394, ~398, ~467 in
HEAD post-RP6/RP7) each get a companion ``write_jsonl_row`` emit so the
autowork daemon stops swallowing extract-failures, extract-loop
OSErrors, and plan-kickoff OSErrors without leaving a breadcrumb on the
``state/impl_progress.jsonl`` ledger.

This is the systemic observability follow-up to R-PROMOTE-6 (the
``is_idle`` misclassification fix that has already landed); RP6 closed
the heartbeat-side gap, this dispatch closes the matching emit-side
gap so the rows RP6's classifier needs are actually there to classify.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
TARGET = REPO_ROOT / "harness" / "autowork_daemon.py"


def _load_auto_promote_function() -> ast.FunctionDef:
    """Parse harness/autowork_daemon.py and return the _auto_promote FunctionDef node.

    Raises a clear AssertionError if the function is not found so the
    xfail message points at a structural drift rather than a parse
    error.
    """
    src = TARGET.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_auto_promote":
            return node
    raise AssertionError(
        "harness/autowork_daemon.py:_auto_promote not found — "
        "function may have been renamed/moved; re-evaluate the brief."
    )


def test_auto_promote_has_at_least_three_write_jsonl_emits() -> None:
    """AST-walk _auto_promote and count write_jsonl_row Call nodes.

    Expectation post-dispatch: the three silent ``except`` blocks each
    get a companion ``write_jsonl_row`` (or ``harness._journal.write_jsonl_row``)
    call, so the total count inside the function body is >= 3. Counted
    by substring-matching ``'write_jsonl_row'`` against
    ``ast.unparse(call.func)`` so both the
    ``from harness._journal import write_jsonl_row`` and the fully
    qualified ``harness._journal.write_jsonl_row`` forms count.
    """
    fn = _load_auto_promote_function()
    write_calls = [
        call
        for call in ast.walk(fn)
        if isinstance(call, ast.Call) and "write_jsonl_row" in ast.unparse(call.func)
    ]
    assert len(write_calls) >= 3, (
        f"_auto_promote has {len(write_calls)} write_jsonl_row call(s); "
        "expected >= 3 (one per silent-except site at approx. lines "
        "394, 398, 467 in HEAD)."
    )


def test_silent_skip_rows_carry_phase_tag() -> None:
    """Source-grep the function body for 'silent_skip' AND 'phase_tag'.

    Both literals must appear inside the unparsed function body so the
    rows are distinguishable from happy-path ``_emit_telemetry`` calls
    AND each row can be attributed to a specific step (1=stage_task,
    2=extract_loop, 3=plan_kickoff).
    """
    fn = _load_auto_promote_function()
    body = ast.unparse(fn)
    assert "silent_skip" in body, (
        "'silent_skip' event literal missing from _auto_promote — "
        "rows must use event='silent_skip' to be distinguishable from "
        "happy-path _emit_telemetry rows."
    )
    assert "phase_tag" in body, (
        "'phase_tag' key missing from _auto_promote — rows must carry "
        "phase_tag so dashboards can build per-step skip histograms."
    )


def test_existing_except_blocks_have_companion_emit() -> None:
    """For each ExceptHandler in _auto_promote, assert a write_jsonl_row
    Call exists within its body OR within 3 statements after it (i.e.,
    at the same indentation level following the except block).

    Carve-out: the ``FileExistsError``-only handler is intentionally
    silent (idempotent re-stage) and is exempted. The narrower nested
    handlers inside the plan-kickoff try-block (size-stat OSError,
    planner-subprocess Exception, JSONDecodeError on plan read,
    output_plan.unlink OSError, marker write OSError) are transitively
    covered by the outer step-3 OSError wrapper and are also exempted
    — only the THREE outermost silent-skip sites are checked here.

    Post-dispatch expectation: the three sites at approx. lines 394
    (multi-exception with FileNotFoundError), 398 (outer extract-loop
    OSError), and 467 (outer plan-kickoff OSError) each have a
    companion write_jsonl_row Call within the body or 3 statements
    after.
    """
    fn = _load_auto_promote_function()

    # Build a flat list of (node, parent_body_list, index_in_parent)
    # for every ExceptHandler in the function. Walk via parent
    # tracking so we can look ahead 3 statements after the try
    # containing the except.
    def _is_target_except(handler: ast.ExceptHandler) -> bool:
        """Filter for the three outer silent-skip sites we care about.

        Targets:
          - multi-exception tuple including FileNotFoundError
            (step 1, ~line 394)
          - bare OSError (steps 2 and 3, ~lines 398 and 467) — but
            only at the outermost-in-function nesting level.
        """
        if handler.type is None:
            return False
        # FileExistsError-only handler is the carve-out.
        if (
            isinstance(handler.type, ast.Name)
            and handler.type.id == "FileExistsError"
        ):
            return False
        # Tuple containing FileNotFoundError — step 1.
        if isinstance(handler.type, ast.Tuple):
            names = [e.id for e in handler.type.elts if isinstance(e, ast.Name)]
            return "FileNotFoundError" in names
        # Bare OSError — could be step 2/3 (outer) OR a narrower
        # nested handler. We accept all bare-OSError ExceptHandlers
        # at any depth in the helper and let the per-handler search
        # find a companion emit — narrower handlers covered by the
        # outer step-3 wrapper will find the step-3 emit within their
        # ancestor's body.
        if isinstance(handler.type, ast.Name) and handler.type.id == "OSError":
            return True
        return False

    def _emit_in_subtree(node: ast.AST) -> bool:
        for call in ast.walk(node):
            if (
                isinstance(call, ast.Call)
                and "write_jsonl_row" in ast.unparse(call.func)
            ):
                return True
        return False

    def _subtree_calls(node: ast.AST, name: str) -> bool:
        for call in ast.walk(node):
            if isinstance(call, ast.Call) and name in ast.unparse(call.func):
                return True
        return False

    # Track parent for each ExceptHandler so we can look 3 statements ahead.
    parent_of: dict[int, tuple[list[ast.stmt], int] | None] = {}

    def _walk_with_parents(node: ast.AST) -> None:
        for field, value in ast.iter_fields(node):
            if isinstance(value, list):
                for idx, child in enumerate(value):
                    if isinstance(child, ast.stmt):
                        parent_of[id(child)] = (value, idx)
                    if isinstance(child, ast.AST):
                        _walk_with_parents(child)
            elif isinstance(value, ast.AST):
                _walk_with_parents(value)

    _walk_with_parents(fn)

    # The three outermost silent-skip sites live on Try statements that are
    # DIRECT children of the function body (the step-2 extract-loop try and the
    # step-3 plan-kickoff try), plus the step-1 stage_task try nested one level
    # inside the extract loop. The narrower bare-OSError handlers inside the
    # plan-kickoff block sit on Try statements buried deeper and are exempt
    # (transitively covered by the step-3 wrapper, per the brief). Restrict the
    # bare-OSError check to top-level Try statements so this test matches its
    # docstring intent rather than demanding an emit on every nested handler.
    top_level_tries = {id(s) for s in fn.body if isinstance(s, ast.Try)}

    missing: list[str] = []
    for handler in ast.walk(fn):
        if not isinstance(handler, ast.ExceptHandler):
            continue
        if not _is_target_except(handler):
            continue
        # Resolve the enclosing Try for this handler.
        enclosing_try = None
        for ancestor in ast.walk(fn):
            if (
                isinstance(ancestor, ast.Try)
                and handler in ancestor.handlers
            ):
                enclosing_try = ancestor
                break
        # Exempt nested bare-OSError handlers (steps 2 & 3 sit on top-level
        # Try statements; deeper bare-OSError handlers are transitively
        # covered by the step-3 wrapper, per the brief).
        is_bare_oserror = (
            isinstance(handler.type, ast.Name) and handler.type.id == "OSError"
        )
        if (
            is_bare_oserror
            and enclosing_try is not None
            and id(enclosing_try) not in top_level_tries
        ):
            continue
        # The step-1 site is the FileNotFoundError-bearing tuple handler on the
        # ``stage_task`` Try. A different nested tuple handler (the marker-read
        # ``(OSError, FileNotFoundError, json.JSONDecodeError, ValueError)``)
        # also contains FileNotFoundError but guards no silent-skip site the
        # brief targets, so exempt any tuple handler whose enclosing Try does
        # not call ``stage_task``.
        if (
            isinstance(handler.type, ast.Tuple)
            and not (
                enclosing_try is not None
                and _subtree_calls(enclosing_try, "stage_task")
            )
        ):
            continue
        # 1) Look inside the handler body itself.
        if any(_emit_in_subtree(stmt) for stmt in handler.body):
            continue
        # 2) Look 3 statements after the enclosing try statement at
        #    its parent body's indentation level.
        if enclosing_try is None:
            missing.append(
                f"line {handler.lineno}: could not locate enclosing Try"
            )
            continue
        parent_info = parent_of.get(id(enclosing_try))
        if parent_info is None:
            # The Try might itself be the top-level body of the
            # function — fall through and report missing.
            missing.append(
                f"line {handler.lineno}: enclosing Try has no parent body"
            )
            continue
        parent_body, try_idx = parent_info
        lookahead = parent_body[try_idx + 1 : try_idx + 4]
        if any(_emit_in_subtree(stmt) for stmt in lookahead):
            continue
        missing.append(
            f"except at line {handler.lineno} "
            f"({ast.unparse(handler.type) if handler.type else 'bare'}) "
            "has no write_jsonl_row companion in its body or within "
            "3 statements after the enclosing try"
        )

    assert not missing, (
        "Silent-skip sites missing companion write_jsonl_row emit:\n  - "
        + "\n  - ".join(missing)
    )
