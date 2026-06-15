---
working_dir: "/home/xnihil0zer0/NobleGreedv2"
interfaces: "NEW pure module ngv2/demand_source_merge.py exposing merge_expected_payout(live_record, mined_record, severity='critical') -> int and merged_bounty(...) -> dict: merges the zeroed live huntr-feed payouts with the hand-mined data/ngv2/huntr_repo_bounties.json observed_payouts/pool_note ground truth plus a CVSS-proxy fallback on max_paid, live nonzero amount overriding — making the committed oracle tests/test_demand_source_merge.py GREEN"
meta_task_type: data_model
spec_author: "FIX-WAVE agent (JanusMask, 2026-06-12)"
---

# Title

ngv2/demand_source_merge.py (NEW module) — merged demand source for the selection ranker: live huntr-feed payout override > hand-mined `observed_payouts` (pool_note health-discounted) > CVSS-proxy on `max_paid`; fail-safe to 0, never raises.

# Scope

CREATE the NEW single-file module `ngv2/demand_source_merge.py`. Root cause (2026-06-12 live run): the live huntr public RSC feed zeroes `disclosure.amount`, so bounty records built by `ngv2.sourcing.huntr_refresh` carry all-zero `observed_payouts` and `ngv2.selection_ranker`'s demand/bounty term is INERT on live data. This leaf provides the pure merge: a positive live-feed band payout wins verbatim; otherwise the hand-mined per-repo `observed_payouts` from the frozen data/ngv2/huntr_repo_bounties.json ground truth (discounted x0.5 when the record's `pool_note` parses as `'at_risk'` via the EXISTING `ngv2.bounty_corpus_stats._program_health_from_note` — import it, do NOT reimplement); otherwise the CVSS-proxy fallback `max_paid x severity fraction` (critical=1.0, high=0.5, medium=0.08, low=0.01 — the snapshot's documented pricing model), same health discount, mined record first then live; otherwise 0. Every malformed input degrades to 0 — the public functions NEVER raise. Pure: stdlib + ngv2 only; no network, clock, disk, randomness, or input mutation.

DISPATCH DIRECTIVE — PATCH FORMAT (MANDATORY — WHOLE-FILE NEW MODULE): this is a NEW file; new-symbol + symbol-patch is a known `auto_commit_failed` shape. Emit the COMPLETE file `ngv2/demand_source_merge.py` (single-file whole-file emission — NEVER a `__JANUSMASK_PATCHES__` symbol patch, never a `__JANUSMASK_MANIFEST__`, never a dotted qualname). The exact validated reference content (reproduce BYTE-FOR-BYTE):

```python
"""Merged demand source for the selection ranker's bounty/demand term.

The live huntr public RSC feed zeroes ``disclosure.amount``, so bounty records
built by ``ngv2.sourcing.huntr_refresh`` carry all-zero ``observed_payouts``
and the ranker's demand term goes INERT on live data. This module merges THREE
demand sources, in priority order, into one effective expected payout:

1. LIVE override -- a positive live-feed payout for the severity band wins
   verbatim (no discount: it is an observed real payout).
2. HAND-MINED    -- the per-repo ``observed_payouts`` from the frozen
   data/ngv2/huntr_repo_bounties.json ground truth, discounted by a coarse
   program-health multiplier parsed from ``pool_note`` (reuses
   :func:`ngv2.bounty_corpus_stats._program_health_from_note`; 'at_risk'
   programs are halved).
3. CVSS-proxy    -- ``max_paid`` scaled by the snapshot's documented
   CVSS-severity pricing fractions (Critical=100%, High=50%, Medium=8%,
   Low=1%), with the same health discount.

Every failure path (missing/None/non-numeric/zero fields, malformed records,
unknown severity) degrades to ``0`` -- the public functions NEVER raise on
snapshot-shaped input. Pure: standard library + ngv2 only. No network, clock,
disk, randomness, or mutation of the input records.
"""
from __future__ import annotations
from typing import Any, Mapping, Optional
from ngv2.bounty_corpus_stats import _program_health_from_note
__all__ = ['merge_expected_payout', 'merged_bounty']

# Documented huntr pricing model: payouts scale by CVSS severity
# (Critical=100%, High=50%, Medium=~8%, Low=~1% of the repo base bounty).
_SEVERITY_FRACTION: dict = {'critical': 1.0, 'high': 0.5, 'medium': 0.08, 'low': 0.01}
# Coarse pool_note health discount; '$0'/paused/depleted pools still pay when
# the pool refills, so at-risk programs are discounted, never zeroed.
_HEALTH_MULTIPLIER: dict = {'healthy': 1.0, 'unknown': 1.0, 'at_risk': 0.5}


def _positive_number(value: Any) -> Optional[float]:
    """Coerce a strictly-positive int/float to float; anything else is None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if value > 0 else None


def _band_payout(record: Any, severity: str) -> Optional[float]:
    """The record's positive observed payout for *severity*, else None."""
    if not isinstance(record, Mapping):
        return None
    payouts = record.get('observed_payouts')
    if not isinstance(payouts, Mapping):
        return None
    return _positive_number(payouts.get(severity))


def _cvss_proxy(record: Any, severity: str) -> Optional[float]:
    """CVSS-severity-proxy payout: max_paid x documented severity fraction."""
    if not isinstance(record, Mapping):
        return None
    max_paid = _positive_number(record.get('max_paid'))
    fraction = _SEVERITY_FRACTION.get(severity)
    if max_paid is None or fraction is None:
        return None
    return max_paid * fraction


def merge_expected_payout(live_record: Any, mined_record: Any, severity: str = 'critical') -> int:
    """Effective expected payout merging live, hand-mined, and proxy demand.

    Priority: positive live-feed band payout (verbatim) > hand-mined band
    payout (health-discounted) > CVSS-proxy on ``max_paid`` (mined record
    first, then live; health-discounted) > 0. Returns a non-negative int and
    never raises on malformed input.
    """
    sev = str(severity).strip().lower()
    live = _band_payout(live_record, sev)
    if live is not None:
        return int(live)
    pool_note = mined_record.get('pool_note') if isinstance(mined_record, Mapping) else None
    health = _program_health_from_note(pool_note)
    multiplier = _HEALTH_MULTIPLIER.get(health, 1.0)
    mined = _band_payout(mined_record, sev)
    if mined is not None:
        return int(mined * multiplier)
    proxy = _cvss_proxy(mined_record, sev)
    if proxy is None:
        proxy = _cvss_proxy(live_record, sev)
    if proxy is not None:
        return int(proxy * multiplier)
    return 0


def merged_bounty(live_record: Any, mined_record: Any, severity: str = 'critical') -> dict:
    """A bounty mapping consumable by ``selection_ranker._coerce_payout``."""
    return {'expected_payout': merge_expected_payout(live_record, mined_record, severity)}
```

POST-EMIT SELF-CHECK (mandatory): exactly FIVE top-level `def`s (`_positive_number`, `_band_payout`, `_cvss_proxy`, `merge_expected_payout`, `merged_bounty`), `__all__ = ['merge_expected_payout', 'merged_bounty']`, the import `from ngv2.bounty_corpus_stats import _program_health_from_note`, NO other ngv2 import, NO reimplementation of pool_note parsing, and `merge_expected_payout({'observed_payouts': {'critical': 0}}, {'observed_payouts': {'critical': 1500, 'high': 750}, 'max_paid': 1500, 'pool_note': 'Pool shows $0 across all severities. Program may be paused or depleted.'}) == 750`.

LOUD DIRECTIVE: touch NOTHING else. Do NOT edit `ngv2/selection_ranker.py`, `ngv2/bounty_corpus_stats.py`, `ngv2/sourcing/**`, `ngv2/prioritize.py`, or any test file.

# Required plan shape

EXACTLY ONE impl task. Use this task_id VERBATIM (the committed oracle is keyed to this brief): `task_id`: `ngv2_demand_source_merge`. meta_task_type=`data_model` (external NGv2 target — the diff-fuzzer cannot resolve external imports; a pure new data-merge module with no behavior surface beyond the committed oracle). priority: high. dependencies: []. working_dir: `/home/xnihil0zer0/NobleGreedv2`. files_touched: `["ngv2/demand_source_merge.py"]` ONLY. partial_edit semantics: WHOLE-FILE single-file emission per the DISPATCH DIRECTIVE — copy the DISPATCH DIRECTIVE — PATCH FORMAT block (including the full pinned file content) VERBATIM into the task's `implementation_notes` so the blind worker sees it. verification_command: `python -m pytest -q tests/test_demand_source_merge.py tests/test_bounty_corpus_stats_wired.py tests/test_selection_ranker_wired.py` (CWD-relative — NO `cd`). The committed RED oracle `tests/test_demand_source_merge.py` (NGv2 commit ab3f665) is the authoritative acceptance contract — make it GREEN (12 tests; the other two files are the must-stay-green union of the imported/consumer modules); do NOT author new tests. `spec.functional_requirements` MUST be CONSOLIDATED to at most 5 entries, and `test_spec.unit_tests` MUST enumerate AT LEAST as many entries as `spec.functional_requirements` (validator floor: len(unit_tests) >= len(functional_requirements)); unit_tests entries are descriptors NAMING committed-oracle test cases (this does NOT authorize authoring new tests). `test_spec.regression_tests` (>=2 named committed cases): `test_live_nonzero_amount_overrides_mined`, `test_zeroed_live_feed_falls_back_to_mined_payouts`, `test_merged_bounty_is_ranker_consumable`. `test_spec.edge_cases` (>=2, reflected in test names): `test_malformed_inputs_degrade_to_zero`, `test_null_band_falls_back_to_cvss_proxy_on_max_paid`, `test_severity_is_case_insensitive`.

# Non-Goals

This is out of bounds and excluded; this section also carries the literal word integration so the task may reference it to excuse the integration-test requirement (this leaf repeats "integration" in its own non_goals per META_TASK_POLICY):
- Do NOT wire the merge into `ngv2/selection_ranker.py`, `ngv2/hunt_loop.py`, or any live call site — call-site integration is a separate future leaf; this leaf is ONLY the pure merge module.
- Do NOT edit `ngv2/bounty_corpus_stats.py` (a sibling leaf hardens it), `ngv2/prioritize.py`, `ngv2/sourcing/**`, or `data/ngv2/**`.
- Do NOT read any file at runtime (the snapshots are injected as dicts by callers), and do NOT add network, clock, randomness, logging, or new dependencies.
- Do NOT author or modify any test — the oracle is committed and authoritative.

# Inputs

- The committed authoritative oracle `tests/test_demand_source_merge.py` (NGv2 commit ab3f665; currently RED: `ModuleNotFoundError: No module named 'ngv2.demand_source_merge'`). It pins the record shapes (mirroring data/ngv2/huntr_repo_bounties.json `repos` records and huntr_refresh-built live records), the live-override/mined/proxy priority, the at-risk x0.5 discount, the case-insensitive severity, the never-raise fail-safe, and the `merged_bounty` -> `selection_ranker._coerce_payout` consumable shape.
- Existing siblings consulted (read-only): `ngv2/bounty_corpus_stats.py` (`_program_health_from_note` — the pool_note parser to IMPORT), `ngv2/selection_ranker.py` (`_coerce_payout` expects an int `expected_payout` key), `ngv2/sourcing/huntr_refresh.py` (the live record builder whose `observed_payouts` are zeroed by the feed), `ngv2/prioritize.py` (`expected_payout` — the severity-fraction precedent).
- stdlib + ngv2 only.

# Deliverables

The new pure module `ngv2/demand_source_merge.py` exactly as pinned in the DISPATCH DIRECTIVE, verified GREEN by `python -m pytest -q tests/test_demand_source_merge.py tests/test_bounty_corpus_stats_wired.py tests/test_selection_ranker_wired.py` (27 passed).
