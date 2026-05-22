"""JanusMask pipeline smoke-test target (REPL-2).

This module is the deliberate target of the canonical "Prove the pipeline"
dispatch (``brief_hooks_smoke.md`` + ``plan_hooks_smoke.json``). A fresh clone
runs that dispatch to confirm the dual-agent -> AST-merge -> auto-commit path
works end-to-end on this machine: both agents add a ``__version__`` assignment
below, the harness AST-merges + auto-commits the result, and an ``auto_commit``
row lands in ``state/impl_progress.jsonl``.

The committed stub intentionally does NOT define ``__version__`` so the first
dispatch produces a real diff (and a real commit). See README "Prove the
pipeline".
"""