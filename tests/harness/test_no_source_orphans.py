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
    # with final, evidence-backed justifications rather than guessed-at wiring or
    # an unsafe deletion of tested code.
    "harness/config_loader.py":
        "tested-but-unwired: HooksConfig / get_batch_execution_config / ConfigError API "
        "exercised by tests/hooks/unit/test_hooks_config*.py etc., but imported by no live "
        "module (only an injected `config_loader` DI param in hooks_equivalence). Owner "
        "decision: wire as the live hooks-config loader, or retire if superseded.",
    "harness/planner/oracle_attach.py":
        "tested-but-unwired: attach_oracle / task_needs_oracle API exercised by "
        "tests/adversarial/test_oracle_attach.py, but no live caller (the live planner injects "
        "oracle sources via plan_normalizer._inject_oracle_sources). Owner decision: wire into "
        "the planner, or retire as superseded.",
    "tools/brief_status.py":
        "tested-but-unwired: classify_briefs / status_of API exercised by "
        "tests/tools/test_brief_status.py, but no live importer and no __main__ (the live brief "
        "classifier is harness/brief_status.py). Owner decision: wire as a tool entrypoint, or "
        "retire as a superseded duplicate.",
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
