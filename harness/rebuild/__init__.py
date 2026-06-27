"""Clean-room AST-rebuild engine (criterion 9).

Given any target project P (a set of .py modules + a pytest suite), this
package harvests P into reconstructible units, strips every body to a
``NotImplementedError`` skeleton, and drives the existing JanusMask
dual-agent pipeline to reconstruct each body BLIND, gated by three checks:

  1. Claude == Gemini over fuzzed inputs (existing diff_fuzzer / AST merge).
  2. merged == ORIGINAL over fuzzed inputs (NEW: harness.rebuild.oracle).
  3. the unit's scoped tests pass (existing verification_command gate).

The engine reuses the harness's differential-fuzzing core directly; the one
genuinely new idea is the oracle gate (feed the stripped original body into
diff_fuzzer as the equivalence side-B). Pointing the engine at JanusMask
itself produces the replicant JanusMaskEX.
"""

__rebuild_engine_version__ = '0.1.0'
