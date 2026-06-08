---
interfaces: "harness/config.yaml: add an ADDITIVE default-OFF overseer: block (enabled:false, default_mode:observe, default_backend:claude, models.claude:[opus,sonnet,haiku], store_path, unlock_policy) loaded by harness.orchestrator.load_config, without disturbing the existing autowork:/synthesis: blocks or any other key."
meta_task_type: harness_self_fix
---

# Title

EDIT harness/config.yaml — add a default-OFF overseer: block

# Scope

ONE leaf (do NOT split). A THIN ADDITIVE edit to `harness/config.yaml` against its
pre-committed RED oracle `tests/overseer/test_config_overseer.py` (AUTHORITATIVE — it loads the
REAL config via `harness.orchestrator.load_config` and asserts the overseer block + fail-safe
defaults). The overseer chat agent ships OFF; this leaf only adds its configuration surface.

# Required plan shape

Emit EXACTLY ONE task (do NOT decompose):
- meta_task_type: harness_self_fix
- files_touched: ["harness/config.yaml"]
- verification_command: "python -m pytest tests/overseer/test_config_overseer.py -q"
- spec_author: null
- IMPL-only / ADDITIVE: author/edit NO test. Add ONLY the overseer block.
- This is a SINGLE non-Python (.yaml) file → it uses the VERBATIM whole-file
  `__JANUSMASK_MANIFEST__` dispatch (NOT a symbol patch). Emit
  `__JANUSMASK_MANIFEST__ = {'harness/config.yaml': r'''<whole updated file>'''}`.

# Inputs

`harness/config.yaml` is staged read-only at `{WORK_DIR}/inbox/targets/harness/config.yaml`.
Read that CURRENT on-disk content and reproduce it BYTE-FOR-BYTE, then APPEND the new
top-level `overseer:` block. The oracle (`load_config()`) requires, under `overseer:`:
- `enabled: false`                        # ships OFF — no enabled-by-default autonomy
- `default_mode: observe`                 # boot in the read-only mode
- `default_backend: claude`
- `models:` with `claude: [opus, sonnet, haiku]`
- `store_path:` any string (e.g. `state/overseer/sessions.json`)
- `unlock_policy: {}`                      # mapping of which Tier-S modes need unlock

# Non-Goals

Change NOTHING else. Preserve EVERY existing key and value VERBATIM — in particular the current
`autowork:` block (including `auto_approve_ro_gate: false`, `auto_approve_sensitive_harness: false`,
`selfheal_auto_promote: false`) and the `synthesis:` block (including
`accept_single_agent_leaf_plans: true`) are an INTENTIONAL SAFETY POSTURE that MUST survive the edit.
Do NOT flip, add, or remove any flag outside the new `overseer:` block. Do NOT author a test. ONE leaf
editing exactly `harness/config.yaml`.

# Implementation notes

The verbatim staged file already contains the safety posture; copy it whole and add ONLY the
`overseer:` block at top level (YAML key order is irrelevant to the loader). Concrete block:

```yaml
overseer:
  enabled: false
  default_mode: observe
  default_backend: claude
  models:
    claude:
    - opus
    - sonnet
    - haiku
  store_path: state/overseer/sessions.json
  unlock_policy: {}
```

Emit it inside the manifest value so the whole file (existing content + this block) is written
verbatim. Keep two-space indentation consistent with the rest of the file.

# COMMITTED ORACLE CONTRACT (authoritative; reproduced here — your code MUST make it pass)

`tests/overseer/test_config_overseer.py` loads the REAL config via
`harness.orchestrator.load_config()` and asserts:
- `cfg["overseer"]["enabled"] is False`
- `cfg["overseer"]["default_mode"] == "observe"`
- `cfg["overseer"]["default_backend"] == "claude"`
- `cfg["overseer"]["models"]["claude"] == ["opus", "sonnet", "haiku"]`
- `"store_path" in cfg["overseer"]` and `"unlock_policy" in cfg["overseer"]`
- `"autowork" in cfg` and `"synthesis" in cfg` (additive — existing blocks intact)

# Deliverables

`harness/config.yaml` with the default-OFF `overseer:` block added and every existing key preserved,
GREEN under `python -m pytest tests/overseer/test_config_overseer.py -q`.
