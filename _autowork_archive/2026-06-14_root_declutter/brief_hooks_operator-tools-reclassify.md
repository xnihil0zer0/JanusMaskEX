---
interfaces: "Consumes frozen (do not modify the signatures): `check_wired(repo_root, module_rel, *, roots, exclude) -> WireResult`; `discover_live_roots(repo_root) -> list[str]`; `sweep_modules(repo_root, *, roots) -> SweepReport` (the only permitted edit to wire_up.py is appending `tools/` to its EXCLUDE source-set tuple); `SweepReport.wired/.config_wired/.orphan_cluster/.orphan`. `KNOWN_ORPHAN_ALLOWLIST` keys removed by this category: tools/brief_status.py, tools/webui_auth.py, tools/webui_control.py."
---

# Title

Wave-2 Remediation — operator-tools-reclassify (tools/{brief_status,webui_auth,webui_control}.py)

# Scope

Discharge the 3 operator-tools orphans — tools/brief_status.py, tools/webui_auth.py, tools/webui_control.py — as RECLASSIFY. These are standalone operator CLIs (with `if __name__ == '__main__'` entrypoints), not live-import-path code. Triage the live tree to confirm each carries a `__main__` entry and has no static/dynamic importer, then apply the recommended remediation: add `tools/` to the source-set EXCLUDE tuple consumed by `sweep_modules` in harness/wire_up.py (a single additive edit) so all three leave the classified set entirely, OR if the EXCLUDE approach is rejected, confirm each `__main__` entry and rewrite its allowlist justification to a final, evidence-backed reason. Each remediated module's key is deleted from KNOWN_ORPHAN_ALLOWLIST in the same leaf that lands the production edit, so the guard tightens atomically. Decompose into per-module leaves OR a single EXCLUDE leaf that covers all three, as triage dictates. Owner gate stays paused; this child is itself further planned through the leaf pipeline.

# Non-Goals

Do NOT reimplement check_wired, sweep_modules, discover_live_roots, or the regression guard — only edit the EXCLUDE tuple/allowlist additively. Do NOT WIRE these onto the live import path (they are operator CLIs, not runtime code) and do NOT REMOVE them. No new agent/model/network/subprocess. No silent allowlist growth — keys only shrink or get rewritten justifications, never added. No 'pending Wave-2' justifications. Do not touch the overseer, hook-rpc, rebuild, narrow-fuzz, or misc-harness modules or their allowlist keys. Do not author oracles or dispatch builds at this epic level — decomposition only.

# Inputs

ALREADY BUILT (verified at HEAD 6744b1a) — consume, do not rebuild: harness/wire_up.py exposing `check_wired(repo_root, module_rel, *, roots, exclude) -> WireResult`, `discover_live_roots(repo_root) -> list[str]`, `sweep_modules(repo_root, *, roots) -> SweepReport` with the EXCLUDE source-set tuple, and `SweepReport` (`.wired/.config_wired/.orphan_cluster/.orphan/.to_dict()/.to_markdown()`). tests/harness/test_no_source_orphans.py exposing `KNOWN_ORPHAN_ALLOWLIST: dict[module_rel, justification]` baselining the 36 orphans, including keys `tools/brief_status.py`, `tools/webui_auth.py`, `tools/webui_control.py`. The live tools/ modules to triage: tools/brief_status.py, tools/webui_auth.py, tools/webui_control.py. Note tools/** writes are protected-path (scripts/tools policy) and route through planner→stage→worker.

# Deliverables

A RECLASSIFY remediation sub-tree for tools/brief_status.py, tools/webui_auth.py, tools/webui_control.py. Each leaf names a pre-committed RED edge-asserting oracle as its verification_command (`python -m pytest tests/<area>/<oracle>.py -q`). For the EXCLUDE approach, the oracle asserts `tools/*` no longer appear in any SweepReport class (wired/config_wired/orphan_cluster/orphan) from `sweep_modules(repo_root, roots=discover_live_roots(repo_root))` AND the guard passes with the three `tools/...` allowlist keys removed. For the allowlist-rewrite approach, the oracle asserts each module's `__main__` entry exists and the guard passes with the rewritten justification. Each leaf removes its module's KNOWN_ORPHAN_ALLOWLIST key in the same leaf as the production edit. End state for this category: the three tools modules are no longer orphan-classified and their allowlist keys are gone, guard green.
