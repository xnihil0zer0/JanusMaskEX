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
    # `from PACKAGE import SUBMODULE` / package-`__init__` import edges. That left
    # 3 genuinely-unwired residuals (each implemented + self-tested + zero live
    # importer). Wave-2 follow-up (2026-06-09, WIRE_UP_HANDOFF.md §7) resolved the
    # retire-vs-keep call on all three:
    #   * harness/planner/oracle_attach.py -> RETIRED (git rm; it could not be
    #     wired -- attach_oracle only strips EXISTING module source, which the
    #     rebuild loop already does inline; redundant for the brief-planner).
    #   * overseer/actions.py -> RETIRED (git rm; no live importer. It had been
    #     MASKED as a false CONFIG_WIRED by a _grep_config bug, since fixed at
    #     commit 9eebee1 so it correctly surfaced as ORPHAN before removal).
    #   * harness/config_loader.py -> KEPT (judgment call) -- the one entry below.
    "harness/config_loader.py":
        "Tested-but-unwired (reviewed 2026-06-09): a coherent config-schema/validation module "
        "(HOOKS_ALLOWED_VERBS / HooksConfig / get_hooks_config / get_batch_execution_config / "
        "ConfigError). No live (non-test) module imports it -- the runtime reads config inline "
        "(config.get('batch_execution') in diff_fuzzer.py/sandbox.py; hooks_equivalence.py has its "
        "own loader). The hooks tests that import it exercise its OWN functions (self-coverage). "
        "VERDICT KEEP as a judgment call: worth retaining as the canonical config schema / future "
        "consolidation target. By the strict wired definition it is as deletable as the others.",
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
