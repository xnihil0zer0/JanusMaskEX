---
working_dir: "/home/xnihil0zer0/AI-Data/JanusMaskEX"
required_task_ids:
  - gitignore-scratch-dirs-superseded-oracle
  - gitignore-scratch-dirs-superseded-impl
interfaces: >
  EDIT EXACTLY ONE existing file: the repository-root `.gitignore` (a non-.py
  config/doc file, so `meta_task_type: docs_writing` and a `__JANUSMASK_MANIFEST__`
  WHOLE-FILE edit — NOT symbol patches). The factory's operation deposits a fixed
  set of TRANSIENT scratch directories at the repo root that are never tracked and
  permanently pollute `git status` (verified untracked right now:
  `_autowork_scratch/`, `_c3_pending/`, `_ngv2_staged_oracles/`, `_phase4_rebrief/`,
  `_phase_prep/`) plus spent-brief `.superseded` sidecars (e.g.
  `brief_hooks_p11_build_evidence_perphase.md.superseded`). `.gitignore` already
  ignores the factory's OTHER generated trees (`state/`, `logs/`, `_abandoned/`,
  `_archive/`, `_autowork_archive/`, `.agents/`, `JanusMaskEX_agentwork/`,
  `.testmondata*`) but NOT these. FIX: append the five scratch-dir entries and the
  `*.superseded` pattern to `.gitignore` so they stop appearing as untracked noise.
  This is purely a git-tracking hygiene change (gitignore never deletes or moves a
  file on disk and never changes any already-TRACKED file's status), and it
  deliberately does NOT touch the research/PDF dirs or external-repo clones the
  owner may want to keep visible (see Non-Goals).
---

# Title
.gitignore the factory's transient root scratch dirs + spent-brief .superseded
sidecars (git-status hygiene; non-destructive; whole-file docs_writing edit)

# Scope
EDIT the SINGLE EXISTING repo-root file `.gitignore` (READ it first). SINGLE
FILE. `.gitignore` is NOT a `.py` file (so it is NOT module-creating) and is NOT
under any sensitive apply glob (`_SENSITIVE_APPLY_GLOBS = ('harness/**',
'config/**', 'scripts/**', 'services/**')`), so this is an ordinary
`meta_task_type: docs_writing` pure-edit, NOT `harness_self_fix`, and needs no
operator decision file. Because the target is non-.py, the edit is emitted as a
`__JANUSMASK_MANIFEST__` WHOLE-FILE submission (the multi-file/non-.py path —
the `.files.json` whole-file branch), NOT a `__JANUSMASK_PATCHES__` symbol patch.

The edit is purely ADDITIVE: keep every existing `.gitignore` line byte-for-byte
in order and APPEND a new clearly-commented section with six entries.

# Background — why these scratch dirs / sidecars pollute git status (verified)
`git status --porcelain` on this repo currently lists, among the untracked
clutter, these factory-deposited transient root entries that have NO reason to be
tracked:
  - `_autowork_scratch/` — autowork repro scripts / log scratch (the clutter
    scanner in `harness/state_reconciler.py:511` only READS its aged children to
    REPORT them; gitignoring it does NOT affect that read — gitignore only changes
    git tracking, never the filesystem).
  - `_c3_pending/`, `_ngv2_staged_oracles/`, `_phase4_rebrief/`, `_phase_prep/` —
    manual/NGv2 staging + phase-prep scratch; NO `harness/` or `tools/` code
    references any of the four (verified grep), so they are pure scratch.
  - spent-brief `.superseded` sidecars — a superseded brief is renamed to
    `<brief>.md.superseded` (e.g. `brief_hooks_p11_build_evidence_perphase.md.superseded`);
    these are dead paperwork that should never be tracked.

`.gitignore` ALREADY ignores the factory's other generated trees — `state/`,
`logs/`, `_abandoned/`, `_archive/`, `_autowork_archive/` (added by
`reaper-converge-impl` 38d2527 precisely so the archive destination stops
appearing as `?? _autowork_archive` noise), `.agents/`, `JanusMaskEX_agentwork/`,
`.testmondata*` — establishing the exact precedent: transient factory output is
gitignored, not tracked. The five scratch dirs and `*.superseded` were simply
never added. This brief closes that gap.

SAFETY: gitignoring a path is non-destructive — it changes only whether git
treats the path as untracked-noise; it never deletes/moves a file and (critically)
never changes the status of a path that is ALREADY tracked. None of the six
targets is tracked (all are `??` untracked today), so adding them cannot
accidentally drop tracked content. The factory does not require any of these
paths to be git-tracked to function.

WHY A NARROW PATTERN, NOT a blanket `_*/`: a blanket `_*/` would also ignore any
future intentionally-tracked underscore-prefixed dir and is over-broad; the brief
lists the five KNOWN transient scratch dirs explicitly (matching the existing
explicit-entry style of `.gitignore`). `*.superseded` is safe as a global glob
because the suffix is unambiguously dead paperwork.

# Inputs
READ these files FIRST in `/home/xnihil0zer0/AI-Data/JanusMaskEX`:

- `.gitignore` — the SINGLE file the impl task edits. VERIFIED current full
  contents (19 lines; the edit must reproduce ALL of them verbatim then append the
  new section):
      state/
      .venv/
      __pycache__/
      *.pyc
      .hypothesis/
      logs/
      _abandoned/
      _archive/
      # AGENT-ISOLATION §4: vendored, version-pinned agent binaries (reproduce via
      # scripts/setup-agents.sh). Kept out of git — large/host-specific binaries.
      .agents/
      # AGENT-ISOLATION §3.1: per-agent isolated workdirs live OUTSIDE the repo
      # (<repo>_agentwork sibling) so this entry is belt-and-suspenders only.
      JanusMaskEX_agentwork/

      # pytest-testmon impact-selection DB (local, do not commit)
      .testmondata
      .testmondata-journal
      _autowork_archive/
  The new appended section (exact entries to ADD, with a clarifying comment) is:
      # Factory transient root scratch dirs (manual/NGv2 staging + phase prep).
      # Never tracked; deposited by ad-hoc factory work. Filesystem reads (e.g. the
      # state_reconciler clutter scan of _autowork_scratch) are unaffected.
      _autowork_scratch/
      _c3_pending/
      _ngv2_staged_oracles/
      _phase4_rebrief/
      _phase_prep/
      # Spent-brief sidecars renamed when a brief is superseded.
      *.superseded

- `tests/tools/test_brief_reaper_git_converge.py` — DO NOT EDIT (read for the
  test PATTERN only): it builds a `tmp_path` git repo, writes a `.gitignore`,
  `git add`/`commit`s, and asserts `git status --porcelain` does NOT list the
  ignored path as `?? ...` noise (lines 93-119). The oracle for THIS brief mirrors
  that pattern against the repo-root `.gitignore`.

# Non-Goals
Integration is out of scope (the literal word `integration` MUST appear in this
section and in EACH task's `non_goals` to excuse the integration-test
requirement). Specifically OUT OF SCOPE:
- Editing any file other than `.gitignore`. Do NOT touch any `.py` file, the
  allowlist, `harness/config.yaml`, or any harness module.
- Gitignoring (or deleting / moving) the RESEARCH dirs and downloaded PDFs
  (`autocompiler_research/` and its `.pdf`s, `hierarchical_planner_design/`,
  `adversarial_review_*/`, `adversarial_test_plans/`) — the OWNER may want those
  visible / under deliberate version-control review; auto-ignoring them is a
  judgment call out of scope.
- Gitignoring the EXTERNAL-REPO CLONES (`fastgpt/`, `flowise/`, `graphiti/`,
  `mem0/`, `one-api/`, `h4_guildai/`, `w2d_modeldb/`) or `samples/venv/`,
  `cache/`, `held_briefs_selfheal_build/`, `factory-work-handoff.md`,
  `jscpd-report.json`. Several are large clones (~486M total) whose handling
  (submodule vs ignore vs remove) is a separate owner decision; this brief does
  NOT presume to ignore them.
- DELETING or git-rm-ing any existing file. Gitignore is tracking-only; the
  on-disk scratch dirs / `.superseded` files are left in place untouched.
- Using a blanket `_*/` glob (over-broad — see Background). Only the five named
  transient scratch dirs are ignored.
- Adding the entries to the `state_reconciler` clutter scan or any apply/delete
  path. This brief is git-tracking hygiene only.

# Deliverables

## TASK 1 — gitignore-scratch-dirs-superseded-oracle (test_authoring; .gitignore)
The test_authoring stage authors a RED behavioral oracle (NO production edit in
this task). It MUST be a hermetic test that asserts, against the REPO-ROOT
`.gitignore`, that the six target patterns ARE ignored and that the existing
ignores + an UNRELATED path are unaffected — NOT a frozen-blob comparison of the
whole file and NOT satisfiable by hardcoding the expected file text.

ANTI-GAMING ORACLE REQUIREMENTS (the oracle MUST, and MUST NOT leak the answer
key — do NOT paste the expected `.gitignore` bytes into the test, do NOT assert
file equality against a frozen copy):
- Resolve the repo root from the test file location
  (`Path(__file__).resolve().parents[N]`) — do NOT hardcode `/home/...`.
- For EACH of the five scratch dirs (`_autowork_scratch`, `_c3_pending`,
  `_ngv2_staged_oracles`, `_phase4_rebrief`, `_phase_prep`), assert it is IGNORED.
  Prefer the behavioral check `subprocess.run(['git', '-C', str(repo_root),
  'check-ignore', '-q', d])` returns rc 0 (the same semantics git itself applies);
  acceptable fallback is parsing `.gitignore` lines and asserting an exact
  `f'{d}/'` entry is present (stripped, non-comment). The check MUST be against the
  pattern's EFFECT (ignored), not a substring search of the raw bytes.
- Assert a representative `.superseded` path IS ignored: `git check-ignore -q
  some_brief.md.superseded` returns rc 0 (or the `*.superseded` line is present).
- NEGATIVE / NO-OVER-IGNORE: assert an UNRELATED tracked-style path is NOT ignored
  — e.g. `git check-ignore -q harness/orchestrator.py` returns NON-zero, and (to
  prove the brief did not over-reach into research/clones) `git check-ignore -q
  autocompiler_research` returns NON-zero and `git check-ignore -q fastgpt`
  returns NON-zero. This pins the surgical scope.
- REGRESSION (existing ignores intact): assert a pre-existing ignore still holds
  — e.g. `git check-ignore -q _autowork_archive` and `git check-ignore -q state`
  both return rc 0.
This oracle is RED against HEAD (the five scratch dirs + `*.superseded` are NOT
yet ignored — verified: `git check-ignore` returns non-zero for all six today)
and turns GREEN once the impl appends them. It MUST derive its expectations from
git's check-ignore EFFECT, not from a frozen file blob.

`non_goals` MUST contain the literal word `integration`. `regression_tests >= 2`.

- `task_id: gitignore-scratch-dirs-superseded-oracle`
- `priority: high`
- `meta_task_type: test_authoring`
- `files_touched: ["tests/test_gitignore_scratch_dirs.py"]`
  (the RED oracle file)
- OMIT `mutation_target` if the oracle does not exercise a single module
  under-test (it shells out to `git check-ignore` against the repo `.gitignore`,
  not a Python module); if the planner requires one, use the docs target path
  rather than a `.py` module. Do NOT set a `.py` mutation_target that does not
  exist.
- `dependencies: []`
- `verification_command:` `python -m pytest tests/test_gitignore_scratch_dirs.py -q`
  (RED against HEAD; do NOT use a broad `tests/adversarial/ -q` vcmd).

## TASK 2 — gitignore-scratch-dirs-superseded-impl (.gitignore)

IMPLEMENTATION NOTES (LOAD-BEARING):

1. PATCH SHAPE: the target is the non-.py file `.gitignore`, so emit a
   `__JANUSMASK_MANIFEST__` WHOLE-FILE submission mapping `.gitignore` to its
   FULL new contents (the non-.py / multi-file `.files.json` path). Do NOT emit a
   `__JANUSMASK_PATCHES__` symbol patch (symbol patches are for `.py` AST
   symbols; `.gitignore` has no symbols).

2. The new file contents = the EXISTING 19 lines reproduced VERBATIM and in order,
   then the appended section EXACTLY as given in Inputs (the comment lines + the
   five `*/`-suffixed scratch-dir entries + `*.superseded`). Preserve the file's
   trailing newline. Change NOTHING in the existing lines (do not reorder, do not
   drop the AGENT-ISOLATION comments, do not alter `_autowork_archive/`).

3. GENERALITY: the five scratch-dir entries are the GENERAL ignore patterns
   (`_autowork_scratch/` ignores the dir anywhere it appears at that path);
   `*.superseded` is the GENERAL suffix glob. Do NOT add a blanket `_*/` and do NOT
   add any research/clone path.

`non_goals` MUST contain the literal word `integration`. `regression_tests >= 2`.

- `task_id: gitignore-scratch-dirs-superseded-impl`
- `priority: high`
- `meta_task_type: docs_writing`
- `files_touched: [".gitignore"]`
- OMIT `mutation_target`.
- `dependencies: ["gitignore-scratch-dirs-superseded-oracle"]` (the RED oracle
  must exist first; the impl turns it green — preserve the red pair).
- Emit a `__JANUSMASK_MANIFEST__` WHOLE-FILE submission for `.gitignore`.
- `verification_command:` `python -m pytest tests/test_gitignore_scratch_dirs.py -q`
  (the same oracle, now GREEN; do NOT use a broad `tests/adversarial/ -q` vcmd).
  Run the EXACT vcmd yourself before dispatch and confirm `N passed` with N>=2.

# Required plan shape
Emit EXACTLY TWO tasks (pin via
`required_task_ids: [gitignore-scratch-dirs-superseded-oracle, gitignore-scratch-dirs-superseded-impl]`).
PRIORITY MUST be canonical lowercase (`high`), NEVER P0/P1/ints/Capitalized. The
oracle task is `test_authoring` (writes the RED test); the impl task is
`docs_writing` (writes the single non-.py `.gitignore` path via a WHOLE-FILE
`__JANUSMASK_MANIFEST__` submission). Each task's `non_goals` MUST contain the
literal word `integration`; each `regression_tests >= 2`. The impl `dependencies`
on the oracle so the red pair is preserved (oracle RED-before, impl GREEN-after).
Do NOT add any task touching a file other than the one its `files_touched`
declares; do NOT add a task editing any `.py` module, the allowlist, or
`config.yaml`.

`.gitignore` is NOT a sensitive apply glob and NOT in `_NEVER_AUTO_APPROVE`, so
neither task needs an operator decision file; the ordinary non-sensitive apply
path covers both.
