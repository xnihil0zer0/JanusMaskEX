# JanusMaskEX test tiers — inner-loop speedups (levers 1–3).
#
# Hand-landed bootstrap (config/invocation only; no harness logic). The LOGIC
# pieces — auto-tagging slow tests, making the non-hermetic test cluster
# parallel-safe, and wiring impact-selection into the orchestrator's per-task
# verification — are landed through the pipeline with oracles. See the brief.
#
# Tiers (fastest-feedback first):
#
#   make test-changed  IMPACT-SELECTED (testmon): runs only the tests affected
#                      by the current working-tree diff, serially & hermetically.
#                      First run warms the .testmondata DB (full serial cost);
#                      every run after is seconds. This is the RECOMMENDED inner
#                      loop — it sidesteps the parallel-safety problem entirely.
#
#   make test-fast     FAST SCREEN (parallel, ~4.5x: ~145s vs ~650s). Good for a
#                      quick "did I break something far away" check. NOT a gate:
#                      a cluster of non-hermetic tests (the P2 mutation-kill
#                      suite, crash-recovery adversarial tests, config-default
#                      assertions) write shared on-disk state and flake
#                      NONDETERMINISTICALLY across workers — a different handful
#                      fails each run. Re-confirm anything it flags with
#                      test-full before believing it.
#
#   make test-full     AUTHORITATIVE GATE (serial, ~11 min). The result of
#                      record. Use before commit / for "0 new regressions".
#
# Pipeline-brief targets (to retire the caveats above): make the non-hermetic
# cluster write only under tmp_path / per-worker dirs so `-n auto` becomes
# gate-trustworthy, and add the conftest auto-`slow`-marker so test-fast can
# also drop the heavy integration tier.
PY ?= python
PYTEST := $(PY) -m pytest -p no:cacheprovider -q
# testmon needs the cacheprovider plugin (it reads the `lf` option), so its
# invocation must NOT pass `-p no:cacheprovider`.
PYTEST_TM := $(PY) -m pytest -q

# The two worst, reliably-reproducible parallel offenders, pruned from the
# screen so it is less noisy. (Not a complete list — the flake set varies.)
PARALLEL_UNSAFE := \
	--deselect "tests/test_sandbox_recursion.py::test_recursion_depth_below_limit_always_succeeds" \
	--deselect "tests/adversarial/test_P2_mutation_kill.py::TestZeroSentinel::test_aac_crash_recovery_sidecar_present"

.PHONY: test-full test-fast test-changed

test-full:
	$(PYTEST)

test-fast:
	$(PYTEST) -n auto --dist loadscope $(PARALLEL_UNSAFE)

test-changed:
	$(PYTEST_TM) --testmon
