# NGv2 Gap Briefs — ready-to-run, EPIC-scoped JM build briefs

Authored 2026-06-07 from the harvest run-phase (DEFER rows + run discoveries).
Each is **one root epic brief, one distinct subject, maximal reasonable scope** —
feed JM the root and let its planner decide the tree (per the Epic-4 owner
correction: hand JM the decomposition decision, suggestions non-binding). These
are **NOT dispatched this session** — JM gate stays `pause`, allowlist deny-all.
Dispatch each with owner sign-off, one epic at a time, into NGv2
(`JANUSMASK_WORKING_DIR=/home/xnihil0zer0/NobleGreedv2`).

Distinguish the gap kinds:
- **DATA gap** → harvest more (no brief; do it directly like §5 of the harvest).
- **MODULE/CONTRACT gap** → epic brief below (pipeline-built tooling).
- **WIRING gap** → small brief, foldable into a nearby epic.

---

## EPIC 1 — Legacy analytics-data ingestion (deterministic seam extractors)

`# Scope`
NGv2's analytics modules (`ops_analytics`, `portfolio_intel`, `portfolio_scanner`,
`revenue_accelerator`, `rl_debate_weights`, `hunting_roi_tracker`) are pure shells
that consume **injected** Python dicts/lists. The legacy data that fed them lives in
SQLite (`worker_registry.db` ~516 KB, `findings.db` ~1.2 MB) and JSONL
(`rlcf_rewards.jsonl` ~21 KB, `worker_progress.jsonl` ~465 KB). Build a family of
**deterministic, stdlib-only extractor modules** that read a legacy export and emit
the exact injected-seam shape each analytics oracle asserts — turning the analytics
layer from "green on fixtures" into "green on real history". Each extractor takes an
explicit input path (no wall-clock/network), so it is oracle-testable with a small
committed fixture export.

Suggested leaves (JM decides): `findings_export` (findings.db → `list[finding dict]`
with `repo/cwe/severity/poc_status/bounty_eligible`), `workers_export`
(worker_registry.db → `list[worker dict]` with `worker_type/status/duration_min`),
`progress_export` (worker_progress.jsonl → phase-tagged list), `rlcf_export`
(rlcf_rewards.jsonl → `debate_result`+`actual_outcome` records for
`rl_debate_weights.RLState.record_outcome`), `portfolio_export` (portfolio_review.json
+ eligibility → `portfolio_intel` seam dict).

`# Non-goals`
No live DB connections at runtime; no schema migration of the legacy DBs; no network;
no analytics *module* changes (they already take the seam) — extractors only. (This
is a data-ingestion epic, NOT submission/reporting — keep separate.)

`# Inputs`
A committed, down-sampled fixture export per source under
`tests/fixtures/analytics/` (hand-authored, small). The legacy DBs at
`/mnt/ai-data/NobleGreed-legacy/data/` are the real sources (read-only, off-tree).

`# Deliverables`
One extractor module + oracle per source; each oracle asserts the emitted shape
matches the consuming analytics module's documented seam contract; a wiring test
showing `extractor → analytics_module` produces a stable result.

---

## EPIC 2 — Submission & report format fidelity vs the golden corpus

`# Scope`
The 24-package golden PoC corpus is now committed at `data/ngv2/poc_submissions/`.
The run-phase exposed that `submission_parser.parse_submission_file` returns an
**empty title** for the golden `# <ID>: <Title>` H1 + `## Huntr Form Fields` /
`### N. <Field>` layout (Gap G1). Harden the submission/reporting modules so they
round-trip the real golden corpus losslessly: parse every golden `*_submission.md`
into a complete `FindingSubmission` (id, title, repo, cwe, cvss, vuln_type,
description, poc_code), and re-render via `huntr_form` / `submission` / `report` to a
form that matches the golden fields. The golden corpus becomes the regression oracle.

Suggested leaves (JM decides): `submission_parser` format-coverage fix (H1-ID title +
`### N.` field extraction), a `golden_corpus_regression` oracle that parses all 24
packages and asserts non-empty title/repo/cwe, `huntr_form` round-trip fidelity vs
the golden `### 4. Vulnerability Type` / `### 5. CWE` fields, `submission_readiness`
scoring over the corpus.

`# Non-goals`
No live huntr submission/network; no rewriting the golden files (read-only exemplars);
no analytics ingestion (Epic 1) — this is purely parse/format/render fidelity.

`# Inputs`
`data/ngv2/poc_submissions/**` (committed golden corpus). The CWE→vuln-type map in
`huntr_form.CWE_VULN_TYPES`. Existing oracles `tests/test_submission_parser.py`,
`test_huntr_form.py`, `test_submission*.py`.

`# Deliverables`
Format-coverage fix + a corpus-wide regression oracle (parses all golden packages
green); a round-trip test (`parse → build_form → render`) over ≥3 representative
packages (a JS web-vuln, a Python deser, a multi-finding package).

---

## EPIC 3 — Knowledge taint-training corpus loader (`root_cause`)

`# Scope`
The legacy `knowledge/taint_specs/training/taint_specs.jsonl` (36 KB; entries with
`cwe/language/api_pattern/source_spec/sink_spec/ql_snippet`) is a valuable training
corpus for `root_cause`, but no NGv2 oracle pins a contract for it yet. Define a
deterministic, stdlib-only loader/validator (mirroring `taint_spec_library`'s
manifest discipline) that ingests the training JSONL into typed records, validates
each row (CWE regex, non-empty source/sink specs, language), and exposes a query
surface `root_cause` can consume. Then harvest the corpus into `data/ngv2/` behind
the new contract.

Suggested leaves (JM decides): `taint_training_loader` (JSONL → validated records),
`root_cause` consumption wiring over the loaded corpus, a `cwe_index` (group specs by
CWE for lookup).

`# Non-goals`
No model training, no GraphMERT/RLCF pipeline (out of clean-room scope), no GPU, no
CodeQL/semgrep execution — parse + validate + index only.

`# Inputs`
`/mnt/ai-data/NobleGreed-legacy/knowledge/taint_specs/training/taint_specs.jsonl`
(read-only source; harvest a validated copy once the contract lands). The existing
`taint_spec_library` conventions as the design template.

`# Deliverables`
Loader module + oracle (validates + rejects malformed rows); the harvested training
corpus committed at `data/ngv2/taint_specs/training/` once it loads green; a
`root_cause` wiring test.

---

## EPIC 4 — Agentic end-to-end PoC writer (design-first; see NGV2_POC_WRITER_DESIGN.md)

`# Scope`
Graft a JanusMaskJR-style dual-agent + Stop-hook loop onto the NGv2 PoC path so a PoC
is drafted, **detonated, and refined end-to-end** until it reproduces the finding
(replacing the lazy `js_poc_templates` scaffolding). **Mostly a PORT of JM's
synthesis core** (owner-authorized — `ast_retry.py`, `agent_jail.py`, `dbus_proxy.py`
copy-verbatim; `orchestrator_worker`/`cross_examiner`/`sandbox_smoke`/`embedded_test_runner`
light-adjust; Stop hook rewritten around a *detonation* acceptance gate). The net-new
NGv2 **deterministic tooling** pieces (the `poc_writer` drafter/refiner seam contract,
the acceptance-gate evaluator) go through the JM pipeline as their own leaves.

This epic is **design-complete** in `NGV2_POC_WRITER_DESIGN.md` (per-component
COPY/ADAPT/BUILD-NEW table, acceptance-oracle + Stop-hook spec, mock-vs-live seam).
Only the BUILD-NEW leaves are pipeline work; the PORT leaves are direct copies in the
live-runtime layer (not clean-room, per §9 authorization). Keep separate from Epics
1–3 (distinct subject: live-runtime PoC authoring, not deterministic data tooling).

`# Non-goals`
No real/live detonation during the build (scripted/mock runner only; real bwrap
runner stays behind an owner-gated flag); no clean-room re-synthesis of the ported JM
orchestration (copy it); no submission/analytics scope (Epics 1–2).

`# Inputs`
`NGV2_POC_WRITER_DESIGN.md`; the JM source files it names; NGv2 seams
`detonation.DetonationChamber`, `poc_runner.make_scripted_runner`, `contracts.PoC`,
`submission_readiness.check_submission_pkg`; the golden corpus as exemplars +
acceptance ground-truth.

`# Deliverables`
Per the design doc's sequenced plan: the ported synthesis core landed in NGv2's
runtime layer; the BUILD-NEW `poc_writer` tooling + acceptance-gate evaluator built
via the pipeline with oracles; an e2e demo drafting → detonating (scripted) → refining
one finding to a reproduced verdict.
