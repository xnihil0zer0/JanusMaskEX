# Title

SMOKE: prove the dual-agent -> AST-merge -> auto-commit pipeline on a fresh clone.

# Scope

A single-file `harness_self_fix` that adds a top-level `__version__ = '0.0.1'`
assignment to `harness/smoke_target.py`. This is the canonical "prove the
pipeline" dispatch a fresh cloner runs to confirm Claude + Gemini synthesis, AST
merge, the verification gate, and the scoped auto-commit all work end-to-end on
their machine. The committed `harness/smoke_target.py` stub deliberately omits
`__version__` so the first dispatch produces a real diff and a real commit.

# Non-Goals

- Do NOT modify any file other than `harness/smoke_target.py`.
- Do NOT change or remove the module docstring; only ADD the `__version__` line.
- Do NOT add imports, functions, or any statement other than the `__version__`
  assignment.
- Do NOT use pytest or xfail-strict markers in the verification_command.

# Inputs

- `harness/smoke_target.py` — a tracked stub module with only a docstring.
- `plan_hooks_smoke.json` — the companion plan carrying the `SMOKE_VERSION` task.

# Deliverables

- `harness/smoke_target.py` with a top-level `__version__ = '0.0.1'` assignment,
  the docstring preserved, and the module still importable / py_compilable.
- An `auto_commit` ledger row in `state/impl_progress.jsonl` and a new git commit
  scoped to `harness/smoke_target.py`.
