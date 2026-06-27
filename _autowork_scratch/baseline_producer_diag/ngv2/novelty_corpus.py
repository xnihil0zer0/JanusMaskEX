"""ngv2.novelty_corpus — load prior accepted huntr submissions into the shape
that ngv2.novelty_gate.classify_novelty expects (Phase 7.2c).

The legacy corpus feed was ``[]`` so EVERYTHING was NOVEL. This loader reads
data/ngv2/huntr_existing_submissions.json — structured as
``{repo: {status, count, titles: [...]}}`` — and flattens it into a list of
``{'title', 'cwe', 'file'}`` entries usable as ``known_corpus``. Stdlib-only;
no network/clock/randomness. Path is injectable for hermetic tests.
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any, List, Optional, Union
DEFAULT_CORPUS_PATH = Path(__file__).resolve().parent.parent / 'data' / 'ngv2' / 'huntr_existing_submissions.json'
PathLike = Union[str, Path]

def corpus_from_submissions_map(data: Any) -> List[dict]:
    from ngv2.title_cwe_classifier import classify_title
    if not isinstance(data, dict):
        return []
    entries: List[dict] = []
    for repo, info in data.items():
        if not isinstance(info, dict):
            continue
        titles = info.get("titles")
        if not isinstance(titles, list):
            continue
        for title in titles:
            if not isinstance(title, str):
                continue
            entries.append({
                "title": title,
                "cwe": classify_title(title),
                "file": repo,
                "repo": repo,
            })
    return entries

def load_known_corpus(path: Optional[PathLike]=None) -> List[dict]:
    if path is None:
        path = DEFAULT_CORPUS_PATH
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return []
    return corpus_from_submissions_map(data)
