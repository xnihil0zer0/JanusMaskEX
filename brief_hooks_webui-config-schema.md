---
complexity_score: 5
dependencies: []
interfaces: "harness/webui_config_schema.py: ConfigField(name, dtype, default, *, choices=None, min=None, max=None, role=None); RoleSpec(name, config_key, dual: bool); ProviderSpec(provider_id, label, api_key_env, api_backed: bool); CONFIG_FIELDS: list[ConfigField]; ROLES: list[RoleSpec]; PROVIDERS: dict[str, ProviderSpec]; ValidatedConfig(values: dict); ConfigValidationError(field_errors: dict[str,str]); validate_config(submitted: dict, *, secrets: dict[str,str]) -> ValidatedConfig; atomic_save_config(validated: ValidatedConfig, config_path) -> None."
---

# Title

NEW typed config schema module that drives server-side validation: a single declarative field list (typed int/float/str/bool/path-file/path-dir/enum), a `validate_config()` that coerces+validates each field and rejects with a per-field error map, enforces dual-agent-distinct and provider-locked-unless-keyed cross-field rules, and an atomic `atomic_save_config()` writer.

# Scope

Create NEW `harness/webui_config_schema.py`. Mirror the typed-dataclass + explicit-validator precedent in `harness/config_loader.py` (`HooksConfig`/`get_hooks_config` raising `ConfigError`, with the `isinstance(x, bool)`-before-`int` guards). Provide:

- `ConfigField(name, dtype, default, *, choices=None, min=None, max=None, role=None)` — `dtype` in `{"int","float","str","bool","path-file","path-dir","enum"}`.
- `RoleSpec(name, config_key, dual)` — e.g. `RoleSpec("synthesis", "synthesis.active_agents", dual=True)`, plus single-select roles `overseer` (`overseer.default_backend`) and `autobrief` (`control.autobrief_default_agent`).
- `ProviderSpec(provider_id, label, api_key_env, api_backed)` — the selectable model backends: non-api-backed CLI agents (`claude`, `gemini`, `antigravity`, `codex`) with `api_backed=False`, and api-backed providers (`openai`, `gemini_api`, `anthropic`, `deepseek`, `moonshot`, `zhipu`, `qwen`, `minimax`) with `api_backed=True` and the env var from `_autowork_scratch/CHINESE_API_RESEARCH.md`.
- `CONFIG_FIELDS` — the existing tunables typed: `parallel_cap`(int 1..16), `min_ram_mb`(int >=0), `cooldown_tier_1/2/3`(float >=0), `antigravity_mode`(bool), plus `sandbox.filesystem_root`(path-dir), `overseer.store_path`(path-file) to exercise path types.
- `validate_config(submitted, *, secrets)` — coerces each field by dtype (reject non-coercible with a clear message in `field_errors[name]`), bounds/choice-checks, and applies TWO cross-field rules: (a) for every `RoleSpec.dual` role, the two chosen agents must be present and DIFFERENT else `field_errors[role_key]`; (b) any role assigned a provider with `api_backed=True` whose `secrets[api_key_env]` is empty/absent -> `field_errors[role_key]` "provider locked: set <ENV> first". Raises `ConfigValidationError(field_errors)` if any error; returns `ValidatedConfig(values)` on success. `bool` must NOT accept arbitrary truthy ints (guard `isinstance(x, bool)` precedence as config_loader does); `"true"/"false"` strings coerce to bool.
- `atomic_save_config(validated, config_path)` — merge `validated.values` into the existing YAML and write via temp file in the same dir + `os.replace` (atomic); never partial-write config.yaml.

# Non-Goals

No WebUI/Flask code, no template work (that is `webui-typed-widgets`). No backend instantiation or network calls (that is `webui-model-backends`; this module only reads `secrets` as a passed-in dict to gate locks). No secret persistence (the store is `harness/secrets_store.py`). No edits to any `_NEVER_AUTO_APPROVE` file or to `harness/config_loader.py`/`config.yaml`. The NEW module is the schema body; the ONLY additional edit is a minimal, additive live-wiring anchor in `harness/control_gate.py` (see Required plan shape) — a new top-level import + a thin accessor, never a change to any existing function/class.

# Inputs

- Precedent: `harness/config_loader.py` (dataclass + `__post_init__` validator + bool/int guard + `ConfigError`).
- Real config keys + defaults: `harness/config.yaml` (`autowork.parallel_cap`, `cooldown_tier_*`, `synthesis.antigravity_mode`, `synthesis.active_agents`, `overseer.default_backend`/`store_path`, `control.autobrief_default_agent`, `sandbox.filesystem_root`).
- Provider env vars + labels: `_autowork_scratch/CHINESE_API_RESEARCH.md`.
- Committed oracle (the contract): `tests/webui/test_config_schema.py`.

# Deliverables

ONE GREEN leaf: `harness/webui_config_schema.py` verified by `python -m pytest tests/webui/test_config_schema.py -q`. Frozen surface exactly as the frontmatter `interfaces` line. The oracle is RED against a `raise NotImplementedError` stub and asserts: typed coercion + per-field rejection; dual-agent same-agent rejection; role→keyless-api-provider rejection; role→keyed-api-provider acceptance; atomic save round-trips and does not corrupt other config blocks.

# Required plan shape

The plan MUST be a single working_dir (this repo; `working_dir` null) DAG of EXACTLY TWO tasks. One new `.py` module is created (`harness/webui_config_schema.py`), which sits under the SENSITIVE `harness/**` apply-glob, so the impl task MUST use `meta_task_type: "harness_self_fix"` (the only non-test type permitted to commit a `harness/**` path — any other type is rejected at plan time with `sensitive_files_touched`). The integration wiring into the WebUI server / Flask routes is genuinely DEFERRED to the dependent `webui-typed-widgets` leaf and an owner-gated hand-edit, so the impl task EXCUSES the integration-test gate by listing the literal word "integration" in `spec.non_goals`.

**LIVE-WIRING ANCHOR (deadlock break).** A NEW `harness/**` module is rejected at acceptance with `orphan_unwired` (`harness/wire_up.py:check_wired`) unless it is reachable through the import graph from a LIVE_ROOT (`harness/orchestrator.py`, `harness/orchestrator_worker.py`, `harness/autowork_daemon.py`, `harness/planner/cli.py`), has a live importer transitively reachable from a root, or is CONFIG_WIRED. The UI leaf that imports this schema lives under `tools/` (NOT a root) and is dep-gate-held behind this leaf, so it cannot supply the importer. Therefore the impl task MUST itself add the live importer, WITHIN THIS LEAF'S SCOPE, into the root-reachable anchor **`harness/control_gate.py`** (verified `check_wired(...).wired is True`; directly imported by `harness/orchestrator.py`; NOT in `_NEVER_AUTO_APPROVE`, so a `harness_self_fix` may commit it). The edit MUST be MINIMAL and ADDITIVE (never-patch-existing-class-methods): add a module-level `from harness import webui_config_schema` plus a NEW thin top-level accessor `def typed_config_schema(): return webui_config_schema.CONFIG_FIELDS` (rides as a TRAILING top-level node), so `harness/webui_config_schema.py` becomes reachable: `webui_config_schema ← control_gate ← orchestrator (root)`. Do NOT alter any existing `control_gate.py` function or class.

The created module is proven by a paired `test_authoring` oracle whose top-level `mutation_target` (bare dotted module-under-test) resolves to the impl's `.py` (the auto-authored, mutation-gated oracle IS the contract proof). In ADDITION, because this leaf supplies its own root-anchor, the oracle MUST carry an explicit wiring assertion (a `*_wired`-style check) so the deadlock-break is verified in-band:

```python
def test_webui_config_schema_is_wired():
    from pathlib import Path
    from harness.wire_up import check_wired
    assert check_wired(Path('.'), 'harness/webui_config_schema.py').wired is True
```

Emit these tasks verbatim in shape:

1. `task_id: "config-schema-impl"`
   - `meta_task_type: "harness_self_fix"`
   - `files_touched: ["harness/webui_config_schema.py", "harness/control_gate.py"]`
   - `dependencies: []`
   - `verification_command: "python -m pytest tests/webui/test_config_schema.py -q"`  (NO leading/embedded `cd `)
   - This task creates the whole-file `harness/webui_config_schema.py` AND makes a MINIMAL ADDITIVE live-wiring edit to `harness/control_gate.py`: add a module-level `from harness import webui_config_schema` and a NEW trailing top-level function `def typed_config_schema(): return webui_config_schema.CONFIG_FIELDS`. Do NOT modify any existing `control_gate.py` symbol; ride the new import + function as trailing nodes. This anchors `webui_config_schema` to a LIVE_ROOT (`control_gate ← orchestrator`) so it passes `check_wired`.
   - `spec.non_goals` MUST include a line containing the word **integration**, e.g. "Integration wiring into the WebUI server and Flask routes is OUT OF SCOPE here — deferred to the dependent webui-typed-widgets leaf and an owner-gated hand-edit; this leaf only produces the schema + validators plus a minimal additive live-wiring anchor in harness/control_gate.py."

2. `task_id: "config-schema-oracle"`
   - `meta_task_type: "test_authoring"`
   - top-level `mutation_target: "harness.webui_config_schema"`
   - `files_touched: ["tests/webui/test_config_schema.py"]`
   - `dependencies: ["config-schema-impl"]`  (oracle depends on impl — impl-first ordering)
   - `verification_command: "python -m pytest tests/webui/test_config_schema.py -q"`
   - The oracle MUST include the explicit wiring assertion shown above (`assert check_wired(Path('.'), 'harness/webui_config_schema.py').wired is True`) so the live-wiring anchor is verified in-band alongside the schema contract.

Note: `mutation_target` is a BARE DOTTED module name (no path, no slashes, no `.py`). `harness.webui_config_schema` resolves to `harness/webui_config_schema.py`, which is in the impl task's `files_touched` — this satisfies the paired-auto-oracle wiring exemption.
