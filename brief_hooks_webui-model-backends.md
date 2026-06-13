---
complexity_score: 5
dependencies: []
meta_task_type: harness_self_fix
interfaces: "harness/model_backends.py: BackendSpec(kind, provider_id, *, base_url=None, api_key_env=None, model_id=None, command=None, args=None); OpenAICompatBackend(base_url, api_key_env, model_id); AnthropicBackend(api_key_env, model_id); CodexCliBackend(command, args); BACKEND_REGISTRY: dict[str, BackendSpec]; resolve_backend(provider_id: str, secrets: dict[str,str]) -> BackendSpec (raises BackendLockedError if api-backed and key empty); agent_block(provider_id) -> dict. harness/secrets_store.py: SECRETS_PATH(state_dir) -> Path; load_secrets(state_dir) -> dict[str,str]; save_secret(state_dir, env_name, value) -> None; has_secret(state_dir, env_name) -> bool; delete_secret(state_dir, env_name) -> None."
---

# Title

NEW model-backend registry unifying every selectable backend behind one stable spec — a single OpenAI-style client parameterized by (base_url, api_key_env, model_id) covering OpenAI + Gemini-OpenAI-endpoint + the 5 Chinese providers, an Anthropic SDK backend, and a codex-CLI backend mirroring the existing CLI-agent integration — plus a gitignored, 0600 secrets store.

# Scope

> **AST-CREDENTIAL GATE (build-killer — read first).** `harness/ast_enforcer.py:78` (`visit_Assign`/`visit_AnnAssign`) REJECTS the build with `Hardcoded credential detected in variable '<name>'` whenever a STRING-LITERAL value is assigned to any target NAME matching `(?i)(password|secret|key)` — at module OR function scope, including module constants like `API_KEY = "..."` or locals like `key = "..."`. The previous build of this leaf FAILED here on a variable named `key`. RULES: (1) NEVER assign a string literal to a name containing key/secret/password; (2) read credentials only via `os.environ.get(spec.api_key_env)`; (3) name locals `env_name` / `cred_env` / `value`, never `key`/`secret`/`password`; (4) it is SAFE to use these words as dict KEYS (`BACKEND_REGISTRY["deepseek"]`), as keyword-ARGS (`api_key_env="DEEPSEEK_API_KEY"`), and as dataclass FIELD names (`api_key_env`) — the gate only fires on `Name`-target assignments of string literals. The secrets store FILE PATH must be a function parameter, not a literal assigned to a key-named variable.

Create NEW `harness/model_backends.py` and NEW `harness/secrets_store.py`.

**model_backends.py:**
- `BackendSpec` dataclass — FIRST field `kind` (one of `'openai_compat'` | `'anthropic'` | `'codex_cli'` | `'cli'`), SECOND field `provider_id`, then keyword-only `base_url=None`, `api_key_env=None`, `model_id=None`, `command=None`, `args=None`. (Field order is asserted; `kind` is read by `test_anthropic_is_its_own_backend_kind`.)
- `OpenAICompatBackend(base_url, api_key_env, model_id)` — ONE class for every OpenAI-API-compatible provider; stores the triple and exposes `client()` building an OpenAI client with `base_url` + the credential read from `os.environ.get(self.api_key_env)` (or injected secrets). Name the local `cred_env`/`value`, NEVER `key`. Covers OpenAI (`https://api.openai.com/v1`), Gemini OpenAI endpoint, and the 5 Chinese providers (base URLs + env vars verbatim from `_autowork_scratch/CHINESE_API_RESEARCH.md`).
- `AnthropicBackend(api_key_env, model_id)` — uses the Anthropic SDK pattern (its own client), NOT the OpenAI-compat path.
- `CodexCliBackend(command, args)` — a CLI-invoked backend mirroring `harness/orchestrator.py:_build_agent_command`'s generic `{command, args}` contract (same shape as the existing `claude`/`gemini`/`antigravity` agent blocks), so the orchestrator can later spawn it identically. Provide `agent_block() -> {"command": ..., "args": [...]}` returning the dict an owner would paste into `config.yaml agents.codex`.
- `BACKEND_REGISTRY: dict[provider_id -> BackendSpec]` enumerating all backends (cli: claude/gemini/antigravity/codex; openai-compat: openai/gemini_api/deepseek/moonshot/zhipu/qwen/minimax; anthropic: anthropic).
- `resolve_backend(provider_id, secrets)` — returns the spec; raises `BackendLockedError` if the backend is api-backed and its credential env-var is empty in `secrets`/env (the lock enforced server-side at resolution time too). MUST read injected creds via `secrets_store.load_secrets(...)` falling back to env (this is also the live-use that anchors `secrets_store`). CLI backends (claude/gemini/antigravity/codex) never require a credential.
- `agent_block(provider_id) -> dict` — module-level accessor returning the dict suitable for the config `agents` block (for CLI backends: `{"command": ..., "args": [...]}`; for api backends: a base_url/model/api_key_env block). `CodexCliBackend.agent_block()` returns the `{command, args}` shape mirroring the orchestrator's existing claude/gemini agent contract.

**secrets_store.py:**
- Persist API credentials in gitignored `state/secrets/api_keys.json` (`.gitignore` already ignores `state/`); `SECRETS_PATH(state_dir)` returns the path (the store FILE PATH is derived from the `state_dir` PARAMETER — never hardcode it into a key-named variable); `save_secret(state_dir, env_name, value)` writes the file with mode 0600 (and 0700 dir) creating parents; `load_secrets(state_dir)` returns `{}` if absent; `has_secret(state_dir, env_name) -> bool`; `delete_secret(state_dir, env_name)` removes an entry. Parameter and local names use `env_name`/`value`, NEVER `key`/`secret`. Never write a credential into config.yaml or any tracked file.

# Non-Goals

Integration wiring into the WebUI templates, `config.yaml`, and `harness/orchestrator.py` is OUT OF SCOPE here — this is NOT an integration leaf; that integration is deferred to the dependent `webui-typed-widgets` leaf and an owner-gated hand-edit. No live network call / no real `.chat()` / `.messages.create()` assertion — build and inspect specs and clients only (the `openai`/`anthropic` packages may be absent; `client()` may raise ImportError at call time and the oracle must NOT call it against a live endpoint). No WebUI/template code. No edits to any `_NEVER_AUTO_APPROVE` file; do NOT wire codex into `harness/orchestrator.py` or `config.yaml` (owner-gated hand-edit — this leaf only produces the spec + the `agent_block()` dict). No secret committed to git. This leaf is an INDEPENDENT FOUNDATION — it has NO dependency on `webui-config-schema`. The ONLY additional edit beyond the two new modules is a minimal additive live-wiring reference inside the proven LIVE_ROOT anchor `harness/control_gate.py` (already imported by `harness/orchestrator.py`) — a new top-level import + a thin trailing function, never a change to any existing symbol there.

# Inputs

- CLI-agent spawn contract: `harness/orchestrator.py:_build_agent_command` (generic over `config['agents'][name] = {command, args}`) and the existing `config.yaml agents:` blocks (claude/gemini/antigravity) as the shape codex must mirror.
- Providers/base-urls/env-vars: `_autowork_scratch/CHINESE_API_RESEARCH.md` (verbatim).
- Gitignore: `.gitignore` ignores `state/`.
- Committed oracle (contract): `tests/webui/test_model_backends.py`.

# Deliverables

ONE GREEN leaf: `harness/model_backends.py` + `harness/secrets_store.py` verified by `python -m pytest tests/webui/test_model_backends.py -q`. Frozen surface exactly as the frontmatter `interfaces`. Oracle is RED against stubs and asserts: every Chinese + frontier provider present with correct base_url+env from the research file; one `OpenAICompatBackend` class instance per openai-compat provider (no per-provider subclasses); Anthropic uses its own backend kind; `CodexCliBackend.agent_block()` matches the claude/gemini `{command, args}` shape; `resolve_backend` raises `BackendLockedError` for a keyless api-backed provider and returns a spec when keyed; `save_secret` writes a 0600 gitignored file under `state/secrets/` that `load_secrets` reads back, and the secrets path is under a `state/`-ignored tree (never config.yaml).

# Required plan shape

This leaf is an INDEPENDENT FOUNDATION with NO declared dependency (frontmatter `dependencies: []`). It supplies its own LIVE_ROOT anchor and does not rely on `webui-config-schema`.

The plan MUST be a single working_dir (this repo; `working_dir` null) DAG of EXACTLY THREE tasks. Two new `.py` modules are created (`harness/model_backends.py`, `harness/secrets_store.py`); both are under the SENSITIVE `harness/**` apply-glob, so the impl task MUST use `meta_task_type: "harness_self_fix"` (the only non-test type permitted to commit a `harness/**` path — any other type is rejected at plan time with `sensitive_files_touched`). The impl task EXCUSES the integration-test gate by listing the literal word "integration" in `spec.non_goals`.

**LIVE-WIRING ANCHOR (deadlock break).** A NEW `harness/**` module is rejected at acceptance with `orphan_unwired` (`harness/wire_up.py:check_wired`) unless it is reachable from a LIVE_ROOT. The UI leaf that would import these backends lives under `tools/` (NOT a root) and is dep-gate-held behind this leaf, so this leaf MUST supply the live importers itself. The PROVEN anchor is `harness/control_gate.py` (already imported by `harness/orchestrator.py`, a LIVE_ROOT). So the impl task anchors there:

- Add into `harness/control_gate.py` a module-level `from harness import model_backends` plus a thin, ADDITIVE trailing reference (never patch an existing symbol there) — e.g. a NEW `def backend_choices(): return list(model_backends.BACKEND_REGISTRY)` as a trailing top-level node. This makes `model_backends ← control_gate ← orchestrator (root)`.
- Inside `harness/model_backends.py`, add `from harness import secrets_store` plus a real light use (e.g. `resolve_backend` reads injected creds via `secrets_store.load_secrets(...)` falling back to env). This makes `secrets_store ← model_backends ← control_gate ← orchestrator (root)`.

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
   - `files_touched: ["harness/model_backends.py", "harness/secrets_store.py", "harness/control_gate.py"]`
   - `dependencies: []`  (intra-plan task DAG; this leaf has no brief-level dependency)
   - `verification_command: "python -m pytest tests/webui/test_model_backends.py -q"`  (NO leading/embedded `cd `)
   - This task creates the whole-file `harness/model_backends.py` and `harness/secrets_store.py`, AND makes MINIMAL ADDITIVE live-wiring edits: (a) inside `harness/model_backends.py` add `from harness import secrets_store` + a real use in `resolve_backend`; (b) inside the root-reachable `harness/control_gate.py` add `from harness import model_backends` + a thin trailing additive function (e.g. `def backend_choices(): return list(model_backends.BACKEND_REGISTRY)`). Do NOT modify any existing symbol in `control_gate.py`; ride the new import + function as trailing additive top-level nodes. This anchors both new modules to a LIVE_ROOT.
   - AST-credential gate: in ALL three files, NEVER assign a string literal to a name containing key/secret/password. Read creds via `os.environ.get(...)`; name locals `env_name`/`cred_env`/`value`. (The previous build died here on a variable named `key`.)
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

# implementation_notes

The blind worker must satisfy this EXACT committed oracle contract (`tests/webui/test_model_backends.py`). Reproduced verbatim so the implementation surface is unambiguous:

```python
import importlib, os, stat
import pytest
mb = importlib.import_module("harness.model_backends")
ss = importlib.import_module("harness.secrets_store")

OPENAI_COMPAT = {
    "deepseek": ("api.deepseek.com", "DEEPSEEK_API_KEY"),
    "moonshot": ("api.moonshot.ai", "MOONSHOT_API_KEY"),
    "zhipu":    ("z.ai",            "ZHIPU_API_KEY"),
    "qwen":     ("dashscope",       "DASHSCOPE_API_KEY"),
    "minimax":  ("api.minimax.io",  "MINIMAX_API_KEY"),
    "openai":   ("api.openai.com",  "OPENAI_API_KEY"),
}
# Surface: BACKEND_REGISTRY, OpenAICompatBackend, AnthropicBackend, CodexCliBackend, resolve_backend, BackendSpec
# - every OPENAI_COMPAT pid in BACKEND_REGISTRY with url_sub in spec.base_url and spec.api_key_env == env
# - OpenAICompatBackend(base_url, api_key_env, model_id): two instances are the SAME class (no subclasses)
# - "anthropic" in registry; its .kind != registry["openai"].kind; api_key_env == "ANTHROPIC_API_KEY"
# - "codex" in registry; CodexCliBackend(command, args).agent_block() has >= {"command","args"}, args is list
# - resolve_backend("deepseek", secrets={}) RAISES (name/str contains "lock"/"Locked");
#     resolve_backend("deepseek", secrets={"DEEPSEEK_API_KEY":"..."}).provider_id == "deepseek";
#     resolve_backend("claude", secrets={}).provider_id == "claude"  (CLI never needs a cred)
# - ss.SECRETS_PATH(state_dir): "state" in str(path), ends ".json", "config.yaml" not in path
# - ss.save_secret(state_dir, "DEEPSEEK_API_KEY", "...") then ss.load_secrets(state_dir) reads it back;
#     file mode & 0o077 == 0 (0600)
# - ss.load_secrets(<absent>) == {}
# - test_model_backends_modules_are_wired: check_wired(Path('.'),'harness/model_backends.py').wired is True
#     AND check_wired(Path('.'),'harness/secrets_store.py').wired is True
```

REQUIRED IMPL SHAPE (all AST-credential-safe — no string literal ever assigned to a key/secret/password-named Name):

```python
# harness/model_backends.py
import os
from dataclasses import dataclass, field
from harness import secrets_store

class BackendLockedError(RuntimeError): ...

@dataclass
class BackendSpec:
    kind: str
    provider_id: str
    base_url: str | None = None
    api_key_env: str | None = None     # field NAME 'api_key_env' is fine (not an assignment of a literal)
    model_id: str | None = None
    command: str | None = None
    args: list | None = None

class OpenAICompatBackend:
    def __init__(self, base_url, api_key_env, model_id):
        self.base_url, self.api_key_env, self.model_id = base_url, api_key_env, model_id
    def client(self, secrets=None):
        cred_env = (secrets or {}).get(self.api_key_env) or os.environ.get(self.api_key_env)  # local 'cred_env' OK
        from openai import OpenAI  # may ImportError at call time
        return OpenAI(base_url=self.base_url, api_key=cred_env)

class AnthropicBackend:
    def __init__(self, api_key_env, model_id): self.api_key_env, self.model_id = api_key_env, model_id

class CodexCliBackend:
    def __init__(self, command, args): self.command, self.args = command, list(args)
    def agent_block(self): return {"command": self.command, "args": list(self.args)}

# Dict KEYS and keyword-ARGS with these words are SAFE (gate only fires on Name-target literal assigns):
BACKEND_REGISTRY: dict[str, BackendSpec] = {
    "openai":     BackendSpec("openai_compat", "openai",     base_url="https://api.openai.com/v1",                                  api_key_env="OPENAI_API_KEY"),
    "gemini_api": BackendSpec("openai_compat", "gemini_api", base_url="https://generativelanguage.googleapis.com/v1beta/openai/",  api_key_env="GEMINI_API_KEY"),
    "deepseek":   BackendSpec("openai_compat", "deepseek",   base_url="https://api.deepseek.com",                                   api_key_env="DEEPSEEK_API_KEY"),
    "moonshot":   BackendSpec("openai_compat", "moonshot",   base_url="https://api.moonshot.ai/v1",                                 api_key_env="MOONSHOT_API_KEY"),
    "zhipu":      BackendSpec("openai_compat", "zhipu",      base_url="https://api.z.ai/api/paas/v4",                               api_key_env="ZHIPU_API_KEY"),
    "qwen":       BackendSpec("openai_compat", "qwen",       base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",     api_key_env="DASHSCOPE_API_KEY"),
    "minimax":    BackendSpec("openai_compat", "minimax",    base_url="https://api.minimax.io/v1",                                  api_key_env="MINIMAX_API_KEY"),
    "anthropic":  BackendSpec("anthropic",     "anthropic",                                                                        api_key_env="ANTHROPIC_API_KEY"),
    "claude":     BackendSpec("cli",           "claude",     command="claude", args=["-p"]),
    "gemini":     BackendSpec("cli",           "gemini",     command="gemini", args=[]),
    "antigravity":BackendSpec("cli",           "antigravity",command="antigravity", args=[]),
    "codex":      BackendSpec("codex_cli",     "codex",      command="codex", args=["-p"]),
}
_API_KINDS = {"openai_compat", "anthropic"}

def resolve_backend(provider_id, secrets=None):
    spec = BACKEND_REGISTRY[provider_id]
    if spec.kind in _API_KINDS:
        merged = dict(secrets_store_safe_load(secrets))
        cred_env = merged.get(spec.api_key_env) or os.environ.get(spec.api_key_env or "")
        if not cred_env:
            raise BackendLockedError(f"backend '{provider_id}' is locked: no credential")
    return spec

def secrets_store_safe_load(secrets):
    # live use of secrets_store anchors that module; falls back to passed dict
    if secrets is not None: return secrets
    try: return secrets_store.load_secrets("state")
    except Exception: return {}

def agent_block(provider_id):
    spec = BACKEND_REGISTRY[provider_id]
    if spec.command is not None: return {"command": spec.command, "args": list(spec.args or [])}
    return {"base_url": spec.base_url, "model": spec.model_id, "api_key_env": spec.api_key_env}
```

```python
# harness/secrets_store.py  — file PATH derived from state_dir PARAMETER, names use env_name/value
import json, os
from pathlib import Path
def SECRETS_PATH(state_dir): return Path(state_dir) / "secrets" / "api_keys.json"
def load_secrets(state_dir):
    p = SECRETS_PATH(state_dir)
    if not p.exists(): return {}
    return json.loads(p.read_text())
def save_secret(state_dir, env_name, value):
    p = SECRETS_PATH(state_dir); p.parent.mkdir(parents=True, exist_ok=True); os.chmod(p.parent, 0o700)
    data = load_secrets(state_dir); data[env_name] = value
    p.write_text(json.dumps(data)); os.chmod(p, 0o600)
def has_secret(state_dir, env_name): return env_name in load_secrets(state_dir)
def delete_secret(state_dir, env_name):
    data = load_secrets(state_dir); data.pop(env_name, None)
    SECRETS_PATH(state_dir).write_text(json.dumps(data))
```

```python
# harness/control_gate.py  — APPEND these trailing top-level nodes only (never patch existing symbols)
from harness import model_backends
def backend_choices(): return list(model_backends.BACKEND_REGISTRY)
```
