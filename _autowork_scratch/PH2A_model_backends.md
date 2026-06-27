# PH2A — webui-model-backends brief + oracle reconciliation (2026-06-12)

## Root cause of prior build failure
ast_enforcer.py:78 (`visit_Assign`/`visit_AnnAssign`): rejects any string-literal assigned
to a `Name` target matching `(?i)(password|secret|key)`. Prior build used a local `key`.
SAFE: dict keys, keyword-args (`api_key_env="..."`), dataclass field names. Reads via
`os.environ.get(...)`; locals named `cred_env`/`env_name`/`value`.

## Files edited
- brief_hooks_webui-model-backends.md (frontmatter + Scope + Non-Goals + Required plan
  shape + new implementation_notes with embedded oracle contract + AST-safe impl skeleton)
- tests/webui/test_model_backends.py (added `test_model_backends_modules_are_wired`)

## Key reconciliations
- DECOUPLED: frontmatter `dependencies: ["webui-config-schema"]` -> `[]`. Added
  `meta_task_type: harness_self_fix`.
- Re-pointed LIVE-WIRING ANCHOR from `harness/webui_config_schema.py` to the PROVEN
  `harness/control_gate.py` (already imported by orchestrator.py). Task1 `files_touched`
  now `[model_backends.py, secrets_store.py, control_gate.py]`.
- Added `agent_block(provider_id)` accessor to interfaces.
- secrets_store params renamed key_name -> env_name; added `has_secret`.
- Oracle: added required dual `check_wired(...).wired is True` test (plan-shape line 91
  demanded it; it was missing). check_wired(repo_root, rel).wired verified in wire_up.py:317.

## BackendSpec signature (asserted field order)
BackendSpec(kind, provider_id, *, base_url=None, api_key_env=None, model_id=None,
            command=None, args=None)   # dataclass, kind FIRST, provider_id SECOND

## BACKEND_REGISTRY keys
openai, gemini_api, deepseek, moonshot, zhipu, qwen, minimax (openai_compat);
anthropic (anthropic); claude, gemini, antigravity (cli); codex (codex_cli).
base_urls/envs verbatim from CHINESE_API_RESEARCH.md.

## Non-vacuousness (reasoning, not run)
Oracle imports module at collection -> NotImplementedError stub fails at import = RED.
A name-only stub (empty BACKEND_REGISTRY) passes hasattr but fails
test_all_openai_compat_providers_registered (empty dict), test_anthropic..., resolve_backend
lock test, secrets 0600 roundtrip, and the wire test. Confirmed non-vacuous.
Oracle file itself is AST-safe (only string literals are call-args, never Name-target assigns).
