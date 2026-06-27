# Adversarial verify: commit 41685dc "model-backends DONE"

## 1. Oracle re-run: 9 passed (PASS). One SyntaxWarning (invalid escape in docstring, cosmetic).

## 2. Oracle ADEQUACY — PARTIAL
(a) resolve_backend RAISING when key absent: COVERED (test_resolve_backend_enforces_provider_lock, deepseek secrets={} -> BackendLockedError; keyed resolves; CLI 'claude' resolves keyless).
(b) agent_block() output shape: ONLY CodexCliBackend.agent_block() (the METHOD) is tested. The MODULE-LEVEL agent_block(provider_id) function (lines 123-129) is NEVER tested — its api-backend branch {base_url,model,api_key_env} is wholly unexercised.
(c) every provider base_url + api_key_env: NO. Only 6 openai-compat providers checked (deepseek,moonshot,zhipu,qwen,minimax,openai). gemini_api endpoint/env UNTESTED. anthropic only env checked. CLI backends (claude,gemini,antigravity,codex) command/args UNTESTED. model_id-is-None invariant NEVER asserted.
GAPS: module-level agent_block() untested; gemini_api untested; CLI command/args untested; client() (openai/anthropic SDK lazy import) untested; secrets_store_safe_load degrade-path untested; save_secret chmod-before-write race not caught.

## 3. Registry: 12 entries CONFIRMED (openai, gemini_api, deepseek, moonshot, zhipu, qwen, minimax, anthropic, claude, gemini, antigravity, codex). model_id defaults None on BackendSpec; no registry entry sets model_id => all None CONFIRMED (but NOT oracle-asserted).

## 4. GREEN-BUT-DEAD — CONFIRMED DEAD
Only importer = harness/control_gate.py:140 `from harness import model_backends`, used solely by `backend_choices()` (line 142-143) which returns `list(BACKEND_REGISTRY)` (keys only).
- backend_choices() has ZERO callers anywhere (grep clean).
- resolve_backend, agent_block, OpenAICompatBackend.client, AnthropicBackend.client, CodexCliBackend.agent_block, secrets_store.save_secret/has_secret/delete_secret: ZERO runtime callers.
- git_integration.py "agent_block" hits are a local var `agent_block_ids` — FALSE POSITIVE, unrelated.
wire_up oracle passes because check_wired tests IMPORT-REACHABILITY only (control_gate<-orchestrator LIVE_ROOT), NOT call-reachability. Module is import-live, functionally inert.

## 5. secrets_store.py EXISTS. SECRETS_PATH = state_dir/'secrets'/'api_keys.json' CONFIRMED. dir chmod 448(0700), file chmod 384(0600) CONFIRMED. Minor: write_text precedes chmod (transient default-umask window).

## VERDICT: GREEN-BUT-DEAD (oracle also INADEQUATE on module-level agent_block + gemini_api + CLI specs)
