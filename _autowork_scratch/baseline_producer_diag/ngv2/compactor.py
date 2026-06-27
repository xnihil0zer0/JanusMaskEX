"""ngv2.compactor — deterministic context-compaction decision/prompt helper.

Pure stdlib. No network, no LLM call, no clock, no randomness, no file I/O.
This module decides whether summarizing conversation context is
token-worthwhile and builds the (static) compaction prompt. It never calls a
real model; every result is a pure function of its inputs.
"""
from __future__ import annotations
from typing import Dict, Union
__all__ = ['estimate_tokens', 'should_compact', 'build_compaction_prompt', 'COMPACTION_COST_OPUS_EQUIV', 'SUMMARY_TOKEN_BUDGET', 'COMPACTION_PROMPT_TEMPLATE']
COMPACTION_COST_OPUS_EQUIV: int = 1700
SUMMARY_TOKEN_BUDGET: int = 2000
_CHARS_PER_TOKEN: int = 4
_MAX_CONTEXT_CHARS: int = 50000
_BREAKEVEN_THRESHOLD: float = 2.0
COMPACTION_PROMPT_TEMPLATE: str = 'You are compacting conversation context to conserve tokens.\nSummarize the material below, preserving decisions, open questions, file paths, and any state needed to continue the work.\nKeep the summary within {max_tokens} tokens.\n\n## Context to Compact\n{context}\n\n## Summary\n'

def estimate_tokens(text: str) -> int:
    """Estimate the token count of ``text`` as ``len(text) // 4`` (floor)."""
    return len(text) // _CHARS_PER_TOKEN

def should_compact(context_tokens: int) -> Dict[str, Union[bool, str, float]]:
    """Decide whether compacting ``context_tokens`` worth of context pays off.

    Returns a dict with exactly the keys ``should_compact`` (bool),
    ``reason`` (non-empty str), and ``breakeven_messages`` (float).
    """
    savings = max(0, context_tokens - SUMMARY_TOKEN_BUDGET)
    if savings <= 0:
        return {'should_compact': False, 'reason': 'Context is not larger than the summary budget ({0} tokens); compaction would save nothing.'.format(SUMMARY_TOKEN_BUDGET), 'breakeven_messages': float('inf')}
    raw_breakeven = COMPACTION_COST_OPUS_EQUIV / savings
    worth_it = raw_breakeven < _BREAKEVEN_THRESHOLD
    if worth_it:
        reason = 'Compaction saves ~{0} tokens and breaks even in under {1} messages.'.format(savings, _BREAKEVEN_THRESHOLD)
    else:
        reason = 'Compaction saves ~{0} tokens but takes too many messages to break even.'.format(savings)
    return {'should_compact': worth_it, 'reason': reason, 'breakeven_messages': round(raw_breakeven, 2)}

def build_compaction_prompt(context: str, max_tokens: int=SUMMARY_TOKEN_BUDGET) -> str:
    """Build the static compaction prompt embedding ``context`` and budget.

    The raw context is capped at the first 50000 characters.
    """
    capped = context[:_MAX_CONTEXT_CHARS]
    return COMPACTION_PROMPT_TEMPLATE.format(context=capped, max_tokens=max_tokens)