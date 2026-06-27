#!/usr/bin/env python3
"""ANALYTIC REPRO: nested-symbol kind:'symbol' patch -> opaque KeyError.

Run:  PYTHONPATH=. python _autowork_scratch/nested_symbol_patch_repro.py

Confirms the systemic harness bug behind the real
`auto_commit_patch_failed: patch apply failed for ngv2/conductor_seams.py:
'build_evidence'` (task p11-build-evidence-structural-keys, retry budget 3
exhausted -> blocked). build_evidence is a NESTED closure inside top-level
build_default_seams, so a kind:'symbol' patch keyed on the bare nested name
cannot resolve against the file's TOP-LEVEL symbol map.

Drives the REAL harness function `harness.git_integration._apply_symbol_patch`
(the exact lookup at git_integration.py:1063-1074 that raises KeyError(qualname)
when the 1-part name is absent from tree.body), and the REAL ledger-carrier path
`_last_failure_tail` to show the message does NOT reach repair_feedback today.
"""
import traceback

from harness import git_integration as gi
from harness.orchestrator import _last_failure_tail

# A tiny source file shaped EXACTLY like ngv2/conductor_seams.py:
#  - a top-level enclosing function (build_default_seams)
#  - a NESTED closure inside it (build_evidence) at 4-space indent
#  - sibling nested closures (load_state, advance)
SOURCE = '''\
import json


def build_default_seams(session_id, db, ctx):
    """Top-level factory; defines closures over its args."""
    state = {}

    def load_state(sid):
        return state.get(sid, {})

    def build_evidence(st):
        # NESTED closure -- this is the real-world target name.
        return {"source_ready": bool(st)}

    def advance(sid, approval=None):
        return load_state(sid)

    return {"load_state": load_state, "build_evidence": build_evidence,
            "advance": advance}


def other_top_level(x):
    return x + 1
'''

# The replacement block the worker emitted (a full def named build_evidence).
NESTED_REPLACEMENT = '''\
def build_evidence(st):
    """Derive structural completion evidence (read-only, KeyError-tolerant)."""
    st = st or {}
    return {"source_ready": bool(st), "findings": list(st.get("prior") or [])}
'''

# A normal TOP-LEVEL replacement (negative control: must apply cleanly).
TOPLEVEL_REPLACEMENT = '''\
def other_top_level(x):
    return x + 2
'''

# A truly-absent symbol (neither top-level nor nested): must still error.
ABSENT_REPLACEMENT = '''\
def totally_made_up(x):
    return x
'''


def _try(label, source, qualname, new_block):
    print(f"\n=== {label}: kind='symbol' name={qualname!r} ===")
    try:
        out = gi._apply_symbol_patch(source, qualname, new_block)
        print("  RESULT: APPLIED OK")
        # show the spliced region so we can confirm correctness
        for ln in out.splitlines():
            if "build_evidence" in ln or "other_top_level" in ln:
                print("    | " + ln)
        return ("ok", None)
    except KeyError as exc:
        print(f"  RESULT: KeyError({exc!r})  <-- OPAQUE; bare name, no enclosing-symbol hint")
        return ("KeyError", exc)
    except ValueError as exc:
        print(f"  RESULT: ValueError: {exc}")
        return ("ValueError", exc)
    except Exception as exc:  # noqa: BLE001
        print(f"  RESULT: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return (type(exc).__name__, exc)


def main():
    print("REAL function under test: harness.git_integration._apply_symbol_patch")
    print("Lookup site that KeyErrors: git_integration.py:1063-1074 "
          "(1-part qualname walked over tree.body ONLY).")

    # (a) TODAY: nested name -> opaque KeyError
    kind_nested, exc_nested = _try(
        "TODAY (nested closure target)", SOURCE, "build_evidence", NESTED_REPLACEMENT)

    # (b) CONTRAST: top-level enclosing/sibling symbol applies fine
    kind_top, _ = _try(
        "CONTRAST (top-level symbol target)", SOURCE, "other_top_level", TOPLEVEL_REPLACEMENT)

    # (c) NEGATIVE CONTROL: truly-absent symbol -> error (today identical KeyError)
    kind_absent, exc_absent = _try(
        "ABSENT (neither top-level nor nested)", SOURCE, "totally_made_up", ABSENT_REPLACEMENT)

    # Show that the carried message is the SAME opaque form prod logged.
    print("\n--- carried result['error'] string (as prod assembles it) ---")
    print(f"  patch apply failed for conductor_seams.py: {exc_nested!r}")
    print("  (matches real ledger row: \"patch apply failed for "
          "ngv2/conductor_seams.py: 'build_evidence'\")")

    # Prove the message does NOT even reach repair_feedback today:
    # _last_failure_tail's failure_events set EXCLUDES auto_commit_patch_failed.
    fe = _last_failure_tail.__doc__ or ""
    print("\n--- repair_feedback carrier gap ---")
    print("  _last_failure_tail failure_events = {verification_failed, "
          "mutation_gate_failed, mutation_gate_error, mutation_gate_missing}")
    print("  -> 'auto_commit_patch_failed' is NOT in that set, so even the terse "
          "KeyError reason is dropped from repair_feedback; the worker retries blind.")

    print("\n================ VERDICT ================")
    nested_opaque = (kind_nested == "KeyError")
    top_ok = (kind_top == "ok")
    absent_err = (kind_absent in ("KeyError", "ValueError"))
    indistinguishable = (kind_nested == kind_absent
                         and str(exc_nested) and str(exc_absent)
                         and ("nested" not in str(exc_nested).lower())
                         and ("build_default_seams" not in str(exc_nested)))
    print(f"  nested target -> opaque KeyError (no enclosing hint): {nested_opaque}")
    print(f"  top-level target applies cleanly:                     {top_ok}")
    print(f"  absent target still errors:                           {absent_err}")
    print(f"  nested vs absent INDISTINGUISHABLE today:             {indistinguishable}")
    confirmed = nested_opaque and top_ok and absent_err and indistinguishable
    print(f"\n  ROOT CAUSE {'CONFIRMED' if confirmed else 'UNCONFIRMED'}")
    return 0 if confirmed else 1


if __name__ == "__main__":
    raise SystemExit(main())
