---
working_dir: "/home/xnihil0zer0/JanusMaskJR"
required_task_ids:
  - brief-preflight-validator-oracle2
  - brief-preflight-validator-impl2
interfaces: >
  Add a BRIEF PRE-FLIGHT VALIDATOR by INLINING the validation logic INSIDE the
  existing planner entrypoint `harness/planner/cli.py:main`, run the moment
  `cli.main` starts handling a brief and BEFORE the expensive blind-draft /
  reconciliation pipeline, so a malformed brief FAILS LOUD with the EXACT missing
  element (printed to stderr, captured by the daemon into a `stderr_tail`
  telemetry row + a deterministic plan-attempt park marker) instead of being
  discovered ~15-22 min later as a `validate_plan` rc=2 deterministic stall that
  re-spawns costly self-heal agents.

  REDESIGN — NO NEW TOP-LEVEL SYMBOL: the validation logic is INLINED directly
  inside `main`; there is NO `check_brief_preflight` function and NO
  `BriefViolation` dataclass added to the module. A prior version of this brief
  added a new top-level `check_brief_preflight` function AND modified `main` — a
  TWO-SYMBOL patch on the large `cli.py` that the blind agents could not emit;
  they fell back to a WHOLE-FILE submission that drifted an unrelated symbol
  (`_finalize_epic_children`) and was rejected `whole_file_drift` TWICE. The
  redesign makes the impl a SINGLE-symbol patch on `main` ONLY — the same proven
  single-symbol-reproduce-verbatim shape that landed the diff_fuzzer fix.

  TWO tasks, each editing/creating EXACTLY ONE file:

  (1) brief-preflight-validator-oracle2 (test_authoring):
      RED hermetic oracle in `tests/harness/test_brief_preflight_validator.py`
      (OVERWRITING the committed red test from the prior attempt) that tests
      `cli.main` BEHAVIOR ONLY — it does NOT import `check_brief_preflight` or
      `BriefViolation` (those symbols do NOT exist in the redesign). It drives the
      real `cli.main` over synthetic briefs under `tmp_path` and asserts the
      malformed-brief short-circuit (SystemExit code 2, `validation failed` in
      stderr, blind_drafts NOT reached) and the well-formed pass-through
      (blind_drafts IS reached).

  (2) brief-preflight-validator-impl2 (harness_self_fix; harness/planner/cli.py):
      A SINGLE-file `__JANUSMASK_PATCHES__` submission with EXACTLY ONE
      `kind:"symbol"` entry on `main` (name `main`) that reproduces `main`
      VERBATIM from disk plus the inserted inline preflight block. NO new
      top-level symbol, NO R-anchor, NO second symbol patch, NEVER a whole-file
      submission. `harness/planner/cli.py` is NOT in `_NEVER_AUTO_APPROVE`, so NO
      operator decision file is required.
---

# Title
Add a brief pre-flight validator INLINED into `harness/planner/cli.py:main` so a
malformed brief FAILS LOUD with the exact missing element (missing heading section,
a task missing the `integration` excuse, a task missing edge_case->regression
guidance, or a `required_task_ids` mismatch) BEFORE the expensive planner pipeline
runs — instead of silently deterministic-stalling the daemon ~15-22 min later.

# Scope
TWO tasks. One `test_authoring` oracle and ONE `harness_self_fix` impl task, each
editing/creating EXACTLY ONE file. READ each file first.

1. `brief-preflight-validator-oracle2` (test_authoring) OVERWRITES
   `tests/harness/test_brief_preflight_validator.py` with a RED hermetic oracle
   that tests `cli.main` BEHAVIOR ONLY (NO import of `check_brief_preflight` or
   `BriefViolation` — those symbols do NOT exist in this redesign). NO production
   edit in this task.

2. `brief-preflight-validator-impl2` (harness_self_fix) MODIFIES ONLY the existing
   `main` function in `harness/planner/cli.py` by INLINING the preflight logic — a
   SINGLE `__JANUSMASK_PATCHES__` SYMBOL patch with EXACTLY ONE entry (name `main`)
   that reproduces `main` VERBATIM plus the inserted block. NO new module, NO new
   top-level symbol, NO second symbol patch, NEVER a whole-file submission.
   `harness/planner/cli.py` is NOT in `_NEVER_AUTO_APPROVE`, so it is an
   auto-approve-eligible `harness/**` edit needing NO operator decision file.

This brief fixes a RECURRING pipeline-cleanliness defect (a malformed brief
silently stalls the daemon) at its ROOT — the missing earliest-possible fail-loud
check — rather than band-aiding each instance.

# Background — the silent-stall mechanism, the prior-attempt failure, and the redesign (verified)

WHY THE REDESIGN (the load-bearing design change): a prior version of this brief
told the impl to (a) ADD a new top-level `check_brief_preflight` function +
`BriefViolation` dataclass (R-anchored on `main`) AND (b) MODIFY `main` — a
TWO-symbol `__JANUSMASK_PATCHES__` patch on the large `harness/planner/cli.py`. The
blind agents could NOT reliably emit that two-symbol patch; they fell back to a
WHOLE-FILE submission that drifted an UNRELATED symbol (`_finalize_epic_children`)
and was rejected `whole_file_drift` TWICE. Meanwhile the prior oracle (which
imported the not-yet-existing `check_brief_preflight`) had already committed,
leaving a RED test on HEAD. The redesign eliminates BOTH problems: INLINE the
validation logic directly inside `main` so the impl is a SINGLE-symbol patch on
`main` (no new symbol, no R-anchor, no second symbol, no whole-file drift), and
re-author the oracle to test `main` BEHAVIOR ONLY (no `check_brief_preflight`
import) so a fresh oracle OVERWRITES the committed red test and resolves the rot.

A brief is promoted by the daemon's in-process `_auto_promote`
(`harness/autowork_daemon.py`). When it picks an `unplanned`, eligible,
non-recently-failed brief it spawns the planner via `_run_planner_subprocess`,
which runs `python -m harness.planner.cli <brief> --output-plan <plan>`. Inside the
planner (`harness/planner/cli.py:main`, line ~399) the flow is: parse args ->
bootstrap shim -> load config -> `state_dir = Path('state')` (line 440) ->
`try: brief_obj = load_brief(parsed.brief) except Exception: sys.exit(3)`
(lines 441-445) -> `from harness.depth_validator import check_brief_depth`
(line 446) -> `_should_run_epic` -> `blind_drafts` (line 456) -> reconciliation ->
adversarial_review -> auto_amend_gate -> normalize_plan -> `validate_plan`
(line 497). `blind_drafts` spawns the model agents — that is the expensive step
(~minutes).

The three observed silent-stall classes all fail AFTER the expensive step (or in
`load_brief` with a generic exit-3) and surface only as a deterministic park:
  - A brief whose per-task `non_goals` omits the literal word `integration` makes
    the planner emit a plan with zero `integration_tests` and no excuse, so the
    FINAL `validate_plan` (line 497) returns a `missing_integration_test`
    violation -> `cli.main` exits 1 (`plan_validator.py:252-256`).
  - A brief whose a task lacks edge_case->regression guidance yields a plan
    failing `missing_edge_case_tests` (`plan_validator.py:257-263`) -> same exit 1.
  - A brief omitting a required heading (`# Title` etc.) makes `load_brief` raise
    `BriefValidationError` -> `cli.main` exits 3 with a generic message
    (`cli.py:443-445`) — no per-element detail surfaced, and the model spawn for
    the OTHER (integration/edge_case) shapes is already wasted by then.
In every case the daemon's `_auto_promote` non-zero-rc branch (`rc not in (0,
124)`, `autowork_daemon.py:1883-1922`) deletes the partial plan, writes a
`plan_attempts/<slug>.json` park marker, and emits `planner_validation_rejected`.
The marker is stamped `deterministic: true` when `stderr_tail` contains one of
`('planvalidationerror','missing required field','validation failed','failed
validation','missing_required_child','missing_required_task')`
(`autowork_daemon.py:1911`, VERIFIED); a deterministic marker parks the slug for
24h after ONE attempt. Net effect: a malformed brief burns one full planner spawn
(model agents, minutes) THEN sits silently parked, and the inactivity watchdog
re-spawns self-heal agents.

THE RIGHT SEAM (VERIFIED BY PROTOTYPE): insert the inline preflight block in
`cli.main` EARLY — immediately AFTER `state_dir = Path('state')` (line 440) and
BEFORE the existing `try: brief_obj = load_brief(parsed.brief) except Exception:
sys.exit(3)` block (lines 441-445). CRITICAL: it must come BEFORE that try/except,
NOT after it. The inline logic ITSELF calls `load_brief` internally and maps a
`BriefValidationError` (e.g. missing `# Title`) to a missing-section violation; if
it ran AFTER the existing try/except, that existing `except Exception:
sys.exit(3)` would fire FIRST for the single most common malformed shape (a missing
heading) and the preflight would never run for it. Placed BEFORE the try/except,
the preflight short-circuits with `sys.exit(2)` (loud, per-element, deterministic
token) for ALL THREE shapes (missing heading, missing `integration`, missing
edge_case) BEFORE any model agent spawns. A WELL-FORMED brief yields an empty
violation list, so the block is a no-op and `main` proceeds to its existing
`load_brief` -> `check_brief_depth` -> `blind_drafts` flow EXACTLY as today
(PROTOTYPE-CONFIRMED on an isolated copy of cli.py: missing-`# Title` exits 2 not
3 and short-circuits before `blind_drafts`; a clean brief reaches `blind_drafts`).

SINGLE-SOURCE-OF-TRUTH NOTE: the preflight does NOT re-run `validate_plan` (it runs
before any plan exists). It is a STATIC TEXT check on the brief that mirrors the
SAME predicate the validator enforces: `validate_plan`'s `missing_integration_test`
is excused iff `any('integration' in str(ng).lower() for ng in non_goals)`
(`plan_validator.py:254`, VERIFIED); the inline `integration` check mirrors exactly
that "literal word `integration` present" predicate, applied to the brief's
task-section TEXT. `missing_edge_case_tests` (`plan_validator.py:257-263`, VERIFIED)
is satisfied when edge_cases are reflected in regression/property tests; the inline
check mirrors this by requiring each task section to MENTION edge_case OR
regression/property guidance.

# Inputs
READ these files FIRST in `/home/xnihil0zer0/JanusMaskJR`:

- `harness/planner/cli.py` — the file TASK 2 EDITS (NON-trust-core). VERIFIED:
  module top imports are `argparse, importlib.util, json, logging, shutil, sys,
  from pathlib import Path, yaml` — it does NOT import `re` at module top, so the
  inline block MUST add a LOCAL `import re` inside the block (module-level imports
  CANNOT ride in a symbol patch — a symbol patch replaces ONE function body, not
  the module header). `main` is the top-level function at line 399. The inline
  preflight block goes EARLY in `main`: immediately AFTER `state_dir =
  Path('state')` (line 440) and BEFORE the `try: brief_obj = load_brief(parsed.brief)
  except Exception: sys.exit(3)` block (lines 441-445) — see the Background "RIGHT
  SEAM" note for WHY it must precede that try/except. `sys` and `Path` are already
  imported at module top; `parsed.brief` is a `Path`. `blind_drafts` is a
  module-level function (`cli.py:50`), so the wiring oracle can monkeypatch
  `harness.planner.cli.blind_drafts`. cli.py already imports `load_brief` from
  `brief_loader` (line 47); `_parse_frontmatter` is imported locally elsewhere in
  the module (line 287). The inline block adds its own LOCAL imports of
  `BriefValidationError`, `REQUIRED_SECTIONS`, `_parse_frontmatter` from
  `harness.planner.brief_loader`.

- `harness/planner/brief_loader.py` — the loader the inline block REUSES (DO NOT
  EDIT). VERIFIED: `load_brief(path, max_bytes=...) -> PlanningBrief` raises
  `BriefValidationError` (with `.missing: list[str]` and `.empty: list[str]`) when a
  required heading section is absent/empty (`BriefValidationError('Validation
  failed', missing=..., empty=...)` at line 191). `REQUIRED_SECTIONS =
  {'title','scope','non_goals','inputs','deliverables'}` (line 58).
  `_parse_frontmatter(text) -> (fm: dict, body: str)` (line 60) parses the YAML
  front-matter INDEPENDENTLY of heading validation (so it still yields
  `required_task_ids` even when `# Title` is missing). The inline block IMPORTS
  these names (`load_brief` already at cli.py:47; `BriefValidationError`,
  `REQUIRED_SECTIONS`, `_parse_frontmatter` added as a LOCAL import inside the
  block) — they are NOT redefined and brief_loader is NOT edited.

- `harness/planner/plan_validator.py` — the validator whose predicates the inline
  block mirrors. VERIFIED `missing_integration_test` excuse predicate (line 254):
  `excused = any('integration' in str(ng).lower() for ng in non_goals)`. VERIFIED
  `missing_edge_case_tests` (lines 257-263): needs `min(2, len(edge_cases))`
  edge_cases reflected in `regression_tests + property_tests`. DO NOT EDIT — read
  for the exact predicate wording only.

- `harness/autowork_daemon.py` — DO NOT EDIT (in `_NEVER_AUTO_APPROVE`; read for
  context only). VERIFIED: `_auto_promote` non-zero-rc branch at lines 1883-1922
  treats `rc not in (0, 124)` as `planner_validation_rejected`, deletes the partial
  plan, and stamps the park marker `deterministic: true` iff `stderr_tail` (last 512
  bytes of the planner's stderr) contains one of the tokens listed in the Background
  section (line 1911, VERIFIED — `'validation failed'` is one of them). The inline
  block's stderr MUST therefore contain the literal token `validation failed` so the
  brief parks deterministically rather than retrying in a costly loop, AND so the
  exact missing elements ride along in the `stderr_tail=` field. This brief does NOT
  edit the daemon; the daemon's existing handling is already correct.

- `tests/harness/test_brief_preflight_validator.py` — the COMMITTED RED TEST from
  the prior attempt (imports the non-existent `check_brief_preflight`/
  `BriefViolation` at its top, so it errors on collection on HEAD). TASK 1
  OVERWRITES this file entirely with the redesigned behavior-only oracle. READ it
  to confirm what is being replaced; the new file must NOT import
  `check_brief_preflight` or `BriefViolation`.

- `tests/test_rebuild_brief_loader_oracle.py` and any `tests/harness/test_*` — DO
  NOT EDIT (read for the established hermetic `tmp_path` oracle pattern: write
  synthetic brief files under `tmp_path`, drive the entrypoint, assert on behavior;
  NO real `state/`, NO network, NO shared global mutation). Generated oracles import
  the module-under-test via the normal package import (`from harness.planner.cli
  import main`), NOT via `exec`/`eval`/`__import__` (AST-banned).

# Non-Goals
Integration is out of scope (the literal word `integration` MUST appear in this
Non-Goals section AND in EACH task's `non_goals` guidance to excuse the
`validate_plan` integration-test requirement — this brief eats its own dogfood).
Specifically OUT OF SCOPE / HONEST LIMITATIONS:
- Adding ANY new top-level symbol to `harness/planner/cli.py` (NO
  `check_brief_preflight` function, NO `BriefViolation` dataclass). The validation
  logic is INLINED directly inside `main`. The impl is a SINGLE-symbol patch on
  `main` ONLY; there is NO R-anchor and NO second symbol patch.
- Creating ANY new `.py` module anywhere. NO standalone preflight module, NO
  `harness/brief_preflight.py`, NO addition to `harness/planner/brief_loader.py`.
- A WHOLE-FILE submission of `harness/planner/cli.py`. The impl MUST be a
  single-symbol `__JANUSMASK_PATCHES__` patch on `main`. The prior attempt's
  whole-file fallback drifted the unrelated `_finalize_epic_children` symbol and
  was rejected `whole_file_drift` twice; the impl MUST touch NO symbol other than
  `main`.
- Editing `harness/planner/brief_loader.py`, `harness/autowork_daemon.py` (in
  `_NEVER_AUTO_APPROVE`), `harness/planner/plan_validator.py`,
  `harness/orchestrator.py`, or ANY file other than the one each task's
  `files_touched` declares. The inline block REUSES `brief_loader`'s `load_brief` /
  `BriefValidationError` / `REQUIRED_SECTIONS` / `_parse_frontmatter` by IMPORTING
  them. The daemon's existing non-zero-rc handling is reused as-is; no daemon edit
  and no operator decision file are needed.
- Re-running or duplicating `validate_plan`. The preflight runs BEFORE any plan
  exists; it is a STATIC TEXT heuristic on the brief that MIRRORS the validator's
  `integration`-excuse and edge_case predicates, not a re-derivation of the full
  plan schema. It will NOT catch every malformed plan the planner could emit —
  those remain caught by the FINAL `validate_plan` exactly as today. The preflight's
  job is to catch the THREE observed deterministic-stall shapes cheaply and loudly,
  not to be a complete plan oracle.
- Heuristic false-negative/positive tuning beyond the three observed shapes. The
  task-section parse keys on `## ... TASK ...` headings and a canonical `- `task_id`
  bullet; a brief that declares tasks in some other prose form is treated as having
  zero parseable task sections (the per-task checks simply do not fire) — that is an
  accepted limitation, NOT a hard failure, so the preflight never blocks a
  well-formed-but-unconventionally-formatted brief.
- Auto-FIXING a malformed brief, or writing any state/control marker itself. The
  inline preflight is READ-ONLY: it computes a violation list inside `main`; `main`
  decides to exit non-zero; the daemon writes the park marker. The inline block
  performs NO process spawn, NO network, NO model call, and NO filesystem write.
- Wiring the preflight into any OTHER call site (e.g. allowlist edit time, or a
  `brief_status` hook). The single `cli.main` early seam is the earliest
  known-promoted point reachable without a trust-core edit and is sufficient — a
  second call site is out of scope.

# Deliverables

## TASK 1 — brief-preflight-validator-oracle2 (test_authoring; harness.planner.cli)
The test_authoring stage OVERWRITES `tests/harness/test_brief_preflight_validator.py`
with a RED hermetic oracle (NO production edit) that tests `cli.main` BEHAVIOR ONLY.
CRITICAL: the new oracle MUST NOT import `check_brief_preflight` or `BriefViolation`
— those symbols do NOT exist in the redesign (the prior committed test imported them
and is the red rot being resolved). Import ONLY `from harness.planner.cli import
main`. It MUST be hermetic: write synthetic brief `.md` files under `tmp_path`, drive
`main([...])` in-process, and assert on `SystemExit` / stderr / a monkeypatched
sentinel. NO real `state/`, NO network, NO shared global mutation. RED on HEAD:
`main` has no preflight block yet, so the malformed-brief tests do NOT yet exit 2 and
the short-circuit assertions fail (the missing-`# Title` brief exits 3 via the
existing `load_brief` try/except, and the missing-`integration` brief proceeds to
`blind_drafts`); they go GREEN only after TASK 2 inlines the preflight.

HERMETIC SETUP each test needs (so `main` runs in-process without a real model
spawn or config dependency):
- `monkeypatch.setattr('harness.orchestrator.load_config', lambda *a, **k: {})` so
  config load is a no-op stub.
- `monkeypatch.setattr('harness.depth_validator.check_brief_depth', lambda *a, **k:
  True)` so the depth gate never trips.
- A synthetic-brief writer that emits a brief with all five heading sections
  (`# Title`/`# Scope`/`# Non-Goals`/`# Inputs`/`# Deliverables`), a front-matter
  `required_task_ids` list, and one `## TASK 1 — <id>` section whose body contains a
  canonical `- `task_id: <id>`` bullet, the literal word `integration`, and an
  edge_case/regression mention — with toggles to DROP `# Title`, DROP `integration`
  from the task body, DROP the edge_case/regression mention, or mismatch the rti.

ANTI-GAMING ORACLE REQUIREMENTS (derive expectations from the synthetic brief text
the test writes; do NOT paste the impl source into the test; do NOT assert against a
frozen literal stderr message — assert on `SystemExit.code`, on the `validation
failed` token, and on substrings the test itself injected, e.g. the synthetic task
id or section name):

(a) MALFORMED BRIEF SHORT-CIRCUITS BEFORE THE MODEL SPAWN (the core wiring proof):
- MISSING `# Title`: write a brief DROPPING the `# Title` heading. Monkeypatch
  `harness.planner.cli.blind_drafts` to a record-and-flag sentinel (set a flag /
  append to a list — do NOT have it raise a plain `Exception`, because `main` wraps
  the `blind_drafts` call in `try/except Exception: sys.exit(2)` at cli.py:457 and
  would SWALLOW a plain-Exception raise; a record-flag sentinel that returns is the
  robust choice for the short-circuit test). Invoke `main([str(brief_path)])`,
  assert it raises `SystemExit` with code `2`, assert the sentinel flag was NEVER
  set (blind_drafts NOT reached), capture stderr (via `capsys`) and assert it
  contains the literal `validation failed` token (case-insensitive) AND names the
  missing section `title` (case-insensitive). NOTE: passing only `[str(brief_path)]`
  uses the default `--output-plan` under `state/planning/...`; the short-circuit
  before that write proves the brief never reached the persist step.
- TASK MISSING `integration`: write a brief with all five headings but whose
  `## TASK 1 — <id>` body does NOT contain the word `integration`. Drive `main`,
  assert `SystemExit(2)`, blind_drafts NOT reached, stderr contains `validation
  failed` AND names the offending task id `<id>` (the id the test itself injected).
- TASK MISSING edge_case GUIDANCE (regression anchor): write a brief whose task body
  lacks any edge_case/regression/property mention. Drive `main`, assert
  `SystemExit(2)` and blind_drafts NOT reached.

(b) WELL-FORMED BRIEF PROCEEDS PAST THE PREFLIGHT (false-positive guard, regression
anchor): with a complete synthetic brief, monkeypatch
`harness.planner.cli.blind_drafts` to a sentinel that raises a recognizable
`BaseException` SUBCLASS (e.g. `class ReachedBlindDrafts(BaseException): pass`) —
NOT a plain `Exception` — so it ESCAPES `main`'s `try/except Exception` around the
`blind_drafts` call (cli.py:457) and proves the well-formed brief reached
`blind_drafts` rather than being swallowed into a spurious `sys.exit(2)`. Invoke
`main([str(brief_path)])` and assert it raises `ReachedBlindDrafts` (i.e. it
PROCEEDED past the preflight) — proving a clean brief is NOT falsely rejected and the
new block is a no-op on a well-formed brief. (THIS IS LOAD-BEARING and
PROTOTYPE-VERIFIED: a plain-`Exception` sentinel is caught by main's existing
`except Exception: ... sys.exit(2)` and would make the well-formed brief LOOK
rejected — use a `BaseException` subclass so the sentinel escapes.)

(c) DETERMINISM (regression anchor): drive `main` over the SAME malformed brief
twice and assert the same `SystemExit.code` (2) both times (deterministic
rejection), proving the preflight is a pure static check.

The wiring tests MUST drive the real `cli.main`, MUST NOT assert against a frozen
plan/stderr literal, MUST NOT special-case a fixture name, and MUST be hermetic
(synthetic briefs under `tmp_path`, monkeypatched downstream steps, no real model
spawn, no network).

`non_goals` MUST contain the literal word `integration` (a full live-daemon
integration round-trip is out of scope for this hermetic unit oracle — the wiring
tests drive `cli.main` in-process with monkeypatched downstream steps).
`regression_tests >= 2` (e.g. the well-formed-proceeds guard, the missing-edge_case
guard, and the determinism guard are regression anchors).

- `task_id: brief-preflight-validator-oracle2`
- `priority: high`
- `meta_task_type: test_authoring`
- `files_touched: ["tests/harness/test_brief_preflight_validator.py"]`
- `mutation_target: harness.planner.cli`  (BARE DOTTED module-under-test, no `.py`,
  no slashes — this is the module the oracle exercises)
- `dependencies: []`
- `verification_command:` `python -m pytest tests/harness/test_brief_preflight_validator.py -q`
  (RED against HEAD — `main` has no preflight block; do NOT use a broad `pytest
  tests/adversarial/ -q` vcmd).

## TASK 2 — brief-preflight-validator-impl2 (harness_self_fix; harness/planner/cli.py)

NON-TRUST-CORE: `harness/planner/cli.py` is NOT in `_NEVER_AUTO_APPROVE`, so this
task is auto-approve-eligible and REQUIRES NO operator decision file.

IMPLEMENTATION NOTES (LOAD-BEARING — GENERAL correct behavior, NOT fixture-matching):

1. PATCH SHAPE — SINGLE FILE, SINGLE SYMBOL PATCH ON `main`, VERBATIM REPRODUCE +
   INSERT (NO new symbol, NO R-anchor, NEVER whole-file): emit ONE
   `__JANUSMASK_PATCHES__` submission against `harness/planner/cli.py` with EXACTLY
   ONE `kind:"symbol"` entry:
       `{file: 'harness/planner/cli.py', kind: 'symbol', name: 'main',
         code: r'''<the existing main reproduced VERBATIM from disk PLUS the
         inserted inline preflight block>'''}`
   Reproduce the CURRENT `main` body EXACTLY as it is on disk (read the file first),
   changing ONLY the one inserted block described in note 2. Do NOT add any new
   top-level symbol, do NOT add a `BriefViolation` dataclass, do NOT add a
   `check_brief_preflight` function, do NOT use an R-anchor, do NOT emit a second
   symbol entry, and do NOT emit `__JANUSMASK_MANIFEST__`. NEVER submit a whole file.
   This is the SAME proven single-symbol-reproduce-verbatim shape that landed the
   diff_fuzzer fix. WHY THIS SHAPE (the prior failure to avoid): the prior attempt
   used a TWO-symbol patch (new `check_brief_preflight` + modified `main`); the blind
   agents could not emit it and fell back to a WHOLE-FILE submission that drifted the
   unrelated `_finalize_epic_children` symbol and was rejected `whole_file_drift`
   TWICE. A single-symbol patch on `main` that reproduces `main` verbatim and touches
   NO other symbol cannot drift another symbol and cannot trigger `whole_file_drift`.

2. THE INLINE BLOCK — PLACEMENT IS LOAD-BEARING: insert the preflight block EARLY in
   `main`, immediately AFTER `state_dir = Path('state')` (line 440) and BEFORE the
   existing `try: brief_obj = load_brief(parsed.brief) except Exception:
   sys.exit(3)` block (lines 441-445). It MUST come BEFORE that try/except, NOT
   after: the inline logic itself calls `load_brief` internally, and if it ran AFTER
   the try/except, the existing `except Exception: sys.exit(3)` would fire FIRST for
   a missing-heading brief (the most common malformed shape) and the preflight would
   never run for it. PROTOTYPE-VERIFIED on an isolated copy: placing the block BEFORE
   the try/except makes a missing-`# Title` brief exit 2 (not 3) and short-circuit
   before `blind_drafts`. The inserted block computes a list of violation strings
   (call it `preflight_violations`) using the inline logic of note 3, then:
     - the WHOLE computation is wrapped in `try/except Exception` that, on an
       UNEXPECTED error, sets `preflight_violations = []` and CONTINUES (does NOT
       exit) — the preflight must never HARD-FAIL a brief on its own bug; fail-open
       to the existing pipeline so a preflight defect can only ever make the daemon
       behave as it does today, never worse.
     - `if preflight_violations:` -> print a FIRST stderr line containing the literal
       token `validation failed` (so the daemon's `is_deterministic` token match at
       `autowork_daemon.py:1911` fires and the brief parks deterministically), e.g.
       `print(f'Brief pre-flight validation failed (PLANNER_BRIEF_PREFLIGHT):
       {len(preflight_violations)} violation(s)', file=sys.stderr)`, then print EACH
       violation on its own stderr line (so they land in the 512-byte `stderr_tail`
       the daemon captures), then `sys.exit(2)`.
   A WELL-FORMED brief yields an empty list, so the block is a no-op and `main`
   proceeds into its existing `load_brief` -> `check_brief_depth` -> epic/leaf flow
   EXACTLY as today (PROTOTYPE-CONFIRMED: a clean brief reaches `blind_drafts`).

3. THE INLINE VALIDATION LOGIC (inside `main`, computing `preflight_violations`):
   use a LOCAL `import re` at the top of the block (module-level imports CANNOT ride
   in a symbol patch). Add a LOCAL import `from harness.planner.brief_loader import
   BriefValidationError, REQUIRED_SECTIONS, _parse_frontmatter` (the module-level
   `load_brief` already imported at cli.py:47 is reused; `Path` and `sys` are already
   module-level). Build `preflight_violations` as a list of human-readable strings
   (each including a stable code prefix so the code substring rides in stderr_tail):
   - READ the brief text: `text = Path(parsed.brief).read_text(encoding='utf-8')`
     inside a `try/except Exception` — on read failure append
     `'unreadable_brief: <path>'` and SKIP the rest (do NOT raise).
   - (a) HEADING SECTIONS: call `load_brief(parsed.brief)` inside a try. On
     `BriefValidationError`, if `e.missing` append a line like
     `'missing_brief_section: <sorted missing names>'` (so `title` appears verbatim
     when `# Title` is absent), and if `e.empty` append `'empty_brief_section: <sorted
     empty names>'`. On any OTHER exception from `load_brief`, append
     `'brief_load_error: <e>'`. REUSE the imported `REQUIRED_SECTIONS`
     (Title/Scope/Non-Goals/Inputs/Deliverables) — do NOT hardcode a divergent set.
   - parse front-matter via `_parse_frontmatter(text)` (heading-independent, so it
     yields `required_task_ids` even when `# Title` is missing) inside a
     `try/except` that falls back to `({}, text)` on error.
   - (b) PER-TASK DIRECTIVES: split the body into task sections. A task section
     starts at a markdown heading matching `^##\s+.*\bTASK\b` (case-insensitive) and
     runs to the next `^##\s+` heading (or EOF). Within each task section, extract
     the declared task id from the CANONICAL BULLET DIRECTIVE line — a line matching
     `^\s*-\s*` then optional backtick then `task_id` then `:`/`=` then the id
     (tolerate backticks), e.g. ``- `task_id: foo-impl` `` -> `foo-impl`. ANCHOR to
     that bullet form and take the LAST such match in the section (a section's PROSE
     may mention `task_id:` for OTHER ids in example/anti-gaming text; anchoring to
     the canonical bullet and taking the LAST match avoids a SPURIOUS rti mismatch —
     PROTOTYPE-VERIFIED on a brief with a decoy `task_id:` in prose). For EACH task
     section:
       * INTEGRATION: if the section text does NOT contain the literal word
         `integration` (case-insensitive word-boundary, e.g. `re.search(r'\bintegration\b',
         text, re.IGNORECASE)`), append `'task_missing_integration_directive:
         task=<id>'` naming the task id (or the heading text when no id parses). This
         MIRRORS `plan_validator.py:254`'s excuse predicate.
       * EDGE_CASE: if the section text contains NEITHER an edge_case mention
         (`edge[_ ]?case`, case-insensitive) NOR a regression/property mention
         (`regression_tests?` / `property_tests?`), append
         `'task_missing_edge_case_directive: task=<id>'`. This mirrors
         `plan_validator.py:257-263`.
   - (c) `required_task_ids` CONSISTENCY: read `required_task_ids` from the
     `_parse_frontmatter(text)` front-matter dict (coerce list/tuple/comma-string ->
     set of stripped strings) — DO NOT read it via `load_brief(...).required_task_ids`,
     because `load_brief` RAISES when a heading is missing, so an all-at-once brief
     (missing `# Title` AND a bad rti) would never reach the rti check. Collect the
     set of `## TASK` section task ids from (b). If a `required_task_ids` entry has no
     matching section, append `'required_task_id_without_section: <sorted orphans>'`;
     if a section task id is absent from `required_task_ids`, append
     `'task_section_not_in_required: <sorted extras>'`. Only run (c) when at least
     one of the two sets is non-empty.
   - Build the violation list deterministically (e.g. `sorted(...)` before returning)
     so two `main` invocations on the same input behave identically. The inline logic
     NEVER raises out of the block (the outer `try/except` of note 2 guarantees
     fail-open) and NEVER writes anything.

4. GENERALITY: do NOT special-case any brief filename, slug, task id, or fixture
   string. Every check is driven by the brief text + `load_brief` /
   `_parse_frontmatter` for ANY brief. Report ALL violations found in one pass (do
   NOT fail-fast / return after the first).

ANTI-GAMING ORACLE REQUIREMENT (TASK 2): make the TASK 1 oracle GREEN by GENERAL
behavior (real `load_brief` mapping + real task-section text scan over the synthetic
briefs + real `cli.main` short-circuit), NOT by detecting the fixture. Re-run the
EXACT TASK 1 vcmd before dispatch and confirm `N passed` with N >= 2.

`non_goals` MUST contain the literal word `integration` (cross-process integration
with the live daemon is out of scope; this task delivers an inline, hermetically
unit-tested preflight inside `main`). `regression_tests >= 2`.

- `task_id: brief-preflight-validator-impl2`
- `priority: high`
- `meta_task_type: harness_self_fix`
- `files_touched: ["harness/planner/cli.py"]`
- OMIT `mutation_target` (impl task editing a `harness/**` module).
- `dependencies: ["brief-preflight-validator-oracle2"]` (RED oracle first; the
  single-symbol impl turns the WHOLE oracle green at once; red-pair preserved).
- Emit ONE `__JANUSMASK_PATCHES__` SYMBOL patch with EXACTLY ONE `kind:"symbol"`
  entry on `main` (reproduce `main` verbatim plus the inserted block; touch NO other
  symbol; NEVER a whole file).
- `verification_command:` `python -m pytest tests/harness/test_brief_preflight_validator.py -q`
  (the SAME scoped oracle TASK 1 authored — a single impl makes ALL of it green; do
  NOT use a broad `pytest tests/adversarial/ -q` vcmd). Run the EXACT vcmd yourself
  before dispatch and confirm `N passed` with N >= 2.

# Required plan shape
Emit EXACTLY TWO tasks (pin via `required_task_ids: [brief-preflight-validator-
oracle2, brief-preflight-validator-impl2]`). PRIORITY MUST be canonical lowercase
(`high`), NEVER P0/P1/ints/Capitalized.
  - TASK 1 is `test_authoring` (OVERWRITES the committed red test with a
    behavior-only oracle driving `cli.main`; imports ONLY `main`, NOT
    `check_brief_preflight`/`BriefViolation`; carries `mutation_target:
    harness.planner.cli`, BARE DOTTED module path only; `dependencies: []`).
  - TASK 2 is `harness_self_fix` (MODIFIES ONLY `main` in the EXISTING
    `harness/planner/cli.py` via a SINGLE-symbol `__JANUSMASK_PATCHES__` patch on
    `main` — reproduce `main` verbatim plus the inserted inline block; OMITS
    `mutation_target`; depends on TASK 1). NO new symbol, NO new module, NEVER a
    whole-file submission.
Each task emits a single-file submission (TASK 1 the overwritten test file; TASK 2 a
single-file single-symbol `__JANUSMASK_PATCHES__` SYMBOL patch on
`harness/planner/cli.py`). Each task's `non_goals` MUST contain the literal word
`integration`; each `regression_tests >= 2`. Do NOT add any task touching a file
other than the one its `files_touched` declares; do NOT add a task editing
`brief_loader.py`, `autowork_daemon.py`, `plan_validator.py`, `orchestrator.py`, or
`config.yaml`; do NOT add a task creating any new `.py` module or new top-level
symbol.

BOTH files (`harness/planner/cli.py`,
`tests/harness/test_brief_preflight_validator.py`) are NON-trust-core (the
irreducible `_NEVER_AUTO_APPROVE` set is `harness/agent_jail.py`,
`harness/dbus_proxy.py`, `harness/paths.py`, `harness/git_integration.py`,
`harness/orchestrator.py`, `harness/interceptors.py`, `harness/selfheal.py`,
`harness/autowork_daemon.py`, `services/**`), so NO task requires an operator
decision file and `harness/autowork_daemon.py` is NOT edited.
