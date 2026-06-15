---
complexity_score: 3
dependencies:
  - "webui-config-schema"
  - "webui-model-backends"
  - "webui-typed-widgets"
  - "webui-fs-browse"
interfaces: "tests/webui/test_typed_config_e2e.py exercises the full WebUI typed-config surface end-to-end through the LIVE stdlib-http.server sidecar (tools/webui_server.py spun up in a thread on an ephemeral port, ControlHandlers pointed at a sandbox repo_root/state_dir): valid POST /api/config/typed persists atomically; invalid-type / dual-agent-same / role->keyless-provider saves are rejected with field_errors and leave config untouched; a keyed provider unlocks and the key lands ONLY in the gitignored state/secrets store; GET /api/fs/list serves + sandboxes a path field; the mutation keeps the operator-token + CSRF posture."
---

# Title

End-to-end integration leaf: drive the assembled typed-config WebUI (schema + backends + typed widgets + fs-browse) through the REAL stdlib-http.server operator sidecar (`tools/webui_server.py`) to prove the save/validation/lock/sandbox matrix holds across all four upstream leaves together. This targets the LIVE WebUI, NOT the dead Flask tree `webui/app.py`.

# Scope

NEW `tests/webui/test_typed_config_e2e.py` — the integration oracle that wires the four upstream surfaces together end-to-end on the live sidecar. Spin up `tools.webui_server.WebUIServer` in a daemon thread on an ephemeral port (mirroring `tests/integration/test_webui_server.py`), construct `ControlHandlers(state_dir, logs_dir, repo_root=<tmp>)` and assign it to `server.control` so `harness/config.yaml` and `state/secrets` resolve under a tmp sandbox (the live config + secrets are never touched). Drive it with `urllib.request`, obtaining the operator token via `webui_auth.load_or_mint_token(state_dir)` and a fresh CSRF nonce via `GET /api/csrf` for each mutation. Assert the full matrix:
1. A fully-valid typed save (good ints, distinct dual agents, CLI providers) `POST /api/config/typed` returns 200 and atomically updates `harness/config.yaml`; unrelated config blocks survive.
2. An invalid-type save (e.g. `parallel_cap="x"`) returns 400, names the field in `field_errors`, and leaves `config.yaml` byte-identical.
3. A dual-agent-same save (`synthesis.active_agents=[claude,claude]`) returns 400.
4. A role→keyless-api-provider save (e.g. `overseer.default_backend=deepseek` with no key) returns 400; THEN posting the provider's `api_key__DEEPSEEK_API_KEY` field and re-saving the same assignment returns 200 (the key unlocks the provider); the key is found ONLY in the gitignored `state/secrets/` store (`harness.secrets_store.load_secrets`) — never in `config.yaml`, never echoed in the response.
5. `GET /api/fs/list` (no path) returns sandboxed entries; a traversal path (`?path=../..`) is refused (4xx).
6. The `POST /api/config/typed` mutation requires the operator token + CSRF (an unauthenticated POST returns 401/403).

# Non-Goals

No production code edits — this leaf is the test only (it consumes the four upstream leaves). No live LLM/API network call. No Flask, no `webui/app.py`, no Flask test client — drive the real stdlib sidecar via `urllib.request`. No edits to any `_NEVER_AUTO_APPROVE` file. This is the integration test: it is allowed (and required) to exercise multiple modules together.

# Inputs

- Assembled surfaces from upstream leaves: `tools/webui_control.py` handlers `post_save_typed_config`, `get_config_schema`, `get_fs_list` (+ dispatch-table entry for `/api/config/typed`); `tools/webui_server.py` `_dispatch_get` routes `/api/config/schema`, `/api/fs/list`; `harness/webui_config_schema.py`; `harness/model_backends.py`; `harness/secrets_store.py`.
- Sidecar-in-a-thread + sandbox pattern from `tests/integration/test_webui_server.py`: `_free_port()`, `srv.build_tailer`, `srv.WebUIServer(...)`, `server.control = ControlHandlers(state_dir, logs_dir, repo_root=tmp)`, `webui_auth.load_or_mint_token`, `GET /api/csrf` for the nonce, `urllib.request` GET/POST helpers, teardown via `server.shutdown()`/`server.server_close()`/`tailer.stop()`.
- Committed oracle (this file is its own contract): `tests/webui/test_typed_config_e2e.py`.

# Deliverables

ONE GREEN leaf: `python -m pytest tests/webui/test_typed_config_e2e.py -q`. Proves the full save/reject/unlock/sandbox matrix end-to-end against the live sidecar across the four upstream leaves: valid atomic persist; invalid-type per-field reject with config untouched; dual-agent-same reject; keyless-provider reject then key-unlock with the secret only in the gitignored store and never echoed; fs-browse serves + sandboxes; and the typed-save keeps the operator-token + CSRF posture. Depends on all of `webui-config-schema`, `webui-model-backends`, `webui-typed-widgets`, `webui-fs-browse`.
