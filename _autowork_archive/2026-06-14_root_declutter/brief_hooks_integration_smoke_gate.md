---
epic: true
---

# Title

JanusMaskJR — Integration-Smoke Gate. Close the pipeline defect that let a broken I/O adapter
ship behind green tests: the existing smoke gate (`harness/sandbox_smoke.py::smoke_import`) is
(A) **skipped entirely** for the meta-types that I/O leaves get classified as
(`hooks_integration`, `harness_self_fix`, `harness_plumbing` — all `skip_smoke_gates: True` in
`harness/planner/taxonomies.py::META_TASK_POLICY`), and (B) when it does run, only does
`python -S -c 'import <candidate>'` — **hermetic**: it imports the module but never EXECUTES the
real production entrypoint. So an adapter that imports fine but raises the instant it is *called*
(wrong-module import inside a lazy factory, a required kwarg never supplied, a file the command was
supposed to write but never does) passes every gate and lands. This epic adds a new
**accept-time, hard-blocking Integration-Smoke gate** that keys off whether the module is
*I/O-bound* (NOT off the meta_task_type skip-list), and requires that some non-hermetic oracle
actually CALLS the module's real production entrypoint — mocking only the lowest external boundary
(subprocess/socket/network), never the entrypoint or its dep-builder itself. As with every
JanusMask gate, this is enforced by WITHHOLDING and CHECKING a pure, testable function on the
accept path behind a default-OFF flag — never by a longer prompt the worker may ignore. YOU (the
planner) decide the leaf tree; a strong suggested decomposition is at the end.

THE MOTIVATING BUG (real, this session, now fixed by hand on the target tool — use as the
regression fixture, do NOT re-fix it here): `tools/drive_backup/hook_runner.py::_default_build_deps`
imported `ledger` from the wrong module (ImportError), and wired `build_archive`/`upload` without
their required `runner`/`now`/`out_dir`/`queue_dir` seams (TypeError on call); `archiver.build_archive`
built a bare `git diff <sha>` whose stdout was never redirected, so the `.diff` was never written.
All three passed the 37 hermetic unit tests because those tests only ever injected a fake
`build_deps` and never ran the real adapter. THIS GATE EXISTS so that class cannot recur.

# Scope

The defect is structural. Today the only post-synthesis execution check is `smoke_import`, and it
has two holes, both confirmed by codebase read:

- **Hole A — coverage.** `orchestrator_worker.py` and `orchestrator.py` run `smoke_import` only when
  `mtt not in SKIP_SMOKE_GATE_TYPES`. `hooks_integration`, `harness_self_fix`, `harness_plumbing`,
  `config_schema`, the `test_*` types, `docs_writing`, `epic_planning`, `mcp_server_change` are all
  in that skip set. A git-hook runner / uploader / installer is naturally typed `hooks_integration`
  or `harness_self_fix`, so it skips the gate completely.
- **Hole B — depth.** `smoke_import('_smoke_candidate', src)` runs `python -S -c 'import
  _smoke_candidate'` in a scrubbed subprocess. It catches a SyntaxError or a top-level import crash
  of the single candidate. It does NOT execute `__main__`, does NOT call any function, and tests
  only the one candidate module in isolation — so call-time failures and cross-module integration
  failures sail through.

The cure is a new gate that is orthogonal to and composes with `smoke_import` and the wire-up gate
(`autowork.wire_up_gate`, the directly-analogous accept-path precedent). Three deterministic layers,
each shippable behind a default-OFF flag `autowork.integration_smoke_gate`:

1. **Integration-smoke gate (accept-time, the load-bearing piece).** At the single convergent accept
   chokepoint `harness/orchestrator.py::_auto_commit_accepted`, at the post-mutation / post-wireup /
   pre-merge point (the same insertion point `_run_wire_up_gate` already uses), when the flag is ON
   and a touched module is I/O-BOUND, verify that the leaf's committed test set contains at least one
   *executing integration oracle* (a test that calls the module's real production entrypoint, not a
   fake). If an I/O-bound module ships none, REJECT exactly as the wire-up gate rejects an orphan:
   `_rollback_rejected_commit` + `git_integration.remove_staging_worktree` + `_mark_blocked(outcome=
   'missing_integration_smoke')` + an `impl_progress.jsonl` ledger row + `return False`. The gate
   keys off I/O-boundness, NOT the meta_task_type skip-list — that is the Hole-A fix.

2. **Plan-validation requirement (pre-spawn).** A leaf that creates or edits an I/O-bound module must
   declare an executing integration oracle among its tests. A leaf lacking one is rejected before a
   worker is dispatched, with a `missing_integration_smoke` violation — beside the existing
   `missing_wiring_oracle` check in `harness/planner/plan_validator.py`.

3. **Adversarial acceptance corpus (test-only).** A committed corpus of fixtures the gate MUST get
   right — import-OK-but-call-raises, fake/monkeypatched-entrypoint "integration" oracle, pure-logic
   module needing no oracle, real boundary-mocked executing oracle, and the drive_backup regression
   shape — that pins both true-positives (catches the bug) and true-negatives (no false friction).

Layer 1 alone closes the autonomous-pipeline hole. They are belt-and-suspenders.

# Inputs

ALREADY BUILT; do NOT rebuild, wrap/extend (signatures verified at HEAD 2026-06-13):

- `harness/orchestrator.py::_auto_commit_accepted(state_dir, task, task_id) -> bool` — the single
  convergent accept chokepoint. The wire-up gate is already inserted here at the post-mutation /
  pre-merge point: `if _wire_up_gate_enabled(state_dir): if _run_wire_up_gate(task, files_touched,
  state_dir, task_id, staging_path, worktree_root, result, working_dir): return False`. The new
  integration-smoke gate is inserted **immediately after** that block, in the identical shape.
- `harness/orchestrator.py::_run_wire_up_gate` and `::_wire_up_gate_enabled` — the EXACT templates
  to copy for the new `_run_integration_smoke_gate` and `_integration_smoke_gate_enabled` (flag read
  via `load_config()['autowork'].get('integration_smoke_gate', False)`).
- The rejection machinery `_rollback_rejected_commit(staging_path, sha, rel, task_id, reason)`,
  `git_integration.remove_staging_worktree(...)`, `_mark_blocked(state_dir, task_id, outcome=...)`,
  and `write_jsonl_row(state_dir / 'impl_progress.jsonl', {...})` — REUSE verbatim; the
  `orphan_unwired` arm is the line-for-line model for the `missing_integration_smoke` arm.
- `harness/planner/plan_validator.py` — the per-task checks; the `missing_integration_smoke`
  violation plugs in beside `missing_wiring_oracle` (study that one first; mirror it).
- `harness/sandbox_smoke.py::smoke_import` — the existing hermetic import gate. Do NOT modify it;
  the new gate is additive and complementary (import-safety vs execution-safety).
- `harness/planner/taxonomies.py::META_TASK_POLICY` / `SKIP_SMOKE_GATE_TYPES` — read-only context.
  The new gate deliberately does NOT consult the skip-list (that is what made Hole A possible);
  it keys off the I/O-bound classifier instead.
- `harness/config.yaml` `autowork:` block — add `integration_smoke_gate: false` beside
  `wire_up_gate`. Default-OFF; flip is owner-gated on the dogfood.
- `tools/drive_backup/hook_runner.py`, `tools/drive_backup/archiver.py`, and their tests
  `tests/drive_backup/test_hook_runner_production_deps.py`, `tests/drive_backup/test_archiver.py`
  (the new `test_real_git_and_tar_produce_both_artifacts`) — the REGRESSION FIXTURE for the
  adversarial corpus. The fixed adapter + its executing oracle MUST pass the gate; the pre-fix
  shape MUST be rejected. Do NOT modify these files; reference their shapes.

# What "I/O-bound" and "executing integration oracle" mean (how the gate checks, deterministically)

A module is **I/O-bound** iff a pure AST scan of its source finds any real-world boundary signal:
imports or uses of `subprocess`, `socket`, `http.client`/`urllib`/`requests`, file writes
(`open(..., 'w'|'a'|'x'|'wb'|...)`), `os.system`/`os.popen`, `shutil.copy*`/`move`, a `__main__`
entrypoint that calls into the module, or a known external tool driven via subprocess argv
(`git`, `tar`, `rclone`, `gcloud`, `curl`). Pure logic modules (no such signal) are NOT I/O-bound
and are exempt — the gate must impose ZERO friction on them (no false positives).

An **executing integration oracle** for module M is a test (in the leaf's committed test set) that,
by AST inspection: (a) imports M (the real module, not a stub), (b) CALLS one of M's production
entrypoints — the default-deps adapter / `main` / `build_*` / `run*` / a `__main__` via `runpy`,
from a declared `ENTRYPOINT_NAMES` set plus any names the task lists in
`spec['integration_entrypoints']`, and (c) does NOT neutralize that entrypoint: it must NOT
`monkeypatch.setattr(M, '<entrypoint>', ...)` the entrypoint itself, and must NOT pass an injected
replacement for the entrypoint's own dep-builder (e.g. `build_deps=<fake>`, `runner=<the-whole-thing>`).
Mocking the LOWEST boundary seam only — `subprocess.run`, `socket`, a network client object — is
ALLOWED and expected (that is what makes it runnable in CI). The classifier's job is to tell
"executes the real wiring, mocks the boundary" (PASS) from "replaces the wiring with a fake" (the
hermetic anti-pattern that hid the drive_backup bug; FAIL).

Both classifiers are PURE: `ast`-only over source strings supplied through injected file-read seams.
NO subprocess, NO network, NO clock, NO randomness. State the limits LOUDLY in docstrings: the AST
classifier cannot prove the oracle's assertions are meaningful (a test that calls the entrypoint and
asserts nothing still counts as "executing") — the mutation gate and code review remain the backstop
for "executes but asserts nothing"; do not pretend coverage. Reflectively-constructed entrypoints
the AST cannot see are a stated blind spot.

# THE TRAP — read before authoring any call-site leaf

The gate machinery is itself new code called BY the accept path, exactly the kind of thing that
lands orphaned/unexecuted, and at build time there is no live integration-smoke gate to catch it.
Avoid by construction, mirroring the wire-up epic:

1. **Never split "create module" from "wire it into the accept path" across an unowned boundary.**
   The call-site leaf (the edit to `_auto_commit_accepted`) OWNS the edge and proves it with an
   EDGE-ASSERTING oracle.
2. **Call-site leaves ship EDGE-ASSERTING oracles, not isolated unit tests.** Canonical shape the
   automated oracle author must follow for the accept-path leaf:
   ```python
   def test_accept_path_invokes_integration_smoke_and_blocks_unproven_io_module(monkeypatch):
       called = {}
       real = orchestrator._run_integration_smoke_gate
       monkeypatch.setattr(orchestrator, "_run_integration_smoke_gate",
           lambda *a, **k: called.setdefault("hit", True) or real(*a, **k))
       # candidate = an I/O-bound module whose committed tests are import-only (hermetic)
       result = orchestrator._auto_commit_accepted(state_dir, <io-bound, hermetic-only task>, tid)
       assert called.get("hit")    # the LIVE accept path actually invoked the gate
       assert result is False       # and the unproven I/O module was blocked, not merged
   # plus the converse: an I/O-bound module WITH an executing integration oracle merges (True),
   # and a pure-logic module merges without needing one.
   ```
   If the worker lands the gate fn but forgets to call it, `called["hit"]` is never set → RED.
3. **The substrate primitive is the ONE isolated-oracle leaf.** `harness/integration_smoke.py`
   (the pure classifiers) is a single-file whole-file NEW module; its oracle legitimately tests the
   pure functions in isolation. Keep it in a SEPARATE, dependency-CHAINED leaf from the call-site
   edit (a NEW file + an EXISTING-file edit in one leaf trips `auto_commit_failed` — the patches
   path cannot create files). The call-site leaf `dependencies` MUST list the substrate leaf.
4. **Dogfood once (mandatory manual acceptance, recorded).** After the call-site leaf merges and
   before the flag is flipped: run the gate against `tools/drive_backup/hook_runner.py` (I/O-bound,
   now ships `tests/drive_backup/test_hook_runner_production_deps.py` which calls the real
   `_default_build_deps`) → MUST PASS; run it against a synthetic import-OK-but-call-raises fixture
   with an import-only oracle → MUST be REJECTED. Only then is the flag eligible to flip (owner).
5. **The flag stays OFF until the dogfood passes.**

# Correctness regimes (the build boundary)

DETERMINISTIC logic — the `integration_smoke.py` classifiers, the plan-validator violation — is
fully JM-rebuildable and MUST be pure/stdlib-only (`ast`, injected file reads). It NEVER spawns a
process, makes a model/API/network call, or shells out. The INTEGRATION edits
(`_auto_commit_accepted`, `plan_validator`) modify EXISTING symbols ADDITIVELY behind the default-OFF
flag and MUST preserve every current behaviour and passing test.

THE CARDINAL PROJECT RULE this epic encodes: NEVER hand-edit production outside the pipeline. It
would be self-parody to land an unexecuted execution-checker by hand. Everything here is built by
the autonomous pipeline; the oracles are authored by the automated `test_authoring` workers from the
per-leaf contracts below — not hand-written.

# Per-leaf contract (automated-oracle-author edition)

Each leaf carries, in its `spec['implementation_notes']`, (1) the exact behavioral contract of the
symbol it builds, and (2) the ORACLE CONTRACT — the cases its paired oracle must assert (the
automated `test_authoring` worker writes the actual test file from this contract; do NOT pre-write
it). NEW modules are single-file whole-file emissions; integration leaves are EXISTING-symbol edits
to ONE file each — never bundle multiple files into one leaf. Every call-site leaf's oracle contract
MUST specify the EDGE-ASSERTING shape from THE TRAP rule 2; only the substrate leaf may specify an
isolated oracle. Every oracle contract MUST include adversarial cases (see Adversarial testing).

# Adversarial testing (MANDATORY — extensive, every leaf)

This epic is adversarial-first. Each oracle contract enumerates explicit attack/evasion fixtures the
gate must defeat, and a dedicated corpus leaf concentrates them:

- **Evasion 1 — import-OK / call-raises.** Module imports cleanly; its entrypoint raises on call
  (the drive_backup ImportError-in-factory shape). With an import-only oracle ⇒ gate REJECTS.
- **Evasion 2 — fake integration oracle.** A test that `monkeypatch.setattr`s the entrypoint, or
  passes a fake `build_deps`, so it "calls the entrypoint" but exercises no real wiring ⇒ classifier
  must rule it HERMETIC ⇒ gate REJECTS (this is the exact pattern that hid the original bug).
- **Evasion 3 — boundary-only mock (legitimate).** A test that calls the real entrypoint and mocks
  only `subprocess.run`/`socket` ⇒ classifier rules it EXECUTING ⇒ gate PASSES.
- **False-positive guard.** A pure-logic module (no I/O signal) with only unit tests ⇒ NOT I/O-bound
  ⇒ gate PASSES with no oracle required (zero friction).
- **I/O-signal coverage matrix.** One fixture per boundary signal (subprocess, socket, urllib, file
  write, os.system, shutil, `__main__`, tool-argv git/tar/rclone) ⇒ each classified I/O-bound.
- **Regression — drive_backup.** The fixed `hook_runner`/`archiver` + their executing oracles ⇒
  PASS; the pre-fix adapter shape + hermetic-only oracle ⇒ REJECT.
- **Idempotency / purity.** Classifiers are deep-copy-pure and deterministic across repeated calls.

# Suggested decomposition (NON-BINDING — you decide the final tree)

Substrate (NEW, deterministic, stdlib-only, single-file whole-file; ISOLATED oracle allowed):
- `harness/integration_smoke.py` → `tests/harness/test_integration_smoke.py`.
  `is_io_bound(module_rel, module_src, *, signals=BOUNDARY_SIGNALS) -> IoBoundResult(io_bound,
  signals, reason)` and `has_executing_integration_oracle(module_rel, test_srcs, *,
  entrypoints=ENTRYPOINT_NAMES) -> SmokeOracleResult(present, oracle_files, reason, fix_hint)`,
  both pure AST. Declare `BOUNDARY_SIGNALS`, `ENTRYPOINT_NAMES`, `BOUNDARY_MOCK_ALLOWLIST` here.
  Oracle: the full I/O-signal matrix, executing-vs-hermetic discrimination (incl. monkeypatched-
  entrypoint and fake-build_deps anti-patterns), pure-logic exemption, idempotency.

Integration (EDIT existing symbols, one file per leaf — TRAP-PRONE; EDGE-ASSERTING oracles):
- EDIT `harness/orchestrator.py` (add `_integration_smoke_gate_enabled` + `_run_integration_smoke_gate`,
  call them in `_auto_commit_accepted` right after the wire-up block) →
  `tests/harness/test_integration_smoke_accept_gate.py`. Flag-gated `autowork.integration_smoke_gate`.
  On an I/O-bound module with no executing oracle: `_rollback_rejected_commit` +
  `remove_staging_worktree` + `_mark_blocked(outcome='missing_integration_smoke')` + ledger row +
  `return False`; on a proven module proceed unchanged. `dependencies: [<substrate leaf>]`.
  EDGE-ASSERTING oracle per THE TRAP rule 2 (drive the real `_auto_commit_accepted` over a temp git).
- EDIT `harness/planner/plan_validator.py` (add `missing_integration_smoke` beside
  `missing_wiring_oracle`) → `tests/planner/test_missing_integration_smoke.py`. A new-module /
  io_adapter / hooks_integration leaf whose declared tests contain no executing integration oracle
  is rejected pre-spawn; one that declares it passes. Oracle asserts the violation fires on the live
  validator path.

Config + corpus (one file each):
- EDIT `harness/config.yaml` `autowork.integration_smoke_gate: false` (meta_task_type
  `config_schema` or `harness_self_fix`) → a tiny oracle asserting `load_config()['autowork']` has
  the key defaulting False.
- NEW `tests/harness/test_integration_smoke_adversarial.py` (a `test_authoring` corpus leaf) →
  the full Adversarial-testing fixture set above, including the drive_backup regression.

# Deliverables

A decomposed leaf tree (the planner's call) plus the built result: `harness/integration_smoke.py`
(pure classifiers), the flag-gated accept-time gate in `_auto_commit_accepted`, the
`missing_integration_smoke` plan-validation requirement, the `autowork.integration_smoke_gate: false`
flag, and the adversarial corpus — each leaf's oracle authored by the automated `test_authoring`
worker from the per-leaf oracle contract, every call-site leaf proven by an EDGE-ASSERTING oracle.
End state: an I/O-bound module cannot merge to the real branch unless a non-hermetic oracle executes
its real production entrypoint, a new I/O-bound leaf without such an oracle is rejected at plan time,
and the whole class that shipped the broken drive_backup adapter is gated — all behind a default-OFF
flag whose flip is owner-gated on the recorded dogfood.

# Non-Goals

No modification of `smoke_import` (the new gate is additive). No new agent spawns, model/API/network
calls, or un-injected subprocesses in the deterministic leaves — the AST scans and file reads flow
through injected seams so oracles run hermetically. The gate proves the real entrypoint is EXECUTED
by a non-hermetic oracle, NOT that the oracle's assertions are adequate (the mutation gate + review
remain the backstop for "executes but asserts nothing" — state this; do not pretend coverage).
Reflectively-constructed entrypoints beyond the AST/`ENTRYPOINT_NAMES` view are a stated blind spot,
not silently covered. INTEGRATION leaves preserve all existing behaviour and tests and stay behind
the default-OFF `autowork.integration_smoke_gate` flag. The flag flip is owner-gated on the dogfood.
Do NOT re-fix the drive_backup adapter (already fixed); use it only as a regression fixture.
