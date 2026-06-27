---
name: factory-new-module-wireup-gates
description: Three gates every NEW-module factory leaf must satisfy (plan-shape + wire_up acceptance) and the anchor recipe to break the orphan_unwired deadlock
metadata: 
  node_type: memory
  type: project
  originSessionId: 96305960-8009-4b2d-b010-500dea980a39
---

Authoring a brief whose leaf CREATES A NEW .py module hits three real gates (discovered 2026-06-12 building the WebUI typed-config epic). Allowlisting a brief alone does NOT build it — the daemon auto-plans ONE unplanned eligible brief per heartbeat iteration (newest brief mtime first; `touch` to reorder), then the brief-dep-gate sequences build by declared `dependencies:`.

GATE 1 — plan_validator `missing_wiring_oracle` (harness/planner/plan_validator.py:225-243): a new-module leaf's PLAN must include a paired `test_authoring` task whose top-level `mutation_target` (BARE DOTTED module, e.g. `harness.model_backends`) resolves to a `.py` in the impl task's `files_touched`. That mutation-gated oracle IS the accepted plan-time wiring proof. Encode this in the brief's `# Required plan shape`.

GATE 2 — plan_validator `missing_integration_test` (line 278-284): each impl task needs ≥1 integration_test UNLESS the task's `non_goals` contains the literal word "integration".

GATE 3 — `_sensitive_glob_violations`: tasks editing `harness/**` or `config/**` must be `meta_task_type: harness_self_fix` (the only exempt type) + operator approval. `tools/**` is not sensitive. `_NEVER_AUTO_APPROVE` (orchestrator.py/autowork_daemon.py/paths.py/git_integration.py/selfheal.py/agent_jail.py/...) is editable by NO task type — owner hand-edit only.

GATE 4 (ACCEPTANCE) — wire_up_gate `orphan_unwired` (harness/wire_up.py `check_wired`, config `autowork.wire_up_gate: true`): at acceptance the built module must be reachable via the import graph from `LIVE_ROOTS = harness/orchestrator.py, orchestrator_worker.py, autowork_daemon.py, planner/cli.py` — OR have a transitive live importer — OR be referenced by explicit `.py`-path in `config/**` (CONFIG_WIRED; a `-m dotted` entry does NOT match on a SELF build, and a CONFIG_WIRED module is NOT a root so its imports don't reach siblings — each module needs its own config line). NOTE: `tools/webui_*` and `harness/config_loader.py` are NOT root-reachable.

DEADLOCK + FIX: a standalone module orphans because its only importer is a dep-gated downstream leaf. Break it by wiring the module, IN ITS OWN LEAF SCOPE, into a root-reachable, non-deny-listed `harness/**` anchor. Verified anchor: **`harness/control_gate.py`** (`check_wired` → wired=True, imported by orchestrator.py root; not deny-listed; harness_self_fix-editable). Recipe: impl `files_touched` includes the anchor; add an additive module-level import + a trailing new function/use (never edit existing class methods); the oracle asserts `harness.wire_up.check_wired(repo_root, '<rel>.py').wired is True`. Chain modules: A←B←control_gate←orchestrator. See [[implementation-is-not-wired-defect]], [[ngv2-wireup-epic-complete]].
