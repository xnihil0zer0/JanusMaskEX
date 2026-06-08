---
interfaces: "extends the existing pure helper `harness.planner.cli._finalize_epic_children(merged, epic_wd, child_epics)` with near-synonym (subset-token) dedup IN ADDITION to its current exact-canonical dedup; no signature change, no other function touched"
---

# Title

B1: collapse near-synonym epic child sub-epics in _finalize_epic_children (subset-token dedup) to stop ~2x leaf-build duplication

# Scope

The epic decomposer reconciles TWO child-grouping proposals (the brief's
suggested grouping + the agents' re-derived grouping). They emit the SAME
semantic sub-epics under slugs that differ only by an added domain-qualifier
token — e.g. `analytics-and-roi` vs `kg-analytics-and-roi`, or
`kg-graph-and-extraction` vs `kg-knowledge-graph-and-extraction`. The current
`_finalize_epic_children` dedupes ONLY by exact canonical slug (`_`->`-`), so
both twins survive as distinct child sub-epics. Each twin then decomposes into
the SAME leaves, which self-dedup at build time but only AFTER each redundant
leaf runs a full dual-agent synthesis and blocks — roughly DOUBLING the
wall-time and token cost of the whole epic tree (observed: ~half of all build
cycles are `task_blocked` redundant rebuilds).

Fix: extend `_finalize_epic_children` so that, in addition to the existing
exact-canonical dedup (which MUST be preserved), it also drops a child whose
SIGNIFICANT-TOKEN SET is a subset of, equal to, or a superset of an
already-kept child's token set (a near-synonym twin). First-seen of each group
wins (consistent with the existing first-wins canonical dedup). This is safe:
near-synonym twins decompose into the same leaves, so coverage is preserved
(the handoff's own tolerance rationale). Genuinely distinct sub-epics — those
with no subset/superset token relationship — are all kept.

EXACT behaviour to reproduce (the committed oracle
`tests/planner/test_epic_child_subset_dedup.py` is authoritative):

1. Keep the existing structure: iterate `merged` in order; skip children with a
   falsy `slug`; canonicalize `slug` via `str(slug).strip().replace('_','-')`;
   maintain the existing `seen` set of canonical slugs and skip a child whose
   canonical slug is already in `seen` (exact dedup, first wins).
2. NEW near-synonym dedup, applied to children that pass the exact-canonical
   check: compute the child's token set =
   `frozenset(canonical.split('-')) - _STOPWORDS` where
   `_STOPWORDS = frozenset({'and','of','the','for','to','a','an'})`. Maintain a
   list `kept_token_sets` of the token sets of children already KEPT.
   - If the token set is NON-EMPTY and, for ANY `ts` in `kept_token_sets`, the
     child's token set `<= ts` OR `ts <= child_tokens` (subset, equal, or
     superset), then DROP this child (it is a near-synonym twin; first wins).
   - Otherwise KEEP the child: append its token set to `kept_token_sets`, add
     its canonical slug to `seen`, and emit the finalized child.
   - An EMPTY token set (e.g. a slug that is all stopwords) falls back to
     canonical-only dedup — it is NOT subset-matched (so all-stopword slugs do
     not collapse together).
3. Preserve every existing post-keep behaviour verbatim for kept children: build
   `new_child = dict(child)`, set `new_child['slug'] = canonical`, stamp
   `working_dir = epic_wd` when `epic_wd` is a non-empty str and the child lacks
   a truthy `working_dir`, and set `new_child['epic'] = True` when `child_epics`
   is truthy. Append `new_child` to the result list.
4. The helper stays PURE: it returns a NEW list of NEW dicts and never mutates
   the input list or its dicts. Idempotent on an already-deduped list.

`_STOPWORDS` may be defined as a module-level constant or a local inside the
function (local is fine; do not add new top-level symbols beyond what is needed).

# Required plan shape

EXACTLY ONE task. `meta_task_type: planner_tooling` (the target
`harness/planner/cli.py` is NOT on the `_NEVER_AUTO_APPROVE` deny-list, so this
auto-commits on the worker path with NO operator decision file). A single-symbol
partial edit of `_finalize_epic_children` ONLY (do NOT touch `_run_epic_pipeline`
or any other function; do NOT whole-file edit `cli.py`). No test-authoring task
(oracle already committed). `verification_command:
python -m pytest tests/planner/test_epic_child_subset_dedup.py tests/planner/test_epic_pipeline_dedup_childepics.py tests/planner/test_epic_pipeline_working_dir.py -q`
(the new oracle PLUS the two existing epic-pipeline suites, to prove no
regression). Do NOT glob `tests/planner/`.

# Non-Goals

Do NOT change the `_finalize_epic_children` signature. Do NOT remove or weaken
the existing exact-canonical (`_`->`-`, first-wins) dedup, the working_dir
stamping, or the `child_epics` epic-marking — only ADD the subset-token pass on
top. Do NOT touch `_run_epic_pipeline`, the reconciliation/diff stages, or any
other module. Do NOT add a config flag. Do NOT whole-file edit `cli.py`. Keep
the helper pure (new list/dicts, no input mutation). INTEGRATION-TEST EXCLUSION:
this is a pure deterministic in-memory list transform with no I/O, subprocess,
network, or external collaborator, so NO integration test is required or wanted
— the committed unit-level oracle fully covers it; exclude integration tests
(record this integration exclusion in the task's non_goals).

# Inputs

`harness/planner/cli.py`: the existing `_finalize_epic_children` (lines ~126-154)
— preserve its canonicalization, `seen`-set exact dedup, working_dir stamping,
and `child_epics` marking; ADD the subset-token near-synonym dedup described
above. The committed RED oracle `tests/planner/test_epic_child_subset_dedup.py`
pins the exact contract; the existing
`tests/planner/test_epic_pipeline_dedup_childepics.py` pins the
backward-compatible behaviour that must NOT regress.

# Deliverables

The extended `_finalize_epic_children` landing green against the committed oracle
and the two named regression suites. IMPLEMENTATION CONSTRAINTS to emit as
implementation_notes: meta_task_type planner_tooling (non-deny -> auto-commit, no
decision file); oracle-first (already committed); single-symbol partial edit of
`_finalize_epic_children` only; verification_command names the three test files
explicitly (no glob, no network, no pip).
