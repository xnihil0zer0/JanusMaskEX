---
interfaces: "NEW data_model module ngv2/verdict_reweight.py exposing verdict_weight_delta(verdict) -> float (per-verdict multiplier around 1.0, clamped [0.1,3.0]) and reweight_from_verdicts(verdicts) -> {repo: float}; a deterministic prior-reweight signal for the Phase-1 prioritizer that LEAVES ngv2.prioritize / ngv2.selection_ranker untouched (anti-seesaw new consumer)"
working_dir: "/home/xnihil0zer0/NobleGreedv2"
meta_task_type: data_model
---

# Title

ngv2/verdict_reweight.py — NEW Phase-7.2b consumer: turn huntr verdicts into a {repo: weight} multiplier map that reweights the Phase-1 prioritizer (no edit to prioritize.py)

# Scope

Build a NEW data_model module ngv2/verdict_reweight.py in the external NobleGreedv2 repo (working_dir /home/xnihil0zer0/NobleGreedv2). This is Phase-7.2b: it converts huntr SubmissionVerdicts into a deterministic prior-reweight signal for the Phase-1 prioritizer. Accepted (especially paid) verdicts RAISE a repo key's weight; rejected/duplicate verdicts LOWER it. The output is a plain ``{repo_key: float}`` multiplier map a ranker can multiply into expected_payout — so the EXISTING ngv2/prioritize.py and ngv2/selection_ranker.py symbols stay UNTOUCHED (anti-seesaw: a new consumer module, not an edit of a shared scoring symbol). Pure stdlib; no clock/network/randomness. Emit the whole file VERBATIM from Deliverables. Name the committed oracle tests/test_verdict_reweight_wired.py in the verification_command. Required plan shape: EXACTLY ONE impl task building this one new single file.

# Non-Goals

This is a NEW single-file module, not an edit; integration is out of scope — do NOT author or modify any test (tests/test_verdict_reweight_wired.py is committed and authoritative) and do NOT add integration/e2e tests. Do NOT edit ngv2/prioritize.py, ngv2/selection_ranker.py, or any other module — this leaf only PRODUCES a multiplier map; wiring it into the ranker is a separate concern out of scope here. Do NOT call the network, a clock, or randomness. No LLM, no third-party imports (stdlib only). Touch exactly the one new file ngv2/verdict_reweight.py.

# Inputs

A verdict is either a dict ({state, payout, repo, ...}) or any object exposing ``.state``/``.payout``/``.raw``. The weight constants: ACCEPT_BONUS=0.25, PAYOUT_BONUS=0.25 (added only when payout>0), REJECT_PENALTY=0.30, NEUTRAL=1.0, clamp range [0.1, 3.0]. So accepted -> >1.0 (strictly higher when paid), rejected/duplicate -> <1.0, any other state -> exactly 1.0. ``reweight_from_verdicts`` keys each verdict by its repo (read from the mapping key ``repo`` or from a nested ``raw['repo']``); keyless verdicts are ignored; multiple verdicts for one key compound multiplicatively then clamp. The oracle injects plain dict verdicts and SubmissionVerdict-shaped (via parse_verdict_response with a ``repo`` field surviving in ``raw``).

# Deliverables

ngv2/verdict_reweight.py with EXACTLY this content:

```python
"""ngv2.verdict_reweight — turn SubmissionVerdicts into a deterministic prior
reweight signal for the Phase-1 prioritizer (Phase 7.2b).

Accepted (esp. paid) verdicts RAISE a repo key's weight; rejected/duplicate
verdicts LOWER it. The signal is a plain ``{key: float}`` multiplier map that a
ranker can multiply into expected_payout — keeping the existing prioritizer
untouched (anti-seesaw: a new consumer, not an edit of the shared symbol).
Pure stdlib; no clock/network/randomness.
"""
from __future__ import annotations
from typing import Any, Dict, Iterable, Mapping

ACCEPT_BONUS = 0.25
PAYOUT_BONUS = 0.25
REJECT_PENALTY = 0.30
NEUTRAL = 1.0
_MIN, _MAX = 0.1, 3.0


def _state(v: Any) -> str:
    if isinstance(v, Mapping):
        return str(v.get('state', '')).strip().lower()
    return str(getattr(v, 'state', '') or '').strip().lower()


def _payout(v: Any) -> float:
    raw = v.get('payout') if isinstance(v, Mapping) else getattr(v, 'payout', 0.0)
    try:
        return float(raw or 0.0)
    except (TypeError, ValueError):
        return 0.0


def verdict_weight_delta(verdict: Any) -> float:
    """Per-verdict multiplicative delta around 1.0 (clamped to [0.1, 3.0])."""
    state = _state(verdict)
    w = NEUTRAL
    if state == 'accepted':
        w += ACCEPT_BONUS
        if _payout(verdict) > 0:
            w += PAYOUT_BONUS
    elif state in ('rejected', 'duplicate'):
        w -= REJECT_PENALTY
    return max(_MIN, min(_MAX, w))


def _key(v: Any) -> str:
    if isinstance(v, Mapping):
        repo = v.get('repo') or v.get('raw', {}).get('repo', '')
    else:
        repo = (getattr(v, 'raw', {}) or {}).get('repo', '')
    return str(repo or '')


def reweight_from_verdicts(verdicts: Iterable[Any]) -> Dict[str, float]:
    """Aggregate verdicts into a ``{repo_key: weight}`` multiplier map.

    Multiple verdicts for the same key compound multiplicatively, then clamp.
    Verdicts with no resolvable key are ignored.
    """
    weights: Dict[str, float] = {}
    for v in verdicts:
        key = _key(v)
        if not key:
            continue
        cur = weights.get(key, NEUTRAL)
        weights[key] = max(_MIN, min(_MAX, cur * verdict_weight_delta(v)))
    return weights
```

DISPATCH DIRECTIVE — this is a NEW single-file module. Emit it as a single whole-file deliverable for ngv2/verdict_reweight.py reproducing the Deliverables content BYTE-FOR-BYTE (stdlib-only imports; no ngv2 sibling import needed). Do NOT emit a `__JANUSMASK_PATCHES__` list — this is a new file, not a symbol patch. meta_task_type=data_model (external NGv2 target; fuzzer-bypassed, smoke-gated). Use this task_id VERBATIM: `ngv2-verdict-reweight-prioritizer`. priority: high. dependencies: []. files_touched: `["ngv2/verdict_reweight.py"]` ONLY. verification_command (CWD-relative, NO `cd`): `.venv/bin/python -m pytest tests/test_verdict_reweight_wired.py -q`. The committed oracle tests/test_verdict_reweight_wired.py is the authoritative acceptance contract; do NOT author new tests. `spec.functional_requirements` MUST be CONSOLIDATED to at most 5 entries, and `test_spec.unit_tests` MUST enumerate AT LEAST as many entries as `spec.functional_requirements` (validator floor: len(unit_tests) >= len(functional_requirements)); unit_tests entries are descriptors NAMING committed-oracle test cases (this does NOT authorize authoring new tests). `test_spec.regression_tests` MUST list at least two entries that NAME existing test cases from this brief's committed oracle (descriptors referencing the committed oracle — NOT authorization to author tests), e.g. `test_accepted_raises_weight_paid_raises_more` and `test_reweight_map_keys_on_repo` (also good: `test_rejection_lowers_weight`, `test_reweight_compounds_same_key_and_clamps`).
