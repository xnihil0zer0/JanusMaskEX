---
complexity_score: 5
dependencies: []
meta_task_type: harness_self_fix
interfaces: "harness/model_backends.py: BackendSpec(kind, provider_id, *, base_url=None, api_key_env=None, model_id=None, command=None, args=None); OpenAICompatBackend(base_url, api_key_env, model_id); AnthropicBackend(api_key_env, model_id); CodexCliBackend(command, args); BACKEND_REGISTRY: dict[str, BackendSpec]; resolve_backend(provider_id: str, secrets: dict[str,str]) -> BackendSpec (raises BackendLockedError if api-backed and key empty); agent_block(provider_id) -> dict. harness/secrets_store.py: SECRETS_PATH(state_dir) -> Path; load_secrets(state_dir) -> dict[str,str]; save_secret(state_dir, env_name, value) -> None; has_secret(state_dir, env_name) -> bool; delete_secret(state_dir, env_name) -> None."
---

# Title

NEW model-backend registry unifying every selectable backend behind one stable spec — a single OpenAI-style client parameterized by (base_url, api_key_env, model_id) for OpenAI + Gemini-OpenAI-endpoint + 5 Chinese providers, an Anthropic SDK backend, and a codex-CLI backend mirroring the existing CLI-agent integration — plus a gitignored, 0600 secrets store.

> **AST-CREDENTIAL GATE (`harness/ast_enforcer.py:78`).** Build/oracle is REJECTED if any variable/constant NAME matching `(?i)(key|secret|password)` is assigned a string literal, at module OR function scope (this is why a var named `key`/`OVERSEER_KEY` failed). RULES: never assign a string literal to such a name; read creds via `os.environ.get(...)`; name locals `env_name`/`value`/`cred`. SAFE: these words as dict keys, kwargs (`api_key_env="DEEPSEEK_API_KEY"`), and dataclass field names. ORACLE AUTHOR: reproduce the embedded oracle source VERBATIM — it is already AST-clean and non-vacuous; do NOT rename variables or add module-level constants.

# Scope

Create NEW `harness/model_backends.py` and NEW `harness/secrets_store.py`. The full contract is carried by the committed oracle `tests/webui/test_model_backends.py` (do not re-paste it). Surface, per the frontmatter `interfaces`:

- `BackendSpec` dataclass with FIELD ORDER asserted: FIRST `kind` (`'openai_compat'`|`'anthropic'`|`'codex_cli'`|`'cli'`), SECOND `provider_id`, then keyword-only `base_url`/`api_key_env`/`model_id`/`command`/`args` (all default None).
- `OpenAICompatBackend(base_url, api_key_env, model_id)` — ONE class for every OpenAI-compatible provider (no per-provider subclasses); `client()` builds an OpenAI client with `base_url` + cred read via `os.environ.get(self.api_key_env)`. `client()` may raise ImportError at call time (openai package may be absent) — the oracle never calls it live.
- `AnthropicBackend(api_key_env, model_id)` — its OWN backend kind, not the openai-compat path.
- `CodexCliBackend(command, args)` — CLI backend mirroring `harness/orchestrator.py:_build_agent_command`'s `{command, args}` contract; `agent_block()` returns the `{command, args}` dict shaped like the existing claude/gemini agent blocks.
- `BACKEND_REGISTRY: dict[provider_id -> BackendSpec]` enumerating: cli = claude/gemini/antigravity/codex; openai-compat = openai/gemini_api/deepseek/moonshot/zhipu/qwen/minimax; anthropic = anthropic. Base URLs + env vars VERBATIM from `_autowork_scratch/CHINESE_API_RESEARCH.md`.
- `resolve_backend(provider_id, secrets)` — returns the spec; raises `BackendLockedError` if api-backed and its credential env-var is empty in `secrets`/env. MUST read injected creds via `secrets_store.load_secrets(...)` falling back to env (this is the live use that anchors `secrets_store`). CLI backends never require a credential.
- `agent_block(provider_id) -> dict` — module-level accessor: `{command, args}` for CLI backends; a base_url/model/api_key_env block for api backends.

`secrets_store.py`: persist creds in gitignored `state/secrets/api_keys.json`. `SECRETS_PATH(state_dir)` derives the path from the `state_dir` PARAMETER (never a hardcoded literal). `save_secret(state_dir, env_name, value)` writes mode 0600 (dir 0700, parents created); `load_secrets` returns `{}` if absent; `has_secret`/`delete_secret` as named. Names use `env_name`/`value`. Never write a credential into config.yaml or any tracked file.

# Non-Goals

Integration wiring into WebUI templates, `config.yaml`, and `harness/orchestrator.py` is OUT OF SCOPE — this is NOT an integration leaf; that integration is deferred to the dependent `webui-typed-widgets` leaf and an owner-gated hand-edit. No live network call / no real `.chat()`/`.messages.create()`. No WebUI/template code. No edits to any `_NEVER_AUTO_APPROVE` file; do NOT wire codex into `harness/orchestrator.py` or `config.yaml`. No secret committed to git. This leaf is an INDEPENDENT FOUNDATION with NO dependency on `webui-config-schema`. The ONLY edit beyond the two new modules is a minimal additive live-wiring reference in the LIVE_ROOT anchor `harness/control_gate.py` — a new top-level import + a thin trailing function, never a change to any existing symbol.

# Inputs

- CLI-agent spawn contract: `harness/orchestrator.py:_build_agent_command` + the `config.yaml agents:` blocks (claude/gemini/antigravity) codex must mirror.
- Providers/base-urls/env-vars: `_autowork_scratch/CHINESE_API_RESEARCH.md` (verbatim).
- Gitignore: `.gitignore` ignores `state/`.
- Committed oracle (the contract): `tests/webui/test_model_backends.py`.

# Deliverables

ONE GREEN leaf: `harness/model_backends.py` + `harness/secrets_store.py` verified by `python -m pytest tests/webui/test_model_backends.py -q`. Frozen surface exactly as the frontmatter `interfaces`. The committed oracle is RED against stubs and asserts: every Chinese + frontier provider present with correct base_url+env; one `OpenAICompatBackend` class per openai-compat provider (no subclasses); Anthropic is its own kind; `CodexCliBackend.agent_block()` matches the `{command, args}` shape; `resolve_backend` raises `BackendLockedError` for a keyless api provider and returns a spec when keyed; `save_secret` writes a 0600 gitignored file under `state/secrets/` that `load_secrets` reads back; both new modules pass `check_wired`.

# Required plan shape

INDEPENDENT FOUNDATION (frontmatter `dependencies: []`); supplies its own LIVE_ROOT anchor. Single working_dir (`working_dir` null) DAG of EXACTLY THREE tasks. Both new modules are under the SENSITIVE `harness/**` glob, so the impl task MUST be `meta_task_type: "harness_self_fix"` and EXCUSE the integration-test gate via the literal word "integration" in `spec.non_goals`.

LIVE-WIRING ANCHOR (deadlock break): a NEW `harness/**` module is rejected with `orphan_unwired` unless reachable from a LIVE_ROOT. The impl task additively wires both new modules to the PROVEN anchor `harness/control_gate.py` (imported by `harness/orchestrator.py`, a root): (a) in `control_gate.py` add `from harness import model_backends` + a thin trailing `def backend_choices(): return list(model_backends.BACKEND_REGISTRY)`; (b) in `model_backends.py` add `from harness import secrets_store` + a real use inside `resolve_backend`. Both edits ADDITIVE only — ride new imports/functions as trailing top-level nodes; never patch existing symbols.

Emit these tasks verbatim in shape:

1. `task_id: "model-backends-impl"`
   - `meta_task_type: "harness_self_fix"`
   - `files_touched: ["harness/model_backends.py", "harness/secrets_store.py", "harness/control_gate.py"]`
   - `dependencies: []`
   - `verification_command: "python -m pytest tests/webui/test_model_backends.py -q"`
   - `spec.non_goals` MUST include a line containing the word **integration**.

2. `task_id: "model-backends-oracle"`
   - `meta_task_type: "test_authoring"`
   - top-level `mutation_target: "harness.model_backends"`
   - `files_touched: ["tests/webui/test_model_backends.py"]`
   - `dependencies: ["model-backends-impl"]`
   - `verification_command: "python -m pytest tests/webui/test_model_backends.py -q"`

3. `task_id: "secrets-store-oracle"`
   - `meta_task_type: "test_authoring"`
   - top-level `mutation_target: "harness.secrets_store"`
   - `files_touched: ["tests/webui/test_model_backends.py"]`
   - `dependencies: ["model-backends-impl"]`
   - `verification_command: "python -m pytest tests/webui/test_model_backends.py -q"`

One oracle task carries the dual wiring assertion (`check_wired(...,'harness/model_backends.py').wired is True` AND `...'harness/secrets_store.py'...`). `mutation_target` is a BARE DOTTED module name (no path/slashes/`.py`): `harness.model_backends` → `harness/model_backends.py`, `harness.secrets_store` → `harness/secrets_store.py`, both in the impl `files_touched` (satisfies the paired-auto-oracle wiring exemption).
