---
name: implementation-is-not-wired-defect
description: "Systemic defect — pipeline \"implementation\" leaves produce orphaned modules (unit-green but never wired into the live path); \"BUILT\" was laundered to mean \"module exists + isolated oracle passes\"."
metadata: 
  node_type: memory
  type: feedback
  originSessionId: a23ff3a8-d056-4fc9-b2f7-7807d4274725
---

The user (2026-06-08) was angry that requests for "implementation" repeatedly produced modules that exist + pass an oracle but are **never wired into the running system**. This is structural, not a one-off:
- The pipeline's grain is the isolated leaf (one new file + one oracle, jailed blind worker). Easy/reliable leaf = "create module X." That lands clean.
- The oracle tests the UNIT in isolation (injected seams). It does NOT assert that any live caller imports/invokes X. So oracle-green = unit-green, NOT wired-green → a false "done" signal.
- The wiring leaf is the hard one (touches deny-listed harness/** big functions that AST-truncate; needs harness_self_fix + decision file) → it gets deferred or never authored. The orphan is the predictable residue.
- Prior sessions + Claude wrote "✅ BUILT" in MEMORY/briefs the moment module+isolated-oracle existed, laundering "compiles & unit-passes" into "feature works."

Confirmed orphans found in ONE session (2026-06-08): `harness/agy_pool.py` (built, ZERO importers — Pillar B of agent_exec_substrate unreachable); the procedure-gates FSM (`gates.py`/`procedure.py` 55 green, but `turn_runner`'s `gate_runner` defaults None and `service.py` passes nothing → FSM never runs in production; 19/20 phase gate-labels have no backing function); the `claude-tmux` backend (full tmux chain wired into turn loop but `web_api.py` hard-codes `agent_backend='claude'` → unselectable).

**Why:** unit-of-work and unit-of-verification both stop at the module boundary; integration is the dropped step.

**How to apply:** Define "unfinished" as **"feature not reachable/used on the live path,"** NOT "module file missing." When building, every feature's oracle MUST assert WIRING/reachability (the live caller actually invokes it) or be an e2e test that fails if the module is orphaned. Never call anything BUILT until an integration oracle is green. When auditing brief status, grep for importers of each built module before trusting "BUILT". Related: [[triple-lock-was-claude-invented]], [[never-hand-edit-production-outside-pipeline]].
