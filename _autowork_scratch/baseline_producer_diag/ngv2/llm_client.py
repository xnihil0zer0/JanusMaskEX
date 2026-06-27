"""ngv2/llm_client.py -- injected LLM client seam for PoC synthesis.

The model edge is an injected ``complete`` callable so the oracle is hermetic
(no network). The real network path lives behind :func:`make_anthropic_client`,
which imports the ``anthropic`` SDK lazily inside its body so the module stays
importable with only stdlib + ``typing`` at module scope.
"""
from typing import Any, Callable, Dict, List, Optional
DEFAULT_MODEL = 'claude-fable-5'
DEFAULT_MAX_TOKENS = 4096
CompleteFn = Callable[..., str]
RATE_LIMIT_MARKERS = ('rate limit', 'rate-limit', 'rate_limit', 'ratelimit', '429', 'too many requests', 'overloaded', 'overload', 'quota', 'throttl', 'resource_exhausted', 'resource exhausted', 'capacity')

class LLMError(RuntimeError):
    """Raised on non-transient completion failure or when no seam is injected."""

def _looks_rate_limited(error_text: Optional[str]) -> bool:
    """Return True iff ``error_text`` contains a known rate-limit marker.

    Empty/None text is treated as non-transient (returns False).
    """
    if not error_text:
        return False
    lowered = error_text.lower()
    return any((marker in lowered for marker in RATE_LIMIT_MARKERS))

class LLMClient:
    """Thin client over an injected ``complete`` seam with cascade fallback."""

    def __init__(self, complete: Optional[CompleteFn]=None, *, model: Optional[str]=None, cascade: Optional[Any]=None, max_retries: int=3) -> None:
        self._complete = complete
        self.model = model or DEFAULT_MODEL
        self.cascade = cascade
        self.max_retries = max_retries
        self.last_request: Optional[Dict[str, Any]] = None
        self.last_response: Optional[str] = None

    def _active_model(self) -> str:
        """Prefer the cascade's active model; fall back to ``self.model``.

        Any exception raised by the cascade is swallowed.
        """
        if self.cascade is not None:
            try:
                active = self.cascade.get_active_model()
                if active:
                    return active
            except Exception:
                pass
        return self.model

    def complete_text(self, prompt: str, *, system: Optional[str]=None, max_tokens: int=DEFAULT_MAX_TOKENS) -> str:
        """Wrap a single user prompt and delegate to :meth:`complete_messages`."""
        messages = [{'role': 'user', 'content': prompt}]
        return self.complete_messages(messages, system=system, max_tokens=max_tokens)

    def complete_messages(self, messages: List[Dict[str, Any]], *, system: Optional[str]=None, max_tokens: int=DEFAULT_MAX_TOKENS) -> str:
        """Pass the request contract through to the injected ``complete`` seam.

        Records ``last_request``/``last_response`` and returns the assistant text.
        Retries on transient (rate-limit) errors, advancing the cascade's active
        model; non-transient errors are wrapped and re-raised as :class:`LLMError`.
        """
        if self._complete is None:
            raise LLMError('no completion seam injected')
        attempts = 0
        while True:
            model = self._active_model()
            request: Dict[str, Any] = {'messages': messages, 'model': model, 'max_tokens': max_tokens, 'system': system}
            try:
                response = self._complete(messages, model=model, max_tokens=max_tokens, system=system)
            except Exception as exc:
                error_text = str(exc)
                if _looks_rate_limited(error_text) and attempts < self.max_retries:
                    attempts += 1
                    if self.cascade is not None:
                        try:
                            self.cascade.report_rate_limit(model, error_text=error_text)
                        except Exception:
                            pass
                    continue
                raise LLMError('completion failed for model {0}: {1}'.format(model, error_text)) from exc
            self.last_request = request
            self.last_response = response
            return response

def make_anthropic_client(*, api_key: Optional[str]=None, model: Optional[str]=None) -> CompleteFn:
    """Factory returning a :data:`CompleteFn` backed by the ``anthropic`` SDK.

    The ``anthropic`` import is performed lazily inside this body so the module
    imports cleanly even when the SDK is absent. This is never invoked by the
    oracle.
    """
    import anthropic
    if api_key is not None:
        client = anthropic.Anthropic(api_key=api_key)
    else:
        client = anthropic.Anthropic()
    resolved_model = model or DEFAULT_MODEL

    def complete(messages: List[Dict[str, Any]], *, model: Optional[str]=None, max_tokens: int=DEFAULT_MAX_TOKENS, system: Optional[str]=None) -> str:
        request: Dict[str, Any] = {'model': model or resolved_model, 'max_tokens': max_tokens, 'messages': messages}
        if system is not None:
            request['system'] = system
        response = client.messages.create(**request)
        parts: List[str] = []
        for block in getattr(response, 'content', []) or []:
            text = getattr(block, 'text', None)
            if text is not None:
                parts.append(text)
        return ''.join(parts)
    return complete