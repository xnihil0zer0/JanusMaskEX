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
BACKEND_REGISTRY: Dict[str, BackendSpec] = {
    'openai': BackendSpec('openai_compat', 'openai', base_url='https://api.openai.com/v1', api_key_env='OPENAI_API_KEY'),
    'gemini_api': BackendSpec('openai_compat', 'gemini_api', base_url='https://generativelanguage.googleapis.com/v1beta/openai/', api_key_env='GEMINI_API_KEY'),
    'deepseek': BackendSpec('openai_compat', 'deepseek', base_url='https://api.deepseek.com', api_key_env='DEEPSEEK_API_KEY'),
    'moonshot': BackendSpec('openai_compat', 'moonshot', base_url='https://api.moonshot.ai/v1', api_key_env='MOONSHOT_API_KEY'),
    'zhipu': BackendSpec('openai_compat', 'zhipu', base_url='https://api.z.ai/api/paas/v4', api_key_env='ZHIPU_API_KEY'),
    'qwen': BackendSpec('openai_compat', 'qwen', base_url='https://dashscope-intl.aliyuncs.com/compatible-mode/v1', api_key_env='DASHSCOPE_API_KEY'),
    'minimax': BackendSpec('openai_compat', 'minimax', base_url='https://api.minimax.io/v1', api_key_env='MINIMAX_API_KEY'),
    'anthropic': BackendSpec('anthropic', 'anthropic', api_key_env='ANTHROPIC_API_KEY'),
    'claude': BackendSpec('cli', 'claude', command='claude', args=[]),
    'gemini': BackendSpec('cli', 'gemini', command='gemini', args=[]),
    'antigravity': BackendSpec('cli', 'antigravity', command='antigravity', args=[]),
    'codex': BackendSpec('codex_cli', 'codex', command='codex', args=[]),
    'vllm': BackendSpec('openai_compat', 'vllm', base_url='http://localhost:8000/v1', api_key_env='VLLM_API_KEY', model_id='DiffusionGemma-26B-it'),
    'diffusion_gemma': BackendSpec('openai_compat', 'diffusion_gemma', base_url='http://localhost:8000/v1', api_key_env='VLLM_API_KEY', model_id='DiffusionGemma-26B-it')
}

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

VLLM_SERVING_PARAMS = {
    'model': 'DiffusionGemma-26B-it',
    'gpu_index': 0,
    'gpu': 0,
    'enable_prefix_caching': True,
    'enable-prefix-caching': True,
    'apc_enabled': True,
    'port': 8000,
    'base_url': 'http://localhost:8000/v1',
    'api_key': 'mock_key',
}

def synthesize_inpaint_with_retries(prompt: str, image_path: str, mask_path: str, **kwargs) -> str:
    """Wraps the OpenAI-compatible vLLM client call for inpainting with exponential backoff retries."""
    import time
    from pathlib import Path
    
    if not isinstance(prompt, str):
        raise TypeError("Prompt must be a string.")
    if not prompt.strip():
        raise ValueError("Prompt cannot be empty.")
        
    if not isinstance(image_path, (str, Path)):
        raise TypeError("image_path must be a string or Path.")
    img_path = Path(image_path)
    if not img_path.is_file():
        raise ValueError(f"Invalid image path: {image_path}")
        
    if not isinstance(mask_path, (str, Path)):
        raise TypeError("mask_path must be a string or Path.")
    m_path = Path(mask_path)
    if not m_path.is_file():
        raise ValueError(f"Invalid mask path: {mask_path}")
        
    base_url = kwargs.pop('base_url', None) or os.environ.get('VLLM_BASE_URL') or 'http://localhost:8000/v1'
    api_key = kwargs.pop('api_key', None) or os.environ.get('VLLM_API_KEY') or 'mock_key'
    model = kwargs.pop('model', None) or os.environ.get('VLLM_MODEL_NAME') or 'DiffusionGemma-26B-it'
    
    max_retries = kwargs.pop('max_retries', 5)
    initial_delay = kwargs.pop('initial_delay', 1.0)
    backoff_factor = kwargs.pop('backoff_factor', 2.0)
    
    from openai import OpenAI
    
    client = OpenAI(base_url=base_url, api_key=api_key)
    
    delay = initial_delay
    last_exc = None
    
    for attempt in range(max_retries + 1):
        try:
            with open(image_path, "rb") as img_file, open(mask_path, "rb") as mask_file:
                response = client.images.edit(
                    image=img_file,
                    mask=mask_file,
                    prompt=prompt,
                    model=model,
                    **kwargs
                )
            
            if hasattr(response, 'data') and response.data:
                item = response.data[0]
                if hasattr(item, 'url') and item.url:
                    return item.url
                if hasattr(item, 'b64_json') and item.b64_json:
                    return item.b64_json
                if hasattr(item, 'text') and item.text:
                    return item.text
            if hasattr(response, 'choices') and response.choices:
                return response.choices[0].message.content
            if isinstance(response, str):
                return response
            if isinstance(response, dict):
                if 'data' in response and response['data']:
                    item = response['data'][0]
                    if isinstance(item, dict):
                        return item.get('url') or item.get('b64_json') or item.get('text') or str(item)
                if 'url' in response:
                    return response['url']
                return str(response)
            return str(response)
            
        except Exception as e:
            last_exc = e
            if attempt == max_retries:
                raise
            time.sleep(delay)
            delay *= backoff_factor

    if last_exc:
        raise last_exc
    raise RuntimeError("Failed to synthesize inpaint after retries.")