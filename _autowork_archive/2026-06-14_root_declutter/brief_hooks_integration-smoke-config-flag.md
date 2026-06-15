---
interfaces: "config flag: harness/config.yaml autowork.integration_smoke_gate: false; read as load_config()['autowork'].get('integration_smoke_gate', False) (default False)"
---

# Title

Config: default-OFF autowork.integration_smoke_gate flag

# Scope

Add the single default-OFF flag `integration_smoke_gate: false` to the `autowork:` block of `harness/config.yaml`, sitting beside the existing `wire_up_gate` flag, so the accept-time gate and the plan-validation requirement have a real, flippable switch. The flag is the static contract both consumers read via `load_config()['autowork'].get('integration_smoke_gate', False)`. This is a tiny single-key edit (meta_task_type `config_schema` / `harness_self_fix`) re-planning into the config edit plus a minimal oracle asserting `load_config()['autowork']` contains the key and that it defaults to False.

# Non-Goals

Do NOT flip the flag ON — it ships OFF; the flip is owner-gated on the recorded dogfood and is out of scope for every leaf in this epic. Do NOT add any other config keys. Do NOT touch orchestrator, plan_validator, or the classifiers. Do NOT add gate logic here — only the declaration.

# Inputs

Read-only: `harness/config.yaml` `autowork:` block and its existing `wire_up_gate` entry (the placement and style template). The config loader `load_config()`.

# Deliverables

`harness/config.yaml` `autowork:` block gains `integration_smoke_gate: false`, readable as `load_config()['autowork'].get('integration_smoke_gate', False)` defaulting to False. Plus a minimal oracle asserting the key is present and defaults False.
