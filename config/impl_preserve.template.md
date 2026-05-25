# JanusMask phase write allow-list (template)

This file is materialized by `scripts/bootstrap.sh` into
`state/impl_preserve.md` on a fresh checkout. The harness's pre-write
hook (`scripts/impl_pre_write.py`) reads the live `state/impl_preserve.md`
to gate phase-scoped file writes; when working inside a META wave, edits
outside the allow-list below require a `scope_exception` row in
`state/impl_progress.jsonl`.

The live `state/` directory is gitignored, so this template is the
canonical source the bootstrap script copies on first install. Operators
may add audit notes / DoD gaps to the live file freely; bootstrap will
not overwrite an existing `state/impl_preserve.md`.

- Phase: `META`

## Outstanding DoD gaps
- (none — fresh bootstrap)

## Phase META write allow-list
- `state/impl_progress.jsonl`
- `state/impl_preserve.md`
- `brief_hooks_*.md`
- `plan_hooks_*.json`
- `scripts/impl_*.py`
- `scripts/impl_*.sh`
- `scripts/run_adv.py`
- `tests/adversarial/**`
- `.claude/settings.local.json`
