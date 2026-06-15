---
interfaces: "Consumes frozen: `check_wired(repo_root, module_rel, *, roots, exclude) -> WireResult`; `discover_live_roots(repo_root) -> list[str]`; `sweep_modules(repo_root, *, roots) -> SweepReport`; `SweepReport.wired/.config_wired/.orphan_cluster/.orphan`. WIRE oracle contract: `check_wired(repo_root, m, roots=discover_live_roots(repo_root)).wired is True`. `KNOWN_ORPHAN_ALLOWLIST` keys removed by this category: harness/rebuild/decompose.py, harness/rebuild/harvest.py, harness/rebuild/strip.py, harness/rebuild/venv.py."
---

# Title

Wave-2 Remediation — rebuild-engine-wiring (harness/rebuild/{decompose,harvest,strip,venv}.py)

# Scope

Discharge the 4 rebuild-engine orphans — harness/rebuild/decompose.py, harvest.py, strip.py, venv.py. These are invoked via the rebuild loop/CLI (harness/rebuild/loop.py, which is config-referenced). Triage the live tree per module: determine whether loop.py (or a reachable sibling already on a live root) should statically import and call each module (WIRE — the wiring leaf was never authored), or whether each is a genuine CLI-only / dynamically-invoked surface (RECLASSIFY). If WIRE: add the missing import/call edge from loop.py or a reachable sibling so the rebuild step actually runs, proven by a behavior assertion driving the live rebuild path — not an inert import. If RECLASSIFY: ensure the config/** reference resolves so the module classifies CONFIG_WIRED, or rewrite its allowlist justification to the final CLI-only reason. One leaf per module. Owner gate stays paused.

# Non-Goals

Do NOT reimplement check_wired, sweep_modules, discover_live_roots, the guard, or the rebuild loop. No inert wiring — a WIRE leaf must make the rebuild step run (behavior assertion). No REMOVE unless a module is positively proven dead (no static OR dynamic importer, no `__main__`, not config-referenced) with a green suite; ambiguity RECLASSIFIES. No new agent/model/network/subprocess in deterministic parts. No silent allowlist growth; no 'pending Wave-2' justifications. Do not touch overseer, hook-rpc, narrow-fuzz, misc-harness, or tools modules or their allowlist keys. Decomposition only.

# Inputs

ALREADY BUILT (verified at HEAD 6744b1a) — consume, do not rebuild: harness/wire_up.py exposing `check_wired(repo_root, module_rel, *, roots, exclude) -> WireResult`, `discover_live_roots(repo_root) -> list[str]`, `sweep_modules(repo_root, *, roots) -> SweepReport`, `SweepReport` (`.wired/.config_wired/.orphan_cluster/.orphan`). tests/harness/test_no_source_orphans.py exposing `KNOWN_ORPHAN_ALLOWLIST` baselining the 36, including keys harness/rebuild/decompose.py, harvest.py, strip.py, venv.py. Live modules to triage: harness/rebuild/{decompose,harvest,strip,venv}.py plus harness/rebuild/loop.py (the config-referenced loop/CLI entry) and config/** references. harness/** writes are protected-path ⇒ meta_task_type=harness_self_fix + operator decision file.

# Deliverables

A remediation sub-tree (one leaf per module) resolving decompose/harvest/strip/venv to WIRE or RECLASSIFY. Each leaf names a pre-committed RED edge-asserting oracle. A WIRE leaf's oracle asserts `check_wired(repo_root, m, roots=discover_live_roots(repo_root)).wired is True` with loop.py (or the reachable sibling) named as the new importer, PLUS a behavior assertion that the rebuild step fires via the live path. A RECLASSIFY leaf's oracle asserts the module classifies CONFIG_WIRED or the guard passes with the rewritten justification. Each leaf edits ONE production file plus deletes/rewrites its KNOWN_ORPHAN_ALLOWLIST key atomically. End state: the four rebuild modules are no longer orphan-classified (or are CONFIG_WIRED/justified), allowlist keys removed, guard green.
