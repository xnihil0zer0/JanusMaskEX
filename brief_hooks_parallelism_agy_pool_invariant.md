---
required_task_ids:
  - agy_pool_size_invariant_guard
  - agy_pool_enable_and_config_oracle
---

# Title

Parallelism: enable the agy worker-HOME pool and runtime-enforce the size >= parallel_cap invariant

# Scope

This is the first and highest-priority "Parallelism" hardening for the JanusMask
factory. It does two things, both confined to auto-approvable files:

1. Adds a permanent, reusable, independently-testable guard to
   `harness/agy_pool.py` that makes the documented "size < parallel_cap" footgun
   impossible. Today the invariant ("agy_pool.size MUST be >=
   autowork.parallel_cap") is COMMENT-ONLY in `harness/config.yaml`, which even
   warns it is "NOT runtime-enforced". When the pool is enabled but
   `size < parallel_cap`, a concurrent worker beyond `size` gets no slot
   (`allocate_slot` returns None) and silently falls back to the SHARED
   `~/.gemini` HOME -- the exact cred/registry corruption the pool exists to
   prevent. The guard fail-closes (raises a clear, named error) and provides an
   auto-clamp form that guarantees coverage.

2. Enables the pool by flipping `workers.agy_pool.enabled` from `false` to
   `true` in `harness/config.yaml` (size is already 8, which already covers the
   current `autowork.parallel_cap: 5` -- keep size: 8). It also updates the
   config oracle `tests/test_config_agy_pool.py` to assert the new ENABLED
   default so the suite stays consistent.

Only `harness/agy_pool.py`, `harness/config.yaml`, and the two oracle test files
are touched. `harness/agy_pool.py` and `harness/config.yaml` are both
auto-approvable `harness/**` paths (NOT in `_NEVER_AUTO_APPROVE`). The daemon
(`harness/autowork_daemon.py`) and orchestrator (`harness/orchestrator.py`) are
in the irreducible set and are deliberately NOT touched.

# Scope-Notes

The guard is a pure function of the `(enabled, size, parallel_cap)` tuple --
no I/O, stdlib only -- matching the existing style of `harness/agy_pool.py`.

# Inputs

Existing file `harness/agy_pool.py` (the project-local pool module). It already
defines `POOL_SIZE = 4`, `allocate_slot(busy, size=POOL_SIZE)`, `worker_env`,
`ensure_seeded`, `agy_seed_plan`, `pool_root`, `worker_home`.

Add THREE new top-level names to `harness/agy_pool.py`. To avoid the
new-top-level-symbol auto_commit_failed pitfall, edit the file as a WHOLE FILE
via `__JANUSMASK_MANIFEST__` (reproduce the entire existing module verbatim and
append the three new names at module scope):

  1. A named exception:

         class PoolInvariantError(ValueError):
             """The agy pool is enabled but its size cannot cover parallel_cap,
             so a concurrent worker would be left sharing the operator HOME."""

  2. The auto-clamp resolver -- the size the runtime MUST use:

         def effective_pool_size(*, enabled: bool, size: int, parallel_cap: int) -> int:
             """Return the pool size that guarantees a private slot per concurrent
             worker. When the pool is ENABLED the result is never below
             ``parallel_cap`` (clamps UP) so the size<cap footgun cannot occur.
             When DISABLED, the requested ``size`` is returned unchanged (no
             pooling happens, so nothing is inflated)."""
             if not enabled:
                 return size
             return size if size >= parallel_cap else parallel_cap

  3. The strict fail-closed checker:

         def assert_pool_invariant(*, enabled: bool, size: int, parallel_cap: int) -> None:
             """Raise ``PoolInvariantError`` when the pool is enabled and
             ``size < parallel_cap``; a no-op otherwise. The message names both
             the offending ``size`` and ``parallel_cap``."""
             if enabled and size < parallel_cap:
                 raise PoolInvariantError(
                     "agy_pool.size (%r) must be >= autowork.parallel_cap (%r) "
                     "when the pool is enabled, else a concurrent worker beyond "
                     "size gets no slot and silently shares the operator HOME"
                     % (size, parallel_cap)
                 )

Do NOT remove, rename, or alter any existing function/constant in
`harness/agy_pool.py`. `allocate_slot` already returns `None` for `size <= 0`
(`range(0)` is empty) -- keep that behavior; the oracle locks it.

For `harness/config.yaml`: reproduce the ENTIRE file VERBATIM, changing ONLY the
single line under `workers: -> agy_pool:` from `    enabled: false` to
`    enabled: true`. Keep `size: 8` and every comment and every other key
byte-for-byte identical. config.yaml is the master knob file -- any drift beyond
that one line is a defect.

The config oracle `tests/test_config_agy_pool.py` has ALREADY been updated and
committed to assert the pool is ENABLED (`assert pool["enabled"] is True`). Do
NOT touch that test file -- Task 2 edits ONLY `harness/config.yaml`. The single
config flip turns the already-committed oracle GREEN.

The pre-committed RED oracle for the guard already exists at
`tests/harness/test_agy_pool_size_invariant.py` (committed) -- do NOT modify it;
make it pass.

# Non-Goals

- No integration: do NOT edit `harness/autowork_daemon.py` or
  `harness/orchestrator.py` (both irreducible / in `_NEVER_AUTO_APPROVE`). The
  guard is a standalone, unit-tested capability in `harness/agy_pool.py`; wiring
  it into the daemon's `_agy_pool_assign` is explicitly out of scope and would
  require an operator decision file. No integration test is required for this
  brief.
- Do NOT change `size: 8`, `autowork.parallel_cap`, or any other config key.
- Do NOT alter or delete any existing function/constant in `harness/agy_pool.py`.
- Do NOT touch the multi-GB cache seeding logic.

# Deliverables

1. `harness/agy_pool.py` gains `PoolInvariantError`, `effective_pool_size`, and
   `assert_pool_invariant` (all existing names preserved verbatim).
2. `harness/config.yaml` has `workers.agy_pool.enabled: true` (everything else
   byte-identical).
3. The already-committed `tests/test_config_agy_pool.py` (asserting ENABLED) is
   GREEN once the config flip lands.
4. Both verification commands pass GREEN.

# Required plan shape

Produce EXACTLY TWO tasks. BOTH are implementation tasks. Do NOT emit any
`test_authoring` oracle task -- the RED oracle for Task 1 is already
pre-committed, and Task 2's oracle is co-edited inside Task 2 itself.

PRIORITY (applies to BOTH tasks): every emitted task's `priority` field MUST be a
canonical LOWERCASE STRING from exactly {`critical`, `high`, `medium`, `low`}.
Use `high` for both tasks. The priority must be the bare lowercase word -- NOT an
integer, NOT `P0`/`P1`/`P2` (those are research-report PHASE labels, NOT task
priorities), NOT uppercase. The plan validator REJECTS any non-canonical value.

NON-GOALS / INTEGRATION EXCUSE (applies to BOTH tasks): each task's generated
`spec.non_goals` list MUST contain at least one entry with the literal word
`integration` so the per-task integration-test requirement is excused. Neither
task wires the guard into the daemon/orchestrator, so neither needs an
integration test. Put an explicit non_goal like "No integration: the
daemon/orchestrator wiring is out of scope" in BOTH tasks.

TEST_SPEC COUNTS (applies to BOTH tasks -- the plan validator enforces these):
  * `unit_tests` length MUST be >= `functional_requirements` length.
  * `minimum_test_count` MUST be >= 1.5 * len(functional_requirements).
  * `regression_tests` + `property_tests` MUST total >= 2, reflecting the
    task's `edge_cases`. The pre-committed oracle
    `tests/harness/test_agy_pool_size_invariant.py` already exercises the edge
    cases for Task 1 (size-below-cap clamp/raise, disabled-passthrough,
    degenerate-size allocate). Declare at least TWO `regression_tests` per task
    naming those existing oracle tests (Task 1) / the config oracle tests
    (Task 2), so the `missing_edge_case_tests` and `insufficient_*` rules pass.
  * Keep `functional_requirements` SMALL (1-2 per task) so the count thresholds
    are easy to satisfy.

Task 1 -- id: `agy_pool_size_invariant_guard`
  meta_task_type: harness_self_fix
  priority: high
  files_touched: ["harness/agy_pool.py"]
  non_goals: MUST include an entry containing the word `integration`.
  Implements the three new names in `harness/agy_pool.py` (whole-file via
  `__JANUSMASK_MANIFEST__`).
  verification_command: python -m pytest tests/harness/test_agy_pool_size_invariant.py -q

Task 2 -- id: `agy_pool_enable_and_config_oracle`
  meta_task_type: harness_self_fix
  priority: high
  files_touched: ["harness/config.yaml"]
  non_goals: MUST include an entry containing the word `integration`.
  Flips ONLY `workers.agy_pool.enabled` from false to true in `harness/config.yaml`
  (the entire file reproduced verbatim except that one line). Do NOT touch any
  test file -- the config oracle is already committed asserting ENABLED. Emit the
  whole config.yaml content (it is a non-py YAML target: emit it as the single
  submission body, NOT inside a __JANUSMASK_MANIFEST__ -- a single-file non-py
  task is committed by direct whole-file copy).
  verification_command: python -m pytest tests/test_config_agy_pool.py -q
