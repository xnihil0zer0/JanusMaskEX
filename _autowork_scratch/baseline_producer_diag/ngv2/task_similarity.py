"""Pure, deterministic worker suspend/resume task-matching core.

This stdlib-only module implements a Jaccard-overlap task-similarity
metric and a pure resume-criteria policy for selecting the best
suspended-worker candidate to reuse. It performs no DB, file, network,
clock, or random access and never mutates its inputs.
"""
import dataclasses
import re
from typing import Optional
SUSPEND_TOKEN_THRESHOLD: int = 50000
RESUME_TOKEN_CEILING: int = 500000
TASK_SIMILARITY_THRESHOLD: float = 0.3
_TOKEN_PATTERN = re.compile('[a-z0-9]+')

def _task_similarity(text_a: str, text_b: str) -> float:
    """Return the Jaccard similarity of two strings' token sets.

    Each input is lowercased and tokenized into the set of ``[a-z0-9]+``
    runs. The result is ``|A & B| / |A | B|`` clamped to ``0.0..1.0``.
    Returns ``0.0`` if either token set is empty, and ``1.0`` for
    identical non-empty token sets.
    """
    set_a = set(_TOKEN_PATTERN.findall(text_a.lower()))
    set_b = set(_TOKEN_PATTERN.findall(text_b.lower()))
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    if union == 0:
        return 0.0
    score = intersection / union
    if score < 0.0:
        return 0.0
    if score > 1.0:
        return 1.0
    return score

@dataclasses.dataclass(frozen=True)
class ResumeCriteria:
    """Policy for selecting a resumable worker candidate."""
    worker_type: str
    max_tokens: int = 500000
    similarity_threshold: float = 0.3

def find_resumable_worker(task_description: str, candidates: list[dict], criteria: ResumeCriteria) -> Optional[dict]:
    """Select the best resumable worker candidate for a task.

    Candidates are filtered to those whose ``worker_type`` matches
    ``criteria.worker_type`` and whose ``token_usage`` is strictly less
    than ``criteria.max_tokens``. Each surviving candidate's
    ``prompt_text`` is scored against ``task_description`` with
    :func:`_task_similarity`; only candidates scoring at least
    ``criteria.similarity_threshold`` qualify. The single best-scoring
    candidate (highest score, first-seen wins ties) is returned as a new
    shallow copy with an added ``'similarity_score'`` key, or ``None`` if
    no candidate qualifies. Inputs are never mutated.
    """
    best_candidate: Optional[dict] = None
    best_score: float = -1.0
    for candidate in candidates:
        if candidate.get('worker_type') != criteria.worker_type:
            continue
        if not candidate.get('token_usage', 0) < criteria.max_tokens:
            continue
        score = _task_similarity(task_description, candidate.get('prompt_text', ''))
        if score < criteria.similarity_threshold:
            continue
        if score > best_score:
            best_score = score
            best_candidate = candidate
    if best_candidate is None:
        return None
    result = dict(best_candidate)
    result['similarity_score'] = float(best_score)
    return result