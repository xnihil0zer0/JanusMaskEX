"""Model dropdown resolution for overseer agents.

claude takes ``--model opus|sonnet|haiku``; agy (the compiled
Antigravity/Gemini binary) has NO ``--model`` flag and self-selects, so it
resolves to an empty argv. Unknown agent/model are rejected outright (no
silent fallthrough).

Stdlib-only, whole-file module.
"""
from __future__ import annotations
from typing import Dict, List, Optional
AVAILABLE_MODELS: Dict[str, List[str]] = {'claude': ['opus', 'sonnet', 'haiku'], 'agy': []}

def resolve_model_argv(agent: str, requested: Optional[str]) -> List[str]:
    """Resolve a chosen model into agent CLI argv fragments.

    - ``claude`` -> ``["--model", requested]`` for a valid tier in
      ``AVAILABLE_MODELS["claude"]``.
    - ``agy`` -> ``[]`` regardless of ``requested`` (agy takes no --model flag).

    Raises ``ValueError`` for an unknown agent, and for claude when the
    requested model is not a valid tier (including ``None``).
    """
    if agent not in AVAILABLE_MODELS:
        raise ValueError(f'unknown agent: {agent!r}')
    available = AVAILABLE_MODELS[agent]
    if not available:
        return []
    if requested not in available:
        raise ValueError(f'unknown model {requested!r} for agent {agent!r}; valid choices: {available}')
    return ['--model', requested]