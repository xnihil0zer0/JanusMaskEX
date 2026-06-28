---
working_dir: "/home/xnihil0zer0/AI-Data/JanusMaskEX"
required_task_ids:
  - planner-validation-cause-extractor-impl
interfaces: "OBSERVABILITY ROOT-FIX. When the planner subprocess (`python -m harness.planner.cli`) rejects a merged plan it prints the STRUCTURED cause to stderr — `harness/planner/cli.py:499` `print(f'Merged plan failed validation: {violations}')` (leaf path) and `harness/planner/cli.py:348` `print(repr(v))` per hard violation (epic path) — then `sys.exit(1)`. But `_run_planner_subprocess` (`harness/autowork_daemon.py:1597`) keeps ONLY `_err[-512:]`; the agent-teardown noise emitted AFTER the cause (`harness/control_gate.py:135` `could not record {agent}_pid=...: 'str' object has no attribute 'mkdir'` + `harness/planner/adversarial_review.py:191` reviewer `killing (adversarial_review_cleanup)` ORCH lines) is >512 bytes, so the real cause is PUSHED OFF the tail. The `planner_validation_rejected` ledger row at autowork_daemon.py:1920 then records noise-only `stderr_tail`, and the deterministic classifier at autowork_daemon.py:1911/1954 (token list incl `missing_required_task`,`failed validation`) returns FALSE because no token survives in the tail — MISCLASSIFYING a deterministic plan-validation rejection as a transient crash (300s retry tier instead of escalating-deterministic park). PROVEN LIVE: all 6 `c7_*` rejections (`state/impl_progress.jsonl`) carry noise-only tails (`'str' object has no attribute 'mkdir'`), zero deterministic-token match, while the true cause was `PlanViolation(code='missing_required_task', path='plan.tasks', ...)` for brief-declared `required_task_ids` (`c7c-seams-env-phase-impl`,`c7c-conductor-env-impl`). This brief adds a deterministic, side-effect-free FULL-stderr cause extractor and routes its output into the return tuple, the ledger `detail`, AND the classifier — so the structured PlanViolation reason is surfaced regardless of trailing noise."
---

# Title
Surface the structured planner PlanViolation cause (don't lose it behind truncated teardown noise)

# Scope
EDIT ONE EXISTING file (READ it first): `harness/autowork_daemon.py`.

`harness/autowork_daemon.py` is in `harness/orchestrator.py:2651` `_NEVER_AUTO_APPROVE`
(`'harness/autowork_daemon.py'`), so the implementation task requires an operator decision file at
`state/control/decisions/planner-validation-cause-extractor-impl.json` (the operator authors that
file; the planner/worker do NOT). It is a `harness/**` path, so the impl task is meta_task_type
`harness_self_fix` and must be emitted as `__JANUSMASK_PATCHES__` (symbol patches; NOT a whole-file
manifest — whole-file on this file deterministically yields `whole_file_drift`).

# Background — the live shapes (RE-CONFIRM by reading the file)

`_run_planner_subprocess` (`harness/autowork_daemon.py:1565`) runs the planner and returns
`(rc, wall, stderr_tail)`. On the normal-exit path it keeps `stderr_tail = _err[-512:]` (line 1597);
the timeout path keeps `err_bytes[-512:]` (line 1585). The FULL `_err` bytes are available at the
point of truncation but are discarded.

The non-zero-rc consumer (`harness/autowork_daemon.py:1883`) emits `planner_validation_rejected` with
`detail = f'{target_slug} wall={wall:.1f} reason=rc={rc}'` plus `stderr_tail={escaped}` where
`escaped = stderr_tail[:256]` (line 1918). The deterministic classifier is at line 1911 (and the
hallucination sibling at line 1954):
`is_deterministic = prev_deterministic or any(tok in (stderr_tail or '').lower() for tok in
('planvalidationerror','missing required field','validation failed','failed validation',
'missing_required_child','missing_required_task'))`.

The planner emits the structured cause on stderr BEFORE exiting non-zero:
- leaf path: `harness/planner/cli.py:499` → `Merged plan failed validation: [PlanViolation(code=..., path=..., message=...), ...]`
- epic path: `harness/planner/cli.py:348` → one `repr(PlanViolation(...))` line per hard violation.
Both forms contain the literal substrings `PlanViolation(` and `code=`.

# Functional requirements

1. ADD a new top-level pure helper
   `_extract_planner_validation_cause(full_stderr_text: str) -> str` to `harness/autowork_daemon.py`.
   - Deterministic, no I/O, no clock, no randomness, no module-level side-effect.
   - Input is the FULL decoded stderr text (NOT the 512-byte tail).
   - Scans the text line-by-line and returns the FIRST line that carries the structured planner
     validation cause, identified by containing EITHER `Merged plan failed validation:`
     (leaf form) OR the substring `PlanViolation(code=` (epic per-violation repr; tolerate both
     `code='x'` and `code=x`). If multiple `PlanViolation(` lines are present (epic), return them
     JOINED into one string separated by ` | ` so every hard violation code survives, capped at a
     generous length (e.g. first 1024 chars of the joined result) so the row stays bounded.
   - Returns `''` when no such marker line exists (non-validation failures — e.g. `Brief load
     failed`, `Track record unavailable` — must NOT be misreported as validation causes; those
     already land cleanly in the existing 512-byte tail).
   - Must NEVER raise: wrap the scan so a None / non-str / undecodable input returns `''`.

2. WIDEN the capture in `_run_planner_subprocess` so the cause survives. Change BOTH truncation sites
   (the normal-exit `_err[-512:]` at line ~1597 AND the timeout `err_bytes[-512:]` at line ~1585)
   to ALSO compute the full-text cause and RETURN it. Make `_run_planner_subprocess` return a
   4-tuple `(rc, wall, stderr_tail, validation_cause)` where `validation_cause =
   _extract_planner_validation_cause(<full decoded stderr>)` (decode the full bytes with
   `errors='replace'` BEFORE slicing the tail). Keep `stderr_tail` exactly as today (last 512 bytes)
   for backward continuity. On the OSError early-return (line 1571) and any path with no stderr,
   `validation_cause` is `''`.

3. THREAD the new field through the single caller. At `harness/autowork_daemon.py:1854`
   (`rc, wall, stderr_tail = _run_planner_subprocess(...)`) and its `except` fallback at line 1856,
   capture the result DEFENSIVELY so EXISTING test seams keep passing: the test file
   `tests/adversarial/test_autowork_auto_promote.py` monkeypatches `_run_planner_subprocess` with
   fakes that today return a 3-tuple `(rc, wall, stderr_tail)` (e.g. `(0, 35.0, '')` at the kickoff
   test, `(0, 2.0, '')` at the hallucination test). The caller MUST tolerate BOTH 3- and 4-tuples:
   read the result into a single variable, then derive `validation_cause = result[3]` only when
   `len(result) >= 4` else `''` (and `rc, wall, stderr_tail = result[0], result[1], result[2]`). The
   `except` fallback is `(1, 0.0, '', '')`. Coerce `validation_cause` to `str` if not a str (mirror
   the existing `stderr_tail` coercion at line 1857). This keeps the two existing 3-tuple-returning
   monkeypatched tests GREEN without editing them.

4. PRIORITIZE the cause in the ledger detail. In BOTH the `rc not in (0,124)` block (detail built at
   line 1916) AND the hallucination block (detail built at line 1959), when `validation_cause` is
   non-empty, APPEND ` cause={validation_cause[:512]}` (newline-escaped like the existing tail) to
   `detail` BEFORE the `stderr_tail=` suffix, so an operator reading the ledger sees the real
   `PlanViolation(code=...)` first. Keep the existing `stderr_tail=` suffix unchanged.

5. FEED the cause into the deterministic classifier so truncation can no longer downgrade a
   validation rejection to transient. At BOTH classifier sites (line 1911 and line 1954) change the
   token scan to run over `((stderr_tail or '') + ' ' + (validation_cause or '')).lower()` instead of
   only `stderr_tail`. The `prev_deterministic` sticky term and the token list are unchanged. This
   makes `is_deterministic` True whenever the FULL stderr carried a validation token, even if the
   512-byte tail is pure teardown noise.

# Non-goals (integration excused)
- Do NOT change `harness/planner/cli.py`, `harness/control_gate.py`, or
  `harness/planner/adversarial_review.py`. The benign `mkdir`/cleanup noise is harmless and
  swallowed by design; this brief makes the cause survive ALONGSIDE it rather than suppressing noise.
- No new config flag, no new module, no signature change to any other function.
- "integration": this is an internal observability fix to a single daemon function; the live
  integration surface is the `_run_planner_subprocess` → `planner_validation_rejected` ledger path
  itself, exercised by the unit/regression oracle below — no separate cross-module integration test
  is required.

# Verification command
`pytest tests/adversarial/test_autowork_auto_promote.py -q`

# Acceptance / oracle intent (for the paired test_authoring task)
The RED oracle must, via `importlib` against `harness.autowork_daemon`, assert:
- `_extract_planner_validation_cause` returns the `Merged plan failed validation: ...` line when the
  full stderr is `"<cause line>\n" + (">512 bytes of 'could not record claude_pid=...: 'str' object
  has no attribute 'mkdir'' + 'killing (adversarial_review_cleanup)' noise)"`, i.e. the cause is
  recovered even though it is NOT in the last 512 bytes;
- it joins multiple `PlanViolation(code=...)` epic lines with ` | `;
- it returns `''` for a non-validation stderr (e.g. `"Brief load failed: Validation failed\n"` must
  NOT be reported — note `'failed validation'` token is absent there, `'validation failed'` IS the
  brief-load message, so the extractor keys on the `PlanViolation(`/`Merged plan failed validation:`
  markers, NOT on the classifier tokens);
- monkeypatching `_run_planner_subprocess` is the established test seam (it is patched by attribute
  name in this same test file); the oracle may instead unit-test `_extract_planner_validation_cause`
  directly plus a focused assertion that the classifier token-scan now consults `validation_cause`
  (construct a `validation_cause` containing `missing_required_task` with a noise-only `stderr_tail`
  and assert deterministic-classification True).

# Patch recipe (`__JANUSMASK_PATCHES__`, NOT a manifest)
Emit symbol patches against `harness/autowork_daemon.py`:
- ONE R-anchored patch that ADDS the new top-level `_extract_planner_validation_cause` anchored on an
  existing nearby top-level symbol (e.g. `_run_planner_subprocess` or `_check_hallucination`): the
  `code` reproduces the anchor VERBATIM and adds the new `def` (R-anchor required for a brand-new
  top-level symbol, else patch-apply KeyError → opaque `auto_commit_failed`).
- ONE patch for `_run_planner_subprocess` (4-tuple return + full-text decode at both truncation
  sites).
- ONE patch for the function enclosing the caller at line 1854 (unpack the 4-tuple; build the two
  `detail` strings with the new `cause=` prefix; widen both classifier token-scans). If lines
  1854–1962 live in one enclosing function, a single patch on that function covers requirements
  3/4/5; otherwise split per enclosing symbol. Patch DOTTED-named nested symbols via their enclosing
  top-level symbol (1-part bare nested names are rejected).

# Operator decision file (NOT authored by the pipeline)
Because `harness/autowork_daemon.py` ∈ `_NEVER_AUTO_APPROVE`, the operator must place
`state/control/decisions/planner-validation-cause-extractor-impl.json` =
`{"decision":"approve","by":"operator","reason":"surface structured planner PlanViolation cause into the planner_validation_rejected ledger row + deterministic classifier; pure full-stderr extractor + 4-tuple thread in autowork_daemon._run_planner_subprocess"}`
before the impl task can auto-commit.
