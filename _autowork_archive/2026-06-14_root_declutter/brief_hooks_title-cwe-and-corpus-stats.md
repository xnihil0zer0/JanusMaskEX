---
interfaces: "classify_title(title: str) -> str; compute_corpus_stats(repo_bounties: dict, existing_submissions: dict, poc_dir: str) -> CorpusStats; CorpusStats has fields {saturation: dict[tuple[str,str],float], expected_value: dict[str,float], program_health: dict[str,str], pipeline_capability: dict[str,str]}"
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

Title->CWE classifier (+ novelty_corpus fix) and pure CorpusStats analytics (Part C, Levels 0-1)

# Scope

Build the learning layer's pure analytics foundation. (1) `ngv2/title_cwe_classifier.py`: a deterministic keyword-rule title->CWE classifier returning a CWE id string (e.g. 'CWE-502', 'CWE-918', 'CWE-22', 'CWE-78') or '' when unknown. (2) Apply the additive CWE fix in `ngv2/novelty_corpus.py`: where `load_known_corpus` currently flattens every title with `'cwe': ''`, populate it via the new classifier so the per-finding class signal is preserved (behavior-compatible otherwise). (3) `ngv2/bounty_corpus_stats.py`: a pure module producing a `CorpusStats` dataclass over the three snapshot JSONs plus our PoC ground-truth, computing per-(repo,CWE) saturation, per-repo expected value (REUSING `ngv2/prioritize.py::expected_payout`, not reimplementing), `program_health` parsed from `pool_note`, and a `pipeline_capability[cwe]` map with values in {'scannable+confirmable','scannable','none'}. Each new leaf ships a `test_<module>_wired.py` oracle importing live `ngv2.<module>`, ≥2 edge_cases, CWD-relative `verification_command` (no `cd`).


REQUIRED PLAN SHAPE (the plan validator HARD-REJECTS drafts violating ANY of these):
- Exactly 3 tasks: (T-classifier) NEW single-file module `ngv2/title_cwe_classifier.py`; (T-novelty) EDIT of existing `ngv2/novelty_corpus.py` (additive cwe population only); (T-stats) NEW single-file module `ngv2/bounty_corpus_stats.py`. Unique task_ids, never `T1`.
- EVERY task carries ALL top-level fields: task_id, title, meta_task_type, priority (lowercase one of critical/high/medium/low), dependencies, files_touched, acceptance_criteria, spec_author, estimated_complexity, verification_command.
- EVERY task's test_spec lists >=2 edge_cases AND mirrors each of them in regression_tests or property_tests entries.
- EVERY task's spec non_goals MUST repeat the literal word "integration" (this excuses the otherwise-mandatory integration_test, per the epic Non-Goals) — OR include an integration_test.
- verification_command is CWD-relative pytest, NO `cd` prefix anywhere. Use exactly: T-classifier -> `python -m pytest tests/test_title_cwe_classifier_wired.py -q`; T-novelty -> `python -m pytest tests/test_novelty_corpus_cwe.py -q`; T-stats -> `python -m pytest tests/test_bounty_corpus_stats_wired.py tests/test_novelty_corpus_cwe.py -q`.
- Do NOT add test_authoring tasks: the RED oracles are ALREADY COMMITTED to the target repo master (commit bfee473: tests/test_title_cwe_classifier_wired.py, tests/test_bounty_corpus_stats_wired.py, tests/test_novelty_corpus_cwe.py). Those oracle files ARE the binding contract — implement exactly their asserted signatures and semantics.
- T-novelty and T-stats depend on T-classifier (in-plan dependencies edge).

# Non-Goals

integration. This child includes an EDIT (the `novelty_corpus.py` CWE population fix); per the epic Non-Goals it carries the literal word integration so the EDIT leaf may reference it to excuse the integration-test requirement. Do NOT alter the public behavior of `novelty_corpus.load_known_corpus` beyond populating the previously-empty `cwe` field. Do NOT reimplement `expected_payout` — call the existing one. Do NOT do any network/fetch work, write snapshots, build sink taxonomies, or touch `selection_ranker`. Do NOT auto-submit anything.

# Inputs

Existing modules to reuse unchanged-in-contract: `ngv2/prioritize.py::expected_payout`, `ngv2/novelty_corpus.py::load_known_corpus` (the only file edited here). Real corpus to learn from: `data/ngv2/huntr_existing_submissions.json` (real titles), `data/ngv2/huntr_repo_bounties.json` (`observed_payouts`/`pool_note`), `data/ngv2/huntr_eligible_cache.json`, and `data/ngv2/poc_submissions/*.md` (our confirmed PoCs with `### 5. CWE` fields).

# Deliverables

`ngv2/title_cwe_classifier.py` exposing `classify_title(title: str) -> str` (returns a CWE id like 'CWE-502' or '' if unknown). `ngv2/bounty_corpus_stats.py` exposing the `CorpusStats` dataclass (fields: per-(repo,CWE) saturation, per-repo expected_value, program_health, pipeline_capability: dict[str,str]) and `compute_corpus_stats(repo_bounties: dict, existing_submissions: dict, poc_dir: str) -> CorpusStats`. Edited `ngv2/novelty_corpus.py` now populating `cwe` via `classify_title`.
