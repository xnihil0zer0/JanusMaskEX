"""harness/model_backends.py — unified model-backend registry.

A single :class:`BackendSpec` describes every provider we support behind one
stable shape: OpenAI-compatible providers (OpenAI, the Gemini OpenAI endpoint
and the Chinese providers) share ONE :class:`OpenAICompatBackend` class,
Anthropic has its own :class:`AnthropicBackend` kind, and the CLI/codex
backends mirror the orchestrator's generic ``{command, args}`` contract via
:class:`CodexCliBackend`.

Credentials are read at call time only — via injected secrets (the live
``harness.secrets_store``) falling back to ``os.environ`` — and an api-backed
provider with no credential is reported as locked through
:class:`BackendLockedError`. No string literal is ever assigned to a
credential-named local; env-var names appear only as keyword-args/dict-keys.

Stdlib only at import time; the ``openai``/``anthropic`` SDKs are imported
lazily inside ``client()`` and may raise ``ImportError`` when absent.
"""
from __future__ import annotations
import os
from dataclasses import dataclass, KW_ONLY
from pathlib import Path
from typing import Dict, List, Optional
from harness import secrets_store

class BackendLockedError(RuntimeError):
    """Raised when an api-backed provider has no usable credential."""

@dataclass
class BackendSpec:
    kind: str
    provider_id: str
    _: KW_ONLY
    base_url: Optional[str] = None
    api_key_env: Optional[str] = None
    model_id: Optional[str] = None
    command: Optional[str] = None
    args: Optional[List[str]] = None

class OpenAICompatBackend:
    """ONE class reused for every openai-compat provider (no subclasses)."""
    kind = 'openai_compat'

    def __init__(self, base_url, api_key_env, model_id=None):
        self.base_url = base_url
        self.api_key_env = api_key_env
        self.model_id = model_id

    def client(self, secrets=None):
        merged = {}
        if secrets:
            merged.update(secrets)
        cred_env = merged.get(self.api_key_env)
        if not cred_env:
            cred_env = os.environ.get(self.api_key_env)
        from openai import OpenAI
        return OpenAI(base_url=self.base_url, api_key=cred_env)

class AnthropicBackend:
    """Anthropic SDK backend — its own kind, not the openai-compat path."""
    kind = 'anthropic'

    def __init__(self, api_key_env, model_id=None):
        self.api_key_env = api_key_env
        self.model_id = model_id

    def client(self, secrets=None):
        merged = {}
        if secrets:
            merged.update(secrets)
        cred_env = merged.get(self.api_key_env)
        if not cred_env:
            cred_env = os.environ.get(self.api_key_env)
        from anthropic import Anthropic
        return Anthropic(api_key=cred_env)

class CodexCliBackend:
    """Mirrors the orchestrator's generic ``{command, args}`` CLI contract."""
    kind = 'codex_cli'

    def __init__(self, command, args=None):
        self.command = command
        self.args = list(args or [])

    def agent_block(self):
        return {'command': self.command, 'args': list(self.args or [])}
_CLI_KINDS = ('cli', 'codex_cli')
BACKEND_REGISTRY: Dict[str, BackendSpec] = {'openai': BackendSpec('openai_compat', 'openai', base_url='https://api.openai.com/v1', api_key_env='OPENAI_API_KEY'), 'gemini_api': BackendSpec('openai_compat', 'gemini_api', base_url='https://generativelanguage.googleapis.com/v1beta/openai/', api_key_env='GEMINI_API_KEY'), 'deepseek': BackendSpec('openai_compat', 'deepseek', base_url='https://api.deepseek.com', api_key_env='DEEPSEEK_API_KEY'), 'moonshot': BackendSpec('openai_compat', 'moonshot', base_url='https://api.moonshot.ai/v1', api_key_env='MOONSHOT_API_KEY'), 'zhipu': BackendSpec('openai_compat', 'zhipu', base_url='https://api.z.ai/api/paas/v4', api_key_env='ZHIPU_API_KEY'), 'qwen': BackendSpec('openai_compat', 'qwen', base_url='https://dashscope-intl.aliyuncs.com/compatible-mode/v1', api_key_env='DASHSCOPE_API_KEY'), 'minimax': BackendSpec('openai_compat', 'minimax', base_url='https://api.minimax.io/v1', api_key_env='MINIMAX_API_KEY'), 'anthropic': BackendSpec('anthropic', 'anthropic', api_key_env='ANTHROPIC_API_KEY'), 'claude': BackendSpec('cli', 'claude', command='claude', args=[]), 'gemini': BackendSpec('cli', 'gemini', command='gemini', args=[]), 'antigravity': BackendSpec('cli', 'antigravity', command='antigravity', args=[]), 'codex': BackendSpec('codex_cli', 'codex', command='codex', args=[])}

def _default_state_dir():
    return Path(os.environ.get('JANUSMASK_STATE_DIR', 'state'))

def secrets_store_safe_load(state_dir=None):
    """Live use of ``secrets_store`` that degrades gracefully on failure."""
    target = state_dir if state_dir is not None else _default_state_dir()
    try:
        loaded = secrets_store.load_secrets(target)
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}

def resolve_backend(provider_id: str, secrets: Optional[Dict[str, str]]=None) -> BackendSpec:
    """Return the spec for ``provider_id``.

    CLI/codex backends never require a credential. For api-backed kinds the
    credential is read from merged injected secrets (via
    ``secrets_store.load_secrets``) falling back to ``os.environ``; an empty
    credential raises :class:`BackendLockedError`.
    """
    spec = BACKEND_REGISTRY[provider_id]
    if spec.kind in _CLI_KINDS:
        return spec
    merged = dict(secrets_store_safe_load())
    if secrets:
        merged.update(secrets)
    cred_env = merged.get(spec.api_key_env)
    if not cred_env:
        cred_env = os.environ.get(spec.api_key_env)
    if not cred_env:
        raise BackendLockedError(f'backend {provider_id!r} is locked: no credential for {spec.api_key_env}')
    return spec

def agent_block(provider_id: str) -> dict:
    """Return a ``{command, args}`` block for CLI/codex backends and a
    ``{base_url, model, api_key_env}`` block for api backends."""
    spec = BACKEND_REGISTRY[provider_id]
    if spec.kind in _CLI_KINDS:
        return {'command': spec.command, 'args': list(spec.args or [])}
    return {'base_url': spec.base_url, 'model': spec.model_id, 'api_key_env': spec.api_key_env}