# Root cause: brief `priority: P1` -> planner_validation_rejected (rc=2)

## Symptom (telemetry, state/impl_progress.jsonl:107469/107489/107491)
```
event: planner_validation_rejected
detail: watchdog_stall_detect_escalate wall=92.2 reason=rc=2
  stderr_tail=...path='tasks[0](id=watchdog-stall-detect-escalate-oracle).priority',
  message="priority 'P1' not in canonical {critical,high,medium,low} — run scripts/impl_normalize_priority.py to fix"
```
- Rejected value = EXACTLY `'P1'` (uppercase, no whitespace).
- Offending task = a `test_authoring` ORACLE (`watchdog-stall-detect-escalate-oracle`).
- Exit code = **rc=2**.

## Why the prior fix (978f16a) does NOT cover this
- 978f16a added `_PRIORITY_NORMALIZATION_MAP` + `_normalize_task_priorities` and wired them
  as the LAST pass of `normalize_plan` (plan_normalizer.py:1147-1150).
- That pass DOES map exact `'P1' -> 'high'`. Proven by repro (`_autowork_scratch/repro_priority_gap.py`):
  `input='P1' | normalize_plan-> 'high' | priority_violations=0`.
- So the MERGED-plan path in cli.py:493-500 (which runs normalize_plan at :494 BEFORE
  validate_plan at :497, exits **rc=1** on failure) would NOT reject exact 'P1'.

## The ACTUAL rejecting site (rc=2 is the tell)
- rc=2 != cli.py:500 (`sys.exit(1)`). rc=2 == **cli.py:461-462** "Both agents failed to produce a valid draft".
- That branch is reached because BOTH agent drafts were dropped at the BLIND-DRAFT collection gate:
  `harness/planner/blind_draft.py:187  violations = _validate_plan(draft)` -> :188-190 returns status `'invalid'`.
- `blind_draft.py:187` validates the RAW agent draft with **NO `normalize_plan` first**
  (only `_coerce_meta_task_types` at :178 and `_synthesize_wiring_oracle_tokens` at :180 run).
- Both blind-draft agents copy `priority: P1` verbatim from the brief body. The leaf planning
  prompt (`blind_draft.py:256`) embeds `{brief.raw_text}` (full markdown incl. frontmatter
  `priority: P1`) and shows schema `"priority": "..."` with NO canonical-vocabulary guidance,
  so the agent has no reason to translate P1->high. Both drafts -> 'P1' -> rejected -> rc=2.

## Third unnormalized site (same class)
- `harness/hooks/rpc/submit_plan_draft.py:29  return list(validate_plan(args))` — the single-shot
  PreToolUse submission gate — also validates the RAW draft with no normalize.

## The gap in one sentence
`normalize_plan` (which DOES fix 'P1') runs only on the MERGED plan in cli.py; the EARLIER
blind-draft collection gate (and the submit_plan_draft PreToolUse gate) validate the raw
agent draft with no normalization, so a draft carrying 'P1' is rejected as invalid before it
ever reaches the merge — both drafts die, the planner exits rc=2, the brief parks.

## Fix (reusable, single file)
Normalize task priorities on the draft in `harness/planner/blind_draft.py` BEFORE `_validate_plan(draft)`,
reusing the already-exported `harness.planner.plan_normalizer._normalize_task_priorities`. Purely
widening (canonical inputs unchanged; a genuinely bad value still falls through to the fail-closed
validator). Hooks exactly at the proven rejection site, pre-validation.

## Repro evidence
`PYTHONPATH=. python _autowork_scratch/repro_priority_gap.py`:
- input='P1' -> normalize_plan-> 'high', priority_violations=0  (map covers exact P1)
- input='p1' -> 'p1', priority_violations=1                     (case variant NOT covered)
- input='P1 '-> 'P1 ', priority_violations=1                    (whitespace NOT covered)
=> the map is also brittle to case/whitespace; the impl additionally hardens the map
   (case-insensitive + strip) so the same brittleness can't bite the merged path either.
