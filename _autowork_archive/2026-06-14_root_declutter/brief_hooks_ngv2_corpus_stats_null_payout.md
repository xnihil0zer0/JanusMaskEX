---
working_dir: "/home/xnihil0zer0/NobleGreedv2"
interfaces: "EDIT ngv2/bounty_corpus_stats.py::compute_corpus_stats so a None/non-numeric payout returned by prioritize.expected_payout fails safe to 0.0 instead of crashing float(None) — making the committed oracle tests/test_corpus_stats_null_payout_wired.py GREEN while tests/test_bounty_corpus_stats_wired.py stays GREEN"
meta_task_type: data_model
spec_author: "FIX-WAVE agent (JanusMask, 2026-06-12)"
---

# Title

ngv2/bounty_corpus_stats.py — harden `compute_corpus_stats` against `float(None)`: null/non-numeric payout fields in the frozen huntr_repo_bounties.json snapshot fail safe to `0.0`.

# Scope

EDIT the EXISTING module `ngv2/bounty_corpus_stats.py`, EXACTLY ONE symbol: `compute_corpus_stats`. Root cause (2026-06-12 live run): the frozen data/ngv2/huntr_repo_bounties.json snapshot carries repos whose `observed_payouts` band values are `null` (e.g. `fastai/fastai` has `"critical": null`; `iterative/dvc` is all-null), and `ngv2.prioritize.expected_payout` returns the band value VERBATIM when the severity key is present — so `compute_corpus_stats` crashes with `TypeError: float() argument must be ... not 'NoneType'` on the real snapshot, violating the module's own "never raises on empty or malformed inputs" contract. Fix: coerce any non-numeric (None, str, bool) payout to `0.0` before the `float()` call. Numeric payouts are byte-identically unaffected.

DISPATCH DIRECTIVE — PATCH FORMAT (MANDATORY — SINGLE-SYMBOL PATCH): patch EXACTLY the ONE existing top-level function `compute_corpus_stats` (a 1-part qualname; this adds NO new top-level symbol). Its complete replacement body is pinned below from the validated reference — reproduce it BYTE-FOR-BYTE (the ONLY change versus the baseline is that the single line `expected_value[repo] = float(expected_payout(record, 'critical'))` becomes the four `raw_payout` lines):

```python
def compute_corpus_stats(repo_bounties: dict, existing_submissions: dict, poc_dir: str) -> CorpusStats:
    """Compute a pure :class:`CorpusStats` over the provided snapshots.

    Args:
        repo_bounties: full huntr_repo_bounties.json snapshot
            (``{"repos": {"owner/repo": {...}}}``).
        existing_submissions: full huntr_existing_submissions.json snapshot
            (``{"owner/repo": {"titles": [...], ...}}``).
        poc_dir: directory of ``<repo>/<id>_submission.md`` PoC ground-truth.
    """
    repos = {}
    if isinstance(repo_bounties, dict):
        candidate = repo_bounties.get('repos')
        if isinstance(candidate, dict):
            repos = candidate
    saturation: Dict[Tuple[str, str], float] = {}
    observed_cwes: set = set()
    if isinstance(existing_submissions, dict):
        for repo, record in existing_submissions.items():
            if not isinstance(repo, str) or not isinstance(record, dict):
                continue
            titles = record.get('titles')
            if not isinstance(titles, list):
                continue
            for title in titles:
                cwe = _classify(title)
                if not cwe:
                    continue
                observed_cwes.add(cwe)
                pair = (repo, cwe)
                saturation[pair] = saturation.get(pair, 0.0) + 1.0
    expected_value: Dict[str, float] = {}
    program_health: Dict[str, str] = {}
    for repo, record in repos.items():
        if not isinstance(repo, str) or not isinstance(record, dict):
            continue
        raw_payout = expected_payout(record, 'critical')
        if isinstance(raw_payout, bool) or not isinstance(raw_payout, (int, float)):
            raw_payout = 0.0
        expected_value[repo] = float(raw_payout)
        program_health[repo] = _program_health_from_note(record.get('pool_note'))
    poc_cwes = _poc_ground_truth_cwes(poc_dir)
    all_cwes = set(_BASE_CWES) | observed_cwes | poc_cwes
    pipeline_capability: Dict[str, str] = {cwe: _capability_for(cwe) for cwe in sorted(all_cwes)}
    return CorpusStats(saturation=saturation, expected_value=expected_value, program_health=program_health, pipeline_capability=pipeline_capability)
```

POST-EMIT SELF-CHECK (mandatory): the patched function contains the exact guard line `if isinstance(raw_payout, bool) or not isinstance(raw_payout, (int, float)):`, NO bare `float(expected_payout(...))` call remains, and every other line of the function (and of the module) is byte-identical to the baseline.

LOUD DIRECTIVE: touch NOTHING else. Do NOT modify `CorpusStats`, `_capability_for`, `_program_health_from_note`, `_classify`, `_poc_ground_truth_cwes`, any module-level constant, any import, `ngv2/prioritize.py` (its verbatim-band-value return is RELIED ON by other callers), or any test file.

# Required plan shape

EXACTLY ONE impl task. Use this task_id VERBATIM (the committed oracle is keyed to this brief): `task_id`: `ngv2_corpus_stats_null_payout`. meta_task_type=`data_model` (external NGv2 target — the diff-fuzzer cannot resolve external imports; a pure fail-safe coercion with no new behavior surface beyond the committed oracle). priority: high. dependencies: []. working_dir: `/home/xnihil0zer0/NobleGreedv2`. files_touched: `["ngv2/bounty_corpus_stats.py"]` ONLY. partial_edit semantics: SINGLE-SYMBOL patch of `compute_corpus_stats` per the DISPATCH DIRECTIVE — copy the DISPATCH DIRECTIVE — PATCH FORMAT block (including the full pinned function) VERBATIM into the task's `implementation_notes` so the blind worker sees it. verification_command: `python -m pytest -q tests/test_corpus_stats_null_payout_wired.py tests/test_bounty_corpus_stats_wired.py tests/test_sink_taxonomy_wired.py tests/test_candidate_builder_wired.py` (CWD-relative — NO `cd`; the UNION of every committed oracle touching this module, per the anti-seesaw rule). The committed RED oracle `tests/test_corpus_stats_null_payout_wired.py` (NGv2 commit ab3f665) is the authoritative acceptance contract — make it GREEN (5 tests) with the other three files staying GREEN; do NOT author new tests. `spec.functional_requirements` MUST be CONSOLIDATED to at most 5 entries, and `test_spec.unit_tests` MUST enumerate AT LEAST as many entries as `spec.functional_requirements` (validator floor: len(unit_tests) >= len(functional_requirements)); unit_tests entries are descriptors NAMING committed-oracle test cases (this does NOT authorize authoring new tests). `test_spec.regression_tests` (>=2 named committed cases): `test_numeric_payouts_unaffected`, `test_expected_value_reflects_observed_payouts` (from tests/test_bounty_corpus_stats_wired.py). `test_spec.edge_cases` (>=2, reflected in test names): `test_null_critical_payout_does_not_raise`, `test_non_numeric_payout_fails_safe_to_zero`, `test_every_repo_still_gets_an_expected_value`.

# Non-Goals

This is out of bounds and excluded; this section also carries the literal word integration so this EDIT task may reference it to excuse the integration-test requirement (this EDIT repeats "integration" in its own non_goals per META_TASK_POLICY):
- Do NOT "fix" the snapshot data (`data/ngv2/huntr_repo_bounties.json` is frozen ground truth — null bands are REAL observations).
- Do NOT change `ngv2/prioritize.py::expected_payout` (its verbatim return when the severity key is present is relied on elsewhere; the hardening belongs at THIS call site).
- Do NOT add severity fallback logic (e.g. null critical -> high) — fail-safe is 0.0, full stop; richer demand merging is the sibling `ngv2_demand_source_merge` leaf.
- Do NOT modify any other symbol, signature, import, or test; no network, clock, randomness, logging, or new dependencies.

# Inputs

- The committed authoritative oracle `tests/test_corpus_stats_null_payout_wired.py` (NGv2 commit ab3f665; currently RED: all 5 tests crash on `TypeError: float() argument ... 'NoneType'`). It feeds snapshot-shaped records mirroring the real frozen rows (`fastai/fastai` critical=null, `iterative/dvc` all-null + max_paid=null, a numeric `open-webui/open-webui` row, and a non-numeric `"lots"` string row) and pins: no raise, null/non-numeric -> 0.0, numeric -> unchanged float, every repo keyed.
- The module under edit: `ngv2/bounty_corpus_stats.py` (the baseline is read-only at `{WORK_DIR}/inbox/targets/ngv2/bounty_corpus_stats.py`).
- Must-stay-green union: `tests/test_bounty_corpus_stats_wired.py`, `tests/test_sink_taxonomy_wired.py`, `tests/test_candidate_builder_wired.py`.

# Deliverables

`ngv2/bounty_corpus_stats.py` with `compute_corpus_stats` exactly as pinned in the DISPATCH DIRECTIVE (everything else byte-identical), verified GREEN by `python -m pytest -q tests/test_corpus_stats_null_payout_wired.py tests/test_bounty_corpus_stats_wired.py tests/test_sink_taxonomy_wired.py tests/test_candidate_builder_wired.py` (23 passed).
