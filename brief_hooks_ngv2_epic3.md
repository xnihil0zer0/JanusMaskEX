---
epic: true
child_epics: true
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

NobleGreedv2 Epic-3: the hunt-to-submission DETERMINISTIC tooling — a FAT, multi-level
epic that decomposes into FOUR sub-epics, each itself decomposing into THREE leaf
modules (twelve leaves total), built into the external NobleGreedv2 repo.

# Scope

Decompose this epic into EXACTLY FOUR child briefs, and EACH child brief is ITSELF AN
EPIC (`epic: true`, `plan_kind: epic`) that further decomposes into THREE leaf module
briefs. This is a TWO-LEVEL decomposition (epic -> sub-epic -> leaf). Every leaf is a
pure, deterministic, stdlib-only Python module under the `ngv2/` package in the
external repo (its own git + venv), pinned by a HAND-AUTHORED ORACLE ALREADY COMMITTED
to the NobleGreedv2 repo, so every leaf is IMPL-ONLY (must NOT author tests) and is a
NEW single module file submitted WHOLE-FILE.

This epic manufactures only the DETERMINISTIC, mock-testable tooling that orchestrates
hunting — the dangerous LIVE work (running real exploit PoCs against real targets)
stays data-driven at NobleGreedv2 runtime and is NOT built here. Leaves build ON TOP of
the ALREADY-COMMITTED Epic-1 substrate (`ngv2.contracts`, `ngv2.state_machine`,
`ngv2.detonation`) and Epic-2 modules (`ngv2.grounding`, `ngv2.poc_runner`,
`ngv2.report`, `ngv2.pipeline`); NO leaf depends on another Epic-3 leaf (they are
mutually independent and may build in any order).

Produce these FOUR sub-epic children with these exact slugs:

## Sub-epic A — slug `ngv2-intake` (`epic: true`)
Target INTAKE & prioritization. Decomposes into THREE leaves:
- `ngv2-huntr-data` -> `ngv2/huntr_data.py` — load huntr eligibility/bounty/submission
  JSON into typed `RepoBounty` records (`parse_bounties`, `parse_existing_submissions`).
- `ngv2-prioritize` -> `ngv2/prioritize.py` — `expected_payout(bounty, severity)` +
  `rank_targets(bounties, *, severity)` deterministic ROI ranking with saturation
  tie-break.
- `ngv2-dedup` -> `ngv2/dedup.py` — `normalize_title`, `is_duplicate`,
  `filter_new(findings, existing_titles)` over `ngv2.contracts.Finding`.

## Sub-epic B — slug `ngv2-grounding-full` (`epic: true`)
GROUNDING & confidence. Decomposes into THREE leaves:
- `ngv2-semgrep-adapter` -> `ngv2/semgrep_adapter.py` — `build_semgrep_argv` +
  injected-runner `run_semgrep(target, *, runner)`.
- `ngv2-fp-filter` -> `ngv2/fp_filter.py` — `FPPattern`, `load_fp_patterns`, `matches`,
  `filter_findings` (drop by-design / protocol-mandated FPs).
- `ngv2-confidence` -> `ngv2/confidence.py` — `CONFIDENCE_TIERS` + `classify(signals)`
  4-tier confidence from multi-tool agreement.

## Sub-epic C — slug `ngv2-triage` (`epic: true`)
TRIAGE & verdict. Decomposes into THREE leaves:
- `ngv2-verdict` -> `ngv2/verdict.py` — `Verdict` dataclass (TP/FP + confidence) with
  `to_dict`/`from_dict`/`validate`.
- `ngv2-triage-parser` -> `ngv2/triage_parser.py` — `parse_triage(debate)` mapping an
  ng-triage debate JSON to a normalized verdict dict.
- `ngv2-triage-aggregate` -> `ngv2/triage_aggregate.py` — `aggregate(verdicts)` counts
  + `keep_true_positives(verdicts)`.

## Sub-epic D — slug `ngv2-submission-pkg` (`epic: true`)
SUBMISSION packaging. Decomposes into THREE leaves:
- `ngv2-cvss` -> `ngv2/cvss.py` — `parse_vector`, deterministic CVSS v3.1
  `base_score(vector)`, `severity_label(score)`.
- `ngv2-huntr-form` -> `ngv2/huntr_form.py` — `HUNTR_FORM_FIELDS`, `CWE_VULN_TYPES`,
  `build_form(finding, poc, context)` -> the 12 huntr form fields.
- `ngv2-submission` -> `ngv2/submission.py` — `render_submission(form)` markdown +
  `assemble_package(finding, poc, live_test)`.

# Inputs

- The external NobleGreedv2 repo at the epic `working_dir`
  (`/home/xnihil0zer0/NobleGreedv2`), which already contains the committed Epic-1
  substrate (`ngv2/contracts.py`, `ngv2/state_machine.py`, `ngv2/detonation.py`),
  the committed Epic-2 modules (`ngv2/grounding.py`, `ngv2/poc_runner.py`,
  `ngv2/report.py`, `ngv2/pipeline.py`), and the twelve committed Epic-3 leaf oracles
  (`tests/test_{huntr_data,prioritize,dedup,semgrep_adapter,fp_filter,confidence,verdict,triage_parser,triage_aggregate,cvss,huntr_form,submission}.py`).
- Every leaf consumes only the committed substrate via plain imports; the public
  shapes are stable (already committed + tested). No leaf depends on another Epic-3 leaf.

# Deliverables

Four sub-epic briefs (each `epic: true`, each decomposing into its three named leaves),
and ultimately twelve NEW single-file whole-file `ngv2/` modules. Every brief at every
level carries `working_dir: /home/xnihil0zer0/NobleGreedv2`. Every leaf is IMPL-only
(oracle already committed at `tests/test_<leaf>.py`) with verification_command
`python -m pytest tests/test_<leaf>.py -q`.

# Non-goals

No live exploit execution (stays at NobleGreedv2 runtime). No tests authored by leaves
(oracles committed). No file/network I/O; injected runners only. No leaf depends on
another Epic-3 leaf. No third-party imports. integration: the deterministic tooling is
pinned solely by the committed oracles; no cross-module wiring is added in this epic.
