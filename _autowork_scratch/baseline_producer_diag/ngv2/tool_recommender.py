"""Pure, stdlib-only tool recommender distilled from the legacy NobleGreed
recommender.

This module scores tools against a free-text task description and assembles a
greedy *composition chain* where each step's chosen tool feeds its output
tokens forward into the pool of outputs available to later steps.

Everything here is deterministic and side-effect free:

* ``keyword_score`` / ``usage_boost`` / ``find_composition_chain`` operate purely
  over plain ``dict`` / ``list`` / ``set`` data and never mutate their inputs.
* ``load_catalog`` / ``load_usage_log`` are injected-seam loaders: callers supply
  a ``reader`` callable so the module never touches real disk, the clock, the
  network, or any nondeterministic source.

Only the Python standard library is imported.
"""
from __future__ import annotations
import re
from typing import Callable, Dict, List, Optional, Set, Tuple
__all__ = ['keyword_score', 'usage_boost', 'find_composition_chain', 'load_catalog', 'load_usage_log', 'GRAPHMERT_TRAINING_THRESHOLD']
GRAPHMERT_TRAINING_THRESHOLD: int = 50
_WORD_RE = re.compile('[a-z]+')

def _alpha_tokens(text: str, min_len: int=0) -> Set[str]:
    """Return the set of lowercase ``[a-z]+`` tokens in *text*.

    Tokens shorter than ``min_len`` are dropped. Non-string / empty inputs
    yield an empty set.
    """
    if not text or not isinstance(text, str):
        return set()
    return {tok for tok in _WORD_RE.findall(text.lower()) if len(tok) > min_len}

def _tool_tokens(tool_info: dict) -> Set[str]:
    """Build the bag of searchable tokens for a single tool entry.

    Defensive against missing / ``None`` fields -- every metadata key is
    optional. Tokenization rules:

    * ``name`` and ``description``: lowercase ``[a-z]+`` tokens of length > 2.
    * ``tags``: each tag taken verbatim, lowercased.
    * ``cwe_relevant``: each entry lowercased with hyphens stripped.
    * ``inputs`` and ``outputs``: lowercase ``[a-z]+`` tokens.
    """
    if not isinstance(tool_info, dict):
        return set()
    tokens: Set[str] = set()
    tokens |= _alpha_tokens(tool_info.get('name') or '', min_len=2)
    tokens |= _alpha_tokens(tool_info.get('description') or '', min_len=2)
    for tag in tool_info.get('tags') or []:
        if isinstance(tag, str) and tag:
            tokens.add(tag.lower())
    for entry in tool_info.get('cwe_relevant') or []:
        if isinstance(entry, str) and entry:
            tokens.add(entry.lower().replace('-', ''))
    for field_name in ('inputs', 'outputs'):
        for item in tool_info.get(field_name) or []:
            if isinstance(item, str):
                tokens |= _alpha_tokens(item)
    return tokens

def keyword_score(task_words: set, tool_info: dict) -> Tuple[float, set]:
    """Score a tool against a set of task words by token overlap.

    Returns ``(score, overlap)`` where ``overlap`` is the set of task words
    that appear in the tool's token bag and ``score`` is
    ``len(overlap) / len(task_words)`` (the fraction of the task covered).

    An empty ``task_words`` yields ``(0.0, set())`` with no ``ZeroDivisionError``.
    """
    if not task_words:
        return (0.0, set())
    task_set: Set[str] = set(task_words)
    overlap = task_set & _tool_tokens(tool_info)
    return (len(overlap) / len(task_set), overlap)

def usage_boost(tool_name: str, usage_log: list) -> float:
    """Compute a success-rate-adjusted multiplier for *tool_name*.

    With no recorded history for the tool the boost is neutral (``1.0``).
    Otherwise it is ``0.5 + 0.5 * (successes / total)`` -- ranging from ``0.5``
    when every recorded run failed up to ``1.0`` when all succeeded.
    """
    total = 0
    successes = 0
    for entry in usage_log or []:
        if not isinstance(entry, dict):
            continue
        if entry.get('tool') != tool_name:
            continue
        total += 1
        if entry.get('outcome') == 'success':
            successes += 1
    if total == 0:
        return 1.0
    return 0.5 + 0.5 * (successes / total)

def find_composition_chain(steps: List[str], catalog: dict) -> List[Tuple[str, Optional[str], float]]:
    """Greedily build a tool composition chain over *steps*.

    For each step the best-matching tool in *catalog* is chosen by a combined
    score::

        keyword_score + 0.3 * (len(inputs & available_outputs) / max(len(inputs), 1))

    where ``available_outputs`` accumulates the output tokens of every tool
    chosen so far -- so a tool that consumes earlier outputs is rewarded.

    Returns a list of ``(step, tool_name, score)`` tuples. When no catalog tool
    scores above zero for a step, ``(step, None, 0.0)`` is emitted and the
    available-output pool is left unchanged.

    Inputs are never mutated.
    """
    chain: List[Tuple[str, Optional[str], float]] = []
    available_outputs: Set[str] = set()
    for step in steps:
        task_words = _alpha_tokens(step, min_len=2)
        best_name: Optional[str] = None
        best_score = 0.0
        best_outputs: Set[str] = set()
        for tool_name, tool_info in (catalog or {}).items():
            kw, _overlap = keyword_score(task_words, tool_info)
            input_tokens: Set[str] = set()
            for item in (tool_info or {}).get('inputs') or []:
                if isinstance(item, str):
                    input_tokens |= _alpha_tokens(item)
            matched = len(input_tokens & available_outputs)
            composition_bonus = 0.3 * (matched / max(len(input_tokens), 1))
            combined = kw + composition_bonus
            if combined > best_score:
                best_score = combined
                best_name = tool_name
                output_tokens: Set[str] = set()
                for item in (tool_info or {}).get('outputs') or []:
                    if isinstance(item, str):
                        output_tokens |= _alpha_tokens(item)
                best_outputs = output_tokens
        if best_name is None:
            chain.append((step, None, 0.0))
        else:
            chain.append((step, best_name, float(best_score)))
            available_outputs = available_outputs | best_outputs
    return chain

def load_catalog(reader: Optional[Callable[[], dict]]=None) -> dict:
    """Load the tool catalog via an injected *reader* seam.

    With no reader the loader returns an empty dict (no disk access). When a
    reader callable is supplied its result is returned verbatim.
    """
    if reader is None:
        return {}
    return reader()

def load_usage_log(reader: Optional[Callable[[], list]]=None) -> list:
    """Load the tool usage log via an injected *reader* seam.

    With no reader the loader returns an empty list (no disk access). When a
    reader callable is supplied its result is returned verbatim.
    """
    if reader is None:
        return []
    return reader()