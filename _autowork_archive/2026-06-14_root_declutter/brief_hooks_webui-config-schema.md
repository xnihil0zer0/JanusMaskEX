---
complexity_score: 5
dependencies: []
meta_task_type: harness_self_fix
interfaces: "harness/webui_config_schema.py: ConfigField(name, dtype, default, *, choices=None, min=None, max=None, role=None); RoleSpec(name, config_key, dual: bool); ProviderSpec(provider_id, label, api_key_env, api_backed: bool); CONFIG_FIELDS: list[ConfigField]; ROLES: list[RoleSpec]; PROVIDERS: dict[str, ProviderSpec]; ValidatedConfig(values: dict); ConfigValidationError(field_errors: dict[str,str]); validate_config(submitted: dict, *, secrets: dict[str,str]) -> ValidatedConfig; atomic_save_config(validated: ValidatedConfig, config_path) -> None."
---

# Title

NEW typed config schema module driving server-side validation: a declarative field list (int/float/str/bool/path-file/path-dir/enum), a `validate_config()` that coerces+validates each field and rejects with a per-field error map, enforces dual-agent-distinct and provider-locked-unless-keyed rules, and an atomic `atomic_save_config()` writer.

> **AST-CREDENTIAL GATE (`harness/ast_enforcer.py:78`).** Build/oracle is REJECTED if any variable/constant NAME matching `(?i)(key|secret|password)` is assigned a string literal, at module OR function scope (this is why a var named `key`/`OVERSEER_KEY` failed). RULES: never assign a string literal to such a name; read creds via `os.environ.get(...)`; name locals `env_name`/`value`/`cred`. SAFE: these words as dict keys, kwargs (`api_key_env="DEEPSEEK_API_KEY"`), and dataclass field names. ORACLE AUTHOR: reproduce the embedded oracle source VERBATIM — it is already AST-clean and non-vacuous; do NOT rename variables or add module-level constants.

# Scope

Create NEW `harness/webui_config_schema.py`. Mirror the typed-dataclass + explicit-validator precedent in `harness/config_loader.py` (`HooksConfig`/`get_hooks_config` raising `ConfigError`, with `isinstance(x, bool)`-before-`int` guards). Full contract is carried by the committed oracle `tests/webui/test_config_schema.py`. Surface, per the frontmatter `interfaces`:

- `ConfigField(name, dtype, default, *, choices=None, min=None, max=None, role=None)` — `dtype` in `{int,float,str,bool,path-file,path-dir,enum}`.
- `RoleSpec(name, config_key, dual)` — dual `synthesis` (`synthesis.active_agents`), single-select `overseer` (`overseer.default_backend`) and `autobrief` (`control.autobrief_default_agent`).
- `ProviderSpec(provider_id, label, api_key_env, api_backed)` — CLI agents `{claude, gemini, antigravity, codex}` with `api_backed=False`; api-backed `{openai, gemini_api, anthropic, deepseek, moonshot, zhipu, qwen, minimax}` with `api_backed=True` and env var from `_autowork_scratch/CHINESE_API_RESEARCH.md`. (`gemini_api` = Gemini's OpenAI-compatible endpoint, `GEMINI_API_KEY` — must match the oracle's `required` set.)
- `CONFIG_FIELDS` — typed tunables: `parallel_cap`(int 1..16), `min_ram_mb`(int >=0), `cooldown_tier_1/2/3`(float >=0), `antigravity_mode`(bool), `sandbox.filesystem_root`(path-dir), `overseer.store_path`(path-file).
- `validate_config(submitted, *, secrets)` — coerces by dtype (reject non-coercible into `field_errors[name]`), bounds/choice-checks, and applies TWO cross-field rules: (a) each dual role's two agents must be present and DIFFERENT; (b) any role assigned an api-backed provider whose `secrets[api_key_env]` is empty → `field_errors[role_key]` "provider locked: set <ENV> first". Accumulate errors (do NOT raise mid-loop); raise `ConfigValidationError(field_errors)` if any, else return `ValidatedConfig(values)`. `bool` must reject arbitrary truthy ints (guard `isinstance(x, bool)` precedence); `"true"/"false"` strings coerce to bool.
- `atomic_save_config(validated, config_path)` — merge `validated.values` into existing YAML, write via temp file in the same dir + `os.replace` (atomic); never partial-write.

KNOWN-BUG-TO-FIX #1 — ROLE-VALUE PROPAGATION (acceptance contract): for EVERY role whose assignment passes validation, write the accepted assignment into `ValidatedConfig.values[role.config_key]` — single-select = the provider-id string (e.g. `"deepseek"`), dual = `[agent0, agent1]`. The prior impl validated roles but never populated `values`, so the assertion `validate_config(sub, secrets={env:"..."}).values["overseer.default_backend"] == "deepseek"` KeyError'd. Add the propagation write inside the per-role accept path.

KNOWN-BUG-TO-FIX #2 — SAVE-KEY NESTING (acceptance contract): `values` stays SHORT-keyed (oracle reads `v["parallel_cap"]`), but `config.yaml` nests under blocks. `atomic_save_config` MUST translate short→dotted save paths via an internal map before the nested merge: `parallel_cap`/`min_ram_mb`/`cooldown_tier_1/2/3` → `autowork.<name>`; `antigravity_mode` → `synthesis.antigravity_mode`. Already-dotted fields (`sandbox.filesystem_root`, `overseer.store_path`) and role keys save unchanged. Do NOT change the `ConfigField` signature or re-key `values`. The prior impl merged the short key at top-level, leaving `autowork.parallel_cap` stale; assertion: after save, `yaml.safe_load(cfg)["autowork"]["parallel_cap"] == 5` AND unrelated blocks (`autowork.poll_interval_sec`, `overseer.enabled`) preserved.

This module owns its own `PROVIDERS` table and must NOT import `harness/model_backends*`; keep it decoupled (stdlib + PyYAML only).

# Non-Goals

No WebUI/Flask code, no template work (that is `webui-typed-widgets`). No backend instantiation or network calls (that is `webui-model-backends`; this module only reads `secrets` as a passed-in dict to gate locks). No secret persistence (that is `harness/secrets_store.py`). No edits to any `_NEVER_AUTO_APPROVE` file or to `harness/config_loader.py`/`config.yaml`. This is NOT an integration leaf — the integration wiring into the WebUI server / Flask routes is deferred to the dependent `webui-typed-widgets` leaf and an owner-gated hand-edit. INDEPENDENT FOUNDATION with NO dependency on `webui-model-backends`. The ONLY edit beyond the new module is a minimal additive live-wiring anchor in `harness/control_gate.py` — a new top-level import + a thin accessor, never a change to an existing function/class.

# Inputs

- Precedent: `harness/config_loader.py` (dataclass + `__post_init__` validator + bool/int guard + `ConfigError`).
- Real config keys + defaults: `harness/config.yaml`.
- Provider env vars + labels: `_autowork_scratch/CHINESE_API_RESEARCH.md`.
- Committed oracle (the contract): `tests/webui/test_config_schema.py`.

# Deliverables

ONE GREEN leaf: `harness/webui_config_schema.py` verified by `python -m pytest tests/webui/test_config_schema.py -q`. Frozen surface exactly as the frontmatter `interfaces`. The committed oracle is RED against a `raise NotImplementedError` stub and asserts: typed coercion + per-field rejection; dual-agent same-agent rejection; role→keyless-api-provider rejection; role→keyed-api-provider acceptance (accepted provider id round-trips into `out.values[role.config_key]`); atomic save round-trips without corrupting other blocks; module passes `check_wired`.

# Required plan shape

INDEPENDENT FOUNDATION (frontmatter `dependencies: []`); supplies its own LIVE_ROOT anchor. Single working_dir (`working_dir` null) DAG of EXACTLY TWO tasks. The new module is under the SENSITIVE `harness/**` glob, so the impl task MUST be `meta_task_type: "harness_self_fix"` and EXCUSE the integration-test gate via the literal word "integration" in `spec.non_goals`.

LIVE-WIRING ANCHOR (deadlock break): a NEW `harness/**` module is rejected with `orphan_unwired` unless reachable from a LIVE_ROOT. The impl task additively wires the module to the PROVEN anchor `harness/control_gate.py` (imported by `harness/orchestrator.py`, a root): add `from harness import webui_config_schema` + a thin trailing `def typed_config_schema(): return webui_config_schema.CONFIG_FIELDS`. ADDITIVE only — ride new import/function as trailing top-level nodes; never patch an existing `control_gate.py` symbol.

TEST-SPEC BALANCE (planner gate `insufficient_unit_tests`, severity error): each impl task's `test_spec.unit_tests` MUST have at least as many entries as its `functional_requirements` (`len(unit_tests) >= len(functional_requirements)`), and `test_spec.edge_cases` MUST have ≥2 entries mirrored in regression/property tests. For `config-schema-impl`, keep `functional_requirements` to a TIGHT list of ≤6 and emit ONE matching `unit_tests` entry per requirement: (1) typed coercion + per-field rejection into `field_errors`; (2) dual-agent same-agent rejection; (3) role→keyless-api-provider lock rejection; (4) role→keyed-api-provider acceptance with the provider-id propagated into `values[role.config_key]`; (5) `atomic_save_config` short→dotted nesting that preserves unrelated blocks; (6) module passes `check_wired`. `edge_cases` (≥2): bool must reject arbitrary truthy ints (isinstance precedence); `parallel_cap` out-of-bounds rejected.

Emit these tasks verbatim in shape:

1. `task_id: "config-schema-impl"`
   - `meta_task_type: "harness_self_fix"`
   - `files_touched: ["harness/webui_config_schema.py", "harness/control_gate.py"]`
   - `dependencies: []`
   - `verification_command: "python -m pytest tests/webui/test_config_schema.py -q"`
   - `spec.non_goals` MUST include a line containing the word **integration**.

2. `task_id: "config-schema-oracle"`
   - `meta_task_type: "test_authoring"`
   - top-level `mutation_target: "harness.webui_config_schema"`
   - `files_touched: ["tests/webui/test_config_schema.py"]`
   - `dependencies: ["config-schema-impl"]`
   - `verification_command: "python -m pytest tests/webui/test_config_schema.py -q"`
   - The oracle MUST include the wiring assertion `assert check_wired(Path('.'), 'harness/webui_config_schema.py').wired is True`.

Note: `mutation_target` is a BARE DOTTED module name (no path/slashes/`.py`). `harness.webui_config_schema` → `harness/webui_config_schema.py`, in the impl `files_touched` (satisfies the paired-auto-oracle wiring exemption).
