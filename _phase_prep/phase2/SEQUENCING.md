# Phase-II detector build — dispatch sequencing

Two NEW standalone detector modules, each its own pipeline leaf:

| order | task_id              | new file                  | oracle (commit to NGv2 master first)            | verification_command |
|-------|----------------------|---------------------------|--------------------------------------------------|----------------------|
| 1     | `ngv2_ssrf_detect`   | `ngv2/ssrf_detect.py`     | `tests/ngv2/test_ssrf_detect_wired.py`           | `python3 -m pytest -q tests/ngv2/test_ssrf_detect_wired.py` |
| 2     | `ngv2_pathtrav_detect` | `ngv2/pathtrav_detect.py` | `tests/ngv2/test_pathtrav_detect_wired.py`       | `python3 -m pytest -q tests/ngv2/test_pathtrav_detect_wired.py` |

Both `meta_task_type: data_model`, `working_dir: /home/xnihil0zer0/NobleGreedv2`,
`dependencies: []`, single-file whole-file emission.

## Dependency analysis

- **Independent of each other.** Neither imports the other; they touch disjoint
  files. Order 1-vs-2 is arbitrary.
- **Independent of the Phase-I epic (live_bounty_sourcing_and_learning).** The
  detectors are self-contained rules-as-data modules; they do NOT import
  `ngv2/sink_taxonomy.py`, `candidate_builder`, `huntr_refresh`, or any L0–L3
  Phase-I leaf (mirrors how the shipped `ngv2/deser_detect.py` is standalone).
  Hence `dependencies: []` in both briefs — no `sink_taxonomy` dependency was
  declared because there is no real import edge. They can land before, during,
  or after the Phase-I epic with no ordering constraint.
- **They will AUTO-SERIALIZE at runtime regardless of dispatch order.** Both
  resolve `working_dir` to `/home/xnihil0zer0/NobleGreedv2`, which is in
  `_ISOLATED_EXTERNAL_DIRS` (JM `harness/autowork_parallelism.py`, landed
  `4a80a0d`). `can_run_parallel` returns False for two tasks in the same
  isolated external root, so the daemon runs them one at a time even if both are
  queued. This is correct and desired (one mutable NGv2 tree); do not try to
  force parallelism.

## Per-leaf procedure (do this for EACH leaf, in order)

1. **Commit the RED oracle to NGv2 master FIRST.** Copy
   `_phase_prep/phase2/test_<name>_detect_wired.py` →
   `/home/xnihil0zer0/NobleGreedv2/tests/ngv2/test_<name>_detect_wired.py` and
   `git -C /home/xnihil0zer0/NobleGreedv2 add + commit` it BEFORE dispatching the
   leaf. The blind worker's `verification_command` runs the committed oracle from
   the working tree; an uncommitted oracle is invisible to the accept gate and an
   untracked test can poison the patches commit (see memory
   `untracked-test-poisons-patches-commit`). The oracle is RED at commit time
   (module absent) — that is expected; it goes GREEN when the leaf lands.
2. **Dispatch the leaf** with the brief's `# Required plan shape` honored
   verbatim (exact `task_id`, `working_dir`, single `files_touched`, the full
   pinned module source copied into `implementation_notes`). The detector is a
   `data_model` task — no operator decision file needed (no `harness/**` write;
   contrast `concurrency_isolation`, which was `harness_self_fix`).
3. **Verify GREEN**: 13 tests per oracle. On accept, archive-on-integrate flag
   will sweep the spent brief/plan.
4. Confirm NGv2 master is fast-forward-advanced before starting the next leaf
   (the runtime serialization already enforces this, but verify the integrate
   landed and the suite is green: `python3 -m pytest -q tests/ngv2`).

## Pre-flight checks

- `tests/ngv2/` is an already-collected testpath (40+ `_wired` oracles live
  there; `test_pytest_testpaths_wired.py` pins it). No `pytest.ini`/`conftest`
  edit is needed to collect the two new oracles.
- The reference modules + oracles in `_phase_prep/phase2/_reference/` are
  PROVEN: `PYTHONPATH=_reference python3 -m pytest -q
  test_ssrf_detect_wired.py test_pathtrav_detect_wired.py` → **26 passed**, and
  both detectors were run against the real `zilliztech-gptcache` clone (SSRF: 2
  findings / 0 FP; path-trav: 9 findings / 0 literal-path FP). The pinned brief
  source IS the reference source byte-for-byte, so each leaf is a verbatim
  whole-file emission of an already-validated module.

## After BOTH detectors land (OUT OF SCOPE for these two leaves)

A separate downstream EDIT leaf (Phase-I L3-style, with the literal word
"integration" in its Non-Goals exclusions for the detector leaves) must wire
`detect_ssrf` / `detect_path_traversal` into the live scan catalog and lift the
selection_ranker suppression of CWE-918/22 targets (epic acceptance criterion:
"CWE-918/22 targets suppressed until their detectors land"). That wiring is the
Phase-I epic's responsibility, not these standalone detector leaves.
