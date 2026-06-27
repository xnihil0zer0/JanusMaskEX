"""Pure, deterministic novelty / dedup similarity layer for ngv2.

Distilled from the legacy ``dedup_checker`` tool. This module is stdlib-only
and side-effect free: tokenization, Jaccard + weighted similarity, and a
``check_duplicate`` shell that classifies a finding title as skip / review /
submit against a corpus of existing submission titles.

The only would-be external dependency (fetching existing titles) is routed
through an *injected* ``fetcher`` seam built by :func:`make_scripted_fetcher`;
no real network, clock, file or subprocess access ever occurs here.
"""
from __future__ import annotations
import string
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Set
__all__ = ['STOPWORDS', 'tokenize', 'jaccard_similarity', 'weighted_similarity', 'check_duplicate', 'make_scripted_fetcher']
STOPWORDS: frozenset = frozenset({'a', 'an', 'the', 'and', 'or', 'but', 'if', 'then', 'else', 'when', 'at', 'by', 'for', 'with', 'about', 'against', 'between', 'into', 'through', 'during', 'before', 'after', 'above', 'below', 'to', 'from', 'up', 'down', 'in', 'out', 'on', 'off', 'over', 'under', 'again', 'further', 'is', 'are', 'was', 'were', 'be', 'been', 'being', 'of', 'via', 'using', 'use', 'used', 'allows', 'allow', 'that', 'this', 'these', 'those', 'it', 'its', 'as', 'can', 'will', 'may', 'such', 'per'})
_PUNCT_TABLE = str.maketrans('', '', string.punctuation)

def tokenize(text: str) -> Set[str]:
    """Normalize ``text`` into a set of content tokens.

    Lowercases, removes ASCII punctuation, splits on whitespace, and drops
    stopwords and single-character tokens. Returns an empty set for empty or
    whitespace/stopword-only input.
    """
    if not text:
        return set()
    cleaned = text.lower().translate(_PUNCT_TABLE)
    return {token for token in cleaned.split() if len(token) > 1 and token not in STOPWORDS}

def jaccard_similarity(a: Set[str], b: Set[str]) -> float:
    """Similarity of two token sets via the Sorensen-Dice coefficient.

    Returns ``2 * |a & b| / (|a| + |b|)`` in ``[0.0, 1.0]``; identical
    non-empty sets give ``1.0`` and any empty operand gives ``0.0``.
    """
    total = len(a) + len(b)
    if total == 0:
        return 0.0
    overlap = len(a & b)
    return 2.0 * overlap / total

def weighted_similarity(query: Set[str], target: Set[str]) -> float:
    """Blend standard Jaccard with query-coverage into one score in [0, 1].

    The score is the mean of:

    * jaccard  = ``|I| / |query ∪ target|``
    * coverage = ``|I| / |query|`` (fraction of the query covered)

    Any empty operand yields ``0.0``.
    """
    if not query or not target:
        return 0.0
    overlap = len(query & target)
    union = len(query | target)
    jaccard = overlap / union if union else 0.0
    coverage = overlap / len(query)
    return (jaccard + coverage) / 2.0

def make_scripted_fetcher(script: Mapping[str, Sequence[str]]) -> Callable[[str], List[str]]:
    """Build a deterministic, network-free fetcher from a scripted mapping.

    The returned callable maps a repo identifier to its scripted list of
    existing titles, falling back to an empty list for unknown identifiers.
    """
    table: Dict[str, List[str]] = {ident: list(titles) for ident, titles in script.items()}

    def fetcher(repo: str) -> List[str]:
        return list(table.get(repo, []))
    return fetcher

def check_duplicate(repo: str, finding_title: str, existing_titles: Optional[Sequence[str]]=None, fetcher: Optional[Callable[[str], Sequence[str]]]=None, threshold: float=0.6) -> Dict[str, object]:
    """Classify ``finding_title`` as skip / review / submit for ``repo``.

    ``existing_titles`` provides the corpus directly. When it is ``None`` the
    injected ``fetcher`` seam is consulted (never the network); absent a
    fetcher the corpus is treated as empty.

    Returns a dict with keys: ``status``, ``repo``, ``finding_title``,
    ``existing_count``, ``is_duplicate``, ``max_similarity``, ``threshold``,
    ``similar_titles``, ``recommendation``, ``reason``.
    """
    if existing_titles is None:
        titles = list(fetcher(repo)) if fetcher is not None else []
    else:
        titles = list(existing_titles)
    query = tokenize(finding_title)
    scored: List[Dict[str, object]] = []
    for title in titles:
        target = tokenize(title)
        score = weighted_similarity(query, target)
        if score > 0.0:
            scored.append({'title': title, 'similarity_score': score, 'matching_words': sorted(query & target)})
    scored.sort(key=lambda entry: entry['similarity_score'], reverse=True)
    similar_titles = scored[:5]
    max_similarity = scored[0]['similarity_score'] if scored else 0.0
    is_duplicate = max_similarity >= threshold
    review_floor = threshold * 0.7
    if max_similarity >= threshold:
        recommendation = 'skip'
        reason = 'Highly similar to an existing submission; likely a duplicate.'
    elif max_similarity >= review_floor:
        recommendation = 'review'
        reason = 'Moderate similarity to existing submissions; manual review advised.'
    else:
        recommendation = 'submit'
        reason = 'No similar existing submission found; appears novel.'
    return {'status': 'ok', 'repo': repo, 'finding_title': finding_title, 'existing_count': len(titles), 'is_duplicate': bool(is_duplicate), 'max_similarity': max_similarity, 'threshold': threshold, 'similar_titles': similar_titles, 'recommendation': recommendation, 'reason': reason}