---
epic: true
working_dir: "/home/xnihil0zer0/NobleGreedv2"
interfaces: "Pure injected-seam Python modules under ngv2/**; scraper PRODUCES the three data/ngv2/*.json snapshots the existing loaders already read; learning layer feeds richer facts into the existing selection_ranker contract."
---

# Title

Live Bounty Sourcing and Learning Layer. NobleGreedv2 currently sources bounty targets from three STATIC JSON snapshots in `data/ngv2/` that were hand-placed and frozen on 2026-03-28/06-07 and have never been refreshed. The `ngv2/sourcing/huntr_client.py` "live fetch" seam was written against an imagined public JSON API that does not exist (huntr.com is a Next.js SPA), emits the wrong shape (`Bounty` objects, not the snapshot JSON), and is imported by nothing — so the system has been ranking targets off stale data the whole time. This epic builds (1) a real live multi-source scraper that produces fresh, schema-correct snapshots, and (2) a corpus-learning layer that mines those snapshots to learn which bug classes actually pay in our target repos and steers target + sink selection toward valuable, findable, AND pipeline-confirmable bounties. The strategic motivation is measured: deserialization (CWE-502) + SSRF (CWE-918) + path-traversal (CWE-22) make up 37.9% of all paid huntr findings across 20+ repos each, yet the current scanner only hunts command-injection (CWE-78) — the one over-saturated class. This epic closes the discovery gap by replacing frozen data and command-injection tunnel-vision with live data and data-driven class selection.

# Scope

Build, via the pipeline, into the NobleGreedv2 repo (`working_dir`), as a decomposed set of small pure modules (one file per leaf, each with a `*_wired` oracle that imports the live `ngv2.<module>`):

**Part A — Live sourcing (the scraper).** A producer that writes the three exact JSON files the existing loaders (`ngv2/huntr_cache_loader.py`) already consume, leaving all downstream code untouched:
- `huntr_eligible_cache.json` = `{"repos": [sorted "owner/repo" strings], "fetched_at": "<iso8601 UTC>"}`
- `huntr_repo_bounties.json` = `{"repos": {"owner/repo": {eligible, tier, observed_payouts:{critical,high,medium,low}, max_paid, total_advisories, submissions, pool_note}}, ...}`
- `huntr_existing_submissions.json` = `{"owner/repo": {"status": int, "count": int, "titles": [str,...]}}`

huntr.com delivers data as React Server Component (RSC) "flight" payloads embedded in server-rendered HTML — fetchable with a plain HTTP GET carrying an `RSC: 1` header (no full browser needed for bulk; Playwright only for lazy-loaded per-disclosure bodies). The hacktivity feed `GET /bounties/hacktivity` embeds ~100 full records (fields: id, title, createdAt, patch_commit_sha, status, cve_id, cvss{...}, cwe{id,description}, repository{owner,name,language}, disclosure{amount}, maintainer triage). Per-repo pages `GET /repos/{owner}/{name}` embed the full disclosure set plus maintainer accept/reject rationale (`#score|0|awarded`, `#self_closedduplicate`, free-text rejection reasons). The `/bounties` index is the authoritative eligibility list (legacy lesson — a `/repos/{x}` page returning 200 does NOT mean the repo accepts submissions). All parsing must be pure over injected fetched content so oracles stay offline/hermetic; the live fetcher is an injected seam.

**Part B — Other-platform enrichment (free clean APIs).** Fetchers for OSV.dev (`POST https://api.osv.dev/v1/query`, no auth, plus GCS bulk dumps) and GitHub Security Advisories (`GET https://api.github.com/advisories?ecosystem=pip`, use the already-authenticated `gh` token → 5000 req/hr), joined to huntr records on `cve_id`/`ghsa_id`. Both carry CWE, CVSS, fix-commit, and (GHSA) `vulnerable_functions[]` — direct reachability signal. Same producer pattern: parse pure, merge into the snapshot schema.

**Part C — The learning layer (apply the lessons).** Pure analytics + selection modules that turn the scraped corpus into target+sink prioritization, feeding the EXISTING `ngv2/selection_ranker.py` contract (do not rewrite it):
- A title→CWE classifier (deterministic keyword rules; also fixes the `ngv2/novelty_corpus.py` bug that flattens every title with `'cwe': ''`, discarding the only per-finding class signal).
- A corpus-stats module producing a `CorpusStats` dataclass: per-(repo,CWE) saturation, per-repo expected value (reuse `ngv2/prioritize.py::expected_payout`), `program_health` parsed from `pool_note`, and a `pipeline_capability[cwe]` map (scannable / scannable+confirmable / none).
- A sink-taxonomy registry mapping CWE → sink patterns + a learned per-target weight (`demand × pipeline_capability × novelty`), so the hunter scans high-value classes first per target instead of a fixed catalog.
- A small additive edit to `selection_ranker.score_candidate` adding a minor `demand_score` term and a `×confirmability` multiplier (keeping saturation dominance), plus per-(repo,CWE) candidate granularity.
- Wire the already-built `ngv2/deser_detect.py` (CWE-502) into the live scan catalog — the single highest-leverage leaf (high demand across 21 repos, detector exists, PoC+jail already works).
- A refresh entrypoint that composes fetch → parse → freshness/rate-limit policy → write snapshots, and an append-only `data/ngv2/hunt_verdicts.json` verdict store closing the learn→hunt→verdict→re-learn loop.

# Non-Goals

This is out of bounds and excluded; this section also carries the literal word integration so that any child EDIT task may reference it to excuse the integration-test requirement (each EDIT child must repeat "integration" in its own non_goals):
- NEVER auto-submit to any platform. No HTTP POST to huntr, no Playwright form-fill/click submission. The pipeline parks findings at `awaiting_submission` for a human only.
- Do NOT modify the downstream contracts beyond the one specified additive edit to `selection_ranker.score_candidate` and the `novelty_corpus` CWE fix — `huntr_cache_loader`, `huntr_data`, `check_eligible`, `target_qualify`, `bounty_gate`, and the ranker's hard-gate must stay behavior-compatible.
- Do NOT retrofit the inert `ngv2/sourcing/huntr_client.py` — leave it as dead code; build a fresh correctly-shaped producer.
- Do NOT commit `data/ngv2/*.json` as pipeline artifacts — they are RUNTIME outputs of the refresh entrypoint; only the code that writes them is a pipeline leaf.
- Defer HackerOne and Bugcrowd scrapers (web-target-skewed, low ML value, anti-bot friction) and the full evolutionary generation loop.
- No bulk-harvesting that violates robots/ToS; polite rate-limited fetching only (~1 req/sec, incremental by `published_at`).

# Inputs

Fixed inputs to reuse — do NOT rebuild these:
- Existing NGv2 loaders/consumers (untouched, the scraper's only contract is the 3 JSON files): `ngv2/huntr_cache_loader.py` (`load_cache`/`load_repo_bounties`/`load_existing_submissions`, `_DEFAULT_DATA_DIR = <ngv2>/../data/ngv2`), `ngv2/huntr_eligible_cache.py::check_eligible`, `ngv2/huntr_data.py::parse_bounties`/`parse_existing_submissions`, `ngv2/novelty_corpus.py::load_known_corpus`.
- Existing selection/scoring to extend, not replace: `ngv2/selection_ranker.py::rank_candidates`/`score_candidate`, `ngv2/target_qualify.py::qualify` (hard 5-gate), `ngv2/bounty_gate.py::gate`, `ngv2/prioritize.py::expected_payout`, `ngv2/oracle_materializer.py`.
- Already-built but unwired detector to wire in: `ngv2/deser_detect.py` (CWE-502 patterns: pickle/marshal/yaml.load/torch.load/joblib).
- Existing seam patterns to mirror: `ngv2/sourcing/huntr_client.py` `Fetcher = Callable[[url, headers], (status, body, headers)]` injected-seam style; `ngv2/acquisition/cloner.py` injected-runner style; `ngv2/contracts.py` `Bounty`/`Target` dataclasses (`to_dict`/`from_dict`/`validate`).
- Real data to learn from: `data/ngv2/huntr_existing_submissions.json` (32 repos, real titles), `huntr_repo_bounties.json` (per-repo `observed_payouts`/`pool_note` with hand-mined learnings), `huntr_eligible_cache.json` (~95 eligible repos), `data/ngv2/poc_submissions/*.md` (our own confirmed-PoC ground truth with `### 5. CWE` fields).
- Legacy reference (read-only, for lessons already distilled into this brief): `/home/xnihil0zer0/AI-Data/NobleGreed-legacy` (`services/rate_limiter.py` flock pattern, `services/qualify_target.py` 5-gate, `target_priority_scorer.py` weights, the MFF model-file-format $4000 track).
- The hand-authorable space: `_e2e_run/` and `tests/` in NGv2 are hand-authorable; ONLY `ngv2/**` routes through the pipeline.

# Deliverables

A decomposed child-brief set (you, the planner, decide the actual tree) building roughly this dependency-ordered shape — each leaf one new file with a `test_<module>_wired.py` oracle (imports live `ngv2.<module>`), CWD-relative `verification_command` (no `cd` prefix), ≥2 edge_cases, and EDIT children repeating "integration" in non_goals:

Level 0 (pure, no deps): `ngv2/sourcing/huntr_snapshot_schema.py` (builders+deterministic writers for the 3 JSON shapes; oracle round-trips into the existing loaders), `ngv2/sourcing/huntr_page_parser.py` (pure RSC-flight extractor over injected HTML fixtures), `ngv2/title_cwe_classifier.py` (pure title→CWE; fixes the novelty `'cwe':''` gap).

Level 1 (depends L0): `ngv2/sourcing/browser_fetcher.py` (injected live fetcher: `RSC:1` HTTP for bulk, Playwright for detail bodies; tests use a stub fetcher, stay offline), `ngv2/sourcing/refresh_policy.py` (pure staleness + rate-limit/backoff over `fetched_at`), `ngv2/bounty_corpus_stats.py` (pure `CorpusStats` over the 3 JSONs + our PoCs).

Level 2 (depends L0+L1): `ngv2/sourcing/huntr_refresh.py` (the wired refresh entrypoint composing fetch→parse→policy→write_snapshots into `_DEFAULT_DATA_DIR`; oracle injects a stub fetcher + tmp dir, asserts the 3 files land and the existing `load_cache` consumes them unchanged), `ngv2/sink_taxonomy.py` (CWE→sink-patterns + learned per-target weights), `ngv2/candidate_builder.py` (per-(repo,CWE) candidates with per-CWE saturation), `ngv2/verdict_store.py` (append-only verdict persistence; closes the loop).

Level 3 (small additive EDITs, depend on the learning modules): wire `ngv2/deser_detect.py` into the scan catalog; the additive `selection_ranker.score_candidate` demand + confirmability terms; optional `ngv2/sourcing/osv_fetcher.py` / `ghsa_fetcher.py` (free-API enrichment, same producer pattern) joined on cve_id/ghsa_id.

Sequencing between children is brief-level: hold a child until its dependency level has landed and NGv2 master is ff-advanced (declare `dependencies: [sibling-slug]` frontmatter as a hint). New sub-packages (e.g. `ngv2/sourcing/` already exists) need an empty `__init__.py` committed to NGv2 master before any leaf in them dispatches.

**Definition of done (the behavior that proves it):**
1. `huntr_refresh` run live against real huntr.com produces fresh, schema-valid `data/ngv2/*.json` that the unchanged `huntr_cache_loader`/`check_eligible`/`parse_bounties` read without error, with `fetched_at` current and a meaningfully larger eligible-repo set than the frozen 95.
2. `bounty_corpus_stats` over the live corpus reports per-(repo,CWE) saturation and the CWE-class payout distribution, and `sink_taxonomy.compute_weights` ranks CWE-502/918/22 above CWE-78 for the repos where the data shows they pay (e.g. bentoml/mlflow/metaflow → 502).
3. `deser_detect` is reachable from the live scan path and `selection_ranker` surfaces CWE-502 targets (confirmable today) ahead of CWE-918/22 targets (suppressed until their detectors land), demonstrated on the real corpus.
4. The full NGv2 serial test gate stays green and nothing is auto-submitted.
