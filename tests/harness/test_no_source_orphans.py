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
    # --- overseer subsystem: config/service-wired (reached via the web service
    #     + the P6 PreToolUse hook), not statically import-reachable from a live
    #     root. Wave-2: add a real importer from a live-reachable module, or
    #     reclassify the subsystem entrypoints as roots. ---
    "overseer/driver.py": "overseer subsystem; config/service-wired, pending Wave-2 wiring",
    "overseer/gate_runner.py": "overseer subsystem; config/service-wired, pending Wave-2 wiring",
    "overseer/mode_gate.py": "overseer subsystem; config/service-wired, pending Wave-2 wiring",
    "overseer/mode_prompts.py": "overseer subsystem; config/service-wired, pending Wave-2 wiring",
    "overseer/model_select.py": "overseer subsystem; config/service-wired, pending Wave-2 wiring",
    "overseer/modes.py": "overseer subsystem; config/service-wired, pending Wave-2 wiring",
    "overseer/procedure_artifacts.py": "overseer subsystem; config/service-wired, pending Wave-2 wiring",
    "overseer/procedure_state.py": "overseer subsystem; config/service-wired, pending Wave-2 wiring",
    "overseer/service.py": "overseer subsystem; config/service-wired, pending Wave-2 wiring",
    "overseer/session_store.py": "overseer subsystem; config/service-wired, pending Wave-2 wiring",
    "overseer/tmux_chat.py": "overseer tmux backend; config/service-wired, pending Wave-2 wiring",
    "overseer/tmux_driver.py": "overseer tmux backend; config/service-wired, pending Wave-2 wiring",
    "overseer/tmux_seams.py": "overseer tmux backend; config/service-wired, pending Wave-2 wiring",
    "overseer/tmux_session.py": "overseer tmux backend; config/service-wired, pending Wave-2 wiring",
    "overseer/tmux_transcript.py": "overseer tmux backend; config/service-wired, pending Wave-2 wiring",
    "overseer/transcript.py": "overseer subsystem; config/service-wired, pending Wave-2 wiring",
    "overseer/turn_runner.py": "overseer FSM turn runner; reached via web service, pending Wave-2 wiring",
    "overseer/web_api.py": "overseer web API; reached via the web service, pending Wave-2 wiring",
    # --- hook RPC handlers: dispatched dynamically by the hook router/inbox, not
    #     a static import edge. Wave-2: add the dispatch edge or reclassify. ---
    "harness/hooks/rpc/clarification.py": "hook RPC handler dispatched dynamically, pending Wave-2 wiring",
    "harness/hooks/rpc/error_report.py": "hook RPC handler dispatched dynamically, pending Wave-2 wiring",
    "harness/hooks/rpc/submit_code.py": "hook RPC handler dispatched dynamically, pending Wave-2 wiring",
    "harness/hooks/rpc/submit_plan_draft.py": "hook RPC handler dispatched dynamically, pending Wave-2 wiring",
    "harness/hooks/rpc/submit_reconciliation.py": "hook RPC handler dispatched dynamically, pending Wave-2 wiring",
    # --- rebuild engine: invoked via the rebuild loop/CLI. Wave-2: wire or reclassify. ---
    "harness/rebuild/decompose.py": "rebuild-engine module via the rebuild loop/CLI, pending Wave-2 wiring",
    "harness/rebuild/harvest.py": "rebuild-engine module via the rebuild loop/CLI, pending Wave-2 wiring",
    "harness/rebuild/strip.py": "rebuild-engine module via the rebuild loop/CLI, pending Wave-2 wiring",
    "harness/rebuild/venv.py": "rebuild-engine module via the rebuild loop/CLI, pending Wave-2 wiring",
    # --- narrow-fuzz plugins: registered dynamically. Wave-2: wire or reclassify. ---
    "harness/narrow_fuzz/_registry.py": "narrow-fuzz plugin registry, dynamically loaded, pending Wave-2 wiring",
    "harness/narrow_fuzz/validation.py": "narrow-fuzz validation plugin, dynamically loaded, pending Wave-2 wiring",
    # --- other harness modules pending triage. ---
    "harness/agy_pool.py": "agy worker pool (default-OFF subsystem), pending Wave-2 wire-or-remove",
    "harness/config_loader.py": "config loader, pending Wave-2 wire-or-reclassify",
    "harness/control_gate.py": "operator control gate, pending Wave-2 wire-or-reclassify",
    "harness/planner/oracle_attach.py": "planner oracle-attach helper, pending Wave-2 wire-or-remove",
    # --- operator CLI tools: not part of the live import path. Wave-2:
    #     reclassify (exclude tools/ from the source set) or wire. ---
    "tools/brief_status.py": "operator CLI tool, not on the live import path, pending Wave-2 reclassify",
    "tools/webui_auth.py": "operator CLI tool, not on the live import path, pending Wave-2 reclassify",
    "tools/webui_control.py": "operator CLI tool, not on the live import path, pending Wave-2 reclassify",
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
