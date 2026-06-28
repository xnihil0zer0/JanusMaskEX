---
working_dir: "/home/xnihil0zer0/AI-Data/JanusMaskEX"
operator_decision_required: true
auto_approve_requested: true
required_task_ids:
  - wire-up-contract-runtime-hardening-oracle
  - wire-up-contract-runtime-hardening-primitive
  - wire-up-contract-runtime-hardening-wiring
interfaces: >
  HARDENING of the PHASE-3 runtime-reachability wire-up ENFORCE gate. The
  enforce arm (landed: orchestrator.py `_run_wire_up_gate`, knob
  `wire_up_runtime_gate_enforce`) suppresses a reject when `_contract_valid`
  holds — but `_contract_valid` is a STATIC declared-contract check
  (`bool(entrypoints) and all(ep in LIVE_ROOTS) and bool(runtime_oracle)`). It
  never invokes PHASE-1's `observe_symbol_execution.executed_from_live_root`, so
  a LYING contract (entrypoints in LIVE_ROOTS + a fake/no-op runtime_oracle that
  never exercises the symbol) is falsely SUPPRESSED and the orphan symbol escapes
  the enforce reject. This hardening makes per-symbol SUPPRESSION require B's
  ACTUAL runtime observation that the symbol executed from a LIVE_ROOT, not merely
  a declared oracle. Fail-safe posture preserved: knobs default-OFF => byte-
  identical behavior; the REPORT path never rejects; only the SUPPRESSION criterion
  tightens (declared-only -> requires real observation, fail-CLOSED on no
  observation).

  THREE tasks. A single task may emit only ONE sidecar channel
  (`__JANUSMASK_PATCHES__` OR `__JANUSMASK_MANIFEST__`), and the two production
  files are BOTH `.py`, so each impl edits ONE file via a `__JANUSMASK_PATCHES__`
  SYMBOL patch (per the repo lesson: split multi-file harness edits into one task
  per `.py`):

  (1) wire-up-contract-runtime-hardening-oracle (test_authoring ->
      tests/harness/test_wire_up_contract_runtime_hardening.py): a RED behavioral
      oracle that drives the REAL `_run_wire_up_gate` over a synthetic git tree and
      asserts, under enforce, that a LYING contract (valid-looking entrypoints +
      runtime_oracle but the oracle never observes the symbol from a LIVE_ROOT) is
      NO LONGER suppressed (=> reject), while an HONEST contract (the oracle IS
      observed to execute the symbol from a LIVE_ROOT) IS suppressed (=> proceed).
      mutation_target: harness.orchestrator.

  (2) wire-up-contract-runtime-hardening-primitive (harness_self_fix ->
      harness/wire_up.py ONLY): add a pure helper that, given a runtime_oracle
      path + the declared symbols + a repo_root, runs the oracle in a BOUNDED child
      process under `observe_symbol_execution` and returns the set of symbols
      OBSERVED to have executed from a LIVE_ROOT (empty on any error/timeout — the
      observation is POSITIVE evidence, never absence-of-failure). Submitted via a
      `__JANUSMASK_PATCHES__` SYMBOL patch.

  (3) wire-up-contract-runtime-hardening-wiring (harness_self_fix ->
      harness/orchestrator.py ONLY, TRUST-CORE in _NEVER_AUTO_APPROVE — REQUIRES an
      operator decision file): change the `_run_wire_up_gate` enforce-arm
      SUPPRESSION criterion so a symbol is treated as covered ONLY when the static
      contract is valid AND the new primitive observed that symbol executing from a
      LIVE_ROOT. Report-only/shadow and default-OFF behavior unchanged. Submitted
      via a `__JANUSMASK_PATCHES__` SYMBOL patch.
---

# Title
HARDEN the runtime-reachability ENFORCE gate's suppression: require PHASE-1's
ACTUAL `observe_symbol_execution.executed_from_live_root` observation before
suppressing a reject — a declared-but-lying `integration_contract` (valid
entrypoints + a fake/no-op `runtime_oracle` that never exercises the symbol) must
NO LONGER suppress the enforce reject. Fail-safe and fail-CLOSED: knobs default-OFF
=> byte-identical behavior; the report path never rejects; only the SUPPRESSION
criterion tightens (declared-only -> requires real observation).

# Scope
THREE tasks. READ each file first. This hardening DEPENDS on the landed PHASE-1
primitive (`harness/wire_up.py`: `observe_symbol_execution`,
`executed_from_live_root`, `new_top_level_callables`, `LIVE_ROOTS`) and the landed
PHASE-3 enforce arm (`harness/orchestrator.py`: `_run_wire_up_gate`,
`_wire_up_runtime_gate_enforce_enabled`, and the `_contract_valid`/`uncovered`
computation). It does NOT re-author the AST-diff primitive, the report row, the
enforce reject path, or the two committed config knobs (`wire_up_runtime_gate` /
`wire_up_runtime_gate_enforce`, both already `false` in `harness/config.yaml`).

The change is SPLIT across THREE tasks because a single task emits only ONE sidecar
channel and the two production files are distinct `.py` modules: the wire_up.py
primitive and the orchestrator.py wiring are SEPARATE `__JANUSMASK_PATCHES__` SYMBOL
patches (combining two files in one task forces an infeasible whole-file
`__JANUSMASK_MANIFEST__` of the 4400+-line orchestrator.py).

1. `wire-up-contract-runtime-hardening-oracle` (test_authoring) authors a RED
   behavioral oracle in `tests/harness/test_wire_up_contract_runtime_hardening.py`
   that drives the real `_run_wire_up_gate` over a synthetic git tree and pins:
   under enforce, a LYING contract is REJECTED (no longer suppressed) and an HONEST
   (observed-from-live-root) contract is SUPPRESSED (proceeds). NO production edit.

2. `wire-up-contract-runtime-hardening-primitive` (harness_self_fix) edits ONLY
   `harness/wire_up.py`, adding the bounded-child observation helper, via a
   `__JANUSMASK_PATCHES__` SYMBOL patch. `harness/wire_up.py` is NOT in
   `_NEVER_AUTO_APPROVE`, so this task is auto-approve-eligible and needs no
   operator decision file.

3. `wire-up-contract-runtime-hardening-wiring` (harness_self_fix) edits ONLY
   `harness/orchestrator.py` (the enforce-arm suppression criterion), via a
   `__JANUSMASK_PATCHES__` SYMBOL patch. `harness/orchestrator.py` IS in
   `_NEVER_AUTO_APPROVE` (irreducible TRUST-CORE), so THIS is the only task that
   REQUIRES an operator decision file
   `state/control/decisions/wire-up-contract-runtime-hardening-wiring.json`, and
   `operator_decision_required: true` is set in this brief's frontmatter.

# The gap, line-cited
- `_run_wire_up_gate(...)` — def `harness/orchestrator.py:2233`. Runs at the accept
  chokepoint (call site `harness/orchestrator.py:3178`), AFTER the verification
  command and the mutation gate, BEFORE the staging->parent merge.
- The PHASE-2/3 symbol-addition branch (behind `_wire_up_runtime_gate_enabled`,
  lines ~2281-2333) computes, at `harness/orchestrator.py:2309`:
  ```python
  _contract_valid = bool(_entrypoints) and all((_ep in _live for _ep in _entrypoints)) and bool(_oracle)
  ```
  and at `harness/orchestrator.py:2315`:
  ```python
  uncovered = sorted((_s for _s in new_syms if _s not in _exempt and (not (_contract_valid and _s in _csymbols))))
  ```
  A symbol is therefore SUPPRESSED (dropped from `uncovered` => no reject under
  enforce, `harness/orchestrator.py:2316-2326`) whenever the contract merely
  DECLARES it: `entrypoints` are a subset of LIVE_ROOTS, the symbol is named in
  `symbols`, and ANY non-empty `runtime_oracle` string is present. The
  `runtime_oracle` is NEVER run; `observe_symbol_execution` /
  `executed_from_live_root` (PHASE-1, `harness/wire_up.py:361-466`) are used ONLY in
  tests today and never invoked at gate time. So a task declaring
  `{'entrypoints': ['harness/orchestrator.py'], 'symbols': ['brand_new'],
  'runtime_oracle': 'tests/harness/test_noop.py'}` where the oracle never calls
  `brand_new` from a live root is FALSELY suppressed — the orphan escapes the
  enforce reject.

# Feasibility — why a BOUNDED CHILD that emits POSITIVE observation evidence, not an in-process run
The verification command runs as a JAILED bash SUBPROCESS
(`harness/orchestrator.py:2991`/`:2997`), capturing only exit/stdout/stderr — the
symbol executes in a SEPARATE process, so the orchestrator's in-process
`observe_symbol_execution` (`sys.settrace`) cannot have observed it during
verification, and NO observation evidence is recorded anywhere (verified: the
primitive is referenced only in `harness/wire_up.py` + tests). The gate therefore
cannot "check recorded evidence" — there is none to check.

Two ways to obtain real observation at gate time were weighed:
- (A) run the oracle IN-PROCESS in the orchestrator under
  `observe_symbol_execution`. REJECTED: it imports arbitrary oracle code into the
  TRUST-CORE accept chokepoint and clobbers `sys.settrace` in a hot path — a real
  trust regression and a side-effect/timeout hazard.
- (B) run the oracle in a BOUNDED, JAILED CHILD PROCESS that wraps it in
  `observe_symbol_execution`, and have that child print the set of symbols observed
  to have executed from a LIVE_ROOT; the gate parses that set and uses it as
  POSITIVE evidence. CHOSEN: it isolates oracle execution out of the trust-core
  process, is bounded by a wall-clock timeout, runs the attacker-influenced oracle
  inside the SAME bubblewrap jail the verification command already uses, and the
  gate's only new logic is a set-membership check. The orchestrator trust-core
  surface stays MINIMAL.

# JAIL PARITY (load-bearing security requirement)
The `runtime_oracle` is ATTACKER-INFLUENCED: the wire-up gate exists precisely to
catch a leaf that is GAMING wiring, so the very code whose oracle we re-run is the
code we distrust. Re-running it as a plain UNJAILED subprocess would be a
credential-theft / privilege-escalation vector — this repo has a PROVEN host-cred-read
hazard from unjailed generated-code execution (a candidate can read host
`~/.gemini` / `~/.claude` credentials). The oracle child MUST therefore be JAILED
with PARITY to how the verification command (vcmd) is jailed today:
- The vcmd is launched at `harness/orchestrator.py:2991` via
  `subprocess.run(agent_jail.build_jail_argv([...], repo_root=worktree_root,
  work_dir=staging_path, state_dir=state_dir, extra_ro=[sys.base_prefix, sys.prefix]
  + list(verify_extra_ro) + _ext_venv_ro, extra_rw=list(verify_extra_rw),
  dbus_proxy_socket=_sock, bind_credentials=False), cwd=str(staging_path), ...,
  env=_venv_jail_env())` — gated behind `agent_jail.sandbox_enabled(load_config())`.
  `bind_credentials=False` is the PROVEN seam that DROPS the `~/.gemini` / `~/.claude`
  credential binds AND adds `--unshare-net --unshare-ipc` (no off-host exfil).
- The oracle re-run MUST MIRROR THIS EXACTLY: `agent_jail.build_jail_argv(...,
  bind_credentials=False)`, repo/work rooted at `staging_path` (so the just-committed
  child module AND the staged LIVE_ROOT files resolve), the SAME `extra_ro` venv/base
  binds and the SAME `env=_venv_jail_env()` so pytest + deps resolve inside the jail,
  fail-CLOSED to an EMPTY observed set on any jail-build / exec / timeout / parse
  failure. Inside the jail a small runner imports `observe_symbol_execution` /
  `executed_from_live_root` / `LIVE_ROOTS` from the STAGED `harness.wire_up`, runs the
  declared `runtime_oracle` under observation, and emits the observed-symbol set as a
  single JSON line on stdout; the parent parses that line.

# STAGING-TREE PATH/MOUNT RESOLUTION (the #1 FALSE-POSITIVE risk — get this right)
The jail makes the symbol the gate is judging EXECUTABLE-AND-OBSERVABLE from a live
root for an HONEST oracle ONLY IF the staging tree is the import + mount root:
- The jail's `repo_root`/`work_dir`/`cwd` resolve to `staging_path`, the tree where
  the just-committed child module, the declared `runtime_oracle` file, AND the
  LIVE_ROOT files (`harness/orchestrator.py`, ...) all live, so (a) the child imports
  the STAGED `harness.wire_up` (not the parent/installed copy), (b) the oracle drives
  the STAGED symbol, and (c) `executed_from_live_root` matches the IMMEDIATE caller's
  `co_filename` against `LIVE_ROOTS` resolved INSIDE the staging tree. A mismatch here
  silently fails-closed and FALSE-REJECTS an HONEST leaf.
- PYTHONPATH / cwd must put `staging_path` first on the import path so the staged
  package wins; mirror the vcmd's `cwd=str(staging_path)` + `env=_venv_jail_env()`
  rather than inventing a new env. If `agent_jail.sandbox_enabled(...)` is False (no
  sandbox configured), the oracle re-run does NOT silently run unjailed — match the
  vcmd's posture (fail-closed: no jail => no positive observation => no suppression),
  it must NEVER fall back to a plain unjailed `subprocess.run`.
- THIS is the key false-positive risk the implementer and the backtest must stress:
  an HONEST oracle that genuinely drives the symbol from a live root must be able to
  IMPORT the staged harness and BE OBSERVED; otherwise honest oracles silently
  fail-closed and the enforce gate FALSE-REJECTS real, correctly-wired work.

The fail-closed rule is the load-bearing anti-gaming property: the helper returns
the OBSERVED-from-live-root set, EMPTY on any error/timeout/parse failure. A symbol
is suppressed ONLY if it is positively in that set. A lying/no-op/erroring oracle
yields no positive observation => the symbol stays in `uncovered` => rejected under
enforce. Absence of failure never suppresses; only a real observation does.

# False-positive guard (legit work must still be suppressed)
A genuinely-wired symbol is suppressed because its DECLARED `runtime_oracle` (a
pytest path, e.g. `tests/harness/test_brand_new_runtime.py`) really drives a
LIVE_ROOT entrypoint such that the symbol's IMMEDIATE caller resides in a LIVE_ROOT
file — exactly what PHASE-1's `executed_from_live_root` proves and what
`tests/harness/test_wire_up_runtime_observe.py::test_live_root_symbol_observed_executed_from_live_root_passes`
demonstrates for a real production symbol. The leaf author already writes this
oracle (it is the leaf's own runtime proof); the hardening only makes the gate
ACTUALLY RUN it instead of trusting its mere declaration. A correct contract +
honest oracle => the symbol is in the observed set => suppressed => no reject. The
default-OFF posture and the report path are untouched, so nothing changes in prod
until the operator flips the enforce knob after the soak.

# OPEN BLOCKERS — adversarial review found TWO dispatch-blockers (resolve before dispatch)
These were surfaced empirically (jailed-runner + synthetic-fixture + pre-existing
test analysis) and MUST be resolved in this brief before it ships:

BLOCKER-1 (TASK 1 honest-case is UNCONSTRUCTIBLE in the prescribed fixture; universal
false-reject). The established `_build_tree` fixture (reused by the enforce/accept
oracles) builds a STANDALONE `git init` repo under `tmp_path` containing ONLY
`pkg/mod.py` (+ `__init__.py`). It is NOT a worktree of the JanusMask tree, so the
synthetic `staging_path` has NO `harness/` package and NONE of the LIVE_ROOT files.
The jailed runner does `import harness.wire_up` resolved via `cwd=staging_path`
(EMPIRICAL: `harness` is NOT pip-installed editable — `import harness` fails from any
cwd outside the repo). Therefore inside a staging-rooted jail over the synthetic tree
the runner ImportErrors => child non-zero exit => fail-closed EMPTY set => EVERY
contract (lying AND honest) is rejected under enforce. The brief's required honest
case (`returned is False` / suppressed) CANNOT be authored against this fixture.
  RESOLUTION (pick one, then make TASK 1 mandate it): (a) the honest-case oracle must
  build its staging tree as a real worktree/checkout of the JanusMask repo (so
  `harness/wire_up.py` + the LIVE_ROOT files exist under `staging_path`) and author a
  REAL `runtime_oracle` whose IMMEDIATE caller of the new symbol resides in a
  LIVE_ROOT file (mirror `test_wire_up_runtime_observe.py`'s real-edge drive); OR
  (b) pass the harness importability into the jail explicitly (PYTHONPATH/extra_ro of
  the JanusMask `harness` source) AND seed a LIVE_ROOT-named caller file in the
  staging tree. EITHER way TASK 1 must PROVE the honest path can positively observe —
  not merely assert it. This is the #1 false-positive risk; without it every honest
  leaf false-rejects under enforce.

BLOCKER-2 (TASK 3 vcmd is SELF-CONTRADICTORY: the hardening regresses two
"DO-NOT-EDIT" pre-existing enforce tests). On HEAD,
`tests/harness/test_wire_up_runtime_gate_enforce.py` has TWO GREEN tests that assert
a DECLARED-but-non-executing contract SUPPRESSES under enforce:
`test_enforce_on_valid_live_root_contract_proceeds_no_reject_row` (declares the
NON-EXISTENT oracle `tests/harness/test_brand_new_runtime.py`) and
`test_enforce_on_preexisting_zero_caller_symbol_never_rejected` (declares the
NON-EXISTENT `tests/harness/test_wired_one_runtime.py`). Under TASK 3's new wiring
those declared oracles do not exist => fail-closed EMPTY observed set => the symbol
is uncovered => REJECT => both tests' `assert returned is False` FLIP RED. But TASK
3's vcmd INCLUDES that file and demands "no regression," and the Inputs section marks
it "DO NOT EDIT." This is a hard contradiction: the hardening's whole purpose is to
stop a declared-but-non-executing oracle from suppressing.
  RESOLUTION: this brief MUST own updating those two pre-existing enforce expectations
  to the new (correct) hardened behavior — i.e. the enforce oracle file is NOT
  immutable here; it is part of the behavioral contract this brief changes. Either
  (a) fold the two updated expectations into TASK 1's authored oracle and DROP
  `test_wire_up_runtime_gate_enforce.py` from TASK 3's vcmd (keep only the new
  hardening oracle + the accept/report file, which is unaffected), OR (b) explicitly
  scope TASK 1/TASK 3 to REWRITE those two enforce tests' honest-contract cases to use
  a REAL observing oracle (per BLOCKER-1's resolution). The accept file
  (`test_wire_up_runtime_gate_accept.py`) is report-only (enforce OFF) and stays
  green — keep it in the vcmd. Re-verify the EXACT chosen vcmd is green post-fix.

BLOCKER-3 (TASK 2 vcmd can NEVER go green — dep-edge defect). TASK 2 is a
`harness_self_fix` IMPL task; its vcmd is its GREEN gate (it gets NO fix-forward
red-pair leniency — `is_fix_forward_redpair` accepts a RED gate ONLY for a
`test_authoring` task, `harness/redpair_acceptance.py:25`). But TASK 2's vcmd is
`pytest test_wire_up_contract_runtime_hardening.py test_wire_up_runtime_observe.py`
and the brief itself says that hardening oracle is "RED until TASK 3 lands the
wiring." So TASK 2's green gate DEPENDS on code that lands only in sibling TASK 3 —
TASK 2 can never pass its own vcmd and never lands. This is precisely the
sibling-vcmd-without-the-greening-dep defect that false-blocked a prior brief's task.
  RESOLUTION: TASK 1's authored oracle MUST include a SCOPED, primitive-DIRECT unit
  test (e.g. `test_observe_oracle_from_live_root_*`) that imports
  `observe_oracle_from_live_root` from `harness.wire_up` and exercises it DIRECTLY
  (positive observation for a real live-root-driven oracle; fail-closed EMPTY set for
  lying/missing/timeout/sandbox-off) — this greens after TASK 2 ALONE, before TASK 3.
  TASK 2's vcmd must then select ONLY that primitive-direct slice (+ the observe
  slice that must stay green), NOT the gate-level lying/honest assertions (those need
  TASK 3). Keep the gate-level assertions in TASK 3's vcmd. Re-verify TASK 2's
  amended vcmd is GREEN with only TASK 1+TASK 2 applied (no TASK 3).

# Inputs
READ these FIRST in `/home/xnihil0zer0/AI-Data/JanusMaskEX`:
- `harness/orchestrator.py` — `_run_wire_up_gate` (def ~2233), the
  `_contract_valid` line (~2309), the `uncovered` line (~2315), the enforce reject
  arm (~2316-2326), the report row (~2327-2331), `_wire_up_runtime_gate_enforce_enabled`
  (~2169), `_wire_up_runtime_gate_enabled` (~2193), the contained `try/except`
  (~2282/2332), the call site (~3178), `_NEVER_AUTO_APPROVE` (~2537).
- `harness/wire_up.py` — PHASE-1 `observe_symbol_execution` (~361),
  `executed_from_live_root` (~448), `new_top_level_callables` (~286), `LIVE_ROOTS`
  (~37). The new helper lives here; read these to mirror the pure/fail-soft style.
- `tests/harness/test_wire_up_runtime_gate_enforce.py` and
  `tests/harness/test_wire_up_runtime_gate_accept.py` — DO NOT EDIT (read for the
  hermetic synthetic-git-tree fixture: `git init`, commit a parent `pkg/mod.py`,
  stage a child commit adding `def brand_new(): return 1`, drive `_run_wire_up_gate`,
  read `state_dir/impl_progress.jsonl`, assert rollback/HEAD). The new oracle reuses
  this pattern and ADDS the lying-vs-honest contract distinction.
- `tests/harness/test_wire_up_runtime_observe.py` — DO NOT EDIT (read for how an
  oracle drives a LIVE_ROOT in-process so a symbol is observed from a live root —
  the shape an HONEST runtime_oracle takes).

# Non-Goals
Integration is out of scope (the literal word `integration` MUST appear in this
section and in EACH task's `non_goals` to excuse the integration-test requirement).
Specifically OUT OF SCOPE / honest limitations:
- FLIPPING either knob ON, or the soak that precedes the enforce flip — separate,
  owner-gated manual steps. Both knobs stay `false`; this brief delivers only the
  hardened SUPPRESSION criterion.
- CHANGING the AST-diff enumerator (`new_top_level_callables`), `LIVE_ROOTS`, the
  `executed_from_live_root` provenance rule, the report row schema, the enforce
  reject path, the call-site OR guard, or the committed config knobs. The hardening
  changes ONLY the suppression criterion + adds ONE pure helper.
- FOLLOW-UP (not in scope): make REPORT-mode classification use the SAME real
  observation criterion (`observe_oracle_from_live_root`) as the enforce arm, so the
  report/enforce `uncovered` sets agree (today the report path keeps the static
  `_contract_valid` declared-only criterion, deliberately, to stay byte-identical to
  PHASE-2). This brief tightens ONLY the enforce SUPPRESSION criterion.
- Auto-INFERRING the seam/oracle for a symbol. The `integration_contract`
  (entrypoints + symbols + runtime_oracle) is DECLARED by the brief that builds the
  symbol; the factory never guesses it. This brief only verifies the declared
  oracle actually observes the symbol from a LIVE_ROOT.
- Running the oracle in-process inside the orchestrator (rejected — trust-core
  hazard). Detecting NEW METHODS on a class or non-`.py` sources (scope is
  module-scope new top-level callables per PHASE-1's enumerator).
- Editing any file other than the three each task declares
  (`tests/harness/test_wire_up_contract_runtime_hardening.py`, `harness/wire_up.py`,
  `harness/orchestrator.py`). Do NOT touch `harness/autowork_daemon.py`,
  `harness/orchestrator_worker.py`, `harness/planner/**`,
  `harness/state_reconciler.py`, or `harness/config.yaml`.

# Deliverables

## TASK 1 — wire-up-contract-runtime-hardening-oracle (test_authoring; harness/orchestrator.py)
The test_authoring stage authors a RED behavioral oracle in
`tests/harness/test_wire_up_contract_runtime_hardening.py` (NO production edit). It
MUST be hermetic and reuse the established synthetic-git-tree fixture from
`tests/harness/test_wire_up_runtime_gate_enforce.py`: build a repo under `tmp_path`
(`git init`, commit a PARENT `pkg/mod.py` defining `def already(): ...`), stage a
child commit ADDING `def brand_new(): return 1`, then drive the REAL
`_run_wire_up_gate` (imported from `harness.orchestrator`) with the two knobs armed
via monkeypatching `_wire_up_runtime_gate_enabled` and
`_wire_up_runtime_gate_enforce_enabled` (the established `_arm` pattern), and read
back `state_dir/impl_progress.jsonl` + the real git HEAD/rollback state. Import
`LIVE_ROOTS` from `harness.wire_up` to build contracts (do NOT hardcode the list).

ANTI-GAMING ORACLE REQUIREMENTS (derive expectations from on-disk source + the real
ledger + the real git state; NO frozen literal; NO pasting the impl into the test;
do NOT mock the gate's decision logic; do NOT assert against
`harness/state_reconciler.py`):
- LYING CONTRACT UNDER ENFORCE => REJECTED (the core hardening proof): enforce ON,
  `task['constraints']['integration_contract']` declares
  `entrypoints=[<a real LIVE_ROOT>]`, `symbols=['brand_new']`, and a
  `runtime_oracle` path that, when run, does NOT cause `brand_new` to execute from a
  LIVE_ROOT (e.g. an oracle file that never calls `brand_new`, or whose only call to
  it is from a non-live-root/test frame). Assert the gate returns True (REJECT), a
  `phase:'rejected'` `orphan_symbol_unwired` row names `brand_new`, the task is
  blocked, the worktree removed, and the staged commit rolled back. This is RED on
  HEAD (today `_contract_valid` suppresses it on the mere declaration).
- HONEST CONTRACT UNDER ENFORCE => SUPPRESSED: enforce ON, a `runtime_oracle` that,
  when run, DOES cause `brand_new` to execute from a LIVE_ROOT (the immediate caller
  resides in a LIVE_ROOT file — mirror the live-root drive in
  `tests/harness/test_wire_up_runtime_observe.py`). Assert the gate returns False
  (proceed), NO `phase:'rejected'` row, the commit survives. The way you arrange the
  honest oracle to genuinely drive a LIVE_ROOT must be REAL execution, never a
  fixture-name special-case in production.
- ENFORCE OFF (shadow ON) => REPORT-ONLY regardless of contract honesty: the
  report path NEVER rejects (PHASE-2 parity). Assert a `phase:'report'` row, return
  False, no rollback — for BOTH the lying and the honest contract.
- BOTH KNOBS OFF => STRICT NO-OP (no row, return False), byte-identical to today.
- WIRE_EXEMPT still suppresses under enforce (a `wire_exempt`-listed `brand_new`
  proceeds with no reject row) — the hardening must not regress the exempt path.
- PRE-EXISTING ZERO-CALLER SYMBOL NEVER REJECTED (false-positive guard): a parent
  already defining `def old_uncalled(): ...` and a child adding only a separately
  covered symbol — `old_uncalled` is never in any reject row (it is not new in this
  commit).
The oracle MUST drive the real `_run_wire_up_gate`, read the real ledger AND the
real git HEAD/rollback state for its assertions, and exercise the gate's REAL
suppression decision (not a mocked one). `non_goals` MUST contain the literal word
`integration`. `regression_tests >= 2`.

- `task_id: wire-up-contract-runtime-hardening-oracle`
- `priority: high`
- `meta_task_type: test_authoring`
- `files_touched: ["tests/harness/test_wire_up_contract_runtime_hardening.py"]`
- `mutation_target: harness.orchestrator`  (BARE DOTTED MODULE only)
- `dependencies: []`
- `verification_command:` `python -m pytest tests/harness/test_wire_up_contract_runtime_hardening.py -q`
  (RED against HEAD; do NOT use a broad `pytest tests/adversarial/ -q` vcmd).

## TASK 2 — wire-up-contract-runtime-hardening-primitive (harness/wire_up.py)
Edit ONLY `harness/wire_up.py` via a single `__JANUSMASK_PATCHES__` SYMBOL patch
that ADDS one NEW top-level function (R-ANCHORED on the existing
`observe_symbol_execution` class so the new top-level symbol lands; a brand-new
top-level symbol needs an R-anchor or patch-apply fails with an opaque
`auto_commit_failed`):

```python
def observe_oracle_from_live_root(oracle_path, symbols, *, staging_path,
                                  worktree_root, state_dir, sandbox_enabled,
                                  jail_env=None, jail_extra_ro=(), jail_extra_rw=(),
                                  timeout=120) -> set:
    """Run the declared runtime_oracle in a BOUNDED, JAILED CHILD PROCESS under
    ``observe_symbol_execution`` and return the SET of ``symbols`` OBSERVED to have
    executed FROM a LIVE_ROOT during that run.

    This is the POSITIVE-evidence runtime check the wire-up enforce gate uses to
    decide suppression: a symbol is "covered" only if it is in the returned set.
    The child runs INSIDE the same bubblewrap jail the verification command uses
    (``agent_jail.build_jail_argv(..., bind_credentials=False)``) — the oracle is
    ATTACKER-INFLUENCED, so it must never run unjailed (host-cred-read hazard). The
    jail is rooted at ``staging_path`` so the child imports the STAGED
    ``harness.wire_up``, drives the staged ``runtime_oracle`` (a pytest module path
    resolved under ``staging_path``) while ``observe_symbol_execution(symbols)``
    traces it, then prints the JSON list of names for which
    ``executed_from_live_root(name, LIVE_ROOTS)`` is True. The parent parses that
    list.

    JAIL PARITY: mirror the vcmd at orchestrator.py:2991 —
    ``build_jail_argv([...], repo_root=worktree_root, work_dir=staging_path,
    state_dir=state_dir, extra_ro=[sys.base_prefix, sys.prefix] + jail_extra_ro,
    extra_rw=jail_extra_rw, bind_credentials=False)`` run with
    ``cwd=str(staging_path), env=jail_env``. The caller (TASK 3, in orchestrator.py)
    resolves ``sandbox_enabled = agent_jail.sandbox_enabled(load_config())`` and the
    jail env/ro/rw exactly as the vcmd does and passes them in (wire_up.py imports
    ONLY ``harness.agent_jail`` — never ``harness.orchestrator``/``load_config`` —
    to avoid a circular import). If ``sandbox_enabled`` is False, return ``set()``
    (NEVER fall back to a plain unjailed ``subprocess.run``).

    FAIL-CLOSED / POSITIVE EVIDENCE ONLY: returns an EMPTY set on ANY failure
    (sandbox disabled, jail-build/bwrap unavailable, missing/invalid oracle path,
    child non-zero exit, timeout, unparseable output, malformed inputs). Absence
    of failure NEVER implies coverage; only a name printed by the child counts.
    Pure-ish + fail-soft: never raises. GENERAL behavior only — no special-casing
    of any path, symbol, or task field.
    """
```

IMPLEMENTATION NOTES (LOAD-BEARING):
1. Validate inputs fail-soft: `symbols` -> a clean list of bare identifiers;
   `oracle_path` -> a string with no `..` component, resolved to a real file under
   `staging_path`; on any violation return `set()`.
2. JAIL THE CHILD (parity with the vcmd — NEVER a plain unjailed subprocess).
   The `sandbox_enabled` boolean is PASSED IN by TASK 3 (which computed
   `agent_jail.sandbox_enabled(load_config())`, exactly as the vcmd gate at
   orchestrator.py:2981 does); if it is False, return `set()` (fail-closed, NO
   unjailed fallback). wire_up.py imports `from harness import agent_jail` ONLY
   (NEVER `harness.orchestrator`/`load_config` — that would be circular). Build the
   argv with
   `agent_jail.build_jail_argv([sys.executable, '-c', <runner>], repo_root=worktree_root,
   work_dir=staging_path, state_dir=state_dir, extra_ro=[sys.base_prefix, sys.prefix]
   + list(jail_extra_ro), extra_rw=list(jail_extra_rw), bind_credentials=False)`,
   then `subprocess.run(argv, cwd=str(staging_path), timeout=timeout,
   capture_output=True, text=True, env=jail_env)`. `bind_credentials=False` MUST be
   passed (drops `~/.gemini`/`~/.claude`, adds `--unshare-net`). The `<runner>`
   source: import `observe_symbol_execution`, `LIVE_ROOTS` from `harness.wire_up`
   (resolves to the STAGED copy because cwd/repo_root is `staging_path`); inside
   `with observe_symbol_execution(symbols) as obs:` run the oracle via
   `pytest.main([oracle_path, '-q'])` (or `runpy`); then
   `print(json.dumps([s for s in symbols if obs.executed_from_live_root(s,
   LIVE_ROOTS)]))` on the LAST stdout line. Pass `symbols`/`oracle_path` to the
   child via argv or env, never by string-formatting untrusted values into code.
3. Parse the child's LAST non-empty stdout line as a JSON list; intersect with the
   requested `symbols`; return that set. On sandbox-disabled, jail-build failure
   (`FileNotFoundError` from bwrap-absent), non-zero child exit, timeout, or parse
   error: return `set()`.
4. Reuse PHASE-1 `observe_symbol_execution` / `executed_from_live_root` / `LIVE_ROOTS`
   UNCHANGED — do NOT modify them. Add ONLY this one function. Beyond stdlib
   (`subprocess`, `sys`, `json`, `os`) the helper imports ONLY
   `from harness import agent_jail` (NOT `load_config`, NOT `harness.orchestrator` —
   `harness/orchestrator.py` already imports from `harness.wire_up` at module top, so
   importing it back here is a circular-import hazard). Add the `agent_jail` import
   locally inside the function if not already top-level so `harness/wire_up.py` keeps
   no new module-level coupling.

GENERALITY: do NOT special-case any module/slug/task_id/fixture name. The helper
runs whatever oracle path it is given and reports only genuinely-observed symbols.

ANTI-GAMING ORACLE REQUIREMENT (TASK 2): TASK 1's oracle goes green by GENERAL
behavior (the gate, via TASK 3, calls THIS helper and the helper truly observes —
or fails to observe — the symbol from a LIVE_ROOT), NOT by detecting a fixture. The
vcmd MUST be a SCOPED selection — NEVER `pytest tests/adversarial/ -q`. Re-run the
EXACT vcmd before dispatch and confirm `N passed` with N>=2 and that the existing
`tests/harness/test_wire_up_runtime_observe.py` is NOT regressed.

`non_goals` MUST contain the literal word `integration`. `regression_tests >= 2`.

- `task_id: wire-up-contract-runtime-hardening-primitive`
- `priority: high`
- `meta_task_type: harness_self_fix`
- `files_touched: ["harness/wire_up.py"]`
- OMIT `mutation_target` (impl task editing a `harness/**` path).
- `dependencies: ["wire-up-contract-runtime-hardening-oracle"]`
- Emit a SINGLE `__JANUSMASK_PATCHES__` SYMBOL patch (the NEW
  `observe_oracle_from_live_root` R-anchored on `observe_symbol_execution`). Do NOT
  emit a `__JANUSMASK_MANIFEST__`.
- `harness/wire_up.py` is NOT in `_NEVER_AUTO_APPROVE` -> no operator decision file.
- `verification_command:`
  `python -m pytest tests/harness/test_wire_up_contract_runtime_hardening.py tests/harness/test_wire_up_runtime_observe.py -q`
  (RED until TASK 3 lands the wiring; the observe slice must stay green. Do NOT use a
  broad `pytest tests/adversarial/ -q` vcmd.)

## TASK 3 — wire-up-contract-runtime-hardening-wiring (harness/orchestrator.py)

TRUST-CORE: `harness/orchestrator.py` is in `_NEVER_AUTO_APPROVE`
(`harness/orchestrator.py:2537`). This task REQUIRES an operator decision file
`state/control/decisions/wire-up-contract-runtime-hardening-wiring.json` and
`operator_decision_required: true` is set in this brief's frontmatter. Keep the
trust-core surface MINIMAL: change ONLY the suppression criterion in the existing
PHASE-2/3 branch of `_run_wire_up_gate`; do NOT touch the reject path, the report
row, the call site, the flag-readers, or the module-level new-file gate.

IMPLEMENTATION NOTES (LOAD-BEARING — GENERAL, fail-CLOSED, default-OFF preserved):
1. PATCH SHAPE: ONE file, `harness/orchestrator.py`, ONE `__JANUSMASK_PATCHES__`
   SYMBOL patch editing the EXISTING `_run_wire_up_gate`. Add the import of the new
   helper (`from harness.wire_up import ... observe_oracle_from_live_root` — extend
   the existing `from harness.wire_up import new_top_level_callables, LIVE_ROOTS`
   at `harness/orchestrator.py:2167`, or import locally inside the branch).
2. Inside the PHASE-2/3 symbol-addition branch (behind
   `_wire_up_runtime_gate_enabled`), where `_contract_valid` (~:2309) and
   `uncovered` (~:2315) are computed: compute the SET of symbols that are ACTUALLY
   OBSERVED from a LIVE_ROOT and require it for suppression. Concretely:
     - Keep `_contract_valid` as the STATIC precheck (entrypoints subset of
       LIVE_ROOTS + a `runtime_oracle` declared + symbols named) — it cheaply gates
       whether to bother running the oracle at all.
     - Add: when `_contract_valid` AND the enforce knob is on, compute
       ```python
       import sys
       from harness import agent_jail
       _cfg = load_config()
       _agc = (_cfg.get('agent_sandbox') or {}) if isinstance(_cfg, dict) else {}
       _observed = observe_oracle_from_live_root(
           _oracle, _csymbols,
           staging_path=staging_path, worktree_root=worktree_root,
           state_dir=state_dir,
           sandbox_enabled=agent_jail.sandbox_enabled(_cfg),
           jail_env=_vcmd_scrubbed_env(),
           jail_extra_ro=list(_agc.get('verify_extra_ro', [])),
           jail_extra_rw=list(_agc.get('verify_extra_rw', [])),
       )
       ```
       (the oracle + the just-committed child + the staged LIVE_ROOT files all live
       under `staging_path`; the jail is rooted there so the child imports the STAGED
       `harness.wire_up`). `_run_wire_up_gate` ALREADY receives `staging_path`,
       `worktree_root`, `state_dir`, and `working_dir` as parameters; `agent_jail` is
       imported locally as elsewhere in this module (e.g. orchestrator.py:412/2751);
       `_vcmd_scrubbed_env` is a MODULE-LEVEL helper (orchestrator.py:3797) and is in
       scope. CRITICAL — `_venv_jail_env`/`verify_extra_ro`/`verify_extra_rw`/
       `_ext_venv_ro` are LOCALS of the worker-spawn scope (orchestrator.py:2763-2817),
       NOT visible inside `_run_wire_up_gate`; the gate MUST derive the jail env/ro/rw
       itself from `_cfg` + `sys.base_prefix`/`sys.prefix` (mirroring the vcmd's
       `extra_ro`) as shown — do NOT reference those out-of-scope names. (The
       `[sys.base_prefix, sys.prefix]` venv ro-binds are prepended INSIDE the
       primitive per its docstring, so they need not be passed in `jail_extra_ro`.)
       Then a symbol counts as covered ONLY IF `_contract_valid and _s in _csymbols
       and _s in _observed`. Update the `uncovered` comprehension:
       ```python
       uncovered = sorted(
           _s for _s in new_syms
           if _s not in _exempt
           and not (_contract_valid and _s in _csymbols and _s in _observed)
       )
       ```
     - FAIL-CLOSED: `observe_oracle_from_live_root` returns an EMPTY set on any
       error/timeout, so a lying/no-op/erroring oracle yields no coverage and the
       symbol stays in `uncovered` => rejected under enforce.
3. PRESERVE the REPORT path EXACTLY: when the enforce knob is OFF (shadow only), do
   NOT run the oracle and do NOT change which symbols report — the report path must
   never reject and must stay byte-identical to PHASE-2. Two acceptable shapes: (a)
   only fold `_observed` into `uncovered` when
   `_wire_up_runtime_gate_enforce_enabled(state_dir)` is True (the simplest way to
   keep the report path unchanged), OR (b) compute `_observed` only when enforce is
   on and otherwise treat the static `_contract_valid` as today. EITHER way the
   report path's `uncovered` membership must equal PHASE-2's. Document the choice in
   the symbol's docstring. Default-OFF: both knobs `false` in committed config means
   this branch is never entered in prod, so the edit is byte-identical to PHASE-3-
   landed prod until an operator flips a key.
4. Keep the WHOLE symbol-check inside the existing contained `try/except Exception`
   (~:2282/:2332) so any failure of the new path is inert (logs, never crashes the
   accept path) — and inertness here means the enforce arm simply does not suppress
   (fail-closed), it never silently accepts.
5. GENERALITY: do NOT special-case any module/slug/task_id/fixture. The observation
   check runs the general `_observed` computation for every armed already-tracked
   `.py` file.

ANTI-GAMING ORACLE REQUIREMENT (TASK 3): make TASK 1's oracle GREEN by GENERAL
behavior (the real helper + the tightened suppression), NOT by detecting the
fixture. The vcmd MUST be a SCOPED selection — NEVER `pytest tests/adversarial/ -q`.
Re-run the EXACT vcmd before dispatch and confirm `N passed` with N>=2 and that the
existing enforce/accept oracles are NOT regressed.

`non_goals` MUST contain the literal word `integration`. `regression_tests >= 2`.

- `task_id: wire-up-contract-runtime-hardening-wiring`
- `priority: high`
- `meta_task_type: harness_self_fix`
- `files_touched: ["harness/orchestrator.py"]`
- OMIT `mutation_target` (impl task editing a `harness/**` path).
- `dependencies: ["wire-up-contract-runtime-hardening-oracle", "wire-up-contract-runtime-hardening-primitive"]`
  (RED oracle first; the primitive must exist before the wiring imports it).
- Emit a SINGLE `__JANUSMASK_PATCHES__` SYMBOL patch for `harness/orchestrator.py`
  (edit `_run_wire_up_gate`). Do NOT emit a `__JANUSMASK_MANIFEST__`.
- REQUIRES operator decision file
  `state/control/decisions/wire-up-contract-runtime-hardening-wiring.json`
  (orchestrator.py is `_NEVER_AUTO_APPROVE`).
- `verification_command:`
  `python -m pytest tests/harness/test_wire_up_contract_runtime_hardening.py tests/harness/test_wire_up_runtime_gate_enforce.py tests/harness/test_wire_up_runtime_gate_accept.py -q`
  (the new hardening oracle PLUS the existing enforce/accept oracles that must stay
  green. Do NOT use a broad `pytest tests/adversarial/ -q` vcmd. Run the EXACT vcmd
  before dispatch and confirm `N passed` with N>=2 and no regression.)

# Required plan shape
Emit EXACTLY THREE tasks (pin via
`required_task_ids: [wire-up-contract-runtime-hardening-oracle,
wire-up-contract-runtime-hardening-primitive,
wire-up-contract-runtime-hardening-wiring]`). PRIORITY MUST be canonical lowercase
(`high`), NEVER P0/P1/ints/Capitalized.
  - TASK 1 is `test_authoring` (writes the RED oracle; carries
    `mutation_target: harness.orchestrator`, BARE DOTTED MODULE only).
  - TASK 2 is `harness_self_fix` (writes `harness/wire_up.py` ONLY via a
    `__JANUSMASK_PATCHES__` SYMBOL patch, OMITS `mutation_target`; depends on TASK 1).
    Auto-approve-eligible (`harness/wire_up.py` NOT in `_NEVER_AUTO_APPROVE`).
  - TASK 3 is `harness_self_fix` (writes `harness/orchestrator.py` ONLY via a
    `__JANUSMASK_PATCHES__` SYMBOL patch, OMITS `mutation_target`; depends on TASK 1
    and TASK 2). TRUST-CORE (`_NEVER_AUTO_APPROVE`) — REQUIRES the operator decision
    file named above.
The change is SPLIT across TASK 2 + TASK 3 because each `.py` file is a separate
single-channel `__JANUSMASK_PATCHES__` symbol patch; combining them would force the
whole task into infeasible whole-file `__JANUSMASK_MANIFEST__` mode. Each task's
`non_goals` MUST contain the literal word `integration`; each `regression_tests >= 2`.
Do NOT add any task editing `harness/config.yaml`, `harness/autowork_daemon.py`,
`harness/orchestrator_worker.py`, `harness/planner/**`, or
`harness/state_reconciler.py`.
