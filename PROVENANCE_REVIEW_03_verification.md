# Provenance Review 03 — Verification & Regression Detection (Adversarial)

Reviewer posture: adversarial verification + regression detection. All claims confirmed at file:line against the live tree at `/home/xnihil0zer0/JanusMaskJR` (JM) and `/home/xnihil0zer0/NobleGreedv2` (NGv2). Code was NOT modified.

Central claim under test:
> "Verification is auto-scoped so regressions in non-importing test files escape, and the fix is to (a) give the editor provenance about locking oracles and (b) make test_scoper RUN the oracles that lock an edited symbol."

**Bottom line up front:** The *mechanism* claim is **CONFIRMED** — scoping is real and demonstrably leaky. The *fix* claim is **REFUTED as specified**: the prerequisite (a symbol→oracle map) **does not exist** in the ledger and is not reliably constructible. The leak is real but the measured regression rate is plausibly ~0, so the proposed investment is mis-targeted; a cheap nightly full-suite sweep dominates the proposed fix on every axis.

---

## 1. Mechanics Verdict Table

| # | Claim | Verdict | Evidence (file:line) |
|---|-------|---------|----------------------|
| C1 | The orchestrator rewrites an unscoped `pytest` to test only files that import the touched module | **CONFIRM** | `harness/orchestrator.py:2728-2765`. `_is_unscoped_pytest` detects a `pytest` invocation with no positional target (`2728-2757`); when true it calls `get_relevant_test_files(staging_path, files_touched)` and appends the result to the command (`2758-2765`). |
| C2 | It falls back to `tests/test_import.py` when no relevant tests are found | **CONFIRM** | `harness/orchestrator.py:2761-2763`: `if not existing_tests: existing_tests = ['tests/test_import.py']`. Mirrored by `DEFAULT_FALLBACK_TEST = "tests/test_import.py"` and the no-relevant-tests return in `test_scoper.py:166-168`. |
| C3 | `get_relevant_test_files` selects tests by static AST import analysis | **CONFIRM** | `harness/test_scoper.py:91-179`. Per-test imports parsed via `ast` (`_parse_imports` `60-70`, `_imports_from_tree` `30-44`); relevance = candidate dotted-module set ∩ test's import set (`149-160`). |
| C4 | Selection ALSO uses a `test_<stem>.py` naming convention | **CONFIRM (REFINE)** | `test_scoper.py:162-164`: any test whose stem == `test_<stem-of-touched-file>` is added regardless of imports. Also: a touched file that is itself a test is included directly (`142-147`); and a bare-stem "last component" match (`156-160`) widens beyond exact dotted import (e.g. `from x import orchestrator` matches touched `harness/orchestrator.py`). So scope is import-set ∪ bare-stem-tail ∪ name-convention ∪ self. |
| C5 | Scoping MISSES regressions reached via a different module / integration / cross-module parametrized tests | **CONFIRM** | By construction in `test_scoper.py:152-164`: a test that exercises a regression in `harness/X.py` through an *intermediary* (`import harness.Y` where `Y` calls `X`, and the test never imports `X` nor is named `test_X`) is NOT selected. No transitive/reverse-import expansion exists (confirmed C9). Integration tests (`tests/integration/*`) that import a top-level entrypoint but not the edited leaf are systematically skipped. |
| C6 | There IS a full-suite gate available (`make test-full`) | **CONFIRM** | `Makefile:48-55`: `test-full:` → `$(PYTEST)` = `python -m pytest -p no:cacheprovider -q` (bare, no scope). Header (`Makefile:28-30`) calls it "AUTHORITATIVE GATE (serial, ~11 min). ... Use before commit / for '0 new regressions'." |
| C7 | The daemon / auto-commit path USES the full suite | **REFUTE** | No reference to `test-full`, `make test`, full-suite, or a sweep cadence in `scripts/run-autowork.sh`, `harness/autowork_daemon.py`, or the commit path. Grep for `test-full\|full_suite\|sweep` in the daemon returns only unrelated "orphan sweep" pidfile reaping (`autowork_daemon.py:1840,2220`). The per-task gate at `orchestrator.py:2758-2793` is the ONLY automated verification; it is always scoped when the vcmd is unscoped pytest. |
| C8 | A symbol→oracle ("locking oracle") map exists / is knowable for fix-part (a) and (b) | **REFUTE** | The only ledger, `harness/symbol_ledger.py`, maps **symbol name → committed *signature*** (`record_symbols`, `94-140`; `_extract_signatures` `94-108` emits `name -> "name(args) -> ret"`). It records NOTHING about which test/oracle exercises a symbol. No file in `harness/` contains a symbol→oracle or locking-oracle structure (grep `locking.?oracle\|oracle.?map` → 0 hits beyond `mutation_target`, which is the *editor's own* paired test, not a reverse index of all tests that touch a symbol). |
| C9 | No reverse-dependency / coverage-based selection exists today | **CONFIRM** | Grep for `reverse.?dep\|rdep\|dependents\|coverage\|--cov` in `harness/*.py` → 0 selection hits. A FORWARD import graph exists: `harness/rebuild/discover.py:125 module_import_graph(source_root, modules) -> dict[str, set[str]]` (module → its imports) and `harness/wire_up.py` (reachability from live roots). It is invertible to a reverse-dep graph but is NOT currently used for test scoping. |

### Mechanics summary

The claim's *diagnosis* is sound and verifiable: the gate runs a strict subset of the suite, selected by import-string + filename heuristics, and the daemon never runs the authoritative full suite. A regression in `A` caught only by a test that reaches `A` through `B` (and neither imports `A` nor is named `test_A`) will pass the scoped gate and be auto-committed. That is a genuine escape channel.

The claim's *proposed fix* is the weak part. Fix (b) — "make test_scoper RUN the oracles that lock an edited symbol" — presumes a symbol→oracle index. **That index does not exist (C8) and cannot be built accurately from static imports** (the same import-blindness that causes the leak also defeats any attempt to *statically* enumerate "all oracles that lock symbol S"). The only way to know which tests truly exercise a symbol is dynamic per-symbol coverage — which is alternative (iv), a strictly different and more expensive design than what the fix describes. Fix (a) — "provenance about locking oracles" to the editor — is downstream of the same nonexistent map and would at best surface the editor's own paired `mutation_target` test, which already gates.

---

## 2. Ranked Alternatives (cost / benefit)

Suite facts measured this session: **JM = 7,890 tests collected** (`pytest --collect-only`), 710 test files, 342 adversarial tests; `test-full` ≈ **11 min serial** (Makefile header). NGv2 = 2,004 tests. JM env is currently **missing z3 and tree-sitter** (both `import` failed) — relevant to experiment noise (§3).

Ranked best → worst for *this* system (a factory that auto-commits ~1 leaf per iteration):

**Rank 1 — (v) Keep scoped gate + nightly/cadence full-suite sweep that opens self-heal briefs.**
- Cost: ~11 min once per cadence (nightly, or every N commits), off the critical path. Zero added latency on the auto-commit gate. Implementation: one cron/daemon hook running `make test-full`, diffing red set vs a committed baseline, and emitting a self-heal brief per *new* red (the self-heal machinery already exists — `autowork_daemon.py:839-843` corrective-spec path). 
- Benefit: catches 100% of regressions the full suite can catch, with bounded blast radius (≤ one cadence of commits to bisect). Decouples *detection* (must be complete) from *gating* (must be fast). This is the canonical CI pattern and the Makefile already anticipates it ("0 new regressions" framing, `Makefile:28-30`).
- This is the dominant option. It needs no symbol→oracle map.

**Rank 2 — (iii) Reverse-dependency import-graph scope expansion.**
- Cost: cheap — invert the EXISTING `module_import_graph` (`discover.py:125`) to get importers, take the transitive closure of touched modules, and union the importer modules into `files_touched` before calling `get_relevant_test_files`. ~seconds. No new infra.
- Benefit: closes the *intermediary-module* leak (C5's main case) deterministically and statically. Catches "test imports B, B imports edited A" without running everything. 
- Limit: still misses pure-behavioral integration tests that import only a top-level entrypoint and reach the leaf via runtime dispatch/plugins (not a static edge). Partial fix, but high value per line of code. Pairs well with Rank 1 (expansion shrinks the nightly's job).

**Rank 3 — (iv) Coverage-based test selection.**
- Cost: high. Requires a maintained per-test coverage DB (warm full run + invalidation on edits), and the JM suite has known non-hermetic clusters that corrupt shared coverage state. This is effectively what the central claim's fix-(b) *wants* (a true symbol→test map) but honestly priced: the map must be **dynamic**, not static.
- Benefit: precise selection (run exactly the tests that execute the changed lines). Strong in theory. 
- Verdict: over-engineered for a 1-leaf-per-iteration factory; the precision buys little over Rank 1's "just run all of it nightly," at much higher maintenance and flake-surface cost.

**Rank 4 — (ii) Full suite on a commit cadence with bisect-on-red.**
- Essentially Rank 1 keyed on commit count instead of wall-clock, plus auto-bisect. Bisect adds value only if the cadence batches many commits; at ~1 leaf/iter, the red is almost always the last commit, so bisect is mostly redundant. Fold into Rank 1.

**Rank 5 (do NOT) — (i) Full suite on EVERY auto-commit.**
- Cost: **+11 min serial per leaf** on the critical path (or fight the `-n auto` non-hermetic flake cluster the Makefile explicitly warns about, `Makefile:14-26,40-45`). At factory throughput this is a throughput killer and would itself inject false rejects from the known flaky classes. 
- Benefit: completeness, but Rank 1 already delivers completeness off the critical path. Strictly dominated.

**Rank 6 (rejected) — the claim's fix as written ("run oracles that lock the symbol").**
- Requires C8's nonexistent map; the only honest implementation collapses into Rank 3 (dynamic coverage) at Rank 3's cost. As a *static* shortcut it provides no coverage beyond what `mutation_target` + Rank 2 already give. Lowest benefit-per-cost of the buildable options.

---

## 3. Experiment to Measure the Real JM Regression Rate

Goal: estimate the population proportion P(full-suite RED | scoped gate was GREEN) across recently auto-committed leaves. NGv2's analogous pop-2 was 34 fail / 1970 pass with **all 34 = missing-toolchain (z3/tree-sitter/pins), i.e. 0 real regressions**. We must run the JM half and, critically, separate toolchain noise from true regressions.

### Step 0 — neutralize known noise first
The JM env is missing z3 and tree-sitter (confirmed this session) and has non-hermetic clusters. Pre-register the exclusions:
```bash
cd /home/xnihil0zer0/JanusMaskJR
# (a) establish toolchain so missing-dep reds don't masquerade as regressions
pip install z3-solver tree_sitter   # match requirements pins NGv2 uses
# (b) record the known non-hermetic deselects already curated in the Makefile
#     (PARALLEL_UNSAFE) plus the live-config-rewriting webui tests.
```
Known-flaky/non-hermetic classes to quarantine (do NOT count their reds as regressions):
- `tests/test_sandbox_recursion.py::test_recursion_depth_below_limit_always_succeeds` and `tests/adversarial/test_P2_mutation_kill.py::TestZeroSentinel::test_aac_crash_recovery_sidecar_present` (Makefile `PARALLEL_UNSAFE`, `Makefile:41-44`).
- The webui cluster that rewrites live `config.yaml`/allowlist (memory + `tests/unit/test_webui.py`, `tests/test_webui_kickoff_autopromote.py`, several `tests/adversarial/test_webui_*`). Run these only serially under `tmp_path`-clean state, never under `-n auto`.

### Step 1 — establish the authoritative baseline (clean tree)
```bash
cd /home/xnihil0zer0/JanusMaskJR
git stash -u            # or checkout a clean known-good commit
make test-full 2>&1 | tee /tmp/jm_baseline.txt   # serial, ~11 min, ~7890 tests
grep -E "^(FAILED|ERROR)" /tmp/jm_baseline.txt | sort > /tmp/jm_baseline_reds.txt
```
Any red here is a PRE-EXISTING failure, not a regression. (Memory notes a pre-existing z3 34-fail class — Step 0 should clear most; whatever remains is the baseline.)

### Step 2 — replay each auto-committed leaf and compare scoped-green vs full-red
Population = the accepted auto-commits in the impl ledger. For each:
```bash
cd /home/xnihil0zer0/JanusMaskJR
# enumerate accepted commits (phase=accepted,event=auto_commit) from the ledger
python - <<'PY'
import json,pathlib
rows=[json.loads(l) for l in pathlib.Path("state/impl_progress.jsonl").read_text().splitlines() if l.strip()]
acc=[r for r in rows if r.get("phase")=="accepted" and r.get("event")=="auto_commit"]
print("\n".join(f"{r.get('commit_sha')}\t{r.get('files')}" for r in acc))
PY
```
For each accepted commit SHA with files F:
```bash
git checkout <SHA>
# (a) reproduce the SCOPED gate verdict the daemon used:
python - <<PY
from pathlib import Path
from harness.test_scoper import get_relevant_test_files
print(get_relevant_test_files(Path('.'), $F_as_py_list))
PY
# run exactly those → expect GREEN (that's why it was committed)
python -m pytest -q <scoped files>          # SCOPED verdict
# (b) run the FULL suite at the same SHA:
make test-full 2>&1 | tee /tmp/jm_$SHA.txt
grep -E "^(FAILED|ERROR)" /tmp/jm_$SHA.txt | sort > /tmp/jm_${SHA}_reds.txt
# (c) NEW reds at this SHA = regressions introduced by this leaf:
comm -13 /tmp/jm_baseline_reds.txt /tmp/jm_${SHA}_reds.txt > /tmp/jm_${SHA}_new.txt
```
A leaf is a **confirmed regression escape** iff: scoped run GREEN, and `jm_${SHA}_new.txt` is non-empty after removing Step-0 quarantined tests. 
Regression rate = (#leaves with non-empty new-red) / (#accepted leaves).

### Step 3 — cheap one-shot approximation (if per-SHA replay is too costly)
Run the full suite once at HEAD and diff against baseline:
```bash
git checkout master && make test-full 2>&1 | tee /tmp/jm_head.txt
grep -E "^(FAILED|ERROR)" /tmp/jm_head.txt | sort > /tmp/jm_head_reds.txt
comm -13 /tmp/jm_baseline_reds.txt /tmp/jm_head_reds.txt   # all new reds since baseline
```
After quarantining Step-0 noise, any survivor is a regression that the cumulative scoped gating let through. **This single command is also exactly the Rank-1 nightly sweep** — i.e. building the experiment harness IS building the recommended fix.

Expected result, given NGv2 pop-2 = 0 real and JM's gate also runs the editor's own `mutation_target` oracle (`orchestrator.py:2836-2860`): the regression count is plausibly very low (0–small). Use it to size the investment.

---

## 4. Bottom Line — Is This the Right Problem?

**The leak is real (C1–C9 CONFIRM) but the cure as specified is wrong, and the disease may be benign.**

1. **The proposed fix is not buildable as described.** Parts (a) and (b) both require a symbol→oracle map that does not exist (`symbol_ledger.py` stores signatures, not oracle reverse-indexes; C8) and cannot be derived statically without the very import-blindness that creates the leak. The only honest implementation degrades into expensive dynamic coverage selection (alternative iv), which the JM non-hermetic clusters actively fight (`Makefile:14-26`). The fix conflates "tests named/importing the symbol" (cheap, already covered) with "tests that *execute* the symbol" (dynamic, expensive).

2. **A strictly better fix already exists, half-built.** Rank 1 (nightly `make test-full` → self-heal briefs) gives complete regression detection off the critical path, reuses `Makefile:48-55` and the self-heal corrective-spec path (`autowork_daemon.py:839-843`), needs no new index, and *is the same artifact as the measurement experiment* (§3 Step 3). Rank 2 (invert the existing `module_import_graph`, `discover.py:125`) cheaply closes the dominant intermediary-module leak class. Together they dominate the proposed fix on cost, completeness, and maintenance.

3. **Evidence says regression detection is probably the wrong place to spend.** NGv2 pop-2 measured 0 real regressions (34/34 were missing-toolchain). The JM gate additionally runs the editor's own paired oracle (`mutation_target`, `orchestrator.py:2836-2860`), shrinking the escape surface further. Per the owner-recorded error taxonomy, the dominant error class is **gate false-REJECTS** (auto_commit_failed / over-strict scoping), not false-accepts. Investing a bespoke symbol→oracle engine to chase a near-zero false-accept rate, while false-rejects throttle real throughput, is mis-prioritized.

**Recommendation:** Do NOT build the symbol→oracle "locking oracle" fix. Instead: (1) run the §3 measurement to get the actual JM regression number; (2) if it is non-trivial, ship Rank 1 (nightly full-suite sweep → self-heal) + Rank 2 (reverse-dep scope expansion); (3) redirect the saved effort to the dominant false-reject error class. The scoped gate is fine as a *fast* gate — it just must not be the *only* line of defense, and the second line should be the cheap complete sweep, not a fragile static oracle map.

— end —
