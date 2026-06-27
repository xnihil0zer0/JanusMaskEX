# PH2B — webui-config-schema fix-forward (brief + oracle hardening)

Date: 2026-06-12. NO commit (orchestrator commits). NO dispatch.

## Status of committed impl (06e2e55)
`harness/webui_config_schema.py` is WIRED (control_gate anchor live; `check_wired` True)
but BUGGY. Actually **8/10** oracle tests pass, not 8/9 — TWO real impl bugs, both
pre-existing on HEAD (verified via git stash), both targeted by the strengthened brief.

### Bug 1 — role-value not propagated
`validate_config` validates each role (distinct + provider-locked-unless-keyed) but
never writes the accepted assignment into `values`. → `test_role_assigned_keyed_api_provider_is_accepted`
KeyErrors on `out.values["overseer.default_backend"]`.

### Bug 2 — save-key nesting (newly surfaced)
`values` is SHORT-keyed (`parallel_cap`) but real config nests under `autowork.parallel_cap`.
`atomic_save_config` merges the short key at top-level, leaving `autowork.parallel_cap` stale.
→ `test_atomic_save_roundtrips_without_clobbering` fails (`autowork.parallel_cap` stays 1, not 5).

## Contracts specified in brief (implementation_notes)
- ROLE-VALUE PROPAGATION: per accepted role, `values[role.config_key] = <provider_id>`
  (single) / `[agent0, agent1]` (dual). Exact assertion embedded:
  `validate_config(sub, secrets={env:"sk-real-key"}).values["overseer.default_backend"] == "deepseek"`.
- SAVE-KEY NESTING: internal short→dotted map in `atomic_save_config`:
  `parallel_cap|min_ram_mb|cooldown_tier_{1,2,3}` → `autowork.<name>`;
  `antigravity_mode` → `synthesis.antigravity_mode`; already-dotted fields/roles unchanged.
  Do NOT change frozen `ConfigField(...)` sig; do NOT re-key `values` (oracle reads short).
- Kept: meta_task_type harness_self_fix, 5 bare headings, Non-Goals w/ literal "integration",
  paired test_authoring + control_gate.py additive wiring plan-shape, AST cred-gate (api_key_env
  field only), no model_backends dep.

## gemini_api reconciliation
Oracle `required` set (was missing `gemini_api`) now includes it →
`{openai, gemini_api, anthropic, deepseek, moonshot, zhipu, qwen, minimax}`, agreeing with
brief + impl PROVIDERS table. (Gemini OpenAI-compat endpoint, GEMINI_API_KEY.) Impl already
registered gemini_api, so test_api_backed_providers_have_env_vars stays green.

## Oracle wiring proof
Added `test_webui_config_schema_is_wired` using verified signature
`check_wired(repo_root, new_module_rel)` → `check_wired(Path('.'), 'harness/webui_config_schema.py').wired is True`.
PASSES now (control_gate anchor from 06e2e55 is live). importlib import at module top also present.

## Files edited (on disk, uncommitted)
- brief_hooks_webui-config-schema.md  (2 contracts + impl-notes + gemini_api note)
- tests/webui/test_config_schema.py   (gemini_api in required; + wiring assertion)

## Verification
`pytest tests/webui/test_config_schema.py -q` → 9 passed, 2 failed (the two target bugs).
Oracle is NON-VACUOUS (RED on buggy impl, concrete-value assertions). Re-run of
config-schema-impl (harness_self_fix EDIT) should turn both red tests green.
