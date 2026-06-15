---
interfaces: "ngv2/llm_client.py exposes `LLMClient`, `LLMError`, `DEFAULT_MODEL` (='claude-fable-5'), `CompleteFn`, and `make_anthropic_client(*, api_key=None, model=None)`."
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

ngv2/llm_client.py — injected LLM client seam for PoC synthesis (P4.1, io_adapter, smoke-gated)

# Scope

Build `ngv2/llm_client.py` as a NEW single-file, whole-file Python module (IMPL-only;
the oracle `tests/test_llm_client_wired.py` is ALREADY COMMITTED to the NobleGreedv2
repo). This is an io_adapter (smoke-gated meta-type): the model edge is an INJECTED
`complete` callable so the oracle is hermetic and never touches the network. The real
network-backed completion lives behind `make_anthropic_client`, which lazily imports
the `anthropic` SDK INSIDE the function body so the module stays importable without it.
Default model is `claude-fable-5` (the latest Claude model in the environment).
`LLMClient` composes with an optional `ngv2.model_cascade.ModelCascade`-shaped object:
on a rate-limit error it calls `cascade.report_rate_limit(model, error_text=...)` and
retries with the next `cascade.get_active_model()`. working_dir:
/home/xnihil0zer0/NobleGreedv2.

Submit the module as EXACTLY this validated whole-file artifact (proven GREEN against
the committed oracle):

```python
"""ngv2.llm_client -- injected LLM client seam for PoC synthesis.

NGv2's runtime needs a real model client to synthesize PoCs. This module is an
io_adapter (smoke-gated): every model call goes through an INJECTED ``complete``
callable, so oracles inject a canned client and assert the request/response
contract without ever touching the network.

``ModelCascade`` (ngv2.model_cascade) decides *which* model NAME to use across
rate-limit boundaries; THIS seam decides *how* a single completion call is made.
The two compose: on a rate-limit error the client reports it to the cascade and
retries with the next active model name.

Default model: ``claude-fable-5`` (the latest Claude model in the environment).
The real network-backed ``complete`` lives behind ``make_anthropic_client`` and
is imported lazily so the module stays importable without the SDK.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

# The injected completion seam. Given a list of {role, content} messages plus a
# model id + generation params, return the assistant's text response.
CompleteFn = Callable[..., str]

DEFAULT_MODEL: str = "claude-fable-5"
DEFAULT_MAX_TOKENS: int = 4096

# Phrases that mark a transient rate-limit / overload error (mirrors
# model_cascade.RATE_LIMIT_PATTERNS so the two agree).
RATE_LIMIT_MARKERS = (
    "429", "rate limit", "rate_limit", "too many requests",
    "overloaded", "quota exceeded",
)


class LLMError(RuntimeError):
    """Raised when a completion call fails non-transiently or budget is spent."""


def _looks_rate_limited(text: Optional[str]) -> bool:
    if not text:
        return False
    low = text.lower()
    return any(m in low for m in RATE_LIMIT_MARKERS)


class LLMClient:
    """Thin, injectable completion client.

    Parameters
    ----------
    complete:
        Injected ``(messages, *, model, max_tokens, system) -> str`` callable.
        Oracles pass a canned function; production passes
        :func:`make_anthropic_client`. If ``None``, calls raise ``LLMError``.
    model:
        Default model id (``claude-fable-5`` when unset).
    cascade:
        Optional ``ngv2.model_cascade.ModelCascade``-shaped object exposing
        ``get_active_model()`` / ``report_rate_limit(model, error_text)``. When
        provided, a rate-limit error triggers one fallback retry with the next
        active model. ``None`` disables cascading.
    max_retries:
        Max additional attempts on rate-limit errors (default 3).
    """

    def __init__(
        self,
        complete: Optional[CompleteFn] = None,
        *,
        model: Optional[str] = None,
        cascade: Optional[Any] = None,
        max_retries: int = 3,
    ) -> None:
        self._complete = complete
        self.model = model or DEFAULT_MODEL
        self._cascade = cascade
        self._max_retries = int(max_retries)
        # Last request/response are retained for contract assertions + logging.
        self.last_request: Optional[Dict[str, Any]] = None
        self.last_response: Optional[str] = None

    def _active_model(self) -> str:
        if self._cascade is not None:
            try:
                return self._cascade.get_active_model() or self.model
            except Exception:
                return self.model
        return self.model

    def complete_text(
        self,
        prompt: str,
        *,
        system: Optional[str] = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> str:
        """Send a single user ``prompt`` and return the assistant text."""
        messages: List[Dict[str, str]] = [{"role": "user", "content": prompt}]
        return self.complete_messages(
            messages, system=system, max_tokens=max_tokens
        )

    def complete_messages(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        system: Optional[str] = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> str:
        """Send a multi-turn ``messages`` list and return the assistant text."""
        if self._complete is None:
            raise LLMError("LLMClient has no injected `complete` seam")
        msg_list = [dict(m) for m in messages]
        last_err: Optional[str] = None
        attempts = 0
        while True:
            model = self._active_model()
            request = {
                "messages": msg_list,
                "model": model,
                "max_tokens": max_tokens,
                "system": system,
            }
            self.last_request = request
            try:
                resp = self._complete(
                    msg_list, model=model, max_tokens=max_tokens, system=system
                )
            except Exception as exc:  # noqa: BLE001 -- map to typed error below
                text = str(exc)
                if _looks_rate_limited(text) and attempts < self._max_retries:
                    if self._cascade is not None:
                        try:
                            self._cascade.report_rate_limit(model, error_text=text)
                        except Exception:
                            pass
                    last_err = text
                    attempts += 1
                    continue
                raise LLMError("completion failed: %s" % text) from exc
            self.last_response = resp
            return resp


def make_anthropic_client(
    *, api_key: Optional[str] = None, model: Optional[str] = None
) -> CompleteFn:
    """Build the real network-backed ``complete`` seam (smoke-gated).

    Lazily imports the anthropic SDK so this module imports without it. The
    returned callable matches the injected seam signature. NEVER called by
    oracles -- they inject a canned ``complete`` instead.
    """
    import anthropic  # noqa: F401 -- lazy, optional dependency

    client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()

    def _complete(
        messages: Sequence[Mapping[str, str]],
        *,
        model: str,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        system: Optional[str] = None,
    ) -> str:
        kwargs: Dict[str, Any] = {
            "model": model or DEFAULT_MODEL,
            "max_tokens": max_tokens,
            "messages": [dict(m) for m in messages],
        }
        if system:
            kwargs["system"] = system
        resp = client.messages.create(**kwargs)
        parts = [
            getattr(block, "text", "")
            for block in getattr(resp, "content", [])
        ]
        return "".join(parts)

    return _complete
```

Verify with `.venv/bin/python -m pytest tests/test_llm_client_wired.py -q` (NO `cd`
prefix — the verification runs in the staging worktree).

# Non-Goals

No real network call in the import path or in any oracle path (the `anthropic` import is
lazy inside `make_anthropic_client`). No third-party imports at module scope (stdlib +
the lazy anthropic only). No tests authored (the oracle `tests/test_llm_client_wired.py`
is already committed). Must NOT modify `ngv2/model_cascade.py` — only compose with an
injected cascade-shaped object. No PoC-writing logic here (that is P4.2).

# Inputs

The NobleGreedv2 repo at working_dir /home/xnihil0zer0/NobleGreedv2, with the committed
oracle `tests/test_llm_client_wired.py` pinning: `DEFAULT_MODEL == 'claude-fable-5'`;
the request contract (`messages`/`model`/`max_tokens`/`system`) passes through to the
injected `complete`; multi-turn `complete_messages`; `LLMError` when no seam is injected
and on non-transient failures; a cascade fallback that advances the model on a
rate-limit error; and that `make_anthropic_client` is a callable factory (not invoked
by the oracle). `ngv2.model_cascade.ModelCascade` exists in the repo as a reference for
the cascade shape but is consumed only via the injected object.

# Deliverables

One NEW single-file whole-file module `ngv2/llm_client.py` exactly as the embedded
artifact above, passing `tests/test_llm_client_wired.py`.
