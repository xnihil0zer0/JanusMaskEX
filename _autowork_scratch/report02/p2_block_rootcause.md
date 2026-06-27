P2 BLOCK ROOT CAUSE (evidence-backed)
=====================================
Ledger row (state/impl_progress.jsonl, worker_exit, ts 1781880134):
  claude partial-edit submission (1 patches) has 1 AST errors:
    security@L253: exec() is banned for security reasons
  gemini partial-edit submission (1 patches) has 1 AST errors:
    security@L283: exec() is banned for security reasons
  outcome=synthesis_or_ast_failed (deterministic, retry budget 1 -> .exhausted)

Banned by harness/ast_enforcer.py:71-72 ({'eval','exec','__import__'}).

Agent submissions (both):
  claude L254: exec(compile(side_code, '<onesided_shadow>', 'exec'), _ns)
  gemini L288: exec(defining_code, locs)

WHY: my P2 brief said "compute _one_sided_fuzz(fn, ...)" where fn is a CALLABLE,
but fuzz_from_task only has code_a/code_b SOURCE STRINGS. To get a callable the
agents reached for exec()/compile() -> banned.

Both agents structured ALL oracle fns correctly (_one_sided_fuzz, _metamorphic_oracle,
_golden_oracle, _onesided_oracle_enabled, _mr_determinism present). ONLY the exec()
bridge in the fuzz_from_task shadow wiring failed.

FIX (brief correction, routed through pipeline): the shadow-mode wiring in
fuzz_from_task MUST NOT exec/compile/eval the candidate. Shadow telemetry logs the
one-sided occurrence + which degrade-ladder TIER would apply (golden present /
relations declared / strategy buildable) WITHOUT executing the candidate in-process.
The oracle fns stay (unit-tested directly with real callables in the authored test).
