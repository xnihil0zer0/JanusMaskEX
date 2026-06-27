#!/usr/bin/env python3
"""Analytic root-cause proof for the BLOCKED task ``p11-gate-oracle-perphase``.

This script uses ONLY ``ast`` + ``importlib`` (and a from-source spec import for
the import-clean variant). It does NOT use ``exec``/``eval``/``compile``/
``__import__``. It establishes, with printed evidence, WHY the rolled-back
candidate oracle was rejected with ``verification_failed`` (exit=2), and proves
the difference between a module-scope ImportError (collection-time, exit 2) and
a failing-assertion RED (run-time, exit 1, but importable/collectable).

Run from the JanusMask repo root:
    python _autowork_scratch/diag_p11_oracle_import_red.py
"""
from __future__ import annotations

import ast
import importlib.util
import sys
import textwrap
from pathlib import Path

JM_ROOT = Path("/home/xnihil0zer0/JanusMaskJR")
NGV2_ROOT = Path("/home/xnihil0zer0/NobleGreedv2")
CANDIDATE = JM_ROOT / "state" / "output" / "p11-gate-oracle-perphase.py"
GATE_EXECUTOR = NGV2_ROOT / "ngv2" / "gate_executor.py"
TRANSITION_PLANNER = NGV2_ROOT / "ngv2" / "transition_planner.py"


def _rule(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


# ---------------------------------------------------------------------------
# AST helpers (NO exec/eval/compile/__import__).
# ---------------------------------------------------------------------------
def module_toplevel_names(py_path: Path) -> set[str]:
    """Return the set of top-level def/class/assignment names defined in a module."""
    tree = ast.parse(py_path.read_text(encoding="utf-8"), filename=str(py_path))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    names.add(tgt.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def module_scope_imports_from(py_path: Path, module_prefix: str) -> list[tuple[str, str]]:
    """Return [(module, imported_name)] for MODULE-SCOPE `from <module> import ...`.

    Only module-scope (top of the file body) imports are returned — these are the
    ones that fire at pytest COLLECTION time. ``module_prefix`` filters to the
    module(s) of interest (e.g. 'ngv2.gate_executor').
    """
    tree = ast.parse(py_path.read_text(encoding="utf-8"), filename=str(py_path))
    out: list[tuple[str, str]] = []
    for node in tree.body:  # body == module scope only
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith(module_prefix):
            for alias in node.names:
                out.append((node.module, alias.name))
    return out


# ===========================================================================
# (a) Parse candidate module-scope imports; check each vs LIVE gate_executor.
# ===========================================================================
def part_a() -> dict[str, set[str]]:
    _rule("(a) MODULE-SCOPE `from ngv2.gate_executor import ...` vs LIVE definitions")
    live_names = module_toplevel_names(GATE_EXECUTOR)
    print(f"LIVE {GATE_EXECUTOR}")
    print(f"  top-level definitions: {sorted(live_names)}")

    imports = module_scope_imports_from(CANDIDATE, "ngv2.gate_executor")
    print(f"\nCANDIDATE {CANDIDATE}")
    print(f"  module-scope `from ngv2.gate_executor import`: "
          f"{[n for _, n in imports]}")

    present: set[str] = set()
    absent: set[str] = set()
    for _mod, name in imports:
        if name in live_names:
            present.add(name)
        else:
            absent.add(name)
    print(f"\n  PRESENT in live gate_executor : {sorted(present)}")
    print(f"  ABSENT  in live gate_executor : {sorted(absent)}")

    # Cross-check PHASE_ORDER comes from transition_planner (and exists there).
    tp_names = module_toplevel_names(TRANSITION_PLANNER)
    tp_imports = module_scope_imports_from(CANDIDATE, "ngv2.transition_planner")
    print(f"\n  module-scope `from ngv2.transition_planner import`: "
          f"{[n for _, n in tp_imports]}")
    for _mod, name in tp_imports:
        status = "PRESENT" if name in tp_names else "ABSENT"
        print(f"    {name}: {status} in transition_planner top-level")

    verdict = (
        "  => `run_gates` PRESENT; `TypedTerminal`/`no_template_terminal` ABSENT "
        "(they land later via the SEPARATE impl task p11-gate-table-typed-terminals).\n"
        "  => A module-scope `from ngv2.gate_executor import TypedTerminal, "
        "no_template_terminal` therefore CANNOT bind at import time."
    )
    print("\n" + verdict)
    return {"present": present, "absent": absent}


# ===========================================================================
# (b) Demonstrate the TWO failure modes:
#     - candidate as-is -> ImportError at module LOAD (collection time, exit 2)
#     - import-clean variant -> imports fine, fails only at run-time assertion
# ===========================================================================
def _import_from_source(py_path: Path, mod_name: str):
    """Import a module from a file path using importlib (NO exec/eval/compile).

    ``spec.loader.exec_module`` is the importlib machinery, NOT the builtin
    ``exec``; this is the AST-sanctioned mechanism the brief itself permits.
    """
    spec = importlib.util.spec_from_file_location(mod_name, str(py_path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)  # noqa: this is importlib, not builtin exec
    return module


def part_b() -> None:
    _rule("(b) FAILURE-MODE DIFFERENCE: collection ImportError (exit 2) vs "
          "run-time assertion RED (exit 1)")

    # Put NobleGreedv2 on sys.path so `ngv2.gate_executor` resolves to the LIVE
    # (symbol-incomplete) module.
    if str(NGV2_ROOT) not in sys.path:
        sys.path.insert(0, str(NGV2_ROOT))

    # --- b1: candidate as-is raises ImportError at module LOAD ---------------
    print("\n[b1] Import the candidate oracle AS-IS (module-scope hard import):")
    try:
        _import_from_source(CANDIDATE, "_diag_candidate_asis")
        print("    UNEXPECTED: candidate imported without error")
    except ImportError as exc:
        print(f"    RAISED ImportError at MODULE LOAD (collection-time): {exc}")
        print("    -> pytest reports `collected 0 items / 1 error`, exit code 2.")
    except Exception as exc:  # pragma: no cover - defensive
        print(f"    RAISED {type(exc).__name__} at module load: {exc}")
    finally:
        sys.modules.pop("_diag_candidate_asis", None)

    # --- b2: build a minimal import-clean variant; it collects, fails at run ---
    print("\n[b2] Build a minimal IMPORT-CLEAN variant (module imports only "
          "run_gates + PHASE_ORDER; the not-yet-existing symbol is referenced "
          "INSIDE a test body):")
    clean_src = textwrap.dedent(
        """
        import ngv2.gate_executor as ge
        from ngv2.gate_executor import run_gates
        from ngv2.transition_planner import PHASE_ORDER

        # Module collects cleanly: no hard import of TypedTerminal at module scope.
        def test_run_gates_shape():
            res = run_gates(PHASE_ORDER[0], PHASE_ORDER[1], {})
            assert set(res) == {'advance', 'blocked_by', 'results'}

        def test_typed_terminal_present_RED_by_assertion():
            # RED comes from a FAILING ASSERTION at RUN time, not a load-time import.
            assert hasattr(ge, 'TypedTerminal'), 'TypedTerminal not yet defined'
            tt = getattr(ge, 'TypedTerminal')
            assert tt is not None
        """
    )
    clean_path = JM_ROOT / "_autowork_scratch" / "_diag_import_clean_variant.py"
    clean_path.write_text(clean_src, encoding="utf-8")
    try:
        mod = _import_from_source(clean_path, "_diag_import_clean")
        print("    IMPORT-CLEAN variant imported/collected SUCCESSFULLY "
              "(no module-level ImportError).")
        # Run the shape test (should pass) and the RED-by-assertion test.
        try:
            mod.test_run_gates_shape()
            print("    test_run_gates_shape(): PASSED (run_gates exists & shape ok).")
        except AssertionError as ae:
            print(f"    test_run_gates_shape(): unexpectedly FAILED: {ae}")
        try:
            mod.test_typed_terminal_present_RED_by_assertion()
            print("    test_typed_terminal_present_RED_by_assertion(): "
                  "PASSED (would mean TypedTerminal already exists)")
        except AssertionError as ae:
            print(f"    test_typed_terminal_present_RED_by_assertion(): "
                  f"FAILED at RUN-TIME assertion (RED-but-importable): {ae}")
            print("    -> pytest reports `collected 2 items, 1 failed`, exit code 1.")
    except ImportError as exc:  # pragma: no cover
        print(f"    UNEXPECTED ImportError in clean variant: {exc}")
    finally:
        sys.modules.pop("_diag_import_clean", None)
        try:
            clean_path.unlink()
        except OSError:
            pass

    print("\n  => RED-by-ImportError = exit 2 (collection error, UNIMPORTABLE).")
    print("  => RED-by-assertion   = exit 1 (collected, then a test fails). "
          "IMPORTABLE/collectable.")


# ===========================================================================
# (c) How does the harness treat each? Cite the verification path.
# ===========================================================================
def part_c() -> None:
    _rule("(c) HARNESS RULE — how the verification gate treats each (cited)")
    print(textwrap.dedent(
        """
        Source of truth: harness/orchestrator.py, inside the auto-commit
        verification flow (the function that sets `verify_exit = vproc.returncode`).

        STEP 1 -- run the verification_command in the staging worktree:
          harness/orchestrator.py:3077  `verify_exit = vproc.returncode`
          (exit 2 = pytest collection error / ImportError;
           exit 1 = collected-but-a-test-failed;
           exit 0 = collected & all assertions passed.)

        STEP 2 -- TWO (and only two) escape hatches let a NON-ZERO exit be
        accepted, both folded into `_nm_oracle`:

          (A) harness/orchestrator.py:3105
              `_nm_oracle = _new_module_red_by_absence(task, worktree_root,
                            verify_exit, ...)`
              Defined at orchestrator.py:2111. It returns True ONLY when the
              mutation_target MODULE FILE is ABSENT on disk:
                orchestrator.py:2147-2149
                  `target_file = Path(worktree_root)/(mt.replace('.','/')+'.py')`
                  `if target_file.exists(): return False`
              => For `ngv2.gate_executor` the file EXISTS, so this returns FALSE.
              (Only individual SYMBOLS are missing, not the module — RED-by-absence
              is for a not-yet-created MODULE, not for not-yet-added symbols.)

          (B) harness/orchestrator.py:3111-3115 (only if (A) was False AND
              verify_exit not in (None,0)):
              `from harness.redpair_acceptance import is_fix_forward_redpair,
                load_sibling_tasks`
              `_nm_oracle = is_fix_forward_redpair(task, worktree_root,
                            load_sibling_tasks(state_dir, task, task_id))`
              Defined in harness/redpair_acceptance.py:21. It returns True ONLY
              when there is a PAIRED IMPL sibling in the SAME plan whose
              files_touched includes the oracle's target module file AND whose
              verification_command references the oracle's OWN test file
              (redpair_acceptance.py:42-52). The blocked task has
              `dependencies: []` and the impl `p11-gate-table-typed-terminals`
              lives in a SEPARATE plan/brief, so there is NO in-plan sibling.
              => returns FALSE.

        STEP 3 -- the rollback decision:
          harness/orchestrator.py:3116
            `if verify_exit != 0 and not _nm_oracle:`
                ... `_rollback_rejected_commit(... 'verification_failed')`
                ... ledger event 'verification_failed' (orchestrator.py:3124)
                ... `return False`  (commit rolled back; task -> blocked)

        => For THIS task, `_nm_oracle` is FALSE no matter what (module exists;
           no in-plan paired impl). Therefore ANY non-zero exit -- whether
           exit 2 (ImportError at collection) OR exit 1 (assertion failure) --
           hits the `verification_failed` rollback. The ONLY way to land is
           `verify_exit == 0` (GREEN).

        STEP 4 -- after a GREEN (exit 0) test_authoring commit, the mutation
        (non-vacuity) gate runs:
          harness/orchestrator.py:3131
            `if (_mtt == 'test_authoring' or _mut_specs or _mut_target)
                 and not _nm_oracle:`
          It copies the staging tree, re-runs the vcmd as a baseline (must be
          exit 0 -- orchestrator.py:3180-3181), then STUBS the mutation_target
          module and requires the test to FAIL against the stub
          (`_mvacuous = (_mproc.returncode == 0)`; a vacuous/still-passing test
          is rejected). Ledger events: 'mutation_gate_failed' /
          'mutation_gate_error' / 'mutation_gate_missing'.

        NET RULE (this task): the oracle MUST be IMPORT-CLEAN and GREEN (exit 0)
        the moment it is committed -- i.e. it must NOT hard-import any
        not-yet-existing symbol at module scope. A RED-by-ImportError oracle
        (exit 2) is rejected; here even a RED-by-assertion oracle (exit 1) is
        rejected, because there is no module-absence bypass and no in-plan
        paired impl. (The brief's claim "RED today via ImportError -- EXPECTED"
        is the defect: it is NOT an accepted state for an EXISTING module with
        no paired impl.)
        """
    ))


def main() -> None:
    print("ROOT-CAUSE PROOF: p11-gate-oracle-perphase verification_failed")
    info = part_a()
    part_b()
    part_c()

    _rule("ROOT CAUSE VERDICT")
    absent = sorted(info["absent"])
    print(textwrap.dedent(
        f"""
        The rolled-back oracle imports {absent} at MODULE SCOPE from
        ngv2.gate_executor, but those symbols do NOT yet exist in the live module
        (only `run_gates` does). pytest hits the ImportError at COLLECTION time,
        exits 2, and the harness verification gate rolls the commit back as
        `verification_failed` (orchestrator.py:3116).

        Crucially, BECAUSE the module ngv2.gate_executor already EXISTS on disk,
        the `_new_module_red_by_absence` bypass (orchestrator.py:2111/3105) does
        NOT apply; and BECAUSE there is no in-plan paired impl sibling
        (dependencies=[]), the `is_fix_forward_redpair` bypass
        (redpair_acceptance.py:21 / orchestrator.py:3113) does NOT apply either.
        So `_nm_oracle` is False and EVERY non-zero exit is rejected.

        FIX (brief-level): make the oracle IMPORT-CLEAN -- module scope imports
        ONLY symbols that exist today (`run_gates` from ngv2.gate_executor,
        `PHASE_ORDER` from ngv2.transition_planner). Reference the not-yet-existing
        symbols ({absent} + the per-phase gate callables) INSIDE test bodies via
        `import ngv2.gate_executor as ge` + `assert hasattr(ge, 'TypedTerminal')`,
        so the oracle COLLECTS cleanly and the RED comes from a FAILING ASSERTION.

        NOTE: a RED-by-assertion (exit 1) oracle is ALSO rejected for this task
        as long as there is no in-plan paired impl (no module-absence bypass).
        For the oracle to LAND it must be GREEN (exit 0) once the gate-table impl
        is present, and pass the non-vacuity mutation gate. The import-clean
        pattern is what makes the file committable/collectable at all -- it removes
        the exit-2 collection error so the oracle can reach GREEN after the impl
        lands, instead of being permanently un-collectable.
        """
    ))


if __name__ == "__main__":
    main()
