"""RED-first oracle for harness/model_backends.py + harness/secrets_store.py
(leaf: webui-model-backends).

Constrains:
  - the OpenAI-compatible providers (OpenAI + Gemini-OpenAI + 5 Chinese) are all
    served by ONE OpenAICompatBackend class parameterized by
    (base_url, api_key_env, model_id) -- no per-provider subclasses
  - Anthropic uses its own backend kind; codex is a CLI backend whose agent_block()
    mirrors the existing {command, args} agent contract
  - resolve_backend enforces the provider-lock (raises for keyless api-backed)
  - secrets persist to a gitignored, 0600 state/secrets/ file, never config.yaml

Must FAIL against a NotImplementedError stub.
"""
import importlib
import os
import stat

import pytest

mb = importlib.import_module("harness.model_backends")
ss = importlib.import_module("harness.secrets_store")

# (provider_id, expected base_url substring, env var) from CHINESE_API_RESEARCH.md
OPENAI_COMPAT = {
    "deepseek": ("api.deepseek.com", "DEEPSEEK_API_KEY"),
    "moonshot": ("api.moonshot.ai", "MOONSHOT_API_KEY"),
    "zhipu": ("z.ai", "ZHIPU_API_KEY"),
    "qwen": ("dashscope", "DASHSCOPE_API_KEY"),
    "minimax": ("api.minimax.io", "MINIMAX_API_KEY"),
    "openai": ("api.openai.com", "OPENAI_API_KEY"),
}


def test_registry_surface():
    for sym in ("BACKEND_REGISTRY", "OpenAICompatBackend", "AnthropicBackend",
                "CodexCliBackend", "resolve_backend", "BackendSpec"):
        assert hasattr(mb, sym), f"missing {sym}"


def test_all_openai_compat_providers_registered_with_correct_endpoint():
    for pid, (url_sub, env) in OPENAI_COMPAT.items():
        assert pid in mb.BACKEND_REGISTRY, f"{pid} not registered"
        spec = mb.BACKEND_REGISTRY[pid]
        assert url_sub in (spec.base_url or ""), f"{pid} base_url {spec.base_url!r}"
        assert spec.api_key_env == env, f"{pid} env {spec.api_key_env!r}"


def test_openai_compat_is_a_single_parameterized_class():
    # Build two different providers and assert they are the SAME class instance type
    # (one client class parameterized by the triple, not bespoke subclasses).
    a = mb.OpenAICompatBackend("https://api.deepseek.com", "DEEPSEEK_API_KEY", "deepseek-v4-pro")
    b = mb.OpenAICompatBackend("https://api.minimax.io/v1", "MINIMAX_API_KEY", "minimax-m2.5")
    assert type(a) is type(b) is mb.OpenAICompatBackend
    assert a.base_url != b.base_url and a.api_key_env != b.api_key_env


def test_anthropic_is_its_own_backend_kind():
    assert "anthropic" in mb.BACKEND_REGISTRY
    spec = mb.BACKEND_REGISTRY["anthropic"]
    # Anthropic is NOT served by the openai-compat path.
    assert spec.kind != mb.BACKEND_REGISTRY["openai"].kind
    assert spec.api_key_env == "ANTHROPIC_API_KEY"


def test_codex_cli_backend_mirrors_agent_block_shape():
    assert "codex" in mb.BACKEND_REGISTRY
    cb = mb.CodexCliBackend("/path/to/codex", ["-p"])
    block = cb.agent_block()
    # Same shape the orchestrator's _build_agent_command consumes for claude/gemini.
    assert set(block.keys()) >= {"command", "args"}
    assert isinstance(block["args"], list)


def test_resolve_backend_enforces_provider_lock():
    with pytest.raises(Exception) as ei:
        mb.resolve_backend("deepseek", secrets={})  # keyless api-backed -> locked
    assert "Locked" in type(ei.value).__name__ or "lock" in str(ei.value).lower()
    # keyed -> resolves
    spec = mb.resolve_backend("deepseek", secrets={"DEEPSEEK_API_KEY": "sk-x"})
    assert spec.provider_id == "deepseek"
    # a CLI backend never needs a key
    cli = mb.resolve_backend("claude", secrets={})
    assert cli.provider_id == "claude"


def test_secrets_store_is_gitignored_and_0600(tmp_path):
    state_dir = tmp_path / "state"
    path = ss.SECRETS_PATH(state_dir)
    # Must live under a state/ tree (which .gitignore ignores), never config.yaml.
    assert "state" in str(path) and path.name.endswith(".json")
    assert "config.yaml" not in str(path)
    ss.save_secret(state_dir, "DEEPSEEK_API_KEY", "sk-secret")
    loaded = ss.load_secrets(state_dir)
    assert loaded["DEEPSEEK_API_KEY"] == "sk-secret"
    mode = stat.S_IMODE(os.stat(path).st_mode)
    assert mode & 0o077 == 0, f"secrets file is group/world accessible: {oct(mode)}"


def test_load_secrets_absent_returns_empty(tmp_path):
    assert ss.load_secrets(tmp_path / "nope") == {}
