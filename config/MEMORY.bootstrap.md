# MEMORY.md — operator memory index (bootstrap seed)

This is a clone-survivable seed copied here by `scripts/bootstrap.sh` on a fresh
clone (REPL-9). The live operator memory dir
(`~/.claude/projects/<slug>/memory/`) is keyed to the absolute CWD and does not
survive a clone, so this seed primes a new checkout with the load-bearing
operating procedure. Per-session wrap memos accrete below over time.

## Three standing rules (full rationale in docs/operator-context.md)

1. **`claude --model opus` always.** Haiku/Sonnet fail the validator on tasks
   Opus passes. They are wrong defaults the operator never sanctioned.
2. **META freeze.** New `brief_hooks_*.md` files need a P-phase blocker citation,
   a critical regression, or an explicit `[FREEZE-LIFT]` waiver. Editing existing
   briefs is fine.
3. **Planner Gemini hallucination guard.** Sub-10s Gemini drafts are typically
   hallucinated. Sanity-check hand-authored plans against the brief's `# Title`
   and `# Scope`.

## Operating procedure (the dispatch loop)

1. Pick work — briefs are "what's queued", ledger + `git log` are "what's done".
2. Plan (Path-B): `python -m harness.planner.cli <brief>.md` if no companion plan.
3. Stage + dispatch:
   `python scripts/impl_plan_to_queue.py plan_hooks_<slug>.json --task <ID> --canonical`
   then `python -m harness.orchestrator_worker --state-dir state --task-id <ID>`.
4. Review: `grep <ID> state/impl_progress.jsonl` for `"event": "auto_commit"`.
5. Close: rebase drift pin, run pytest baseline, record a wrap memo here.

## Prove the pipeline (first-run smoke)

```bash
python scripts/impl_plan_to_queue.py plan_hooks_smoke.json --task SMOKE_VERSION --canonical
python -m harness.orchestrator_worker --state-dir state --task-id SMOKE_VERSION
```
Expect: `harness/smoke_target.py` gains `__version__ = '0.0.1'`, a scoped commit,
and an `auto_commit` row for `SMOKE_VERSION`.

## Durable observations

(Add `session_*`, `feedback_*`, `project_*`, `user_*` memos as one file per
durable, non-obvious fact. Do not record things git can already tell you.)
