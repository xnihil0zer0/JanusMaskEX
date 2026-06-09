---
dependencies:
  - "rebuild-engine-wiring"
---

# Title

Remediate Narrow-Fuzz and Misc Harness

# Scope

Remediate 6 modules: narrow_fuzz/{_registry,validation}.py, harness/agy_pool.py, harness/config_loader.py, harness/control_gate.py, harness/planner/oracle_attach.py. Apply WIRE, REMOVE, or RECLASSIFY verdict to each. Remove their keys from KNOWN_ORPHAN_ALLOWLIST.

# Non-Goals

Do not remove any module without positive proof of deadness. Do not add inert imports.

# Inputs

narrow_fuzz/*.py, harness/agy_pool.py, harness/config_loader.py, harness/control_gate.py, harness/planner/oracle_attach.py, tests/harness/test_no_source_orphans.py.

# Deliverables

Verdicts applied (WIRE/REMOVE/RECLASSIFY) for the 6 modules; allowlist keys removed; test_no_source_orphans.py passes.
