---
complexity_score: 5
dependencies: ["webui-config-schema"]
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

No live network call / no real `.chat()` / `.messages.create()` assertion — build and inspect specs and clients only (the `openai`/`anthropic` packages may be absent; `client()` may raise ImportError at call time and the oracle must NOT call it against a live endpoint). No WebUI/template code. No edits to any `_NEVER_AUTO_APPROVE` file; do NOT wire codex into `harness/orchestrator.py` or `config.yaml` (owner-gated hand-edit — this leaf only produces the spec + the `agent_block()` dict). No secret committed to git. The ONLY additional edit beyond the two new modules is a minimal additive live-wiring reference inside `harness/webui_config_schema.py` (see Required plan shape; that module is already root-reachable once `webui-config-schema` has landed) — a new top-level import + a thin reference, never a change to any existing symbol there.

# Inputs

- CLI-agent spawn contract: `harness/orchestrator.py:_build_agent_command` (generic over `config['agents'][name] = {command, args}`) and the existing `config.yaml agents:` blocks (claude/gemini/antigravity) as the shape codex must mirror.
- Providers/base-urls/env-vars: `_autowork_scratch/CHINESE_API_RESEARCH.md` (verbatim).
- Gitignore: `.gitignore` ignores `state/`.
- Committed oracle (contract): `tests/webui/test_model_backends.py`.

# Deliverables

ONE GREEN leaf: `harness/model_backends.py` + `harness/secrets_store.py` verified by `python -m pytest tests/webui/test_model_backends.py -q`. Frozen surface exactly as the frontmatter `interfaces`. Oracle is RED against stubs and asserts: every Chinese + frontier provider present with correct base_url+env from the research file; one `OpenAICompatBackend` class instance per openai-compat provider (no per-provider subclasses); Anthropic uses its own backend kind; `CodexCliBackend.agent_block()` matches the claude/gemini `{command, args}` shape; `resolve_backend` raises `BackendLockedError` for a keyless api-backed provider and returns a spec when keyed; `save_secret` writes a 0600 gitignored file under `state/secrets/` that `load_secrets` reads back, and the secrets path is under a `state/`-ignored tree (never config.yaml).

# Required plan shape

This leaf DEPENDS ON `webui-config-schema` (declared in frontmatter `dependencies`) so that `harness/webui_config_schema.py` has already landed and is root-reachable (it was anchored into `harness/control_gate.py ← harness/orchestrator.py` by that leaf) before this leaf runs.

The plan MUST be a single working_dir (this repo; `working_dir` null) DAG of EXACTLY THREE tasks. Two new `.py` modules are created (`harness/model_backends.py`, `harness/secrets_store.py`); both are under the SENSITIVE `harness/**` apply-glob, so the impl task MUST use `meta_task_type: "harness_self_fix"` (the only non-test type permitted to commit a `harness/**` path — any other type is rejected at plan time with `sensitive_files_touched`). The integration wiring into the WebUI / config.yaml / orchestrator is genuinely DEFERRED to the dependent `webui-typed-widgets` leaf and an owner-gated hand-edit, so the impl task EXCUSES the integration-test gate by listing the literal word "integration" in `spec.non_goals`.

**LIVE-WIRING ANCHOR (deadlock break).** A NEW `harness/**` module is rejected at acceptance with `orphan_unwired` (`harness/wire_up.py:check_wired`) unless it is reachable from a LIVE_ROOT. The UI leaf that would import these backends lives under `tools/` (NOT a root) and is dep-gate-held behind this leaf, so this leaf MUST supply the live importers itself. Because `webui-config-schema` has landed, `harness/webui_config_schema.py` is now root-reachable, so the impl task uses it as the anchor:

- Add into `harness/webui_config_schema.py` a module-level `from harness import model_backends` plus a thin, ADDITIVE reference (never patch an existing symbol there) — e.g. populate the model-role provider enum `choices` from `model_backends.list_backends()` (or, if a trailing top-level statement is cleaner, a NEW `def backend_choices(): return list(model_backends.BACKEND_REGISTRY)` referenced where the provider field's choices are built). This makes `model_backends ← webui_config_schema ← control_gate ← orchestrator (root)`.
- Inside `harness/model_backends.py`, add `from harness import secrets_store` plus a real light use (e.g. `resolve_backend` reads injected keys via `secrets_store.load_secrets(...)` falling back to env). This makes `secrets_store ← model_backends ← webui_config_schema ← control_gate ← orchestrator (root)`.

Both edits MUST be additive (never-patch-existing-class-methods; ride new imports/functions as trailing top-level nodes). Each created module is proven by its own paired `test_authoring` oracle whose top-level `mutation_target` (bare dotted module-under-test) resolves to that impl's `.py` (the auto-authored, mutation-gated oracle IS the contract proof). In ADDITION, because this leaf supplies its own root-anchors, the oracle MUST carry explicit wiring assertions for BOTH new modules so the deadlock-break is verified in-band:

```python
def test_model_backends_modules_are_wired():
    from pathlib import Path
    from harness.wire_up import check_wired
    assert check_wired(Path('.'), 'harness/model_backends.py').wired is True
    assert check_wired(Path('.'), 'harness/secrets_store.py').wired is True
```

Emit these tasks verbatim in shape:

1. `task_id: "model-backends-impl"`
   - `meta_task_type: "harness_self_fix"`
   - `files_touched: ["harness/model_backends.py", "harness/secrets_store.py", "harness/webui_config_schema.py"]`
   - `dependencies: []`  (the BRIEF-level frontmatter `dependencies: ["webui-config-schema"]` orders this leaf after config-schema lands; this is the intra-plan task DAG)
   - `verification_command: "python -m pytest tests/webui/test_model_backends.py -q"`  (NO leading/embedded `cd `)
   - This task creates the whole-file `harness/model_backends.py` and `harness/secrets_store.py`, AND makes MINIMAL ADDITIVE live-wiring edits: (a) inside `harness/model_backends.py` add `from harness import secrets_store` + a real use in `resolve_backend`; (b) inside the already-landed root-reachable `harness/webui_config_schema.py` add `from harness import model_backends` + a thin additive reference (e.g. provider enum `choices` from `model_backends`). Do NOT modify any existing symbol in `webui_config_schema.py`; ride the new import + reference as trailing additive nodes. This anchors both new modules to a LIVE_ROOT.
   - `spec.non_goals` MUST include a line containing the word **integration**, e.g. "Integration wiring into the WebUI, config.yaml, and orchestrator is OUT OF SCOPE here — deferred to the dependent webui-typed-widgets leaf and an owner-gated hand-edit; this leaf only produces the spec + agent_block() dict plus the minimal additive live-wiring references that anchor the new modules to a root."

2. `task_id: "model-backends-oracle"`
   - `meta_task_type: "test_authoring"`
   - top-level `mutation_target: "harness.model_backends"`
   - `files_touched: ["tests/webui/test_model_backends.py"]`
   - `dependencies: ["model-backends-impl"]`  (oracle depends on impl — impl-first ordering)
   - `verification_command: "python -m pytest tests/webui/test_model_backends.py -q"`

3. `task_id: "secrets-store-oracle"`
   - `meta_task_type: "test_authoring"`
   - top-level `mutation_target: "harness.secrets_store"`
   - `files_touched: ["tests/webui/test_model_backends.py"]`
   - `dependencies: ["model-backends-impl"]`
   - `verification_command: "python -m pytest tests/webui/test_model_backends.py -q"`

One of the two oracle tasks above MUST include the explicit dual wiring assertion shown in the Required plan shape (`check_wired(...,'harness/model_backends.py').wired is True` and `check_wired(...,'harness/secrets_store.py').wired is True`) so both new modules' root-anchoring is verified in-band alongside the backend/secrets contracts.

Note: `mutation_target` is a BARE DOTTED module name (no path, no slashes, no `.py`). `harness.model_backends` resolves to `harness/model_backends.py` and `harness.secrets_store` to `harness/secrets_store.py`, both in the impl task's `files_touched` — this satisfies the paired-auto-oracle wiring exemption for each created module.
