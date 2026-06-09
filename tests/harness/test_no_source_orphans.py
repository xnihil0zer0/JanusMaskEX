"""Wire-up-sweep leaf 4: the durable regression guard.

This committed test is the load-bearing deliverable of the wire-up sweep. It
runs the live classifier (``sweep_modules`` seeded from ``discover_live_roots``)
over the REAL source tree and asserts that NO *new* confirmed orphan appears
beyond an explicit, reviewed baseline allowlist. The instant a freshly-added
module lands unwired (or an edit orphans an existing one) outside the allowlist,
this test fails -- so the orphan class proven by the Wave-1 audit cannot
silently regrow.

A "confirmed orphan" is a source module the sweep classifies ORPHAN (zero
inbound importers, no config reference) or ORPHAN_CLUSTER (inbound importers
exist but none is reachable from a live root).

ALLOWLIST POLICY: every entry is a module the Wave-1 audit found already
unwired, each with a one-line justification and an implicit Wave-2 remediation
obligation (wire it into a live importer, remove it as dead, or reclassify it as
a legitimate entrypoint/config-wired surface). As Wave-2 remediates a module,
delete its allowlist entry so the guard tightens. Adding a NEW entry requires a
human decision recorded here -- it is never automatic.
"""
from __future__ import annotations

from pathlib import Path

from harness.wire_up import discover_live_roots, sweep_modules

REPO_ROOT = Path(__file__).resolve().parents[2]

# Baseline of confirmed orphans found by the Wave-1 audit (2026-06-09), each
# justified. Wave-2 shrinks this set; nothing may be added without a recorded
# human decision.
KNOWN_ORPHAN_ALLOWLIST: dict[str, str] = {
    # Wave-2 reconciliation (2026-06-09): leaf A (import-tracer accuracy fix,
    # commit 154fa38) made 33 of the original 36 baseline entries classify WIRED
    # -- they were never broken; the tracer simply could not see their
    # `from PACKAGE import SUBMODULE` / package-`__init__` import edges. Those 33
    # keys are removed below. The 3 that remain are GENUINELY not on the live
    # import path: each is implemented AND has a dedicated test, but no live
    # (non-test) module imports it. Whether each should be WIRED to a live
    # consumer or RETIRED is an owner design decision (each looks like a
    # superseded alternative to a live module), so they are reclassified here
    # with evidence-backed justifications rather than guessed-at wiring or an
    # unsafe deletion of tested code. All three are the SAME situation:
    # implemented + self-tested + zero live importer (their tests cover only
    # their own functions, so the coverage would vanish cleanly with the module);
    # each is a retire-vs-keep judgment call, not a wiring task.
    "harness/config_loader.py":
        "Tested-but-unwired (reviewed 2026-06-09): a coherent config-schema/validation module "
        "(HOOKS_ALLOWED_VERBS / HooksConfig / get_hooks_config / get_batch_execution_config / "
        "ConfigError). No live (non-test) module imports it -- the runtime reads config inline "
        "(config.get('batch_execution') in diff_fuzzer.py/sandbox.py; hooks_equivalence.py has its "
        "own loader). The hooks tests that import it exercise its OWN functions (self-coverage). "
        "VERDICT KEEP as a judgment call: worth retaining as the canonical config schema / future "
        "consolidation target. By the strict wired definition it is as deletable as the others.",
    "harness/planner/oracle_attach.py":
        "Tested-but-unwired (reviewed 2026-06-09): attach_oracle generates an oracle by stripping "
        "an EXISTING target module's source (test_author.author_oracle:71), so it only applies to "
        "the rebuild flow over existing modules -- and harness/rebuild/loop.py already does that "
        "inline via test_author (loop.py:364). It cannot wire into the main brief-planner (which "
        "builds not-yet-existent modules, no source to strip). Redundant; retire candidate.",
    "overseer/actions.py":
        "Tested-but-unwired (added 2026-06-09 by adversarial review): no live importer "
        "(only tests/overseer/test_actions.py). NOTE: sweep_modules currently MIS-classifies this "
        "as CONFIG_WIRED, not ORPHAN, because _grep_config whole-word-matches the unrelated "
        "\"actions\" JSON key in config/gemini_settings.json -- a false CONFIG_WIRED that MASKS the "
        "orphan (see WIRE_UP_HANDOFF.md open items: fix _grep_config to not match arbitrary config "
        "keys). Listed here so the true residual set is complete. Retire-vs-keep, same as above.",
}


def _confirmed_orphans() -> set[str]:
    report = sweep_modules(REPO_ROOT, roots=discover_live_roots(REPO_ROOT))
    return set(report.orphan) | set(report.orphan_cluster)


def test_no_new_source_orphans():
    """No confirmed orphan exists outside the reviewed baseline allowlist."""
    confirmed = _confirmed_orphans()
    new_orphans = sorted(confirmed - set(KNOWN_ORPHAN_ALLOWLIST))
    assert not new_orphans, (
        "New unwired source module(s) detected (orphan or orphan-cluster) that are "
        "not in the reviewed allowlist. Wire each into a live importer, remove it, "
        "or -- with a recorded decision -- add it to KNOWN_ORPHAN_ALLOWLIST with a "
        f"justification:\n  " + "\n  ".join(new_orphans)
    )
