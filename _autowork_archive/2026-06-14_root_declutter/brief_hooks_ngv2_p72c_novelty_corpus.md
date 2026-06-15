---
interfaces: "NEW data_model module ngv2/novelty_corpus.py exposing corpus_from_submissions_map(data) and load_known_corpus(path=None) plus DEFAULT_CORPUS_PATH; flattens data/ngv2/huntr_existing_submissions.json ({repo:{titles:[...]}}) into the [{title,cwe,file}] entries ngv2.novelty_gate.classify_novelty expects so prior accepted submissions are no longer NOVEL. Does NOT edit novelty_gate.py (anti-seesaw new consumer)."
working_dir: "/home/xnihil0zer0/NobleGreedv2"
meta_task_type: data_model
---

# Title

ngv2/novelty_corpus.py — NEW Phase-7.2c loader: seed classify_novelty's known_corpus from data/ngv2/huntr_existing_submissions.json (legacy fed []), so a known prior submission is non-NOVEL

# Scope

Build a NEW data_model module ngv2/novelty_corpus.py in the external NobleGreedv2 repo (working_dir /home/xnihil0zer0/NobleGreedv2). This is Phase-7.2c: ngv2.novelty_gate.classify_novelty was being fed an empty ``known_corpus`` so EVERYTHING classified NOVEL. This loader reads data/ngv2/huntr_existing_submissions.json — shaped ``{repo: {status, count, titles: [...]}}`` — and flattens it into the ``[{'title','cwe','file'}]`` entries classify_novelty expects (file = the repo, so same-repo locus hints survive), so a known prior submission classifies NOT-NOVEL. It is a pure CONSUMER feeding the existing classify_novelty — it does NOT edit ngv2/novelty_gate.py (anti-seesaw: classify_novelty is referenced by several oracle files; add a new consumer module instead of touching the shared symbol). Pure stdlib (json only); no network/clock/randomness; the corpus path is injectable for hermetic tests. Emit the whole file VERBATIM from Deliverables. Name the committed oracle tests/test_novelty_corpus_wired.py in the verification_command. Required plan shape: EXACTLY ONE impl task building this one new single file.

# Non-Goals

This is a NEW single-file module, not an edit; integration is out of scope — do NOT author or modify any test (tests/test_novelty_corpus_wired.py is committed and authoritative) and do NOT add integration/e2e tests. Do NOT edit ngv2/novelty_gate.py, ngv2/dedup_novelty.py, or any other module — consume classify_novelty as-is. Do NOT modify data/ngv2/huntr_existing_submissions.json. Do NOT call the network, a clock, or randomness (the only I/O is reading the injectable JSON corpus path). No LLM, no third-party imports (stdlib json/pathlib only). Touch exactly the one new file ngv2/novelty_corpus.py.

# Inputs

data/ngv2/huntr_existing_submissions.json is a mapping ``{repo: {status:int, count:int, titles:[str,...]}}`` (32 repos, 664 titles live). ``ngv2.novelty_gate.classify_novelty(finding: dict, known_corpus: list) -> str`` (HEAD) returns NOVEL/POSSIBLE_DUP/CONFIRMED_DUP and treats each corpus entry as a dict read by keys title/cwe/file; it is total over malformed entries. The DEFAULT_CORPUS_PATH resolves from this module's parent.parent to data/ngv2/huntr_existing_submissions.json. The oracle writes a small tmp corpus AND (when present) checks the real default file: a title drawn from the loaded corpus, re-classified against it, must not be NOVEL.

# Deliverables

ngv2/novelty_corpus.py with EXACTLY this content:

```python
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

DEFAULT_CORPUS_PATH = (Path(__file__).resolve().parent.parent
                       / 'data' / 'ngv2' / 'huntr_existing_submissions.json')
PathLike = Union[str, Path]


def corpus_from_submissions_map(data: Any) -> List[dict]:
    """Flatten a ``{repo: {titles: [...]}}`` mapping into novelty-gate entries.

    Each emitted entry carries ``title`` (the submission title), ``cwe`` (''),
    ``file`` (the repo, so same-repo dup hints survive) plus ``repo``. Malformed
    shapes are skipped, never raised.
    """
    out: List[dict] = []
    if not isinstance(data, dict):
        return out
    for repo, entry in data.items():
        if not isinstance(entry, dict):
            continue
        titles = entry.get('titles')
        if not isinstance(titles, list):
            continue
        for title in titles:
            if not isinstance(title, str):
                continue
            out.append({'title': title, 'cwe': '', 'file': str(repo), 'repo': str(repo)})
    return out


def load_known_corpus(path: Optional[PathLike] = None) -> List[dict]:
    """Load the prior-submission corpus as classify_novelty-shaped entries.

    Returns ``[]`` when the file is absent or unparseable (never raises).
    """
    p = Path(path) if path is not None else DEFAULT_CORPUS_PATH
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding='utf-8'))
    except (ValueError, OSError):
        return []
    return corpus_from_submissions_map(data)
```

DISPATCH DIRECTIVE — this is a NEW single-file module. Emit it as a single whole-file deliverable for ngv2/novelty_corpus.py reproducing the Deliverables content BYTE-FOR-BYTE (stdlib json/pathlib only; no ngv2 sibling import). Do NOT emit a `__JANUSMASK_PATCHES__` list — this is a new file, not a symbol patch. meta_task_type=data_model (external NGv2 target; fuzzer-bypassed, smoke-gated). Use this task_id VERBATIM: `ngv2-novelty-corpus-loader`. priority: high. dependencies: []. files_touched: `["ngv2/novelty_corpus.py"]` ONLY. verification_command (CWD-relative, NO `cd`): `.venv/bin/python -m pytest tests/test_novelty_corpus_wired.py -q`. The committed oracle tests/test_novelty_corpus_wired.py is the authoritative acceptance contract; do NOT author new tests. `spec.functional_requirements` MUST be CONSOLIDATED to at most 5 entries, and `test_spec.unit_tests` MUST enumerate AT LEAST as many entries as `spec.functional_requirements` (validator floor: len(unit_tests) >= len(functional_requirements)); unit_tests entries are descriptors NAMING committed-oracle test cases (this does NOT authorize authoring new tests). `test_spec.regression_tests` MUST list at least two entries that NAME existing test cases from this brief's committed oracle (descriptors referencing the committed oracle — NOT authorization to author tests), e.g. `test_loaded_corpus_makes_known_submission_not_novel` and `test_flatten_shape_has_title_cwe_file` (also good: `test_load_missing_path_returns_empty`, `test_flatten_skips_malformed_entries`).
