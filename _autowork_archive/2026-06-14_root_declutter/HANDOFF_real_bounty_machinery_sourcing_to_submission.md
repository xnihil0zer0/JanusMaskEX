# HANDOFF — Build the REAL NobleGreed machinery: scrape bounties → clone targets → scan → synthesize PoC → live-test → submit

You are the **overseer**. The previous session proved the **back-half spine** end-to-end against five *synthetic* vulnerable fixtures (`_e2e_run/targets/<pattern>/svc.py`, run via `_e2e_run/run_parallel.py` → `FIVE_POC_RUN: 5/5 confirmed`). That demonstrated the *machinery wiring* (scan → triage → PoC → real bwrap-jail detonation under the strong fs-effect oracle → confirmed → submission package), but it used **hand-written PoCs against fake code**. This handoff builds the **real product**:

> **Scrape bounty platforms (huntr) in parallel → rank and select VALUABLE targets → clone those real target repos → scan them → AUTOMATICALLY synthesize a PoC → live-test it in the jail → render a submission package → (human-gated) submit, and ingest the platform verdict as feedback.**

Two repos in play: **JanusMaskJR** (`/home/xnihil0zer0/JanusMaskJR`) — the factory that builds NGv2 through the pipeline — and **NobleGreedv2 (NGv2)** (`/home/xnihil0zer0/NobleGreedv2`) — the runtime being built. The legacy predecessor at **`/mnt/ai-data/NobleGreed-legacy`** is a design quarry: it shipped 50+ real huntr packages but most of its stack was prompt-driven, orphaned, or manual. **Every design decision incorporated from legacy must be UPGRADED, not copied** — the specific upgrades are itemized per phase below.

---

## Build discipline (unchanged — this is how NGv2 is built)

* Every NGv2 **production** change (`ngv2/**`) routes through the JanusMaskJR pipeline as `data_model` / `config_schema` (bypass-fuzzer external types) — **RED oracle committed to NGv2 master FIRST**, then `brief_hooks_<slug>.md` at JM root → allowlist the slug → the running daemon plans/stages/dispatches → verify the landing. Rule: `[[never-hand-edit-production-outside-pipeline]]`.
* **e2e scaffolding** under `_e2e_run/` and **test fixtures/oracles** under `tests/` are **hand-authorable** (the existing drivers and the 5-PoC harness were hand-authored).
* ★ **The prove-satisfiable recipe** (reuse it for every oracle): a prep subagent builds a throwaway reference implementation in `/tmp`, proves the RED oracle goes green against it (inject via `sys.modules`/monkeypatch or run live), deletes the scratch, then embeds the *exact validated artifact* verbatim in the brief so the blind jailed worker cannot mis-implement. Memory: `[[concurrency-isolation-and-ngv2-solver-ast-epic]]`.
* ★ **ANTI-SEESAW (learned again 2026-06-12):** a same-symbol fix's `verification_command` MUST run the **union** of every committed oracle touching that symbol (`grep -rl <symbol> tests/` before authoring). Last session a reorder of `SessionApi._classify` passed its new oracle but silently regressed a sibling oracle; the worker accepted it because its verification ran only the new file. Memory: `[[ngv2-autonomous-bounty-fsm-epic]]`, `[[verify-harden-5poc-e2e-session]]`.
* Daemon restart (only if a JM harness change must load live): `kill -TERM "$(cat state/control/autowork.pid)"` + supervisor respawn + single-survivor check. NEVER `nohup` a second daemon. Memory `[[daemon-supervisor-respawn]]`. NGv2 changes need **no** JM restart. NGv2 must be **git-clean** at each dispatch (`EXTERNAL_DIRTY_GATE`) — commit oracles first, set aside any unbuilt scratch oracle.
* Daemon promote cadence observed: ~200s from allowlist-append to `plan_kickoff`, then ~50–80s to build+land a small leaf. NGv2 same-external-root tasks serialize under T1 isolation — let the daemon sequence them; do not hand-drive parallel external workers.
* Gating runs are SERIAL (no xdist). NGv2 gate = `cd /home/xnihil0zer0/NobleGreedv2 && .venv/bin/python -m pytest tests -q` (post the C-1 testpaths pin, bare `pytest` also works; current baseline **1254 passed**). JM gate = `python3 -m pytest -q` (7744 pass / 8 skip / 5 xfail).

---

## Orientation — verified current state (2026-06-12)

* **JM** HEAD has the 5-PoC harness work; daemon RUNNING under `scripts/run-autowork.sh` (pidfile `state/control/autowork.pid`). **NGv2** HEAD `6574e68`, tree clean, 1254 tests green.
* **NGv2 venv**: `/home/xnihil0zer0/NobleGreedv2/.venv` (z3-solver 4.16, tree-sitter 0.25 + c/java/javascript grammars, pytest).
* **The 5-PoC harness is the executable spec for the back-half wiring.** `_e2e_run/drive_one.py` drives source→done through the REAL gates; the real front-end's job is to **replace its two hardcoded inputs** — the local `--target` dir and the literal `oracle_result` stub (`drive_one.py:254-258`) — with live producers (a cloner and a scraper-fed qualifier).

### What is REAL vs STUB vs MISSING (from a 4-agent audit)

**NGv2 front half (sourcing/acquisition) — a pure decision library with ZERO live data ingestion:**
| Capability | Status | Anchor |
|---|---|---|
| Lifecycle FSM incl. `source` phase | REAL (pure) | `ngv2/state_machine.py:69` `LIFECYCLE_PHASES` |
| `source→hunt` gate + `qualify()` | REAL (pure) | `ngv2/session_gate.py` `_gate_source_to_hunt`; `ngv2/source_qualify_gate.py:11` `qualify` |
| Bounty economics gate + tier data | REAL (pure) | `ngv2/bounty_gate.py:86` `gate`; `data/huntr_repo_bounties.json` |
| Batch ranker (sort by decision, payout desc) | REAL (pure) | `ngv2/batch_qualify.py` `sort_results` |
| huntr parsers + eligibility cache seam | REAL (pure) | `ngv2/huntr_data.py`, `ngv2/huntr_eligible_cache.py:33` `check_eligible(load_cache=…)` |
| **Live scraper (huntr/H1/Bugcrowd)** | **MISSING** | — |
| **`load_cache()` real impl** (read the `data/huntr_*.json` already on disk) | **MISSING** | static snapshots are orphaned; nothing opens them |
| **`oracle_result` materializer** (compute payout/saturation/freshness/fp_risk per repo) | **MISSING** | `drive_one.py` hand-fakes all four |
| **Target repo cloner/downloader** | **MISSING** | `repo_root` is always a hardcoded local path |
| **Candidate enumeration + ranked work queue driver** | **MISSING** | ranker exists, feeder doesn't |
| **Autonomous production entrypoint / loop** | **MISSING** | no CLI/daemon iterates bounties → `create_session` → `advance()` |
| `Bounty` / `Target` data contracts | **MISSING** | only `Finding`/`PoC`/`LiveTestReport` typed (`ngv2/contracts.py`); bounties/targets are loose dicts |

**NGv2 back half (scan/PoC/detonate/submit) — real spine, hollow intelligence ends:**
| Capability | Status | Anchor |
|---|---|---|
| Regex pattern scan (5 CWEs) | REAL, but ONLY scanner on the live path | `ngv2/pattern_scanner.py:33` |
| z3 solver adapter, tree-sitter verifier | **ORPHANED** (only their own `*_wired` tests import them) | `ngv2/z3_solver_adapter.py`, `ngv2/treesitter_verifier.py`, `ngv2/ast_verifier.py` |
| **Automated PoC synthesis** | **DESIGNED-ONLY → effectively MISSING** | `JanusMaskJR/NGV2_POC_WRITER_DESIGN.md`; `ngv2/poc_writer.py` does **not exist**; **zero** LLM client anywhere in `ngv2/` |
| PoC code in practice | DEMO hand-written, hard-bound to `from svc import …` | `_e2e_run/drive_one.py:45-103` |
| Live detonation jail (production-grade for arbitrary repos) | **REAL** | `ngv2/poc_runner_live.py:258` `detonate_live` (bwrap `--unshare-net/ipc/pid`, ro-bind target, tmpfs, fs-snapshot diff, fail-closed) |
| Strong semantic oracle (marker + fs signature) | REAL; **weak marker-only path is the default when `expected_fs_signature=None`** | `ngv2/detonation.py:3` `semantic_verdict`, `:36` weak default |
| Confidence / novelty gates | REAL but starved (no live signal producer; novelty corpus passed `[]` → everything NOVEL) | `ngv2/grounding_confidence_gate.py`, `ngv2/novelty_gate.py` |
| Submission package (9-section md) + readiness + human checkpoint | REAL, **LOCAL LEDGER ONLY** (halts at human approval; no platform POST) | `ngv2/submission_package.py:194`, `ngv2/submission_readiness_gate.py`, `ngv2/human_checkpoint_gate.py` |
| **Real platform submission + feedback ingestion** | **MISSING** | nothing posts to huntr; no verdict poll |

**Legacy reality (don't inherit blindly):** legacy had **no automated scraper** (discovery was an LLM doing `WebSearch`/`WebFetch` by prompt) and **no programmatic PoC generator** (LLM workers + per-CWE markdown templates, *no* generate→run→repair loop); static analysis (Joern/CodeQL/GraphMERT) was **orphaned dead code**; PoCs ran **on the host as uid 1000** (no sandbox); submission was ultimately **copy-paste manual**; the feedback loop **never ingested a single real verdict**; cron self-chaining caused a **spawn-storm self-DoS**. What *worked* and should be ported: the per-repo **tiered pricing** (`data/huntr_repo_bounties.json`), the **5-gate qualification** (`services/qualify_target.py`), the **target priority scorer weights** (saturation-dominant), the **submission artifact format** (`{ID}_submission.md` + `{ID}_poc.js`), **permalink SHA-pinning** (`prepare_submissions.sh`), the **`_not_eligible/` quarantine**, and the **flock rate limiter**.

---

## Target architecture (the real pipeline)

```
  [huntr poller] --new bounties--> [bounty DB] --enumerate--> [qualify+rank] --work queue-->
     │ (deterministic scrape, dedup, cache)         (5-gate hard filter + saturation-dominant soft rank)
     ▼
  per selected target:  [cloner] --repo_root--> create_session(source) --advance-->
     hunt:   [scan: regex prefilter + tree-sitter/z3 semantic + confidence signals] -> findings
     poc:    [PoC WRITER: per-CWE template + codebase-memory pre-grounding + LLM draft
              -> detonate in bwrap -> observe fs/exit -> REPAIR from stderr -> repeat] (dual Py/JS)
     detonate: [detonate_live STRONG oracle: marker + expected_fs_signature in fs diff]  (HARD gate)
     novelty:  [classify_novelty vs a REAL corpus of prior submissions]
     report:   [9-section submission package + {ID}_poc.js + SHA-pinned permalinks]
     awaiting_submission: ── FAIL-CLOSED human checkpoint ── (operator approves; NEVER auto-submit)
     submitted->done: [render/queue package; optional Playwright filler under human gate]
                                  │
  [feedback ingester] <--huntr verdict (accept/reject/dup/payout)-- reprioritize + grow FP patterns + novelty corpus
```

Parallelism is at the **sourcing/hunt** fan-out (the real "4 in parallel"), governed by an explicit concurrency-ceiling scheduler — **not** the legacy cron self-chaining. The 4-way `ProcessPoolExecutor` demo (`run_parallel.py`) is the *shape*; the real version fans qualified targets, not fixtures.

---

## Implementation plan — phased, oracle-first

> Sequence the phases; within a phase, land leaves through the pipeline (NGv2 clean between dispatches) or hand-author scaffolding/oracles. **Safety guards apply throughout** (see the dedicated section). Build the *deterministic* pieces first; the LLM-bearing PoC writer (Phase 4) is the hardest and highest-value.

### Phase 0 — Data model + wire the static caches (foundations)
* **P0.1 `Bounty` and `Target` contracts** *(data_model leaf)* — add to `ngv2/contracts.py`: `Bounty{platform, repo_url, package, cwe, advisory_id, tier, observed_payout, max_paid, submissions, eligible, fp_risk, discovered_at}` and `Target{repo_url, repo_root, pinned_commit, language, loc, cloned_at}`. RED oracle pins the field set + `validate()`. (Use the R-ANCHOR additive pattern to add new dataclasses next to an existing one — `__JANUSMASK_PATCHES__` symbol patch anchored on an existing top-level symbol; memory `[[rev16-exec-session]]`.)
* **P0.2 `load_cache()` real implementation** *(config_schema/data_model leaf)* — a stdlib loader that reads the already-present `data/huntr_eligible_cache.json` / `huntr_repo_bounties.json` / `huntr_existing_submissions.json` and feeds `huntr_eligible_cache.check_eligible` and `huntr_data.parse_bounties`. This alone gives **cached** sourcing immediately, decoupled from any live scraper. RED oracle: `check_eligible` with the real loader returns the known-eligible set from the on-disk JSON.

### Phase 1 — Real bounty sourcing (UPGRADE legacy's prompt-scraping → deterministic poller)
* **P1.1 `ngv2/sourcing/huntr_client.py`** *(io_adapter — this touches the network, so it is a smoke-gated meta-type; keep the network call behind an injected fetcher seam so the oracle is hermetic)*. Deterministic fetch of huntr's `/bounties` (and per-repo `/repos/{owner}/{repo}` for saturation), resilient parse (NOT brittle HTML regex — legacy fought the markup; prefer any JSON/GraphQL endpoint, else a tolerant parser), produce the `{repos:{…}, formats:{…}}` shape `bounty_gate`/`parse_bounties` already consume. ETag/retry/exponential-backoff; flock per-host rate limit (PORT `services/rate_limiter.py` concept). **Oracle**: inject a canned HTTP response fixture → assert the parsed `Bounty` set; assert backoff/ratelimit invoked. **Keep legacy's load-bearing insight**: "/bounties is authoritative for *paid* eligibility."
* **P1.2 `oracle_result` materializer** *(data_model leaf)* — per candidate repo, compute `{expected_payout (via bounty_gate), open_submissions (saturation), days_since_audit (real clock + audit-history store), fp_risk (data/fp_patterns.json by CWE)}` — replacing the `drive_one.py:254-258` stub. RED oracle: given a repo + injected bounty/saturation data, returns the exact dict `qualify()` consumes and `qualify()` → GO/SKIP correctly.
* **P1.3 Selection ranker + work queue** *(planner_tooling/data_model leaf)* — merge the hard gate (`qualify_target` 5-check: bounty→saturation>50→freshness<7d→fp-warn) with the soft `target_priority_scorer` weights (PORT, saturation-dominant: 0-subs +25, ≤3 +20…; bounty $ deliberately minor). Emit a DB-backed ranked queue of `(repo, score, oracle_result)`. **Model dedup/consolidation** (legacy lesson: N same-CWE findings ≠ N payouts — "pickle fatigue"). RED oracle: a fixture set ranks in the expected order, saturated/ineligible repos drop.

### Phase 2 — Target acquisition (UPGRADE hand `git clone` → a real module)
* **P2.1 `ngv2/acquisition/cloner.py`** *(io_adapter; keep `subprocess`/clone behind a seam for hermetic oracles)* — `git clone --depth 1` to an in-tree `tmp/` (NOT `/tmp` — legacy bash-guard lesson), **record the pinned commit SHA**, enforce a **size cap** and **language detection**, refuse archived repos, support a **clone cache/reuse**. Returns a `Target` (P0.1) with `repo_root`. **Oracle**: against a tiny local bare-repo fixture, clone → assert `repo_root` populated, SHA recorded, size cap enforced, language detected. Note: `JanusMaskJR/harness/target_bootstrap.py:bootstrap_target` is *adjacent* (provisions a work-branch/venv over a dir that already exists) — compose it *behind* the cloner if useful, but it does NOT clone from a URL.

### Phase 3 — Scan upgrade (WIRE the orphaned semantic analyzers; legacy "implementation ≠ wired" lesson)
* **P3.1 Wire `tree-sitter`/`z3`/`ast_verifier` into the hunt path** *(validation/orchestration leaves)* — make `session_gate`/the hunt handler actually call the semantic verifiers so `compute_confidence` receives live `taint_flow`/`formal_path` **signals** instead of regex-only findings. Each wiring is its own leaf with a `*_wired` oracle that asserts the analyzer is reachable on the live hunt path (not just unit-green). DISCARD legacy's Joern/CodeQL-as-built (dead weight); re-introduce a taint engine only if wired+tested.
* **P3.2 Confidence-signal producers** *(orchestration leaf)* — emit the structural proof signals `grounding_confidence_gate.compute_confidence` expects, from the real scan + (later) the live PoC. Until Phase 4, the regex finding + a live-detonation result are the signals.
* *(Optional, concept-only)* GraphMERT's best idea — fuse deterministic facts `[TAINT][SCAN][CWE]` into LLM judgment and **defer on an uncertainty band** — maps onto the prove-oracle-then-embed recipe. Do NOT port the training rig.

### Phase 4 — Automated PoC synthesis (THE HEADLINE GAP — PORT-AND-UPGRADE legacy's writer)
Legacy had per-CWE prompt templates + mandatory codebase-memory pre-grounding + dual Py/JS output, but **NO generate→run→repair loop** — which is exactly why some "confirmed" findings were hallucinated. NGv2 has **no LLM client at all** yet. Build, per `JanusMaskJR/NGV2_POC_WRITER_DESIGN.md`, upgraded with the closed loop:
* **P4.1 LLM client seam** *(io_adapter; injected client so oracles stay hermetic)* — the NGv2 runtime needs a real model client (none exists). Default to the latest Claude model for synthesis. Keep every call behind an injected seam.
* **P4.2 `ngv2/poc_writer.py`** *(the core)* — inputs: a `Finding` (P0.1) + the cloned `Target` + a per-CWE template (PORT the library: CWE-502 `__reduce__`, CWE-95 `__import__('os').system`, CWE-918 metadata-IP + canary listener, CWE-78 `; id #`, CWE-89). **Mandatory pre-grounding** (PORT): before writing, resolve the real vulnerable symbol/entrypoint from the finding (codebase-memory `index_repository`→`trace_call_path`→`search_code`, or tree-sitter) so the PoC binds to the *actual* target API, not a guessed `from svc import …`. **Dual output**: a Python PoC for the internal jail test AND a standalone **Node.js `.js`** for huntr (legacy needed 87 Python→JS rewrites — JS is mandatory for huntr).
* **P4.3 The repair loop (the upgrade)** *(orchestration leaf + e2e)* — `generate → detonate_live in bwrap → observe (fs diff / marker / exit_code) → if not confirmed, feed the runner's stderr+fs-diff back to the writer → repair → repeat` up to a budget. The detonation **Stop-hook** that ends the loop on a strong-oracle `confirmed`. Harmless payloads only (`id`/`whoami`/`: > $WORK/pwned`). **Oracle**: against the 5 committed synthetic targets (`_e2e_run/targets/<pattern>/`), the writer produces a PoC that detonates `confirmed` *without a hand-written exploit* — i.e. replace `drive_one.py`'s hand-coded `_poc_*` functions with `poc_writer` output and still get 5/5. That is the acceptance bar: **the writer reproduces the hand-authored PoCs from the finding alone.**

### Phase 5 — Detonation hardening (the C-3 item the prior session deferred to the owner)
* **P5.1 Make the strong oracle the default / forbid weak `confirmed`** *(data_model leaf)*. Current `DetonationChamber.detonate` returns `confirmed` on **marker-only** when `expected_fs_signature is None` (`ngv2/detonation.py:36`). ★ANTI-SEESAW HAZARD: the strict change breaks **6 committed tests** incl. the production-seam `tests/test_pipeline.py`, and forces NGv2's confirmation path to `inconclusive` unless `expected_fs_signature` is also wired through `ngv2/pipeline.py:36`. The RED oracle for the strict variant is parked at `JanusMaskJR/_c3_pending/test_detonation_requires_semantic_oracle_wired.py`. **Owner decision required** — two clean options: **(a)** strict default + update the 6-oracle union + wire `expected_fs_signature` through `pipeline.py`; **(b)** additive `weak_gate: True` provenance flag on the report + `submission_readiness_gate` rejects `weak_gate`. Pick one with the owner; the FSM `drive_*` path already uses the strong oracle (so this hardens the *legacy* `pipeline.py` path and any future caller). This directly answers legacy post-mortem #1 ("no submit without verified exit_code 0").

### Phase 6 — Submission (PORT the artifact format; UPGRADE to a hard human-gated flow)
* **P6.1 Submission artifact format** *(data_model/docs leaf)* — PORT AS-IS the proven shape: `{ID}_submission.md` (the 10 huntr form fields: Repo URL, Package Manager, Version Affected, Vulnerability Type/CWE, CVSS vector+score, Title, Description w/ inline PoC, Impact, Occurrences as SHA-pinned permalinks, References) + `{ID}_poc.js`. Map `submission_package.build_submission_package` onto this exact field layout. **Oracle**: rendered package contains all 10 fields + a JS PoC reference.
* **P6.2 Permalink SHA-pinning** *(io_adapter leaf)* — PORT `prepare_submissions.sh` logic: `gh` API to pin `/blob/main/` → `/blob/{sha}/`, verify each permalink returns 200, drop if the cited code changed. Oracle hermetic via injected fetcher.
* **P6.3 `_not_eligible/` quarantine + dedup** *(validation leaf)* — quarantine ineligible/duplicate findings (legacy caught 124 → real $ saved). 
* **P6.4 Human-gated submission** — the FSM already parks fail-closed at `awaiting_submission` (`human_checkpoint_gate`). **NEVER auto-submit to a real platform.** A Playwright filler (UPGRADE legacy's `huntr_submitter.py`, which was built but operated copy-paste manual) may *prepare* the form, but the operator confirms each submission. Rate-space submissions to the same repo (legacy lesson: no back-to-back dups).

### Phase 7 — Feedback loop (BUILD the capability legacy faked — it never ingested one real verdict)
* **P7.1 Verdict ingester** *(io_adapter leaf)* — per submission, scrape/poll the huntr verdict (triage/accepted/rejected/dup/payout) into a status DB. **Oracle** hermetic via injected response.
* **P7.2 Feedback application** *(data_model/orchestration leaves)* — verdicts (a) suppress FP patterns (grow `data/fp_patterns.json`), (b) reweight the Phase-1 prioritizer, (c) seed the **novelty corpus** (`classify_novelty` is currently fed `[]` → everything NOVEL; load prior accepted submissions). This is the only honest reward signal legacy's RLCF never had — keep it deterministic; don't resurrect the abandoned ML rigs.

### Phase 8 — Autonomous orchestration (DISCARD cron self-chaining; build a real scheduler)
* **P8.1 Production entrypoint / hunt loop** *(orchestration leaf + e2e scaffolding)* — a CLI/daemon that: pull the ranked work queue (Phase 1) → clone (Phase 2) → `SessionApi.create_session(source)` → `advance()` through the lifecycle → park at `awaiting_submission`. NGv2 has the FSM + session persistence; it lacks the loop.
* **P8.2 Concurrency-ceiling scheduler** — PORT the *caps* (hunt ≤6, PoC/verify ≤4, submit ≤2 for huntr rate limits), worktree isolation, flock/token-bucket rate limiting, a **hard spawn ceiling** (kills the legacy spawn-storm DoS class), and supervisor-based recovery (structurally exempt from bulk task ops — legacy accidentally deleted its own watchdog crons). DISCARD bash-CLI-coupled `spawn_worker.sh` + cron self-chaining + the monolithic 78%-failure Overseer. Concept-port the SQLite-WAL worker registry + atomic `BEGIN IMMEDIATE` registration (legacy's CWE-367 TOCTOU fix) + the 5-gate spawn preflight (cascade/memory/capacity/dedup/cooldown).

### Phase 9 — Live end-to-end test (the real demonstration)
* Pick **one real, currently-eligible huntr repo** (low-saturation, fresh, from the live/cached eligible set). Run the full machinery: poll → qualify → clone → scan → **auto-synthesize** a PoC → detonate `confirmed` under the strong oracle → render the `{ID}_submission.md` + `{ID}_poc.js` with SHA-pinned permalinks → **park at the human checkpoint and STOP**. Success = a confirmed, real-fs-effect PoC against *real cloned code the system had never seen*, with a submission-ready package — **no automatic platform submission.**
* Then scale to the **4-way parallel** real run (the legitimate "4 bounties in parallel"): the Phase-8 scheduler fans 4 qualified targets concurrently, each isolated (own SessionDB, own clone dir, own jail tmpfs), bounded by the concurrency ceiling. Report `n/N confirmed` and the package paths.

---

## Safety guards (apply throughout — these are hard constraints)
* **Never auto-submit to a real bounty platform.** Submission is human-gated at `awaiting_submission`; the operator confirms each. The Playwright path may pre-fill but must not click submit without explicit approval.
* **Every PoC detonates ONLY in the bwrap jail** (`detonate_live`, `--unshare-net/ipc/pid`, ro-bind target, tmpfs workspace, wall-clock timeout). DISCARD legacy's host execution. Harmless payloads only.
* **Scrapers are rate-limited and polite** (flock per-host cooldown, ETag, exponential backoff on 429); respect platform ToS. Keep the network behind injected seams so all oracles are hermetic.
* **Verify data at the source** before committing hunt resources (legacy's costliest failures were corrupt cached saturation/eligibility data). Don't trust stale `data/huntr_*.json` for a go/no-go.
* **A hard spawn ceiling** on the scheduler (legacy's spawn-storm self-DoS). 
* **Confirmation requires real fs effect** (strong oracle), never a marker print (Phase 5).

---

## Suggested sequence
1. **Phase 0** (data model + wire static caches) — unblocks cached sourcing with no network.
2. **Phase 1 + Phase 2** (real scraper + cloner) — gets real targets onto disk.
3. **Phase 3** (wire semantic scan) — richer findings.
4. **Phase 4** (PoC writer + repair loop) — the headline; acceptance = reproduce the 5 hand-authored PoCs from the finding alone.
5. **Phase 5** (detonation hard gate) — owner decides (a) vs (b) first.
6. **Phase 6 + 7** (submission format + feedback) — close the loop.
7. **Phase 8** (scheduler/entrypoint) — autonomy.
8. **Phase 9** (live e2e, then 4-way) — the real demonstration, human-gated.

---

## Appendix — verified file anchors

**NGv2 spine (build on):** `ngv2/state_machine.py:69`, `ngv2/session_gate.py` (`gate_transition`, handler table ~`:433`), `ngv2/session_api.py` (`advance`, `transition`), `ngv2/session_db.py`, `ngv2/poc_runner_live.py:258` `detonate_live`, `ngv2/detonation.py:3` `semantic_verdict` / `:36` weak default, `ngv2/submission_package.py:194`, `ngv2/submission_readiness_gate.py`, `ngv2/human_checkpoint_gate.py`, `ngv2/contracts.py` (Finding/PoC/LiveTestReport).
**NGv2 pure decision logic (feed it real data):** `ngv2/source_qualify_gate.py:11` `qualify`, `ngv2/bounty_gate.py:86` `gate`, `ngv2/batch_qualify.py` `sort_results`, `ngv2/huntr_data.py`, `ngv2/huntr_eligible_cache.py:33`, `ngv2/target_qualify.py`, `ngv2/portfolio_scanner.py`. Static data already on disk: `ngv2/data/huntr_repo_bounties.json` (tiers/pricing), `huntr_eligible_*.json`, `huntr_existing_submissions.json`, `fp_patterns.json`.
**NGv2 orphaned (wire in Phase 3):** `ngv2/z3_solver_adapter.py`, `ngv2/z3_bridge.py`, `ngv2/treesitter_verifier.py`, `ngv2/ast_verifier.py`, `ngv2/codeql_runner.py`, `ngv2/joern_runner.py`, `ngv2/semgrep_adapter.py`.
**NGv2 demo/spec:** `_e2e_run/drive_one.py` (hardcoded inputs at `:53`, `:254-258`; hand PoCs `:45-103`), `_e2e_run/run_parallel.py` (4-way ProcessPool shape), `_e2e_run/targets/<pattern>/svc.py` (5 synthetic targets — the Phase-4 acceptance fixtures). Design doc: `JanusMaskJR/NGV2_POC_WRITER_DESIGN.md`. Deferred strict-detonation oracle: `JanusMaskJR/_c3_pending/test_detonation_requires_semantic_oracle_wired.py`.
**Legacy quarry — PORT/UPGRADE sources:** `services/bounty_gate.py:63` (tier pricing — PORT), `services/qualify_target.py:270` (5-gate — PORT+promote-to-day-1), `services/tools/target_priority_scorer.py:157` (weights — UPGRADE+wire), `services/tools/batch_qualify.py:99` (ThreadPool(4) — the real parallel primitive), `services/huntr_eligibility.py:46` + `services/tools/check_huntr_existing.py:33` (eligibility/saturation scrapers — PORT-harden), `services/rate_limiter.py:38` (flock — PORT), `orchestrator/prompts/poc_phase.md` (per-CWE templates + pre-grounding — PORT-and-add-repair-loop), `huntr-submission-packages/*/` (real `{ID}_submission.md`+`{ID}_poc.js` format — PORT), `huntr-submission-packages/prepare_submissions.sh` (SHA-pin — PORT), `services/tools/huntr_submitter.py` (Playwright — UPGRADE), `orchestrator/worker_registry.py` + `services/tui_dispatch.py` (SQLite-WAL registry, atomic register, CWE-367 fix — concept-PORT), `services/spawn_preflight.py` (5-gate — concept-PORT). **DISCARD:** Joern/CodeQL/GraphMERT as-built, `knowledge/graphmert/*` training rig, cron self-chaining, `spawn_worker.sh` CLI coupling, `services/overseer.py` monolith, `catboost_info/` (phantom ranker — was tool-selection/PoC-target, never ranked targets). **Post-mortems to read:** `noblegreed-post-mortem*.md`, `misconceptions-report.md`, `comprehensive-bug-review.md`, `META_PLAN_v2.md`.

**Reference memories:** `[[verify-harden-5poc-e2e-session]]`, `[[ngv2-e2e-huntr-poc-driven]]`, `[[ngv2-autonomous-bounty-fsm-epic]]`, `[[concurrency-isolation-and-ngv2-solver-ast-epic]]`, `[[implementation-is-not-wired-defect]]`, `[[ngv2-cleanroom-rebuild-plan]]`.
