---
epic: true
---

<!--
# STATUS: ✅ BUILT (2026-06-09) — all 5 leaves pipeline-built + merged to master, 0 new regressions.
Operator authorized build this session. Its record is plan_wire_up_phase_epic.json.
Driven via manual pipeline (planner-bypass: hand plan -> normalize_plan oracle-inject ->
stage_task -> orchestrator_worker), one leaf per task, gate otherwise paused.

BUILT leaves + SHAs (module commits by the worker; oracles committed RED-first at f7b9d16):
  - harness/wire_up.py (check_wired/WireResult/LIVE_ROOTS)        6ac2850  [leaf wire-up-primitive]
  - overseer/gates.py::wired                                      1e27cbe  [leaf wired-gate-fn]
  - overseer/procedure.py WIRE_UP phase (VERIFY->WIRE_UP->RESTORE) ad73ed7 [leaf wire-up-fsm-phase]
  - harness/planner/plan_validator.py missing_wiring_oracle       615c2b2  [leaf wiring-oracle-plan-validation]
  - harness/orchestrator.py _auto_commit_accepted gate (default-OFF
    autowork.wire_up_gate; import+_wire_up_gate_enabled+_run_wire_up_gate) 7964681 [leaf wire-up-accept-gate]
  - regression fix (dispatch phase-order test) + provenance       d801127

TRAP AVOIDED (proven): leaf 2 added `from harness.wire_up import check_wired` to
orchestrator.py, so the DOGFOOD passes — check_wired('harness/wire_up.py') -> wired=True via
harness/orchestrator.py; excluding that importer -> wired=False (no self-laundering). The 3
protected harness/** writes used meta_task_type=harness_self_fix + operator decision files.

ORACLES GREEN (22/22): tests/harness/test_wire_up.py + test_wire_up_accept_gate.py (edge-asserting,
drives real _auto_commit_accepted over temp git), tests/overseer/test_wired_gate.py +
test_wire_up_phase.py, tests/planner/test_missing_wiring_oracle.py. 0 NEW regressions
(pre-existing baseline: test_brief_loader sha256 + 4 test_orchestrator prepare_task_prompt fails).

OPEN (noted, not built): the FSM `wired` gate is defined (gates.py) and the WIRE_UP phase binds
it, but overseer/gate_runner.py has no `wired` label dispatch yet, so the overseer FSM does not
auto-run the gate at runtime (no committed oracle required it). The AUTONOMOUS accept-path gate
(leaf 2) IS fully live behind the default-OFF flag. Flip autowork.wire_up_gate ON only after the
dogfood acceptance (done) + owner sign-off.
-->

# Title

JanusMaskJR — Wire-Up Phase. Close the pipeline's deepest defect: a leaf passes its own
ISOLATED oracle (unit-green), commits, and is marked DONE while **zero live (non-test) code
imports or calls the module it built** — an ORPHAN. "IMPLEMENTATION ≠ WIRED." Confirmed orphans
to date: `agy_pool.py`, the procedure-gates FSM (pre-P6), the `claude-tmux` backend. This epic
makes WIRING a CHECKED, HARD-BLOCKING property: a new module cannot merge to the real branch,
and a build cannot reach DONE, until a live importer is proven to exist. As with every JanusMask
gate, this is enforced by WITHHOLDING and CHECKING — a pure, testable reachability function on
the accept path and a new FSM phase — never by a longer prompt the worker may ignore. YOU (the
planner) decide how to decompose this into leaves; a non-binding suggested grouping is at the end.

# Scope

The defect is structural, not incidental. The pipeline decomposes a goal into leaves; the
orphan class in our own post-mortems is *"the wiring leaf was never authored"* — decomposition
yields a `[build module X]` leaf and an implicit `[wire X into the live path]` step that no leaf
owns, so X lands unit-green and unreachable. The ONLY post-apply verification today is the leaf's
isolated oracle plus the mutation gate, both of which a standalone module passes while orphaned.
There is no reachability or importer check anywhere in `harness/` (grep-confirmed).

The cure is three DETERMINISTIC enforcement layers, earliest-catch to latest, each a pure
checkable gate, each shippable behind a default-OFF flag:

1. **Reachability gate (accept-time, the load-bearing piece).** At the single convergent accept
   chokepoint, after a candidate's own oracle and the mutation gate are green but BEFORE the
   commit merges to the real branch, statically verify that some LIVE (non-test, non-oracle)
   module reaches the new module. If none does, REJECT exactly as a failed mutation gate is
   rejected: roll back the staging commit, remove the worktree, route the task to `blocked/`.

2. **Plan-validation requirement (pre-spawn).** A leaf that creates a NEW module must declare a
   *wiring oracle* — a test that imports a LIVE entrypoint (not the leaf, not under `tests/`) and
   asserts the live code now reaches the new module. A new-module leaf lacking one is rejected
   before a worker is ever dispatched.

3. **WIRE_UP FSM phase (interactive/overseer path).** A new phase in the `dispatch` procedure,
   inserted between VERIFY and RESTORE, holds the lattice so RESTORE (whose pass yields the
   terminal `Complete`, i.e. DONE) is unreachable until the wiring gate passes — and the computed
   next action surfaces every turn like every other phase.

Each is independently valuable; layer 1 alone closes the autonomous-pipeline hole. They are
belt-and-suspenders, not alternatives.

# Inputs

The new leaves consume fixed inputs they may NOT rebuild:
1. The reachability primitive `harness/rebuild/discover.py` (ALREADY BUILT — see below): its
   `discover_modules` and `module_import_graph` are the engine; the new check WRAPS them.
2. The single accept chokepoint `harness/orchestrator.py::_auto_commit_accepted` and its existing
   rejection machinery (`_rollback_rejected_commit`, `git_integration.remove_staging_worktree`,
   `_mark_blocked`) — the new gate is inserted beside the mutation gate and REUSES this machinery.
3. The overseer procedure substrate (`overseer/procedure.py`, `overseer/gates.py`,
   `overseer/gate_runner.py`) — the FSM the WIRE_UP phase extends, by name, additively.
4. The plan validator `harness/planner/plan_validator.py` — the wiring-oracle requirement is added
   beside the existing per-task checks, not a reimplementation.

# ALREADY BUILT — do NOT rebuild; these are DONE inputs the new leaves import / edit

Treat as fixed seams (signatures verified at HEAD 2026-06-09):

- `harness/rebuild/discover.py` — `discover_modules(source_root: Path) -> (modules, tests, seeds)`
  partitions the tree into non-test / test / seed module lists; `module_import_graph(source_root,
  modules) -> dict[str, set[str]]` AST-walks the FULL tree (so it catches FUNCTION-LOCAL imports,
  which is how most wiring in this repo actually works) returning `{module_rel -> set(intra-project
  modules it imports)}`. Trusted: `order_modules`, `rebuild/loop.py`, `rebuild/harvest.py` use it.
  THE NEW CHECK BUILDS ON THESE — it does not re-parse imports.
- `harness/orchestrator.py::_auto_commit_accepted(state_dir, task, task_id) -> bool` — the single
  convergent accept chokepoint (all four accept paths funnel here). Inside it, in order: apply
  candidate into an isolated staging worktree → run the leaf's oracle/`verification_command` →
  mutation gate → **(insertion point)** → `git_integration.merge_staging_to_parent(...)` →
  `_mark_processed`. The mutation-gate failure arm (`_rollback_rejected_commit(staging_path,
  result.get('sha'), target_rel, task_id, <reason>)` + `remove_staging_worktree(...)` +
  `return False`) and the merge-failure arm (`_mark_blocked(state_dir, task_id,
  outcome='merge_failed')` + `return False`) are the EXACT templates the wire-up rejection copies.
- `overseer/procedure.py` — `Phase(name, gate, next_action)`, `Procedure(mode, phases)`,
  `PROCEDURE_REGISTRY` (dispatch = `PREFLIGHT → STAGE → BUILD → VERIFY → RESTORE`), and the pure
  reducer `advance(procedure, phase, gate_result) -> Decision` (next phase | `Blocked` | `Complete`).
- `overseer/gates.py` — `GateResult(ok: bool, reason: str, fix_hint: str)` and the pure gate
  functions; THIS is where the new `wired(...)` gate function plugs in.
- `overseer/gate_runner.py` — `_run_gate(label, arts, attested, sd) -> GateResult` (the label→gate
  dispatch) and `gate_label_for(mode, phase)`; THIS is where the `wired` label is mapped.
- `harness/planner/plan_validator.py` — the per-task plan checks; the `missing_wiring_oracle`
  violation plugs in beside them.

# The wiring model (what "wired" means and how it is checked)

A module is WIRED iff some LIVE module reaches it. "Live" = on the import-reachability frontier
from the system's real entrypoints, excluding test and oracle files. The check is a BFS:

- **Roots** are the real entrypoints (top-level modules with inbound-import-degree 0 BY DESIGN, so
  they must be SEEDED, never flagged): `orchestrator`, `orchestrator_worker`, `autowork_daemon`,
  `planner.cli`, the claude/gemini hook entrypoints, `webui_control`, the `overseer`/`services`
  entrypoints. The root set is a declared constant the check consumes.
- **Reachable set** = BFS over `module_import_graph` from the roots, NEVER traversing into a
  test/oracle module.
- **Wired?** = the new module is imported by at least one module in the reachable set, AFTER
  EXCLUDING THE MODULE'S OWN ORACLE from the importer set. (Excluding the own-oracle is the single
  most important rule: otherwise the test that proves the contract launders the module as "wired.")
- **Hard signal** = zero live importers ⇒ ORPHAN ⇒ reject. Deterministic, zero false-negatives for
  the dominant orphan class.
- **Soft signal** = "imported but never called" is a WARN only (static call resolution is
  approximate; do not hard-block on it).
- **Dynamic-wiring supplement** = wiring registered by NAME in config (`config/**` entrypoint
  strings, hook tables — how the `claude-tmux` orphan was wired) is invisible to a static import
  graph. The check MUST also grep `config/**` for the module/symbol before declaring ORPHAN. State
  this limit loudly; even the grep cannot see wiring expressed in data the runtime resolves
  reflectively.

NOTE on the codebase-memory-mcp graph: it is indexed and richer, but was EMPIRICALLY shown to
produce both false positives (IMPORTS edges target the imported symbol, not the module node) and
false negatives (misses function-local wiring). It is ADVISORY enrichment for the failure report
ONLY — never the gate. The in-process AST check is authoritative.

# THE TRAP — and how every leaf avoids it (READ BEFORE AUTHORING ANY WIRING LEAF)

The wire-up machinery is recursive: the reachability check and its call sites are themselves new
code that GETS CALLED BY the accept path — exactly the kind of thing that lands orphaned — and at
the moment they are built, there is no live wire-up gate yet to catch them being orphaned. You
CANNOT bootstrap-verify the verifier with itself. The trap is avoided by construction, not by hope:

1. **Never split "create module" from "wire it up" across an unowned boundary.** Every leaf that
   adds a CALL SITE (the accept-path call, the gate_runner dispatch branch, the FSM phase) owns
   BOTH the code and the edge that connects it, in one leaf, proven by that leaf's oracle.

2. **Wiring leaves ship an EDGE-ASSERTING oracle, not an isolated unit test.** It is not enough to
   test `check_wired(orphan) == fail` — that proves the function works and proves NOTHING about
   wiring (and the function is excluded from its own importer set anyway). The oracle must DRIVE
   THE LIVE PATH and assert the edge fired. Canonical shape for the accept-path leaf:
   ```python
   def test_accept_path_invokes_wire_up_gate_and_blocks_orphan(monkeypatch):
       called = {}
       real = orchestrator.check_wired
       monkeypatch.setattr(orchestrator, "check_wired",
                           lambda *a, **k: called.setdefault("hit", True) or real(*a, **k))
       result = orchestrator._auto_commit_accepted(state_dir, <orphan-candidate task>, tid)
       assert called.get("hit")     # the LIVE accept path actually called the gate
       assert result is False        # and the orphan was rolled back / blocked (not merged)
   # plus the converse: a WIRED candidate proceeds to merge and returns True.
   ```
   If a worker lands the call-site module but forgets the call, `called["hit"]` is never set and
   the oracle is RED. The wiring oracle catches its own author.

3. **The substrate primitive is the ONE allowed isolated-oracle leaf — and it is rendered safe by
   leaf 2 + the dogfood bootstrap, not left to chance.** `harness/wire_up.py` (the pure
   `check_wired` primitive) is a single-file whole-file NEW module; its oracle legitimately tests
   the pure function in isolation (orphan→fail, wired→pass, own-oracle-excluded, BFS-from-roots).
   It is born importable but not yet CALLED. Its reachability is established by the accept-path
   leaf's edge-asserting oracle (rule 2) AND by the dogfood acceptance (rule 4). DO NOT add the
   accept-path call in this same leaf — a NEW-file + EXISTING-file edit in one leaf trips
   `auto_commit_failed` (the patches path cannot create files). Keep new-module and call-site in
   SEPARATE, dependency-CHAINED leaves: the call-site leaf `dependencies` MUST list the primitive
   leaf, so it can never be dispatched or marked DONE without the primitive present.

4. **Dogfood the gate against its own modules as a MANDATORY manual acceptance, once.** After the
   accept-path leaf merges, run the gate on its own outputs: `check_wired(repo_root,
   "harness/wire_up.py")` MUST return WIRED (importer = `orchestrator`). If it returns ORPHAN, the
   tool has caught itself — the cleanest possible acceptance signal. This is the single hand-
   verified bottom; everything after it is self-sustaining (once layer 1 is live, every subsequent
   leaf — INCLUDING any future edit to the wire-up modules themselves — is checked by the now-live
   gate).

5. **The flag stays OFF until the dogfood passes.** Layer 1 lands behind `autowork.wire_up_gate`
   (default-OFF). Flipping it ON is gated on the dogfood acceptance, not on the oracle alone.

# Correctness regimes (the build boundary)

DETERMINISTIC logic — the `check_wired` reachability primitive, the `wired` gate function, the
phase-registry entry, the plan-validator violation — is fully JM-rebuildable and MUST be
pure/stdlib-only over INJECTED seams (the root set as a parameter/constant, the import graph via
`discover`, plain filesystem reads). It NEVER spawns a process, makes a model/API/network call, or
shells out un-injected. The INTEGRATION edits (`_auto_commit_accepted`, `gate_runner._run_gate`,
`procedure.py` registry, `plan_validator`) modify EXISTING symbols ADDITIVELY behind the
default-OFF flag and must preserve every current behaviour and passing test.

THE CARDINAL PROJECT RULE this epic encodes and must never violate: NEVER hand-edit production
outside the pipeline. The wire-up gate exists to make the WIRED path the only reachable path — it
would be self-parody to land an orphaned orphan-checker by hand-editing it in.

# Per-leaf contract (oracle-first)

Each leaf's `verification_command` MUST name its own pre-committed RED oracle as
`python -m pytest tests/<area>/<oracle>.py -q`. Those oracles are HAND-AUTHORED + committed BEFORE
any leaf is dispatched (the next gated step after this digestion). NEW modules are single-file
whole-file emissions; integration leaves are EXISTING-symbol edits to ONE file each (do NOT bundle
multiple files into one leaf — multi-file emission is fragile here). **Every leaf that adds a call
site ships an EDGE-ASSERTING oracle per THE TRAP rule 2; only the substrate primitive leaf may use
an isolated oracle.**

# Suggested decomposition (NON-BINDING — you decide the final tree)

Substrate (NEW, deterministic, stdlib-only, single-file whole-file; ISOLATED oracle allowed):
- `harness/wire_up.py` → `tests/harness/test_wire_up.py`. The reachability primitive
  `check_wired(repo_root, new_module_rel, *, roots=LIVE_ROOTS, exclude=()) -> WireResult(wired:
  bool, importers: list[str], reason: str, fix_hint: str)`: build the import graph via
  `discover.module_import_graph`, BFS from `roots` skipping test/oracle modules, exclude the
  module's own oracle from the importer set, hard-fail on zero live importers, soft-warn on
  imported-but-uncalled, plus a `config/**` grep supplement. `LIVE_ROOTS` declared here. Oracle:
  orphan→not-wired, live-importer→wired, own-oracle-excluded, root-seeded (roots not flagged).

Wiring / integration (EDIT existing symbols, one file per leaf — TRAP-PRONE; EDGE-ASSERTING oracles):
- EDIT `harness/orchestrator.py::_auto_commit_accepted` → `tests/harness/test_wire_up_accept_gate.py`.
  Insert the gate at the post-mutation / pre-merge point: when the candidate created a NEW module
  and the `autowork.wire_up_gate` flag is ON, call `wire_up.check_wired`; on ORPHAN reuse
  `_rollback_rejected_commit` + `remove_staging_worktree` + `_mark_blocked(outcome=
  'orphan_unwired')` + `return False`, emitting via the existing `_emit_gate_failure`/ledger
  pattern; on WIRED proceed to merge unchanged. `dependencies: [wire-up-primitive]`. EDGE-ASSERTING
  oracle (rule 2): spy on `check_wired`, drive `_auto_commit_accepted` with an orphan candidate,
  assert the spy fired AND the orphan was blocked; converse for a wired candidate.
- EDIT `overseer/gates.py` (+ `overseer/gate_runner.py`) → `tests/overseer/test_wired_gate.py`.
  Add the pure `wired(report) -> GateResult` (zero `live_importers` ⇒ not-ok) to `gates.py` and a
  `wired` branch to `gate_runner._run_gate` mapping the label to it over the importer-count seam.
  Oracle asserts `gate_runner` DISPATCHES the `wired` label to `gates.wired` (the wiring edge), not
  just that `wired()` works in isolation.
- EDIT `overseer/procedure.py` → `tests/overseer/test_wire_up_phase.py`. Insert a `WIRE_UP` phase
  (gate name `wired`, a next-action string) into `PROCEDURE_REGISTRY['dispatch']` BETWEEN `VERIFY`
  and `RESTORE`. Oracle asserts the registry contains WIRE_UP ordered before RESTORE AND that
  `advance` returns `Blocked` on a zero-importer `wired` GateResult (so DONE is unreachable while
  orphaned) — wiring assertion on the FSM, not an isolated dataclass test.

Plan-validation (EDIT existing symbol, one file):
- EDIT `harness/planner/plan_validator.py` → `tests/planner/test_missing_wiring_oracle.py`. Add a
  `missing_wiring_oracle` violation: a `test_authoring`/new-module leaf whose declared tests
  contain no wiring oracle (an `_is_wiring_oracle` classifier: imports a live entrypoint that is
  NOT the leaf and NOT under `tests/`, carries a `test_*_wired`/`registers`/`invokes` marker, does
  NOT mock the seam) is rejected pre-spawn. Oracle asserts a new-module leaf without a wiring test
  is rejected and one with it passes.

# Bootstrap dogfood acceptance (MANDATORY, manual, once)

After the accept-path leaf merges and before `autowork.wire_up_gate` is flipped ON: run
`check_wired(repo_root, "harness/wire_up.py")` and confirm WIRED (importer = `orchestrator`); run
it against a known orphan fixture and confirm ORPHAN. Record the result. Only then is the flag
eligible to be flipped (owner sign-off).

# Deliverables

A decomposed leaf tree (one `brief_hooks_<slug>.md` per leaf at repo root) plus an epic plan
record, covering: the reachability substrate (`harness/wire_up.py`), the accept-time gate (edit to
`_auto_commit_accepted`, flag-gated), the FSM phase (the `wired` gate in `gates.py`/`gate_runner.py`
+ the WIRE_UP phase in `procedure.py`), and the plan-validation requirement (edit to
`plan_validator.py`). Each leaf names its own pre-committed RED oracle as its `verification_command`;
every call-site leaf ships an EDGE-ASSERTING oracle. The end state: a NEW module cannot merge to the
real branch while orphaned, a `dispatch` build cannot reach DONE until the wiring gate passes, and a
new-module leaf without a wiring oracle is rejected at plan time — all behind a default-OFF flag
whose flip is gated on the dogfood acceptance. This epic delivers the DECOMPOSITION ONLY — no oracle
is authored and no leaf is built or dispatched here.

# Non-Goals

No new agent spawns, model/API/network/SSE calls, or un-injected subprocesses in the deterministic
leaves — the import graph, root set, and filesystem reads flow through injected seams so the oracles
drive them hermetically. No reimplementation of `discover.module_import_graph` or
`plan_validator` — wrap/extend them. The wire-up gate proves REACHABILITY, not USEFULNESS: a leaf
can still satisfy it with a trivial inert importer; code review and the mutation gate remain the
backstop for "wired but inert" (state this; do not pretend coverage). The codebase-memory-mcp graph
is advisory only, never the gate. Dynamically/reflectively-registered wiring beyond the `config/**`
grep is a stated blind spot, not silently covered. INTEGRATION leaves preserve all existing
behaviour and tests and stay behind the default-OFF `autowork.wire_up_gate` flag. This epic is
DECOMPOSITION ONLY: it authors no oracle and dispatches no build; the owner gate stays paused.
