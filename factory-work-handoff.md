# Factory-Work Handoff — 2026-06-18

> **✅ EXECUTED 2026-06-19.** This handoff was adversarially re-verified (6 evidence-backed doc fixes
> applied to README + this file) and then executed. **§3a archival DONE** (106 hooks + 20 planning
> dumps + 4 scratch docs → `_autowork_archive/2026-06-19_stray_hooks_and_scratch/`; quarantine + live
> artifacts preserved). **§3b gap brief DONE+WORKS** — the deterministic `clutter_candidates` extension
> landed via the pipeline (commits 3b962a0 oracle + eda2fdc impl); `cleanup_state` now surfaces real
> clutter with `ready:False` instead of the false `ready:True`. While running it, a reconciler footgun
> surfaced (the PLANNED_STALE sweep EVICTED a brief edited mid-flight); owner approved a pipeline fix —
> the **reclaim-allowlist-skip hardening** landed (c9ba58a + 023a468: an allowlisted stale-plan brief
> now re-plans instead of being evicted) and `state_reconcile` was re-enabled. See
> memory `doc-verify-and-reconciler-hardening-2026-06-19.md`. The §3/§4 text below is the pre-execution
> plan, kept for provenance.


> **Purpose.** Resume an in-progress metadata/state-cleanup + pipeline-gap-fill effort. This file
> will be adversarially checked next session. Every factual claim below is written to be
> **independently re-verifiable** with the exact command given. Where something is *not yet done*
> or *uncertain*, it says so explicitly. Do not treat any "DONE" item as true without running its
> verify command — the working tree is uncommitted and could drift.

## 0. Snapshot (verify first)

```bash
cd /home/xnihil0zer0/JanusMaskJR
git rev-parse --short HEAD          # expected: 4897a3c (master)
git branch --show-current           # expected: master
git status --porcelain | wc -l      # expected: 82 uncommitted (this session's moves+edits, UNCOMMITTED)
cat state/control/autowork.pid       # expected: 1665755 (a live, idle daemon)
ps -p "$(cat state/control/autowork.pid)" -o pid=,cmd=   # daemon process must be alive
grep -vcE '^\s*(#|$)' state/control/autowork/auto_promote.allowlist   # expected: 0 (DENY-ALL)
test -e state/control/autowork/pause && echo PAUSED || echo running    # expected: running
test -e state/control/autowork/full_stop && echo STOP || echo go        # expected: go
test -e state/control/autowork/git_commit.lock && echo LOCK || echo nolock  # expected: nolock (cleared this session)
```

**Nothing is committed.** All of this session's changes (memory archive, root-doc archive, MEMORY.md
rewrite, lock clear) are uncommitted working-tree changes. The owner has NOT asked to commit. Do not
commit without asking.

## 1. The mission and the core finding

The session goal: audit "metadata" in this repo for **staleness vs README.md** and **redundancy**,
**test the stale-state-cleanup system** by using it, and **if the pipeline can't self-clean this,
submit a brief to fill the gap** through the pipeline.

**CORE VERIFIED FINDING — the pipeline gap (this is the real deliverable, NOT yet built):**
`harness/state_reconciler.py::cleanup_state(root, mode='report'|'apply')` is **structurally blind**
to the metadata this audit flagged. It classifies only `brief_hooks_*.md` (repo-root glob) +
`state/plans/*`, then reaps runtime disk (orphaned workdirs, logs, ledger). It has **no concept** of
root-level planning docs (`PLAN_*`, `INTERVENTION_*`, `PROVENANCE_*`, …), `_autowork_scratch/`
leftovers, or `state/planning/*.json` dumps. Re-verify:

```bash
cd /home/xnihil0zer0/JanusMaskJR
PYTHONPATH=. python -c "from harness.state_reconciler import cleanup_state; s=cleanup_state('.',mode='report'); print('products:',len(s.products),'ready:',s.ready)"
# OUTPUT TODAY: products: 0  ready: True   <-- reports the workspace CLEAN while clutter exists
sed -n '325,376p' harness/state_reconciler.py   # confirm it globs brief_hooks_*.md + state/plans only
```
So `cleanup_state` says `ready: True` while there are stale root docs, 108 stray hook files, 22
`state/planning/*.json` dumps, and spent scratch docs on disk. **That blind spot is the gap a brief
should fill** (scope in §4).

## 2. DONE this session (each with a verify command)

### 2a. Memory pass — COMPLETE (2-round, 8-agent, evidence-backed)
Built an evidence engine and ran two rounds of four sub-agents (Round 2 adversarial, assignments
derived from Round 1's contested findings). Every proposed change was backed by analysis-script test
results, not opinion.

- **Engine:** `_autowork_scratch/memory_audit/audit_memory.py` (per-file: dead-SHA checked vs BOTH
  JanusMaskJR and NobleGreedv2, config-flag claim vs live `harness/config.yaml`, missing paths,
  not-in-index orphans, dangling `[[links]]`). Evidence dump: `_autowork_scratch/memory_audit/evidence.json`.
  Disposition: `_autowork_scratch/memory_audit/round1_disposition.md`.
- **Archived 82 memory files** (move, never delete) → `_autowork_archive/2026-06-18_memory_audit/memory/`.
- **Rewrote** `MEMORY.md`: 126→46 lines, 35248→16355 bytes (now under the ~24.4KB limit).
- **Content fixes:** `brief-staleness-reconciler.md` header flag claim corrected
  (`archive_spent_briefs` is ON/true, header had said OFF); canonical top index entry de-staled
  (NEXT TARGET=db-gpt #54 not "InvokeAI-first"; HEAD→4897a3c; removed dead "campaign_run1 running");
  rescued the spine `20bc82c` `__main__` AST-merge nugget into the daemon-run entry; added 3 orphan
  entries (deterministic-plan-park, turn-recurring-failures, auto-commit-failed-multifile).

Verify:
```bash
MEMDIR="/home/xnihil0zer0/.claude/projects/-home-xnihil0zer0-JanusMaskJR/memory"
wc -lc "$MEMDIR/MEMORY.md"                                  # 46 lines / 16355 bytes
ls "$MEMDIR"/*.md | grep -vc '/MEMORY.md$'                  # 44 topic files remain
ls _autowork_archive/2026-06-18_memory_audit/memory/*.md | wc -l   # 82 archived
```
**Adversarial notes on the memory pass (things the checker should re-test, because R1 agents
disagreed and the raw script over-fired):**
- The raw `flag_mismatch` signal had FALSE POSITIVES on bare `.enabled` (many config keys end in
  `.enabled`) and on prose that *quotes* a flag value. After correction, **only ONE** flag mismatch
  was a real current-state staleness: `brief-staleness-reconciler` (`archive_spent_briefs`). The two
  durable feedback files flagged (`triple-lock-was-claude-invented`,
  `webui-autobrief-streamjson-…`) were CORRECT (the `:true` token was a quotation) and were KEPT
  UNCHANGED — do not "fix" them.
- **All 7 dead-SHA findings are false positives** (session UUIDs, a third-party `gptcache` commit, an
  OOM'd sub-agent task-id, a rolled-back transient, file-history path-hashes). No fabricated build
  SHA was found.
- All 6 superseding chains were verified to hold; archives rest on **incidental/superseded** grounds,
  NOT on flag/SHA staleness.
- **Deferred (honestly incomplete):** the file BODIES of `test-tiering-bootstrap.md` and
  `source-driving-doesnt-fire-on-live-findings.md` still contain some stale detail; only their INDEX
  lines were corrected. Low risk (the index is the loaded surface) but not zero.

### 2b. Root-doc audit — COMPLETE analysis, PARTIAL execution
Four sub-agents audited all 19 root `*.md` docs against README.md. **10 spent docs archived** →
`_autowork_archive/2026-06-18_root_doc_audit/`. **9 KEEP docs + README + this handoff doc (11 total) remain at root.**
```bash
ls *.md   # expect exactly (11): AUTONOMY_GAPS, DESIGN_self_healing_remediation_agent,
          # INTERVENTION_ANALYSIS_02_git_selfheal, INTERVENTION_ANALYSIS_03_archive_forensics,
          # INTERVENTION_PLAN_v2, PLAN_autonomous_resume, PROVENANCE_REVIEW_01_internal_jm,
          # PROVENANCE_REVIEW_02_external_ngv2, PROVENANCE_REVIEW_04_roi_priority, README.md,
          # factory-work-handoff.md (this handoff doc itself)
ls _autowork_archive/2026-06-18_root_doc_audit/   # 10 archived docs
```
KEEP rationale (verify against the docs if challenged): `PLAN_autonomous_resume`=canonical mission;
`INTERVENTION_PLAN_v2`=live backlog; `DESIGN_self_healing`=unbuilt FSM design; `AUTONOMY_GAPS`=holds
unfiled gaps beyond README §12; `INTERVENTION_ANALYSIS_02/03`=unique forensic data; `PROVENANCE_01/02/04`=
design records + a live config-arithmetic finding. ARCHIVED (spent/superseded/stale): the two
INTERVENTION_00 final reports, _01, _04; `PLAN_stale_state_recovery` (work shipped); root
`stale-state-cleanup-design.md` (feature shipped); `epic-contracts-brief-outline-list` (landed);
`EPIC_source_driving_poc_synthesis` (landed); `PROVENANCE_REVIEW_03` (covered by README §2);
`turn-based-stages-efficiency-report` (**STALE+misleading**: its §8 reports "PASSED" tests for fixes
absent from the code — flag this if anyone cites it).

### 2c. Stale lock — CLEARED
`state/control/autowork/git_commit.lock` held dead PID `1653337` while the daemon (1665755) ran idle.
Removed (a copy is in `_autowork_archive/2026-06-18_memory_audit/cleared_lock/`). README §11 confirms
hand-removal of a stale lock is safe.

## 3. PENDING — interrupted, NOT done (resume here)

The owner approved scope via an explicit decision: **archive "Docs + stray hooks"** (NOT the 480MB
external clones), **"Draft + allowlist + run" the gap brief**, clear the lock (done), MEMORY.md was
"flag only" but later upgraded to the full pass above (done). Remaining:

### 3a. Archive the stray hooks + planning dumps + misleading scratch docs (mechanical, approved)
- **108 stray `brief_hooks_*.md` / `plan_hooks_*.json` files** live OUTSIDE `_autowork_archive` (NONE
  at repo root — all in subdirs like `epic4_handauthored_reference/`, `held_briefs_selfheal_build/`,
  `_phase4_rebrief/`, `hierarchical_planner_design/phase1_pipeline_artifacts/`, `_autowork_scratch/…`,
  and 2 under `state/control/autowork/quarantine/`). Re-list before moving:
  ```bash
  find . -path ./_autowork_archive -prune -o \( -name 'brief_hooks_*.md' -o -name 'plan_hooks_*.json' \) -print | grep -v '^./_autowork_archive' | wc -l   # 108
  ```
  NOTE: the daemon promotes **only root-level** `brief_hooks_*.md` that are **allowlisted**; with a
  DENY-ALL allowlist and zero root hooks, these subdir hooks are inert — archiving them is hygiene,
  not safety-critical. **The 2 under `state/control/autowork/quarantine/`** should be inspected first
  (they are quarantine artifacts — may be live control state, not stray briefs) — do NOT blind-move those.
- **22 `state/planning/*.json`** are spent old-planner dumps (e.g. `plan_redpair*`, `plan_ngv2-*`,
  `wire_up*`, `critique*`, plus `ngv2_wireup_epic.json`, `brief.json`, `current_diff.json` — these
  globs are ILLUSTRATIVE, not exhaustive; `ls state/planning/*.json` and enumerate before moving, or
  ~6 spent dumps get left behind). `merged_plan.json` = `{"tasks": []}` (empty/authoritative).
  ARCHIVE the spent dumps; the ONLY LEAVE set is `merged_plan.json`, `amendment_report.json`,
  `planner_progress.jsonl` (live planner artifacts).
- **4 misleading scratch docs present** → archive (confirmed present today):
  `_autowork_scratch/BOUNTY_SUBMISSION_DECISION_2026-06-13.md` (claims claimable PoCs — contradicts
  the canonical "0 confirmed PoCs"), `_autowork_scratch/CHINESE_API_RESEARCH.md` (fabricated future
  model IDs), `_autowork_scratch/FACTORY_ORIENTATION.md` + `_autowork_scratch/BRIEF_AUTHORING_CONTRACT.md`
  (read authoritative but are spent scratch; README is canonical).
- **Suggested archive destination:** `_autowork_archive/2026-06-18_stray_hooks_and_scratch/` (move,
  NEVER delete; preserve relative subpaths so provenance is legible).
- **DO NOT** move the 480MB untracked external clones (`fastgpt/ flowise/ mem0/ w2d_modeldb/
  graphiti/ h4_guildai/ one-api/`) — owner did NOT approve that. At most propose `.gitignore`-ing
  them in a future turn.

### 3b. Draft + allowlist + RUN the gap brief (approved "Draft + allowlist + run")
This re-activates the currently-idle, DENY-ALL daemon. See §4 for the full brief spec. After writing
`brief_hooks_<slug>.md` at repo root and adding `<slug>` to
`state/control/autowork/auto_promote.allowlist`, the live daemon (pid 1665755) will wake on the
allowlist/brief change and plan it. **It does NOT need a restart** for a new brief (workers/planner
are fresh subprocesses); a restart is only needed for changes to the daemon's own cached code.

## 4. The gap-brief spec (DESIGNED, NOT WRITTEN)

**Honest scoping (important — the adversarial checker should pressure-test this):** "stale *relative
to README*" is a **semantic** judgment that needs an LLM; the deterministic reconciler cannot make it.
The factory's discipline is *deterministic tooling*. Therefore the buildable gap fill is a
**deterministic DETECTION/REPORT extension**, not auto-archival-by-semantics:

> Extend `cleanup_state(mode='report')` (or add a sibling `scan_clutter(root)`), in
> `harness/state_reconciler.py`, to ALSO enumerate — as advisory **review candidates**, never
> auto-moved — the non-product clutter it is currently blind to: (1) repo-root `*.md` not in a small
> KEEP allowlist (README.md, the canonical PLAN, etc.) and older than a threshold; (2)
> `state/planning/plan_*.json` / `wire_up_*` / `critique_*` leftovers when `merged_plan.json` is empty
> and the queue is idle; (3) `_autowork_scratch/` entries older than a threshold. Output them in the
> `WorkspaceStatus` (or a parallel structure) with a `clutter_candidates` list, each carrying a
> reason — so `ready` is no longer reported `True` while clutter exists. Auto-archival stays a
> separate, explicit operator/agent decision (the semantic "is it stale vs README" call is NOT
> automated).

**Brief authoring constraints (from README §4 — get these exactly right or the brief is rejected at
load / stalls):**
- Five REQUIRED sections as **bare** `#` headings (or frontmatter keys), each non-empty: `title`,
  `scope`, `non_goals`, `inputs`, `deliverables`. Decorated headings (e.g. `# Inputs (notes)`) do
  NOT match → rejected.
- `working_dir: "/home/xnihil0zer0/JanusMaskJR"` (internal build).
- It writes `harness/state_reconciler.py` ⇒ `meta_task_type: harness_self_fix` (sensitive glob).
  **Good news:** `state_reconciler.py` is NOT in the irreducible `_NEVER_AUTO_APPROVE` set
  (`harness/orchestrator.py:2285` lists agent_jail, dbus_proxy, paths, git_integration, orchestrator,
  interceptors, selfheal, autowork_daemon, services/** — state_reconciler is absent), and
  `auto_approve_sensitive_harness: true`, so the commit can auto-approve hands-off. **No decision
  file needed** (re-verify the deny-list before relying on this).
- Pin the task id: `required_task_ids: [<id>]`, force it in a `# Required plan shape` section.
- `# Non-Goals` MUST contain the literal word `integration` (excuses the integration-test requirement).
- `verification_command` must select ≥1 REAL test and be non-vacuous — author a RED pre-committed
  oracle (e.g. `tests/harness/test_state_reconciler_clutter_scan.py`) and run the EXACT vcmd by hand
  first to confirm `N passed, N≥1` (pytest exit 5 = "collected 0" fails identically to a real failure;
  a trivially-green vcmd lets unverified code land).
- If you add a NEW oracle file alongside the edit, that's 2 files → multi-file manifest rules apply;
  simpler to keep the impl as a `__JANUSMASK_PATCHES__` symbol patch on the existing function and
  pre-commit the oracle by hand (allowed: oracles are hand-authorable).

**Alternative the owner may prefer instead of a brief:** if the deterministic report-only extension
feels too thin to be worth a pipeline build, the honest answer is "the semantic doc-staleness audit
is an agentic task (what we did this session with sub-agents), not a deterministic-reconciler task" —
surface that trade-off and let the owner choose. Do not over-promise a "doc reconciler that knows
what's stale vs README"; that would be BUILT≠WORKS theater.

## 5. Hard constraints / footguns (owner rules — violating these is the failure mode)
- **ARCHIVE, NEVER DELETE.** Every cleanup this session was a `mv` into `_autowork_archive/`. Keep it.
- **Never hand-edit production (`harness/**`, `config/**`, `scripts/**`, `services/**`) outside the
  pipeline.** The gap fix to `state_reconciler.py` MUST go through a brief→planner→worker, not a hand
  edit. (Memory/audit-script files under `_autowork_scratch/` and pre-committed test oracles are
  hand-authorable.)
- **Don't conflate BUILT with WORKS.** A green oracle ≠ the reconciler actually surfacing real
  clutter on the live tree. Prove the report lists the actual current clutter after landing.
- **Daemon control = FILE existence**, not strings: `state/control/autowork/pause`,
  `…/full_stop`. `state/control/orchestrator.flag` does NOT gate the daemon (README §6). One
  supervised daemon only — never `nohup` a second.
- **External roots:** only `/home/xnihil0zer0/NobleGreedv2` is approved
  (`state/control/autowork/external_roots.allow`). This gap brief is internal (no working_dir change).
- The `audit_memory.py` engine and its outputs live under `_autowork_scratch/memory_audit/` (also
  copied into `_autowork_archive/2026-06-18_memory_audit/` for provenance) — reuse it to re-verify
  any memory claim.

## 6. Adversarial-check checklist (what the four sub-agents should independently confirm)
1. `cleanup_state(mode='report')` really returns `products:0 ready:True` AND really globs only
   `brief_hooks_*.md` + `state/plans` (§1). If false, the whole "gap" premise collapses — report it.
2. The 82 archived memory files + 10 archived root docs are present in their archive dirs AND absent
   from their source dirs (no half-moves). `MEMORY.md` is < 24.4KB and every KEEP/feedback rule still
   has an index line (no durable rule silently dropped).
3. No durable `type: feedback`/`user` memory was archived. (Cross-check the archive dir against
   frontmatter `type:`.)
4. `state_reconciler.py` is genuinely absent from `_NEVER_AUTO_APPROVE` (so the gap brief can
   auto-approve) — re-read `harness/orchestrator.py:2285`.
5. The PENDING items in §3 are genuinely still pending (stray hooks not yet moved; no gap brief at
   root; allowlist still DENY-ALL). `ls brief_hooks_*.md 2>/dev/null` at root → none.
6. Nothing was committed (`git log -1` still `4897a3c`).
7. **Challenge the over-claims:** is the gap-brief scope in §4 honest (deterministic report, not
   semantic auto-cleanup)? Is `turn-based-stages-efficiency-report.md` actually fabricated-as-claimed
   (re-grep its §8 "PASSED" counts vs the codebase)?
```
