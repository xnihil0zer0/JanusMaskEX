---
working_dir: "/home/xnihil0zer0/JanusMaskJR"
required_task_ids:
  - wire-up-symbol-caller-gate-core-oracle
  - wire-up-symbol-caller-gate-core-impl
  - wire-up-symbol-caller-gate-accept-wiring-impl
interfaces: >
  Close a SYSTEMIC HOLE in the accept-time orphan/wire-up gate: today the gate
  (harness/orchestrator.py:_run_wire_up_gate -> harness/wire_up.py:check_wired)
  fires ONLY for a BRAND-NEW MODULE FILE (it `continue`s on any path already
  tracked in parent HEAD via `_tracked_in_parent`). When a leaf ADDS new
  top-level callable symbols to an ALREADY-EXISTING module, the gate skips the
  file entirely, so a dead (zero-caller) new function lands unit-green and
  unflagged. This is exactly how the 2026-06-18 disk-reaper battery
  (`reap_stale_disk`, `cleanup_state`, `_reconcile_stale_ledger_heads`, etc.)
  landed in the already-existing `harness/state_reconciler.py` with no live
  caller. This brief adds a NARROW, default-OFF, report-only symbol-level
  caller check that complements the existing module-level reachability gate.

  THREE tasks, each editing/creating exactly ONE file via __JANUSMASK_PATCHES__
  SYMBOL patches (no whole-file manifest, no multi-file task):

  (1) wire-up-symbol-caller-gate-core-oracle (test_authoring):
      RED behavioral oracle for the new symbol-caller primitive in
      harness/wire_up.py — adding an uncalled new top-level callable to an
      existing module FAILS the check; gaining an in-repo caller (or a
      `wire_exempt` marker) PASSES; the current tree's pre-existing
      zero-caller symbols are NOT flagged (no false positives).

  (2) wire-up-symbol-caller-gate-core-impl (harness/wire_up.py):
      A NEW pure primitive `check_new_symbols_called(repo_root, module_rel,
      parent_src, *, exempt=()) -> SymbolWireResult` that diffs the just-
      committed module source against the PARENT source, finds top-level
      callables (def/async def/top-level lambda assignment) that are NEW in
      this commit, and reports any new symbol with ZERO in-repo caller
      (callers searched across the non-test/non-scratch/non-archive source
      set; an explicit `wire_exempt` justification suppresses one). PURE
      (stdlib + AST + filesystem reads); no process spawn / model / network.

  (3) wire-up-symbol-caller-gate-accept-wiring-impl (harness/orchestrator.py):
      Wire the primitive into `_run_wire_up_gate` for the ALREADY-TRACKED
      (symbol-addition) branch, behind a NEW default-OFF
      `autowork.wire_up_symbol_gate` flag, in REPORT-ONLY mode (ledger row +
      log warning, NEVER a rollback) so it cannot fail-close prod until proven.
---

# Title
Close the symbol-addition hole in the accept-time wire-up/orphan gate: add a
default-OFF, report-only symbol-level caller check (`check_new_symbols_called`)
in harness/wire_up.py and wire it into `_run_wire_up_gate` for the
already-tracked-file branch, so a new top-level callable added to an existing
module with ZERO in-repo caller is detected (not silently landed).

# Scope
THREE tasks. Two `harness_self_fix` impl tasks (each one `harness/**` file) and
one `test_authoring` oracle task. READ each file first.

1. `wire-up-symbol-caller-gate-core-oracle` (test_authoring) authors a RED
   behavioral oracle in `tests/harness/test_wire_up_symbol_caller_gate.py`
   against the new `harness/wire_up.py` primitive. NO production edit in this
   task.

2. `wire-up-symbol-caller-gate-core-impl` edits `harness/wire_up.py` to ADD a
   new pure top-level primitive `check_new_symbols_called` plus a small
   `SymbolWireResult` dataclass. `harness/wire_up.py` is NOT in
   `_NEVER_AUTO_APPROVE`, so it is an auto-approve-eligible `harness/**` edit.

3. `wire-up-symbol-caller-gate-accept-wiring-impl` edits
   `harness/orchestrator.py` to call the primitive from the EXISTING
   `_run_wire_up_gate` on the symbol-addition branch, behind a new default-OFF
   flag, REPORT-ONLY. NOTE: `harness/orchestrator.py` IS in `_NEVER_AUTO_APPROVE`
   (it is the irreducible trust-core), so this task REQUIRES an operator decision
   file `state/control/decisions/wire-up-symbol-caller-gate-accept-wiring-impl.json`
   and `operator_decision_required: true` in this frontmatter. Do NOT put the new
   LOGIC in `orchestrator.py`: the substantive primitive lives in `wire_up.py`
   (task 2); task 3 adds ONLY the gated call site + ledger row, which is the
   minimal trust-core surface.

This is the ROOT-CAUSE gate fix, distinct from the symptom fix
`brief_hooks_wire_disk_reapers_live_loop.md` (which wires the specific dead
reapers into the live loop). That brief fixes the instance; THIS brief fixes the
gate that should have caught the instance — see "Relationship to the disk-reaper
brief" below. Do NOT fold them together.

# Background — the gate's true granularity and the exact hole (verified)
The accept-time orphan gate is:
`harness/orchestrator.py:_run_wire_up_gate` (line ~2188), gated by
`_wire_up_gate_enabled` (line ~2169, reads `config['autowork']['wire_up_gate']`,
currently `true` at `harness/config.yaml:80`), called at the accept chokepoint
`harness/orchestrator.py:3265-3267` (after the staged commit, before the
staging->parent merge). The reachability primitive it consults is
`harness/wire_up.py:check_wired` (line ~317).

VERIFIED TRUE GRANULARITY of the existing gate (`_run_wire_up_gate`, lines
~2213-2222):
  - It iterates `files_touched`, skipping any entry that is not `.py`, is under
    a `tests/` dir, or is named `test_*`/`*_test.py`.
  - **The load-bearing skip:** `if _tracked_in_parent(rel): continue`
    (line ~2221). `_tracked_in_parent` runs `git cat-file -e HEAD:<rel>` against
    `worktree_root` (the PARENT tree before this commit). If the file already
    existed in HEAD, the gate SKIPS it entirely. So the gate fires ONLY for a
    BRAND-NEW MODULE FILE.
  - For a new file it calls `check_wired(staging_path, rel)`, which is
    MODULE-level import-reachability: a module is WIRED iff it (or one of its
    direct importers) is reachable, via the forward intra-project import graph,
    from a `LIVE_ROOTS` entrypoint
    (`['harness/orchestrator.py','harness/orchestrator_worker.py','harness/autowork_daemon.py','harness/planner/cli.py']`,
    `wire_up.py:37`) or is config-referenced. It NEVER checks individual
    function/symbol call-reachability.
  - There is NO `meta_task_type` carve-out and NO `harness_self_fix` exemption in
    `_run_wire_up_gate` (the `task` parameter is referenced for nothing). The
    only carve-outs are: non-`.py`, tests, and already-tracked files.

THE HOLE (the precise mechanism, verified by git history):
`harness/state_reconciler.py` was CREATED as a new module on 2026-06-18 in commit
`7d063d2` ("stale-reconcile-serialization-lock-impl"). That first commit's body
was `state_reconcile_lock` + `_archive_move_collision_safe`. At creation the
module passed the module-level `check_wired` because it was imported by a
root-reachable module at that time (`tools/brief_reaper.py`); the daemon import
of `state_reconciler` landed LATER, in commit `cc7327b` (so "imported by the
daemon at autowork_daemon.py:2232" is the present state, NOT the wiring that
satisfied the gate at creation). EVERY subsequent reaper function
(`reap_orphaned_workdirs` `b03a2cd`, `compact_impl_progress_ledger`/`age_out_logs`/
`prune_autowork_archive`/`reap_stale_disk` in `b03a2cd`, `cleanup_state` `fe8e9c3`,
`_reconcile_stale_ledger_heads` `44efd58`, `reap_spent_briefs` `3c05d6d`) was ADDED
to the NOW-ALREADY-TRACKED module. So at each of those commits the gate hit
`_tracked_in_parent(rel) -> True -> continue` and NEVER examined the added
symbols. At `b03a2cd` ALL of the added reapers (`reap_orphaned_workdirs` and the
disk-reaper battery) were zero-live-caller at the moment they landed; the
`reap_orphaned_workdirs` daemon wiring (its tail-call into the live loop) landed
SEPARATELY in commit `6fa232e`. So the module-level gate was satisfied ONCE (at
creation, by the `tools/brief_reaper.py` import) and the dead siblings rode in
under cover of the already-tracked module.

VERIFIED CURRENT DEADNESS (grep across repo, excluding tests/scratch/archive/the
module itself): the daemon calls ONLY `reap_orphaned_workdirs`
(`autowork_daemon.py:2370`), which tail-calls `detect_and_heal_stalls`. The
TRULY root-dead new top-level callables in `state_reconciler.py` are:
  - `cleanup_state` (line ~333) — ZERO live callers (only tests).
  - `reap_stale_disk` (line ~957) — ZERO live callers (only tests). It DOES
    internally call `compact_impl_progress_ledger`/`age_out_logs`/
    `prune_autowork_archive`/`reap_spent_briefs`/`reap_orphaned_workdirs`, so
    those four are reachable from `reap_stale_disk` — but `reap_stale_disk`
    itself has no root caller (the classic "orphan_cluster": importers exist but
    none is reachable from a live root).
  - `_reconcile_stale_ledger_heads` (line ~1078) — ZERO live callers (only
    tests).
The other four reapers are wired ONLY through the dead `reap_stale_disk`; the
disk-reaper brief addresses their live-loop wiring. THIS brief's symbol gate
would have flagged the root-dead additions at accept time.

PRIOR DEFECT KNOWLEDGE (institutional): the "implementation-is-not-wired-defect"
note (owner, 2026-06-08) says pipeline leaves "repeatedly produced modules that
exist + pass an oracle but are never wired into the running system" and that
"every feature's oracle MUST assert WIRING/reachability." The module-level
wire-up gate (`wire_up.py`, landed 2026-06-09, flag ON since 2026-06-09) was the
fix for the NEW-MODULE case. Its coverage STOPS at the module boundary and at
file creation; it does not cover new callables added to an existing module. This
brief extends coverage to that case, narrowly and report-only.

# Why a NARROW, default-OFF, report-only symbol check (design realism)
A full static call-graph reachability check for arbitrary Python — dynamic
dispatch, getattr, registry/plugin tables, config-string wiring, tail-call
wiring, decorators — is HARD and WILL false-positive (a real caller invoked via
`getattr(mod, name)()` or a config string looks uncalled to a static scan).
Therefore this brief deliberately does the NARROWEST defensible thing:
  - It checks ONLY NEW top-level callables added in THIS commit (an AST diff of
    the just-committed module against its parent), NOT the whole tree. This means
    the gate can NEVER retroactively flag a pre-existing zero-caller symbol
    (e.g. the `cleanup_state`/`reap_stale_disk`/`_reconcile_stale_ledger_heads`
    already in HEAD): they are not "new in this commit," so the current tree has
    ZERO false positives by construction. The oracle pins this.
  - "Called" is a TEXTUAL/AST in-repo caller search: the new symbol's bare name
    appears as a call/attribute reference somewhere in the non-test/non-scratch/
    non-archive source set OTHER than its own definition site. This is
    intentionally PERMISSIVE (it accepts `getattr`-by-literal, a dotted
    `mod.foo(...)` reference, or even a same-module sibling caller) to keep the
    false-positive rate low; it is a "someone references this name" heuristic,
    not a proven reachability proof.
  - An explicit `wire_exempt` escape hatch: a new symbol whose name is in the
    task's declared exempt list (frontmatter / task field, surfaced to the
    primitive as `exempt=(...)`) is suppressed, for legitimately-deferred wiring
    (a symbol wired in a LATER task of the same plan, a public-API helper, a
    tail-call target added before its caller).
  - REPORT-ONLY + default-OFF: the wiring task writes an `orphan_symbol_unwired`
    ledger row + a log warning and returns WITHOUT rollback. It is gated behind a
    NEW `autowork.wire_up_symbol_gate` flag that DEFAULTS OFF (absent => off), so
    it is a strict no-op in prod until an operator flips it on after observing the
    report rows. This honors BUILT != WORKS and the rule that a risky new gate
    ships report-only/default-OFF first.

# Inputs
READ these files FIRST in `/home/xnihil0zer0/JanusMaskJR`:

- `harness/wire_up.py` — the file TASK 2 edits. VERIFIED current state: it is the
  PURE reachability module (stdlib + AST + filesystem only; module docstring says
  "no process spawns, no network/model/API calls"). It already has: `WireResult`
  dataclass (line ~21), `LIVE_ROOTS` (line ~37), `discover_live_roots` (~51),
  `SweepReport` (~115), `sweep_modules` (~150), `_resolved_graph` (~232),
  `_grep_config` (~286), and `check_wired` (~317). The new primitive
  `check_new_symbols_called` and `SymbolWireResult` join this module as new
  top-level symbols — KEEP the module pure (no new imports beyond `ast`, `re`,
  `pathlib`, stdlib). REUSE the existing `discover_modules` import (line ~19) to
  obtain the non-test source module set for the caller search. Mirror the existing
  EXCLUDE tuple shape used in `sweep_modules` (line ~167:
  `('_archive/','_autowork_archive/','samples/','scripts/','tests/','venv/')`)
  to scope the caller search; ALSO exclude `_autowork_scratch/` and the other
  untracked scratch dirs by restricting to git-tracked OR `discover_modules`
  output (the latter already excludes scratch/test/seed).

- `harness/orchestrator.py` — the file TASK 3 edits (TRUST-CORE,
  `_NEVER_AUTO_APPROVE`). VERIFIED current state:
  - `_wire_up_gate_enabled(state_dir=None) -> bool` at line ~2169 reads
    `config['autowork']['wire_up_gate']` (default False). The new flag check must
    mirror this shape: a sibling `_wire_up_symbol_gate_enabled(state_dir=None)`
    reading `config['autowork']['wire_up_symbol_gate']` (default False).
  - `_run_wire_up_gate(task, files_touched, state_dir, task_id, staging_path,
    worktree_root, result, working_dir) -> bool` at line ~2188. The loop
    (~2213-2222) already computes, per `rel`: the `.py`/tests/test_* skips, and
    `_tracked_in_parent(rel)` (which runs `git cat-file -e HEAD:<rel>` against
    `worktree_root`). The symbol check belongs on the `_tracked_in_parent(rel) is
    True` branch — i.e. when the EXISTING code `continue`s. The just-committed
    source is at `staging_path/<rel>`; the PARENT source is obtainable via
    `git show HEAD:<rel>` run in `worktree_root` (the same tree `_tracked_in_parent`
    probes). Pass both to the primitive.
  - `write_jsonl_row(state_dir / 'impl_progress.jsonl', {...})` is the ledger
    primitive used by the existing reject path (line ~2229). The report-only path
    writes a `phase: 'report'`, `event: 'orphan_symbol_unwired'` row — it must NOT
    write `phase: 'rejected'` and must NOT call `_rollback_rejected_commit` /
    `remove_staging_worktree` / `_mark_blocked`.
  - `task` is a dict; the exempt list is read via
    `task.get('wire_exempt') or (task.get('constraints') or {}).get('wire_exempt')
    or []` (mirror the `meta_task_type` access pattern at line ~2146).

- `harness/config.yaml` — DO NOT EDIT (read lines ~76-92 for context only). The
  `autowork:` section already holds `wire_up_gate: true`. The new
  `wire_up_symbol_gate` flag is read defensively by `_wire_up_symbol_gate_enabled`
  and DEFAULTS OFF when absent — adding the literal config key is OUT OF SCOPE (it
  would be a second file edit and the absent-default is the desired safe default;
  the operator adds+flips it later, exactly like `wire_up_gate` was flipped on
  separately at commit `2c9fa32`).

- `harness/state_reconciler.py` — DO NOT EDIT (read for context only). It is the
  WORKED EXAMPLE: `cleanup_state` (~333), `reap_stale_disk` (~957),
  `_reconcile_stale_ledger_heads` (~1078) are the root-dead new top-level
  callables that the existing gate skipped because the file was already tracked.
  The oracle uses an ANALOGOUS synthetic fixture (do NOT assert against this real
  file — see anti-gaming).

- `tests/harness/test_wire_up_gate_staging_tree_wired.py`,
  `tests/harness/test_wire_up_accept_gate.py`, `tests/test_wire_up.py` — DO NOT
  EDIT (read for the established wire_up fixture pattern: build a synthetic repo
  under `tmp_path`, write modules, `git init`/commit a parent, then assert the
  primitive's verdict). The new oracle follows this hermetic-tmp_path pattern.

# Non-Goals
Integration is out of scope (the literal word `integration` MUST appear in this
section and in EACH task's `non_goals` to excuse the integration-test
requirement). Specifically OUT OF SCOPE / HONEST LIMITATIONS:
- A proven STATIC CALL-GRAPH reachability proof for the new symbol. This brief
  ships a "is the new symbol's name referenced anywhere in source" heuristic, NOT
  a from-live-root reachability proof at the symbol level. It will MISS:
  (a) a new symbol whose only caller is ITSELF a dead/orphaned function or a
      flag-gated caller that never runs (a referenced-but-dead caller still counts
      as "called" — the heuristic checks reference existence, not live
      reachability);
  (b) a new symbol invoked purely via dynamic dispatch with a COMPUTED name
      (`getattr(mod, some_var)()`), which has no literal name reference;
  (c) a new symbol that SHOULD have been wired into a live root but is only
      called by a sibling new function in the same commit (both new, mutually
      referencing) — the heuristic sees the reference and passes.
  These are accepted gaps; the goal is to catch the COMMON case (a brand-new
  top-level callable with literally zero references anywhere), which is exactly
  the disk-reaper pattern.
- FAIL-CLOSING (rollback) on a symbol verdict. This brief is REPORT-ONLY +
  default-OFF. Turning it into a hard gate, or flipping `wire_up_symbol_gate` ON
  in committed config, or restarting the daemon, is a SEPARATE operator decision
  after the report rows are observed in prod. Do NOT make the new path roll back,
  block, or `_mark_blocked`.
- Editing `harness/autowork_daemon.py` (in `_NEVER_AUTO_APPROVE`),
  `harness/orchestrator_worker.py`, `harness/config.yaml`, `harness/planner/**`,
  or ANY file other than the one each task's `files_touched` declares.
- Re-implementing or changing `check_wired`, `sweep_modules`, `discover_modules`,
  `_resolved_graph`, the existing module-level `_run_wire_up_gate` reject path, or
  the `wire_up_gate` flag. The new symbol check is PURELY ADDITIVE and runs only
  on the already-tracked branch the module-level gate currently `continue`s past.
- Detecting NEW METHODS added to an existing class, or new symbols in non-`.py`
  files. Scope is NEW TOP-LEVEL callables (module-scope `def`/`async def`, and a
  top-level `name = lambda ...` assignment) in a `.py` source module. Class
  methods and nested defs are out of scope (their reachability is the enclosing
  class/function's concern).
- Wiring the specific dead reapers (`reap_stale_disk`/`cleanup_state`/etc.) into
  the live loop — that is the deliberately-separate
  `brief_hooks_wire_disk_reapers_live_loop.md`. Do NOT widen this brief to touch
  `state_reconciler.py`.

# Relationship to the disk-reaper brief (do not duplicate)
`brief_hooks_wire_disk_reapers_live_loop.md` (already at repo root, references
`required_task_ids: wire-disk-reapers-live-loop-{oracle,impl}`) wires the SPECIFIC
dead reaper functions into the live daemon loop — it fixes the INSTANCE. THIS
brief fixes the GATE that let the instance through, so the next batch of
zero-caller symbol additions is detected at accept time rather than discovered by
a later audit. They are orthogonal (different files, different task ids) and BOTH
are warranted per the "turn-recurring-failures-into-pipeline-fixes" rule. This
brief deliberately does NOT touch `state_reconciler.py`.

# Deliverables

## TASK 1 — wire-up-symbol-caller-gate-core-oracle (test_authoring; harness/wire_up.py)
The test_authoring stage authors a RED behavioral oracle (NO production edit). It
MUST be hermetic: build a synthetic repo under `tmp_path` (mirror the existing
`tests/test_wire_up.py` / `test_wire_up_gate_staging_tree_wired.py` fixture
pattern — write modules, no real `state/`, no network, no shared global mutation).

ANTI-GAMING ORACLE REQUIREMENTS (the oracle MUST, and MUST NOT leak an answer
key — derive expectations from on-disk source semantics, NOT a frozen literal,
NOT by pasting the impl source into the test):
- NEW UNCALLED SYMBOL FAILS: build a `tmp_path` source tree with an existing
  module `pkg/mod.py` that defines `def already(): ...` AND, in the "child"
  (committed) version, ADDS `def brand_new_uncalled(): return 1` with NO reference
  to `brand_new_uncalled` anywhere in the tree. Call
  `check_new_symbols_called(child_root, 'pkg/mod.py', parent_src=<old source of
  pkg/mod.py>)` and assert the result reports `brand_new_uncalled` as an
  unwired/orphan symbol (e.g. `result.ok is False` and `'brand_new_uncalled' in
  result.unwired`). This MUST be RED on HEAD (the primitive does not yet exist —
  the import itself fails until TASK 2 lands).
- GAINING AN IN-REPO CALLER PASSES: same tree, but ADD a live module
  `pkg/caller.py` containing `from pkg.mod import brand_new_uncalled` and a call
  `brand_new_uncalled()` (or `mod.brand_new_uncalled()`). Assert the new symbol is
  NO LONGER reported (`result.ok is True`, `'brand_new_uncalled' not in
  result.unwired`). Derive this from the on-disk caller existence, not a literal.
- WIRE_EXEMPT MARKER PASSES: same uncalled-symbol tree as the first case, but call
  `check_new_symbols_called(child_root, 'pkg/mod.py', parent_src=...,
  exempt=('brand_new_uncalled',))` and assert it is suppressed (`result.ok is
  True`; ideally the symbol appears in a separate `exempted` list, not `unwired`).
- NO FALSE POSITIVE ON PRE-EXISTING ZERO-CALLER SYMBOLS: build a tree where the
  PARENT source of `pkg/mod.py` ALREADY contains `def old_uncalled(): ...` with no
  caller, and the child commit ADDS only an UNRELATED new called symbol. Assert
  `old_uncalled` is NOT reported (it is not new in this commit) — proving the diff
  is against the parent and the gate never retroactively flags pre-existing
  orphans. This is the load-bearing false-positive guard.
- TESTS/SCRATCH/ARCHIVE CALLERS DO NOT COUNT: place the only reference to a new
  symbol inside a `tests/test_x.py` (and, separately, inside an
  `_autowork_scratch/` or `_archive/` path) and assert the symbol is STILL
  reported as unwired (a test-only/scratch-only caller does not count as wiring —
  this is the exact disk-reaper pattern where every caller was a test).
- DYNAMIC-DISPATCH / MISS DOCUMENTED (negative-knowledge, optional but preferred):
  assert that a symbol referenced ONLY via a computed `getattr(mod, name)()`
  (no literal name) is reported unwired — documenting the known heuristic miss
  honestly (the test states this is the accepted limitation, not a bug).
- PURITY: the primitive performs NO process spawn / network / model call; the
  oracle MUST run fully offline against `tmp_path` and assert determinism (same
  inputs => same `SymbolWireResult`).
The oracle MUST derive expectations from the synthetic source it writes, MUST NOT
paste the impl into the test, and MUST NOT assert against the real
`harness/state_reconciler.py`.

`non_goals` MUST contain the literal word `integration`. `regression_tests >= 2`.

- `task_id: wire-up-symbol-caller-gate-core-oracle`
- `priority: high`
- `meta_task_type: test_authoring`
- `files_touched: ["tests/harness/test_wire_up_symbol_caller_gate.py"]`
- `mutation_target: harness/wire_up.py`  (MODULE-only dotted path; the test
  exercises this module)
- `dependencies: []`
- `verification_command:` `python -m pytest tests/harness/test_wire_up_symbol_caller_gate.py -q`
  (RED against HEAD — the primitive does not yet exist; do NOT use a broad
  `pytest tests/adversarial/ -q` vcmd).

## TASK 2 — wire-up-symbol-caller-gate-core-impl (harness/wire_up.py)

IMPLEMENTATION NOTES (LOAD-BEARING — GENERAL correct behavior, NOT fixture-
matching):

1. PATCH SHAPE: emit a `__JANUSMASK_PATCHES__` SYMBOL patch. ADD two NEW
   top-level symbols to `harness/wire_up.py`: a small `SymbolWireResult`
   dataclass and the function `check_new_symbols_called`. Land each new
   module-level symbol via an R-ANCHORED enclosing patch on an existing top-level
   symbol (anchor on `check_wired` or `_grep_config`) so a brand-new module-level
   symbol lands correctly (a standalone unanchored new-symbol patch fails
   patch-apply with an opaque `auto_commit_failed` — see the new-symbol R-anchor
   rule). Do NOT emit `__JANUSMASK_MANIFEST__` (single existing file, symbol
   patches — not whole-file). Keep the module PURE (stdlib + `ast` + `pathlib`;
   no new third-party import, no subprocess, no network).

2. `SymbolWireResult` dataclass fields:
   `ok: bool` (True iff no NEW symbol is unwired),
   `unwired: list[str]` (sorted names of new top-level callables with zero in-repo
   caller and not exempted),
   `exempted: list[str]` (sorted new symbols suppressed by `exempt`),
   `new_symbols: list[str]` (sorted all new top-level callables this commit added),
   `reason: str` (human-readable).

3. `check_new_symbols_called(repo_root, module_rel, parent_src, *, exempt=()) ->
   SymbolWireResult`:
   - `repo_root` is the COMMITTED (staging) tree root; `module_rel` is the POSIX
     rel-path of the module under test; `parent_src` is the module's source TEXT
     in the PARENT tree before this commit (the caller in TASK 3 fetches it via
     `git show HEAD:<rel>`; when `parent_src` is empty/None treat the module as
     brand-new and run the SAME check over ALL its top-level callables — though in
     practice the brand-new-file case is already covered by the module-level
     gate, the primitive must behave correctly either way).
   - Parse the CHILD source (`repo_root/module_rel`) and the `parent_src` with
     `ast.parse`; be FAIL-SOFT: if the child does not parse, return
     `SymbolWireResult(ok=True, ..., reason='child unparseable; symbol check
     skipped')` (NEVER raise — a parse failure must not block accept). If the
     PARENT does not parse, treat the parent symbol set as empty.
   - Compute TOP-LEVEL CALLABLES on each side: a module-scope `ast.FunctionDef`,
     `ast.AsyncFunctionDef`, or a top-level `name = <lambda>` assignment. Class
     methods, nested defs, and non-callable assignments are NOT in scope. NEW
     symbols = child top-level callables whose name is NOT a parent top-level
     callable name. (Renames are treated as new — acceptable.)
   - For each NEW symbol name, search for an IN-REPO CALLER across the source set:
     use `discover_modules(repo_root)` to get the non-test/non-seed module list,
     EXCLUDE `('_archive/','_autowork_archive/','samples/','scripts/','tests/',
     'venv/','_autowork_scratch/')` (mirror the `sweep_modules` EXCLUDE plus the
     scratch dir), and also exclude the defining module's OWN definition line for
     that symbol (a symbol that only appears at its own `def` site is uncalled).
     A "caller" exists iff the bare symbol name appears as an `ast.Name`/
     `ast.Attribute` reference (NOT a `def`/`class` name, NOT an import alias
     target) in ANY in-scope source module — OR as the imported name in a
     `from <mod> import <symbol>` followed by any reference. Implement this with
     AST walks over the candidate modules (preferred) or a word-boundary regex
     fallback; either way it is the GENERAL "is this name referenced in source"
     heuristic, NOT a hardcoded set. A reference WITHIN the defining module by
     another (already-present, non-new) function DOES count as a caller (intra-
     module wiring is legitimate).
   - A NEW symbol whose name is in `exempt` goes to `exempted`, never `unwired`.
   - `ok = (len(unwired) == 0)`. Set `reason` to name the unwired symbols or state
     "all new top-level callables are referenced in source (or exempt)".
   - DETERMINISTIC: sort all output lists; identical inputs => identical result.
     PURE: filesystem reads + AST only; no spawn/network/model.

4. GENERALITY: do NOT special-case any module path, symbol name, or task field.
   The check is driven by the AST diff + the in-repo reference search for ANY
   module. Do NOT key it on `state_reconciler` or any fixture string.

ANTI-GAMING ORACLE REQUIREMENT (TASK 2): the impl must make the TASK 1 oracle
GREEN by GENERAL behavior (real AST diff + real source reference search over the
synthetic tree), NOT by detecting the fixture. Re-run the EXACT TASK 1 vcmd plus
the existing wire_up suite before dispatch.

`non_goals` MUST contain the literal word `integration`. `regression_tests >= 2`.

- `task_id: wire-up-symbol-caller-gate-core-impl`
- `priority: high`
- `meta_task_type: harness_self_fix`
- `files_touched: ["harness/wire_up.py"]`
- OMIT `mutation_target` (impl task editing a `harness/**` path).
- `dependencies: ["wire-up-symbol-caller-gate-core-oracle"]` (RED oracle first;
  impl turns it green — red-pair preserved).
- Emit a `__JANUSMASK_PATCHES__` SYMBOL patch (NEW `SymbolWireResult` +
  `check_new_symbols_called`, R-anchored on `check_wired` or `_grep_config`).
- `verification_command:` a SCOPED, non-vacuous pytest selecting the new oracle
  AND a slice of the existing wire_up suite that must stay green, e.g.
  `python -m pytest tests/harness/test_wire_up_symbol_caller_gate.py tests/test_wire_up.py tests/harness/test_wire_up_gate_staging_tree_wired.py -q`
  (do NOT use a broad `pytest tests/adversarial/ -q` vcmd). Run the EXACT vcmd
  yourself before dispatch and confirm `N passed` with N>=2 and that the existing
  wire_up tests are NOT regressed.

## TASK 3 — wire-up-symbol-caller-gate-accept-wiring-impl (harness/orchestrator.py)

TRUST-CORE: `harness/orchestrator.py` is in `_NEVER_AUTO_APPROVE`. This task
REQUIRES an operator decision file
`state/control/decisions/wire-up-symbol-caller-gate-accept-wiring-impl.json` and
`operator_decision_required: true` is set in this brief's frontmatter. Keep the
trust-core surface MINIMAL: only a new flag-reader + a report-only call site +
ledger row. The substantive logic is entirely in `wire_up.py` (TASK 2).

IMPLEMENTATION NOTES (LOAD-BEARING — GENERAL behavior, report-only, default-OFF):

1. PATCH SHAPE: emit a `__JANUSMASK_PATCHES__` SYMBOL patch. TWO symbols change:
   - ADD a NEW top-level `_wire_up_symbol_gate_enabled(state_dir=None) -> bool`
     mirroring `_wire_up_gate_enabled` (line ~2169): read
     `config['autowork']['wire_up_symbol_gate']`, DEFAULT False, swallow all
     exceptions -> False. R-ANCHOR it on the existing `_wire_up_gate_enabled` so
     the new top-level symbol lands.
   - EDIT the EXISTING `_run_wire_up_gate` (line ~2188) to add the report-only
     symbol check on the `_tracked_in_parent(rel)` branch.
   Do NOT emit `__JANUSMASK_MANIFEST__`.

2. In `_run_wire_up_gate`, the existing loop does
   `if _tracked_in_parent(rel): continue`. CHANGE that branch so that, BEFORE
   continuing, IF `_wire_up_symbol_gate_enabled(state_dir)` is True, it runs the
   symbol check (and still `continue`s afterward — the symbol path NEVER rolls
   back, so control always proceeds to the next file / to accept):
     - import the primitive at top of the gate function or module scope:
       `from harness.wire_up import check_new_symbols_called` (mirror the existing
       `check_wired` import usage).
     - fetch the parent source:
       `git show HEAD:<rel>` run via `subprocess.run([... 'git','show',
       f'HEAD:{rel}'], cwd=str(worktree_root), capture_output=True, text=True,
       timeout=30)`; on non-zero rc / exception treat parent_src as `''` (fail-
       soft, never raise).
     - read exempt: `task.get('wire_exempt') or (task.get('constraints') or
       {}).get('wire_exempt') or []` (tolerate a non-list -> `[]`).
     - call `check_new_symbols_called(staging_path, rel, parent_src,
       exempt=exempt)` inside a contained `try/except Exception` (any failure ->
       log a warning, do NOT block).
     - IF the result is not `.ok` (there are unwired new symbols): write a
       REPORT row
       `write_jsonl_row(state_dir / 'impl_progress.jsonl', {'ts': ..., 'phase':
       'report', 'task_id': task_id, 'event': 'orphan_symbol_unwired', 'commit_sha':
       result.get('sha'), 'files': files_touched, 'file': rel, 'symbols':
       result.unwired, 'reason': result.reason})` and
       `logger.warning('orphan_symbol_unwired (report-only): task=%s module=%s new
       uncalled top-level symbols: %s', task_id, rel, result.unwired)`.
       NOTE the local name collision: the gate already binds `result` (the worker
       result dict). Bind the symbol verdict to a DISTINCT name (e.g.
       `sym_result`) and read `sym_result.unwired`/`sym_result.reason`/`sym_result.ok`.
     - Then `continue` (the existing behavior). The symbol path MUST NEVER call
       `_rollback_rejected_commit`, `remove_staging_worktree`, `_mark_blocked`, or
       return True. It is strictly observational.

3. DEFAULT-OFF / NO-REGRESSION: when `wire_up_symbol_gate` is absent or false (the
   default — and the committed config does NOT add the key, that is out of scope),
   `_wire_up_symbol_gate_enabled` returns False and the branch behaves EXACTLY as
   today (`continue`). The existing module-level reject path (new-file branch) is
   BYTE-UNCHANGED. So this task cannot regress prod until the operator adds+flips
   the flag.

4. GENERALITY: do NOT special-case any module/slug/task_id. The branch runs the
   general primitive for every already-tracked `.py` file when the flag is on.

ANTI-GAMING ORACLE REQUIREMENT (TASK 3): the oracle (authored by the
test_authoring sibling for this task — see plan shape; if the planner attaches the
oracle to TASK 1 instead, TASK 3's vcmd still selects the behavioral wiring test)
MUST assert BEHAVIORAL wiring of the gate, NOT a literal:
  - DEFAULT-OFF: with the flag absent/false, call `_run_wire_up_gate` (or a thin
    harness that exercises the already-tracked branch) over a staged module that
    ADDED an uncalled new symbol, and assert NO `orphan_symbol_unwired` ledger row
    is written and the gate returns False (proceed) — strict no-op.
  - ARMED (flag true): same scenario, assert an `orphan_symbol_unwired` row with
    `phase: 'report'` and the unwired symbol name IS written, AND the gate STILL
    returns False (report-only, no rollback) and does NOT mark the task blocked /
    remove the worktree.
  - WIRED SYMBOL ARMED: when the added symbol HAS an in-repo caller, assert NO
    report row is written even with the flag on.
  - The oracle MUST drive the real `_run_wire_up_gate`/`check_new_symbols_called`
    behavior over a synthetic git tree, MUST NOT assert against a frozen ledger
    literal, and MUST NOT special-case a fixture name.
  Because `harness/orchestrator.py` is huge and trust-core, the vcmd MUST be a
  SCOPED selection of the new behavioral test plus a small existing wire-up-gate
  slice — NEVER `pytest tests/adversarial/ -q`.

`non_goals` MUST contain the literal word `integration`. `regression_tests >= 2`.

- `task_id: wire-up-symbol-caller-gate-accept-wiring-impl`
- `priority: high`
- `meta_task_type: harness_self_fix`
- `files_touched: ["harness/orchestrator.py"]`
- OMIT `mutation_target` (impl task editing a `harness/**` path).
- `dependencies: ["wire-up-symbol-caller-gate-core-impl"]` (the primitive must
  exist before the gate can import it).
- Emit a `__JANUSMASK_PATCHES__` SYMBOL patch (NEW `_wire_up_symbol_gate_enabled`
  R-anchored on `_wire_up_gate_enabled` + the EDIT to `_run_wire_up_gate`).
- REQUIRES operator decision file
  `state/control/decisions/wire-up-symbol-caller-gate-accept-wiring-impl.json`
  (orchestrator.py is `_NEVER_AUTO_APPROVE`).
- `verification_command:` a SCOPED, non-vacuous pytest selecting the new behavioral
  wiring test AND the existing accept-gate slice that must stay green, e.g.
  `python -m pytest tests/harness/test_wire_up_symbol_gate_accept_wiring.py tests/harness/test_wire_up_accept_gate.py tests/harness/test_wire_up_gate_staging_tree_wired.py -q`
  (do NOT use a broad `pytest tests/adversarial/ -q` vcmd — non-hermetic, flaky-
  blocks). Run the EXACT vcmd yourself before dispatch and confirm `N passed` with
  N>=2 and that the existing accept-gate tests are NOT regressed.

# Required plan shape
Emit EXACTLY THREE tasks (pin via `required_task_ids: [
wire-up-symbol-caller-gate-core-oracle, wire-up-symbol-caller-gate-core-impl,
wire-up-symbol-caller-gate-accept-wiring-impl]`). PRIORITY MUST be canonical
lowercase (`high`), NEVER P0/P1/ints/Capitalized.
  - TASK 1 is `test_authoring` (writes the RED oracle for the wire_up primitive;
    carries `mutation_target: harness/wire_up.py`, MODULE dotted path only).
  - TASK 2 is `harness_self_fix` (writes `harness/wire_up.py`, OMITS
    `mutation_target`; depends on TASK 1).
  - TASK 3 is `harness_self_fix` (writes `harness/orchestrator.py`, OMITS
    `mutation_target`; depends on TASK 2). It is TRUST-CORE
    (`_NEVER_AUTO_APPROVE`) and REQUIRES the operator decision file named above.
Each task emits a `__JANUSMASK_PATCHES__` SYMBOL patch (NOT a manifest). Each
task's `non_goals` MUST contain the literal word `integration`; each
`regression_tests >= 2`. Do NOT add any task touching a file other than the one
its `files_touched` declares; do NOT add a task editing `autowork_daemon.py`,
`orchestrator_worker.py`, `config.yaml`, or `state_reconciler.py`.

`harness/wire_up.py` is NOT in the irreducible `_NEVER_AUTO_APPROVE` set
(`harness/agent_jail.py`, `harness/dbus_proxy.py`, `harness/paths.py`,
`harness/git_integration.py`, `harness/orchestrator.py`, `harness/interceptors.py`,
`harness/selfheal.py`, `harness/autowork_daemon.py`, `services/**`), so TASK 2 is
auto-approve-eligible. `harness/orchestrator.py` IS in `_NEVER_AUTO_APPROVE`, so
TASK 3 requires the operator decision file.
