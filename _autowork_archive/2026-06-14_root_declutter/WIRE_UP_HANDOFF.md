# Wire-Up Sweep & Remediation — Handoff

**Date:** 2026-06-09
**Branch/state:** `master`, pushed through **`bf69e85`** (origin up to date as of this doc).
**Scope:** built the wire-up *sweep* tooling (Wave-1), ran it, then *remediated* the
orphan backlog it surfaced (Wave-2). All commits are on `master` and pushed.

This document is the single source of truth for continuing the work. Every claim names
a file/function/commit/command you can verify. It was itself adversarially reviewed by
three sub-agents on 2026-06-09; their corrections are folded in (notably: a stale-guard
commit, a masked 3rd orphan, and two broken steps in the build recipe — all fixed below).

---

## 1. What this project is

The JanusMaskJR build pipeline can produce **orphaned** modules — a leaf passes its own
isolated oracle, commits, and is marked DONE while *no live (non-test) code reaches it*.
"IMPLEMENTATION ≠ WIRED." A prior epic (`wire_up_phase`, through `ea4955b`) built the
*accept-time gate* that blocks **new** orphans. This work added the complement: a
**tree-wide sweep** of the *existing* source, plus **remediation** of what it found.

- **Wave-1** = the sweep tooling + a permanent regression guard.
- **Wave-2** = remediation: a tooling-accuracy fix that discharged ~33/36 orphans, then
  triage of the genuine residuals.

---

## 2. Commits (chronological, all on `master`, pushed)

```
3a55ba5  RED oracle: live-root reconciliation        (Wave-1 leaf 1)
6620524  Integrate: root_reconciliation              -> discover_live_roots
d2dd3cc  RED oracle: sweep classifier                (leaf 2)
7607c8a  Integrate: sweep_classifier                 -> sweep_modules / SweepReport
0954708  RED oracle: advisory MCP cross-check        (leaf 3)
30645e3  Integrate: mcp_crosscheck                   -> mcp_crosscheck
970232d  Wave-1 regression guard (leaf 4)            -> tests/harness/test_no_source_orphans.py (36-key baseline)
6744b1a  wire-up-sweep epic: child briefs + plans + WIRE_UP_SWEEP_REPORT.md (92/4/15/21)
6171fec  RED oracle: import-tracer accuracy fix      (Wave-2 leaf A)
154fa38  Integrate: wire_tracer_accuracy            -> _resolved_graph
e87ec60  Wave-2: tracer fix discharges 33/36; reconcile guard allowlist 36->3
12395d4  Retire dead tools/brief_status.py (+ test)
bf69e85  Fix stale guard state 12395d4 missed; add masked 3rd residual; correct config_loader rationale
```
> **Caveat on `12395d4`:** its message claimed "allowlist 3->2 / 2 ORPHAN" but a botched
> `git add` meant the diff only deleted the two files; the allowlist key + report regen
> never landed, so HEAD was briefly stale (still listing the deleted file). `bf69e85`
> repaired this. Lesson: after a multi-file change, `git show --stat HEAD` to confirm the
> diff matches the message.

---

## 3. The tooling (all in `harness/wire_up.py`)

Verify with `grep -nE "^def |^class " harness/wire_up.py`:

- `class WireResult(wired, importers, reason, fix_hint)`.
- `LIVE_ROOTS: list[str]` — the *shipped* seed constant. **STALE**: still lists three
  modules that DO NOT EXIST (`harness/webui_control.py`, `harness/overseer.py`,
  `harness/services.py`) plus the old `harness/hooks/{claude,gemini}_hook.py`.
  `discover_live_roots` filters non-existent entries (wire_up.py:62-67), so harmless at
  runtime; cleanup item in §7.
- `discover_live_roots(repo_root) -> list[str]` — reconciles the real root set: shipped
  `LIVE_ROOTS` (existing only) ∪ config/**-registered entrypoints (`-m dotted.module` and
  `*.py` path tokens resolving to discovered modules) ∪ modules with a real
  `if __name__ == '__main__'` guard (anchored regex, NOT substring — §8 gotcha). Returns
  **90** roots on this repo.
- `SweepReport(wired, config_wired, orphan_cluster, orphan, roots)` with `.to_dict()`,
  `.to_markdown()`.
- `sweep_modules(repo_root, *, roots) -> SweepReport` — builds the graph ONCE (via
  `_resolved_graph`), filters the source set (excludes `_archive/**`,
  `_autowork_archive/**`, `samples/**`, `scripts/**`, `tests/**`, `venv/**`), classifies
  each source module WIRED / CONFIG_WIRED / ORPHAN_CLUSTER / ORPHAN.
- `mcp_crosscheck(report, mcp_query) -> list[str]` — ADVISORY ONLY; injected
  `mcp_query(module_rel)->int`; never flips a verdict, never gates. (Run live during this
  work it returned 0 inbound for every sampled orphan — confirming the MCP's own blind spot.)
- `_resolved_graph(repo_root, modules)` — **the Wave-2 fix** (§4).
- `check_wired(repo_root, new_module_rel, *, roots=LIVE_ROOTS, exclude=()) -> WireResult`
  — the per-module primitive, ALSO consumed by the accept-time gate
  (`harness/orchestrator.py:2020` imports it; `_run_wire_up_gate` at :2041 calls it at
  :2069, guarded by `_wire_up_gate_enabled` reading `autowork.wire_up_gate`, default
  False). Now uses `_resolved_graph`.

`harness/rebuild/discover.py` (`discover_modules`, `module_import_graph`) is the trusted
base layer; it was NOT modified — `_resolved_graph` wraps it.

---

## 4. The key Wave-2 finding (read this — it reframes everything)

Wave-1 reported ~**36 confirmed orphans** (≈21 ORPHAN + 15 ORPHAN_CLUSTER; the exact
ORPHAN count drifts ±1 with tree state — treat "36" as approximate). Investigation showed
**~33 were FALSE POSITIVES** — genuinely reached from a live root, but via import forms
`discover.module_import_graph` cannot resolve:

1. `from PACKAGE import SUBMODULE` — e.g. `orchestrator.py:240 from harness import
   agy_pool`; `mcp_server.py:26 from harness.hooks.rpc import submit_code`;
   `overseer/service.py:24 from overseer import turn_runner`. The base graph resolves
   `from a.b import c` as an edge to `a.b` only, never to the submodule `a.b.c`.
2. dotted `import a.b.c`.
3. imports performed by a package `__init__.py` (a seed, excluded from the base graph) —
   e.g. `harness/narrow_fuzz/__init__.py:19 from harness.narrow_fuzz._registry import REGISTRY`.

Also: three `LIVE_ROOTS` were stale-nonexistent, and the real overseer entry is
`tools/webui_server.py` (has `__main__`) → `from tools import webui_control` →
`overseer.service` (function-local) → the cluster.

**The fix was ONE tooling leaf, not 36 per-module WIRE leaves** (which would have added
*inert* imports the tracer still couldn't see). `_resolved_graph` AST-augments the graph
to resolve the three forms above over modules + seed `__init__` nodes; `check_wired` and
`sweep_modules` each changed one token to call it. No new imports were added — real edges
were made visible.

> **STILL-UNCAUGHT wiring (caveat the fix does NOT cover):** dynamic/string-based imports
> (`importlib.import_module`, `__import__`, conditional/runtime imports) remain invisible
> to the AST tracer — a module reached ONLY via `importlib` would be a false-positive
> orphan. (Relative imports `from ..pkg import x` ARE handled, both by the base graph and
> by `_resolved_graph`'s level-aware resolution.) The `config/**` grep supplement (§5) is
> the only dynamic-wiring net, and it is crude (see the `actions.py` false-positive below).

**Ledger before → after:**
```
                Wave-1      now
WIRED              92        128
CONFIG_WIRED        4          1   (* the 1 is a FALSE POSITIVE — see §5 actions.py)
ORPHAN_CLUSTER     15          0
ORPHAN             21          2   (* true residual is 3; one is masked in CONFIG_WIRED)
```

> **LESSON for any future orphan sweep:** before mass per-module remediation, check whether
> the checker has a package-submodule / `__init__` / dynamic-import blind spot. Most
> "orphans" may be tooling false positives. Hand-verify a sample against the real import chain.

---

## 5. The regression guard and the residuals

`tests/harness/test_no_source_orphans.py` runs `sweep_modules` over the real tree and fails
if any confirmed orphan (ORPHAN ∪ ORPHAN_CLUSTER) appears outside `KNOWN_ORPHAN_ALLOWLIST`.
The allowlist only SHRINKS (36 after Wave-1 → 3 after the tracer fix → 2 after retiring
`tools/brief_status` → **3 now**, after adding the masked `actions.py`). The guard is
proven load-bearing (it fails on a synthetic new orphan).

**There are 3 genuinely tested-but-unwired residuals** — all the SAME situation
(implemented + a dedicated test that covers only its own functions + zero live importer).
Each is a **retire-vs-keep judgment call**, NOT a wiring task:

- **`harness/config_loader.py` — KEEP (judgment call).** A coherent config-schema/validation
  module (`HOOKS_ALLOWED_VERBS`, `HooksConfig`, `get_hooks_config`,
  `get_batch_execution_config`, `ConfigError`). No live importer: the runtime reads config
  inline (`config.get('batch_execution')` in `diff_fuzzer.py`/`sandbox.py`;
  `hooks_equivalence.py` has its own loader). The ~11 tests that import it exercise its OWN
  functions (self-coverage — deleting it deletes its own tests, no independent live coverage
  is lost). KEEP is a defensible call (retain the canonical config schema / consolidation
  target); by the strict wired definition it is as deletable as the others. *(An earlier
  "deleting destroys live-hooks coverage" rationale was WRONG and is withdrawn.)*

- **`harness/planner/oracle_attach.py` — retire candidate.** `attach_oracle`
  (oracle_attach.py:38) generates an oracle by STRIPPING an existing target module's source
  via `test_author.author_oracle` (:71), so it only applies to flows over *existing* modules.
  The rebuild engine `harness/rebuild/loop.py:364` already does that inline and never imports
  `oracle_attach`. The main brief-planner builds *not-yet-existent* modules (no source to
  strip), so it CANNOT be wired there. Redundant. (An earlier "wire it into the planner"
  recommendation was WITHDRAWN — misread of the contract.) Test: `tests/adversarial/test_oracle_attach.py`.

- **`overseer/actions.py` — retire candidate, currently MASKED.** No live importer (only
  `tests/overseer/test_actions.py`). **`sweep_modules` mis-classifies it as CONFIG_WIRED,
  not ORPHAN**, because `_grep_config` whole-word-matches the unrelated `"actions"` JSON key
  in `config/gemini_settings.json`. So the tool's "CONFIG_WIRED: 1" is a false positive that
  HIDES this orphan, and the live ledger shows 2 orphans when the truth is 3. It is listed in
  the allowlist anyway so the residual set is complete. This exposes a real `_grep_config`
  weakness — see §7 item 3.

---

## 6. How to reproduce / regenerate

```bash
source venv/bin/activate
# Full wire-up oracle suite (50 tests, all green at bf69e85):
python -m pytest -p no:cacheprovider -q \
  tests/harness/test_wire_up.py tests/harness/test_wire_up_accept_gate.py \
  tests/harness/test_live_root_reconciliation.py tests/harness/test_sweep_classifier.py \
  tests/harness/test_mcp_crosscheck_advisory.py tests/harness/test_wire_tracer_accuracy.py \
  tests/harness/test_no_source_orphans.py
# Just the guard:
python -m pytest -p no:cacheprovider -q tests/harness/test_no_source_orphans.py
# Regenerate the audit ledger:
python -c "from pathlib import Path; from harness.wire_up import sweep_modules, discover_live_roots; \
  open('WIRE_UP_SWEEP_REPORT.md','w').write(sweep_modules(Path('.'), roots=discover_live_roots(Path('.'))).to_markdown())"
```
Live tool output: 128 WIRED / 1 CONFIG_WIRED / 0 ORPHAN_CLUSTER / 2 ORPHAN. **Read that as
128 WIRED / 3 genuinely-unwired** (config_loader, oracle_attach as ORPHAN; overseer/actions.py
falsely in CONFIG_WIRED). To verify a remediation worked: re-run the one-liner and confirm the
module moved into `.wired`, then the guard goes green.

---

## 7. Open items / next steps

1. **`oracle_attach.py` retire-or-leave decision** (§5) — it cannot be wired; choose retire
   (delete module + `tests/adversarial/test_oracle_attach.py`) or leave as a tested utility.
2. **Stale `LIVE_ROOTS` cleanup** (§3) — drop the 3 nonexistent + old-hook entries from the
   constant (via the pipeline, `harness_self_fix`). Cosmetic; `discover_live_roots` already
   filters them.
3. **`_grep_config` false-CONFIG_WIRED fix** (§5) — it whole-word-matches a module's stem in
   ANY `config/**` file, so a stem that happens to appear as an unrelated JSON key (e.g.
   `actions`) yields a bogus CONFIG_WIRED that masks a real orphan. Tighten it (e.g. only count
   a config reference that looks like a module path / `-m` target, not an arbitrary key), then
   re-sweep — `overseer/actions.py` (and possibly others) will correctly surface as ORPHAN.
4. **`config_loader` consolidation (optional)** — refactor the inline `config.get(...)` reads
   to use it; would WIRE it legitimately.
5. **Flip `autowork.wire_up_gate` ON** — the accept-time orphan gate is default-OFF. The key is
   READ with a default and is **absent from `harness/config.yaml`**; to enable, add
   `autowork: {wire_up_gate: true}` (don't expect to find it already there). Owner sign-off after
   dogfood. Independent of this sweep.

---

## 8. Pipeline build mechanics & gotchas (how every leaf here was built)

Production code in `harness/**` is NEVER hand-edited — it routes through the pipeline. Only
oracles/tests are hand-authored.

**TRUST MODEL (why the decision file):** `harness/**` (and `config/**`, `scripts/**`,
`tools/**`) are protected paths; an accepted submission to them will NOT auto-commit unless an
operator approves. The approval channel is a file `state/control/decisions/<task_id>.json` with
`{"decision":"approve"}` (read by `orchestrator._apply_approval_granted`). Combined with
`meta_task_type: harness_self_fix`, this is the manual override that lets the auto-commit land.
(The daemon's `auto_promote` allowlist is the *hands-off* alternative — not used in this manual
recipe.)

**Recipe (exact commands used for every leaf here):**
1. **Hand-author the RED oracle**, confirm it fails, commit it RED-first.
2. **Hand-author `plan_hooks_<slug>.json`.** Don't guess the shape — copy a committed one:
   `plan_hooks_wire-tracer-accuracy.json` / `plan_hooks_root-reconciliation.json` /
   `plan_hooks_sweep-classifier.json` are verbatim templates. Key fields: `task_id`,
   `meta_task_type` (`harness_self_fix` for `harness/**`), `files_touched`,
   `verification_command` (names the oracle(s)), and a rich `spec`
   (objective/functional_requirements/interfaces/edge_cases/non_goals/implementation_notes).
3. **Normalize → WRITE TO DISK → stage.** `normalize_plan(plan_dict, repo_root)` returns a
   **dict**; `stage_task` reads a **file**, so you MUST write the normalized dict back to disk
   between them:
   ```python
   from harness.planner.plan_normalizer import normalize_plan
   from harness.planner.staging import stage_task
   import json, pathlib
   norm = normalize_plan(json.load(open('plan_hooks_<slug>.json')), repo_root=pathlib.Path('.'))
   pathlib.Path('plan_hooks_<slug>.normalized.json').write_text(json.dumps(norm, indent=2))
   stage_task(pathlib.Path('plan_hooks_<slug>.normalized.json'), '<task_id>', pathlib.Path('state'))
   ```
   `stage_task(plan_PATH, task_id, state_dir)` — **first arg is a path, not a dict**
   (staging.py:47). `canonical=True` (default) writes `state/tasks/<task_id>.json`, the path the
   dispatcher scans. `normalize_plan` injects the committed oracle source into
   `spec.implementation_notes` — essential because the worker is SOURCE-BLIND (next point).
4. **Decision file:** write `state/control/decisions/<task_id>.json` = `{"decision":"approve"}`.
5. **Dispatch:** `bash scripts/impl_dispatch_once.sh <task_id> state 1500`. It spawns the
   orchestrator, waits for `state/tasks/processed/<task_id>.json`, and prints the `auto_commit`
   ledger row + new commit (or the rejection).

**SOURCE-BLIND WORKER — the #1 cause of a failed first dispatch.** The synthesis worker cannot
read the repo. Therefore, in `implementation_notes`: (a) NEVER cite repo line numbers; describe
edits structurally; (b) EMBED the exact current source of every function you anchor-on or edit,
verbatim, so the worker can reproduce it.

**R-ANCHOR (new top-level symbol).** A new function emitted as its own patch entry FAILS to
apply. Anchor it on an EXISTING symbol: the patch `code` = the existing function reproduced
verbatim + the new function appended as a trailing def. (We used `_grep_config` as the anchor
repeatedly.) Editing an existing function is a normal symbol-patch (reproduce it with the one
change).

**Recovering from a REJECTION.** The dispatch prints the reject reason; full logs are at
`state/dispatch_once.std{out,err}.log`. The worker's emitted code is at
`state/output/<task_id>.patches.json` (and/or `<id>.files.json` / `<id>.py`). To re-dispatch
after fixing the plan/oracle: `mv state/tasks/processed/<id>.json state/tasks/<id>.json` (or just
re-run `stage_task`, which overwrites a not-yet-accepted task), then `impl_dispatch_once.sh`
again. (Leaf 1 here needed exactly one re-dispatch — see the `__main__` gotcha.)

**Other gotchas proven here:**
- **`__main__` self-match (cost leaf 1 a re-dispatch).** `'__main__' in src` substring-matched
  `discover_live_roots` itself (its body contains the literal). FIX: anchored multiline regex
  `(?m)^[ \t]*if[ \t]+__name__[ \t]*==[ \t]*(['\"])__main__\1` (wire_up.py:94).
- **Per-module `check_wired` is O(n²)** (rebuilds the graph each call) and times out tree-wide;
  `sweep_modules` builds it ONCE.
- **Deletions don't fit the synthesis pipeline** (the worker emits code, not removals).
  `tools/brief_status.py` was retired via direct `git rm` + full-suite verification under
  explicit owner authorization. There is no pipeline path for a file deletion.
- **Dep-slug drift:** the epic decomposer emits hyphenated child slugs but underscore
  `dependencies:` — normalize to hyphens or the DAG won't resolve.
- **codebase-memory-mcp graph is ADVISORY ONLY** — proven unreliable both ways; never gate on it.

---

## 9. Artifacts in the repo

- `harness/wire_up.py` — all tooling (§3).
- `tests/harness/test_{wire_up,wire_up_accept_gate,live_root_reconciliation,sweep_classifier,
  mcp_crosscheck_advisory,wire_tracer_accuracy,no_source_orphans}.py` — oracles + guard (50 tests).
- `WIRE_UP_SWEEP_REPORT.md` — regenerable audit ledger.
- `brief_hooks_wire_up_sweep.md`, `brief_hooks_wire_up_remediation.md`, the per-leaf
  `brief_hooks_*.md` / `plan_hooks_*.json`, `plan_wire_up_*_epic.json` — briefs + hand plans.
- `WIRE_UP_HANDOFF.md` — this file (committed at/after `bf69e85`).
- Memory: `~/.claude/projects/-home-xnihil0zer0-JanusMaskJR/memory/wire-up-sweep-epic.md`.
