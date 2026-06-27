"""DEMO 1 — Phase 1 gaming: the authored oracle manufactures the call, so
observe_symbol_execution reports an ORPHAN as REACHED.

Mirrors the brief's OWN prescribed oracle form (Section TASK 1, requirement A):
  "the simplest faithful form: monkeypatch one of run_pipeline's collaborators
   (e.g. harness.orchestrator.smoke_import) to a wrapper that CALLS reached_probe(),
   then drive one run_pipeline iteration ... INSIDE
   with observe_symbol_execution(['reached_probe']) as obs: ...
   Assert obs.executed('reached_probe') is True"

We model a real LIVE_ROOT (`live_root_entrypoint`) plus a brand-new ORPHAN
(`orphan_symbol`) that NO production code calls. The orphan is reached ONLY
because the test author wired it into the monkeypatched collaborator -- exactly
the answer-key-leak shape.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from wire_up_phase1_primitive import observe_symbol_execution


# ---------------------------------------------------------------------------
# A faithful stand-in for harness/orchestrator.py's run_pipeline:
#   - it is the real LIVE_ROOT
#   - it calls a *collaborator* (smoke_import) the way run_pipeline does
#   - it has ZERO reference to orphan_symbol anywhere in its real body
# ---------------------------------------------------------------------------

def smoke_import(*a, **k):
    """A real production collaborator that run_pipeline calls."""
    return None


def live_root_entrypoint(config, state_dir):
    """THE LIVE_ROOT. Models run_pipeline's one-iteration body.

    NOTE: nowhere does this function (or anything it really calls in prod)
    reference `orphan_symbol`. orphan_symbol is a genuine orphan.
    """
    # ... real work ...
    smoke_import(config)   # collaborator call site
    # ... more real work ...
    return 0


# ---------------------------------------------------------------------------
# The NEW orphan symbol added by some leaf. ZERO real callers anywhere.
# ---------------------------------------------------------------------------

def orphan_symbol():
    """A brand-new top-level callable with no live caller. Pure orphan."""
    return "i ran but nobody real called me"


# ---------------------------------------------------------------------------
# The GAMING oracle (authored by the pipeline's test_authoring stage), built
# EXACTLY per the brief's prescribed 'simplest faithful form'.
# ---------------------------------------------------------------------------

def gaming_oracle():
    import wire_up_phase1_primitive as _p  # noqa

    # The test author monkeypatches a real collaborator to a wrapper that
    # CALLS the orphan. This is the brief's literal recommendation.
    real_smoke = smoke_import

    def smoke_import_wrapper(*a, **k):
        orphan_symbol()          # <-- the manufactured call. NOT a prod call site.
        return real_smoke(*a, **k)

    g = globals()
    g['smoke_import'] = smoke_import_wrapper
    try:
        with observe_symbol_execution(['orphan_symbol']) as obs:
            live_root_entrypoint(config={}, state_dir="/tmp")  # drive the LIVE_ROOT
        return obs.executed('orphan_symbol')
    finally:
        g['smoke_import'] = real_smoke


if __name__ == "__main__":
    reached = gaming_oracle()
    print("=== DEMO 1: Phase 1 observe_symbol_execution under the brief's prescribed oracle ===")
    print(f"orphan_symbol has ZERO real callers in production code.")
    print(f"The oracle monkeypatched smoke_import to call it (brief's 'simplest faithful form').")
    print(f"obs.executed('orphan_symbol') = {reached}")
    if reached:
        print("VERDICT: GAMED -- an ORPHAN is certified REACHED because the test author")
        print("         manufactured the call inside a monkeypatched collaborator.")
        print("         observe_symbol_execution cannot tell a real prod call site from")
        print("         a test-installed mock wrapper -- both produce a 'call' frame event.")
    else:
        print("VERDICT: not reached (gate held)")
