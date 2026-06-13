---
complexity_score: 5
dependencies: []
interfaces: "harness/model_backends.py: BackendSpec(kind, provider_id, *, base_url=None, api_key_env=None, model_id=None, command=None, args=None); OpenAICompatBackend(base_url, api_key_env, model_id); AnthropicBackend(api_key_env, model_id); CodexCliBackend(command, args); BACKEND_REGISTRY: dict[str, BackendSpec]; resolve_backend(provider_id: str, secrets: dict[str,str]) -> BackendSpec (raises BackendLockedError if api-backed and key empty). harness/secrets_store.py: SECRETS_PATH(state_dir) -> Path; load_secrets(state_dir) -> dict[str,str]; save_secret(state_dir, key_name, value) -> None; delete_secret(state_dir, key_name) -> None."
---

# Title

NEW model-backend registry unifying every selectable backend behind one stable spec — a single OpenAI-style client parameterized by (base_url, api_key_env, model_id) covering OpenAI + Gemini-OpenAI-endpoint + the 5 Chinese providers, an Anthropic SDK backend, and a codex-CLI backend mirroring the existing CLI-agent integration — plus a gitignored, 0600 secrets store.

# Scope

Create NEW `harness/model_backends.py` and NEW `harness/secrets_store.py`.

**model_backends.py:**
- `OpenAICompatBackend(base_url, api_key_env, model_id)` — ONE class for every OpenAI-API-compatible provider; stores the triple and exposes `client()` building an OpenAI client with `base_url` + the key read from `os.environ` (or injected secrets). Covers OpenAI (`https://api.openai.com/v1`), Gemini OpenAI endpoint, and the 5 Chinese providers (base URLs + env vars verbatim from `_autowork_scratch/CHINESE_API_RESEARCH.md`).
- `AnthropicBackend(api_key_env, model_id)` — uses the Anthropic SDK pattern (its own client), NOT the OpenAI-compat path.
- `CodexCliBackend(command, args)` — a CLI-invoked backend mirroring `harness/orchestrator.py:_build_agent_command`'s generic `{command, args}` contract (same shape as the existing `claude`/`gemini`/`antigravity` agent blocks), so the orchestrator can later spawn it identically. Provide `agent_block() -> {"command": ..., "args": [...]}` returning the dict an owner would paste into `config.yaml agents.codex`.
- `BACKEND_REGISTRY: dict[provider_id -> BackendSpec]` enumerating all backends (cli: claude/gemini/antigravity/codex; openai-compat: openai/gemini_api/deepseek/moonshot/zhipu/qwen/minimax; anthropic: anthropic).
- `resolve_backend(provider_id, secrets)` — returns the spec; raises `BackendLockedError` if the backend is api-backed and its key is empty in `secrets`/env (the lock enforced server-side at resolution time too).

**secrets_store.py:**
- Persist API keys in gitignored `state/secrets/api_keys.json` (`.gitignore` already ignores `state/`); `SECRETS_PATH(state_dir)` returns the path; `save_secret` writes the file with mode 0600 (and 0700 dir) creating parents; `load_secrets` returns `{}` if absent; `delete_secret` removes a key. Never write a key into config.yaml or any tracked file.

# Non-Goals

No live network call / no real `.chat()` / `.messages.create()` assertion — build and inspect specs and clients only (the `openai`/`anthropic` packages may be absent; `client()` may raise ImportError at call time and the oracle must NOT call it against a live endpoint). No WebUI/template code. No edits to any `_NEVER_AUTO_APPROVE` file; do NOT wire codex into `harness/orchestrator.py` or `config.yaml` (owner-gated hand-edit — this leaf only produces the spec + the `agent_block()` dict). No secret committed to git. NEW files: single whole-file modules; oracles validate against NotImplementedError stubs.

# Inputs

- CLI-agent spawn contract: `harness/orchestrator.py:_build_agent_command` (generic over `config['agents'][name] = {command, args}`) and the existing `config.yaml agents:` blocks (claude/gemini/antigravity) as the shape codex must mirror.
- Providers/base-urls/env-vars: `_autowork_scratch/CHINESE_API_RESEARCH.md` (verbatim).
- Gitignore: `.gitignore` ignores `state/`.
- Committed oracle (contract): `tests/webui/test_model_backends.py`.

# Deliverables

ONE GREEN leaf: `harness/model_backends.py` + `harness/secrets_store.py` verified by `python -m pytest tests/webui/test_model_backends.py -q`. Frozen surface exactly as the frontmatter `interfaces`. Oracle is RED against stubs and asserts: every Chinese + frontier provider present with correct base_url+env from the research file; one `OpenAICompatBackend` class instance per openai-compat provider (no per-provider subclasses); Anthropic uses its own backend kind; `CodexCliBackend.agent_block()` matches the claude/gemini `{command, args}` shape; `resolve_backend` raises `BackendLockedError` for a keyless api-backed provider and returns a spec when keyed; `save_secret` writes a 0600 gitignored file under `state/secrets/` that `load_secrets` reads back, and the secrets path is under a `state/`-ignored tree (never config.yaml).
