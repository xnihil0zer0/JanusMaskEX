---
dependencies:
  - "title-cwe-and-corpus-stats"
interfaces: "SINK_PATTERNS: dict[str, list[str]]; compute_weights(stats: CorpusStats, repo: str) -> dict[str, float]; build_candidates(stats: CorpusStats) -> list[dict]; append_verdict(path: str, verdict: dict) -> None; load_verdicts(path: str) -> list[dict]; score_candidate(...) gains additive demand_score term + x confirmability multiplier (saturation stays dominant)"
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

Sink taxonomy, per-(repo,CWE) candidates, verdict store, deser_detect wiring, and additive ranker edit (Part C, Levels 2-3)

# Scope

Build the data-driven target+sink prioritization that consumes CorpusStats and feeds the EXISTING selection contract. (1) `ngv2/sink_taxonomy.py`: a registry mapping CWE -> sink patterns plus a learned per-target weight (demand x pipeline_capability x novelty) so the hunter scans high-value classes first per target. (2) `ngv2/candidate_builder.py`: builds per-(repo,CWE) candidates carrying per-CWE saturation. (3) `ngv2/verdict_store.py`: append-only persistence to `data/ngv2/hunt_verdicts.json`, closing the learn->hunt->verdict->re-learn loop. (4) EDIT: wire the already-built `ngv2/deser_detect.py` (CWE-502 pickle/marshal/yaml.load/torch.load/joblib) into the live scan catalog. (5) EDIT: a minimal additive change to `ngv2/selection_ranker.py::score_candidate` adding a small `demand_score` term and a `x confirmability` multiplier while KEEPING saturation dominance and the existing hard-gate behavior-compatible. New leaves ship `test_<module>_wired.py` oracles importing live `ngv2.<module>`, ≥2 edge_cases, CWD-relative `verification_command` (no `cd`); EDIT leaves prove behavior-compatibility.


REQUIRED PLAN SHAPE (the plan validator HARD-REJECTS drafts violating ANY of these):
- Exactly 5 tasks: (T-sinks) NEW single-file `ngv2/sink_taxonomy.py`; (T-cands) NEW single-file `ngv2/candidate_builder.py`; (T-verdicts) NEW single-file `ngv2/verdict_store.py`; (T-deser-wire) EDIT of `ngv2/pattern_scanner.py` registering a CWE-502 deserialization entry (pickle/marshal/yaml.load/torch.load/joblib sink patterns mirroring ngv2/deser_detect.py) into VULN_PATTERNS so scan_file/scan_directory emit CWE-502 findings — deser_detect.py itself is NOT modified; (T-ranker) EDIT of `ngv2/selection_ranker.py` adding keyword-only `demand_score: int = 0` (additive under the 100 cap) and `confirmability: float = 1.0` (final multiplier) to score_candidate, byte-identical at defaults. Unique task_ids, never `T1`.
- EVERY task carries ALL top-level fields: task_id, title, meta_task_type, priority (lowercase one of critical/high/medium/low), dependencies, files_touched, acceptance_criteria, spec_author, estimated_complexity, verification_command.
- EVERY task's test_spec lists >=2 edge_cases AND mirrors each of them in regression_tests or property_tests entries.
- EVERY task's spec non_goals MUST repeat the literal word "integration" — OR include an integration_test.
- verification_command is CWD-relative pytest, NO `cd` prefix anywhere. Use exactly: T-sinks -> `python -m pytest tests/test_sink_taxonomy_wired.py -q`; T-cands -> `python -m pytest tests/test_candidate_builder_wired.py -q`; T-verdicts -> `python -m pytest tests/test_verdict_store_wired.py -q`; T-deser-wire -> `python -m pytest tests/test_deser_catalog_wired.py tests/test_pattern_scanner.py -q`; T-ranker -> `python -m pytest tests/test_selection_ranker_demand_confirmability.py tests/test_selection_ranker_wired.py -q`.
- Do NOT add test_authoring tasks: the RED oracles are ALREADY COMMITTED to the target repo master (commit 7f9811c and successors: tests/test_sink_taxonomy_wired.py, tests/test_candidate_builder_wired.py, tests/test_verdict_store_wired.py, tests/test_selection_ranker_demand_confirmability.py, tests/test_deser_catalog_wired.py). Those oracle files ARE the binding contract — implement exactly their asserted signatures and semantics.

# Non-Goals

integration. This child includes EDITs (wiring `deser_detect` into the scan catalog and the additive `selection_ranker.score_candidate` term); per the epic Non-Goals it carries the literal word integration so each EDIT leaf may reference it to excuse the integration-test requirement. Do NOT rewrite `selection_ranker` — the only change is the additive `demand_score` + `confirmability` term; `rank_candidates`, the hard 5-gate, `target_qualify`, and `bounty_gate` must stay behavior-compatible. Do NOT modify `deser_detect.py`'s detection logic — only register it into the catalog. Do NOT auto-submit; findings park at `awaiting_submission`. Do NOT do fetch/scrape work or build snapshot schema.

# Inputs

From sibling `title_cwe_and_corpus_stats`: `classify_title(title: str) -> str` and `compute_corpus_stats(repo_bounties: dict, existing_submissions: dict, poc_dir: str) -> CorpusStats` where `CorpusStats` has fields {saturation: dict[tuple[str,str],float], expected_value: dict[str,float], program_health: dict[str,str], pipeline_capability: dict[str,str]}. Existing to extend (not replace): `ngv2/selection_ranker.py::rank_candidates`/`score_candidate`, `ngv2/target_qualify.py::qualify` (hard 5-gate), `ngv2/bounty_gate.py::gate`, `ngv2/oracle_materializer.py`. Already-built unwired detector: `ngv2/deser_detect.py` (CWE-502 patterns). Legacy reference (read-only): `/home/xnihil0zer0/AI-Data/NobleGreed-legacy/target_priority_scorer.py` weights.

# Deliverables

`ngv2/sink_taxonomy.py` exposing `SINK_PATTERNS: dict[str, list[str]]` (CWE -> sink regex/patterns) and `compute_weights(stats: CorpusStats, repo: str) -> dict[str, float]` (per-CWE weight = demand x pipeline_capability x novelty). `ngv2/candidate_builder.py` exposing `build_candidates(stats: CorpusStats) -> list[dict]` (one candidate per (repo,CWE) with per-CWE saturation). `ngv2/verdict_store.py` exposing `append_verdict(path: str, verdict: dict) -> None` and `load_verdicts(path: str) -> list[dict]` over append-only `data/ngv2/hunt_verdicts.json`. Edited `ngv2/selection_ranker.py::score_candidate` with additive `demand_score` term and `x confirmability` multiplier. `deser_detect` registered in the scan catalog.
