# 02 — Apply/Commit, AST-merge, Validation & Fuzzing — Adversarial Test Plan

Exploration agent 2 of 4. Read-only audit; the tester sub-agent executes this plan next
session. Tests must run WITHOUT real agents (no agy/gemini/claude spawn) using a tmp git
worktree, mirroring `tests/adversarial/test_git_integration_acceptance_adversarial.py`.

---

## 1. Area & scope

The submission-application boundary: the moment a dual-agent-agreed (or fuzzer-bypassed)
submission is written to a staging worktree and committed.

- `harness/git_integration.py`
  - `commit_accepted_output` (single-file path, dispatcher)
  - `_commit_accepted_output_multi` (`.files.json` manifest path)
  - `_commit_accepted_output_patches` (`.patches.json` partial-edit path)
  - `_ast_merge` + helpers (`_node_key`, `_merge_class_body`, `_expand_imports`,
    forward-ref reorder, `JANUSMASK_DELETE`)
  - `_apply_file_to_target`, `_apply_symbol_patch`, `_apply_region_patch`, `_parse_patches`
  - `_enforce_apply_scope`, `_matches_sensitive`, `_SENSITIVE_APPLY_GLOBS` (§1b, commit 9e0fc64)
  - `create_staging_worktree` / `remove_staging_worktree`, `_is_tracked`
- `harness/orchestrator.py` apply-side: `_auto_commit_accepted`, `_apply_approval_granted`,
  `_resolve_files_touched`, `_resolve_verification_command`, `_rollback_rejected_commit`,
  `_save_final_output` (sidecar writer), `_parse_manifest`.
- `harness/ast_enforcer.py` `validate_code`; `harness/depth_validator.py` `check_true_depth`
  (commit f1a746b).
- Fuzzing: `harness/diff_fuzzer.py` (`fuzz_from_task`), BYPASS path
  (`BYPASS_FUZZER_TYPES`), `__JANUSMASK_PATCHES__` (BYPASS_WHOLE_FILE, commit ccf28c3),
  `harness/embedded_test_runner.py`, `harness/sandbox.py` (SANDBOX_PATH_FIX, commit 5192c5c).
- The `__JANUSMASK_MANIFEST__` / `__JANUSMASK_PATCHES__` sidecar contract
  (`state/output/<id>.files.json` / `.patches.json`).

---

## 2. 24h changes in this area (verified via `git show`)

| SHA | Files | What changed |
|-----|-------|--------------|
| **9e0fc64** | `git_integration.py` (+90), `orchestrator.py` (+99), `paths.py`, `autowork_daemon.py`, `hooks/*`, `config.yaml`, several tests | **AGENT_ISOLATION §1b apply-path scoping + CWD relocation.** Added `_SENSITIVE_APPLY_GLOBS=('harness/**','config/**','scripts/**')`, `_matches_sensitive`, `_enforce_apply_scope`. All three commit paths (`commit_accepted_output`, `_commit_accepted_output_multi`, `_commit_accepted_output_patches`) gained `*, allowed_files=None, meta_task_type=None, approval_ok=False` kwargs and call `_enforce_apply_scope` per rel-path before writing/committing. `commit_accepted_output` threads them down into the two sidecar dispatchers. Orchestrator `_auto_commit_accepted` now computes `_mtt` + `_approval_ok=_apply_approval_granted(...)` and passes `allowed_files=set(files_touched)`. New `_apply_approval_granted` reads `state/control/decisions/<id>.json`. |
| **f1a746b** | `depth_validator.py` (+2/-2) | Whitespace-only cleanup of `check_true_depth` (trailing-space removal on two blank lines). NO behavior change — RB_JanusMask_check_true_depth was a no-op-grade edit. Worth flagging: a "validated" pipeline commit that changed nothing semantic. |
| **ccf28c3** | `orchestrator.py` (+6/-3) | **BYPASS_WHOLE_FILE.** `prepare_task_prompt` and `_validate_submission` now treat `mtt in BYPASS_FUZZER_TYPES` (not only `task.get('partial_edit')`) as a trigger for the `__JANUSMASK_PATCHES__` partial-edit dispatch/validation path. Moved `mtt` computation earlier in `_validate_submission`. |
| **5192c5c** | `autowork_daemon.py`, `orchestrator_worker.py` (+1/-1 each) | SANDBOX_PATH_FIX — sandbox path correction at two spawn sites (peripheral to git path). |

---

## 3. Architecture map (codebase-memory-mcp + Read)

### Commit/apply flow (accept → commit)
```
orchestrator main loop (round 1 / r2 / bypass branch)
  └─ _auto_commit_accepted(state_dir, task, task_id)        [orchestrator.py:1306]
       ├─ _resolve_files_touched()  -> files_touched (walks parent_task chain)  [:1146]
       ├─ target_rel = files_touched[0]; multi-file-missing-sidecar warn
       ├─ git rev-parse --show-toplevel (cwd=state_dir.parent) -> worktree_root
       ├─ staging = worktree_root.parent/"<name>_staging"
       ├─ create_staging_worktree(staging, parent_root=worktree_root)           [gi:1150]
       ├─ _mtt = task.meta_task_type | constraints.meta_task_type
       ├─ _approval_ok = _apply_approval_granted(state_dir, task_id)            [:1287]
       ├─ flock(git_commit.lock):
       │     commit_accepted_output(task_id, target_abs, state_dir,
       │        worktree_root=staging, allowed_files=set(files_touched),
       │        meta_task_type=_mtt, approval_ok=_approval_ok)                  [gi:558]
       │       ├─ untracked tests/test_*.py auto-detect -> may BUILD .files.json [gi:593-629]
       │       ├─ if .files.json exists -> _commit_accepted_output_multi        [gi:633]
       │       ├─ elif .patches.json exists -> _commit_accepted_output_patches  [gi:636]
       │       └─ else single-file: relative_to guard -> _enforce_apply_scope
       │              -> _ast_merge (if .py & target exists) -> no_diff guard
       │              -> git add/commit --only/rev-parse                        [gi:638-698]
       ├─ if committed: _resolve_verification_command(); if missing/empty ->
       │     _rollback_rejected_commit() + remove_staging + return False        [:1481]
       ├─ run vcmd under /bin/bash 'set -o pipefail; <vcmd>' env-scrubbed; on
       │     nonzero/timeout -> _rollback_rejected_commit + ledger + False
       └─ _rollback_rejected_commit(): HEAD-guarded reset OR git revert <sha>   [:1200]
```

### §1b gate (the dominant invariant)
`_enforce_apply_scope(rel_strs, *, allowed_files, meta_task_type, approval_ok, sensitive_globs)`
[gi:37] enforces two independent constraints per rel-path:
1. **membership** — if `allowed_files is not None`, every committed rel-path MUST be in it
   (else scope-violation error string). `None` opts out (low-level unit tests only).
2. **sensitive** — a path under `harness/**`/`config/**`/`scripts/**` (`_matches_sensitive`,
   prefix test because `fnmatch` does not treat `**` as recursive) is rejected unless
   `meta_task_type=='harness_self_fix' AND approval_ok is True`.
Returns an error string (truthy) on violation, `None` on pass. All callers treat a non-None
return as commit=False with no git invocation.

`_apply_approval_granted` [orch:1287] reads `state/control/decisions/<id>.json`, returns True
only if `decision in {approve,approved}` (case-insensitive, stripped); fails closed on
missing/corrupt/non-dict.

### AST-merge (`_ast_merge` [gi:68])
Top-level name-keyed merge: `('name', n)` for def/async/class, `('assign', id)` for
single-Name Assign/AnnAssign, `('import', ...)`/`('import_from', module, level, bound)` after
per-alias pre-split (`_expand_imports`), `('assign_tuple', ids)` for tuple/list targets.
Matched ClassDefs get additive `_merge_class_body` (recursion cap 5). Non-keyed nodes
preserved positionally. New output nodes inserted before `if __name__=='__main__'` guard;
G17 forward-reference reorder; G18d `# JANUSMASK_DELETE:` directive; G20 AugAssign-by-target
dedup. Raises on `ast.parse` failure; `commit_accepted_output` catches and falls back to
`shutil.copy2`.

### Partial-edit / patches
`_parse_patches` [gi:849] decodes `__JANUSMASK_PATCHES__` list of `{file,kind,name|marker,code}`.
`_apply_symbol_patch` [gi:913] does a text-line-slice replacement of one def/class (top-level
or `Outer.inner`, decorator-extended), re-indents nested by `col_offset`, validates new_block
parses to exactly one matching-leaf def/class. `_apply_region_patch` [gi:990] is text-only
(language-agnostic) sentinel splice requiring exactly one start + one end sentinel.

### Fuzz flow
`fuzz_from_task` [diff_fuzzer.py] builds a hypothesis strategy from `code_a`, runs differential
fuzz, returns `FuzzResult(equivalent, total_inputs, matching_inputs, failures, error)`.
`equivalent = len(failures)==0`. The orchestrator only `_save_final_output` + commits when
`equivalent` (r1 or r2). For `mtt in BYPASS_FUZZER_TYPES` the differential fuzz is SKIPPED and
replaced by smoke_import + run_embedded_tests + run_narrow_fuzz gates (unless mtt also in
`SKIP_SMOKE_GATE_TYPES`). **This bypass is correct by design — do NOT propose narrowing it.**

### Invariants that MUST hold
- **INV-1** Apply path NEVER commits a rel-path outside `files_touched` (membership).
- **INV-2** Apply path NEVER writes/commits into `harness/**` / `config/**` / `scripts/**`
  unless `meta_task_type=='harness_self_fix'` AND an approval decision file fired.
- **INV-3** All three commit paths fail closed: a scope violation returns committed=False with
  NO git add/commit invoked, and no partial on-disk write committed.
- **INV-4** `no_diff` (byte-identical merge) never produces a commit.
- **INV-5** Dual-agent agreement (fuzz `equivalent`) or a sanctioned BYPASS gate is the ONLY
  route to `_save_final_output` + commit. Never weaken this.
- **INV-6** Rollback restores HEAD/worktree without clobbering a peer worker's commit.

---

## 4. Adversarial test plan (enumerated)

> Fixture: reuse the `git_worktree` / `state_dir` / `_git` pattern from
> `test_git_integration_acceptance_adversarial.py`. For commit-path tests that need a staging
> worktree, init a tmp repo, `git worktree add --detach <sibling>` (or call
> `create_staging_worktree`). Sidecars go in `state_dir/output/<id>.files.json|.patches.json`,
> output in `state_dir/output/<id>.py`. NEVER spawn agy/gemini/claude.

### A. §1b apply-path gate (HIGHEST PRIORITY)

**A1 — membership bypass via path normalization (`./`, `a/../b`, trailing slash).**
Target: `git_integration._enforce_apply_scope` + `_commit_accepted_output_multi`.
Scenario: sidecar key `"./pkg/mod.py"` or `"pkg/./mod.py"` or `"pkg/../pkg/mod.py"` while
`allowed_files={"pkg/mod.py"}`. The membership check compares
`str(target_path.relative_to(worktree_root))` (computed from a `.resolve()`d path, so it IS
normalized) against the RAW `allowed_files` strings (only `\`→`/` normalized, NOT
`.resolve()`d). Expected/correct: a normalized-equal path should still be accepted as a member;
a genuinely different path rejected. Suspected incompleteness: `allowed_files` are compared
**verbatim** — if `files_touched` itself contains `"./pkg/mod.py"` the resolved rel-path
`"pkg/mod.py"` will NOT match and a legitimate commit is rejected (false-positive lockout); OR
if the test feeds a non-normalized member it falsely fails. Assert: feed
`allowed_files={"./pkg/mod.py"}` + sidecar `{"pkg/mod.py": ...}` and check whether
commit is wrongly rejected. Mock: tmp repo, no agents.

**A2 — sensitive-glob case / separator evasion.**
Target: `_matches_sensitive`. Scenario: rel-paths `"Harness/x.py"`, `"HARNESS/x.py"`,
`"harness\\x.py"` (backslash already normalized), `"./harness/x.py"`. Expected: an actual
harness write is blocked. Suspected incompleteness: `_matches_sensitive` is case-sensitive and
keys on exact `harness/` prefix; on a case-insensitive FS (`Harness/`) a write could evade the
sensitive gate while still hitting the real `harness/` dir. Also `"./harness/x.py"` — the
single-file path resolves before matching (safe), but the multi/patches paths compute
`rel_str` from `relative_to` (resolved) so the `./` is stripped — confirm both behave. Assert:
each form returns a scope error when `allowed_files=None, meta_task_type=None`. Flag any form
that returns `None` (evasion).

**A3 — sibling-prefix false negative / false positive.**
Target: `_matches_sensitive`. Scenario: `"harness_extra/x.py"` and `"config_backup/y"` and
`"scripts2/z.sh"` MUST NOT match (base+'/' guard); `"harness"` (bare dir name, no file) and
`"harness/"` edge. Existing test already covers `pkg/harness_helper.py` — extend to top-level
sibling dirs. Expected: siblings return `None`; `"harness"` exact returns error
(base==p branch). Assert both directions. Suspected incompleteness: the `p == base` branch
treats a file literally named `harness` (no extension, top-level) as sensitive — likely fine,
but worth pinning.

**A4 — patches path sensitive-write without approval.**
Target: `_commit_accepted_output_patches`. Scenario: `.patches.json` with
`{"file":"harness/orchestrator.py","kind":"symbol","name":"foo","code":"def foo():\n    pass\n"}`,
`allowed_files={"harness/orchestrator.py"}`, `meta_task_type="harness_self_fix"`,
`approval_ok=False`. Expected: scope error, committed=False, NO git commit, target file
on-disk UNMODIFIED (the scope check at gi:1090 precedes `read_text`/`write_text`). Assert:
result['committed'] is False AND the seeded `harness/orchestrator.py` in the tmp worktree is
byte-identical afterward (proves INV-3 fail-closed before write). Then flip `approval_ok=True`
and assert it commits. Mock: tmp repo with a seeded `harness/orchestrator.py`.

**A5 — multi-file manifest with ONE in-scope + ONE out-of-scope target (atomicity).**
Target: `_commit_accepted_output_multi`. Scenario: `.files.json` = `{"pkg/a.py":..,"pkg/evil.py":..}`,
`allowed_files={"pkg/a.py"}`. The loop applies file-by-file and checks scope per rel BEFORE
write. Expected: on reaching `pkg/evil.py` it returns committed=False — BUT note `pkg/a.py`
was ALREADY written to disk via `_apply_file_to_target` in the prior iteration (no
transaction/rollback of the on-disk write). Suspected incompleteness: **partial on-disk
mutation left behind** when a later manifest entry fails scope — the staging worktree is
dirtied even though committed=False. Assert: committed=False AND check whether `pkg/a.py` was
written (document the dirty-staging leak; the orchestrator removes the staging worktree after,
so impact is bounded, but a unit-level commit_accepted_output caller would see it). Order the
dict so the violating entry is NOT first.

**A6 — `allowed_files=None` from a real dispatch (membership disabled).**
Target: `_auto_commit_accepted` → `commit_accepted_output`. Scenario: confirm the orchestrator
ALWAYS passes `allowed_files=set(files_touched)` (gi call at orch:1475) — `files_touched` is
guaranteed non-empty by the early return at orch:1416. So `allowed_files` is never `None`
in production. Adversarial: a task whose `files_touched=["pkg/a.py"]` but whose `.files.json`
sidecar lists `pkg/b.py` (manifest/declared mismatch — agent emitted the wrong rel-path).
Expected: membership rejects `pkg/b.py`. Assert via a constructed task dict + sidecar (no
agents): drive `_auto_commit_accepted` with a tmp repo and assert returns False.

**A7 — meta_task_type read from `constraints` vs top-level disagreement.**
Target: `_auto_commit_accepted` `_mtt` computation (orch:1467) vs `_validate_submission`
(orch:937). Scenario: `task={"meta_task_type":"harness_self_fix"}` but
`task["constraints"]["meta_task_type"]="io_adapter"`. The apply side uses
`task.get('meta_task_type') or (constraints or {}).get(...)` → top-level wins. Confirm the
sensitive gate uses the same precedence the validator/dispatch used (consistency). Suspected
incompleteness: if a task sets `constraints.meta_task_type=harness_self_fix` but top-level
unset, `_mtt` resolves to harness_self_fix — verify that a non-harness_self_fix top-level does
NOT accidentally authorize a sensitive write. Assert the resolved `_mtt` matches what the gate
expects across both placements.

### B. AST-merge edge cases

**B1 — agent submission renames/deletes a target-only top-level symbol via manifest.**
Target: `_ast_merge`. Scenario: target has `def keep()` + `def drop()`; output (single-file)
has only `def drop()` rewritten + a `# JANUSMASK_DELETE: keep` directive. Expected: `keep`
removed, `drop` replaced. Adversarial: a `JANUSMASK_DELETE: _enforce_apply_scope` inside a
submission targeting `git_integration.py` would delete the gate itself — but INV-2 blocks the
write unless harness_self_fix+approval. Assert the delete directive works on a benign target
AND is moot on a sensitive target (blocked upstream). This pins that the DELETE directive can't
be a gate-removal vector without approval.

**B2 — multi-alias import collision / drop.**
Target: `_ast_merge` `_expand_imports`. Scenario: target `from tools import a, b`; output
`from tools import a`. Expected (G23a): `b` preserved (per-alias keys). Assert `b` survives.
Regression-pin (commit history shows this was a real bug class).

**B3 — `_ast_merge` parse failure fallback path.**
Target: `commit_accepted_output` single-file. Scenario: output `.py` is syntactically valid but
the EXISTING target on disk is NOT parseable (e.g. seeded with a syntax error). `_ast_merge`
raises → caught → `shutil.copy2` overwrites the whole target. Expected: copy2 fallback whole-file
replaces. Suspected incompleteness: the fallback DISCARDS the target's other top-level symbols
(it's a whole-file copy, not a merge) — a single-file submission could thereby drop unrelated
code if the target ever has a transient parse error. Assert the fallback produces the output
verbatim and document the data-loss surface. (Scope gate still applies first, so it can't reach
harness/** without approval.)

**B4 — class-body additive merge recursion cap.**
Target: `_ast_merge` `_merge_class_body`. Scenario: deeply nested ClassDef (6 levels) where
the agent omits an inner attribute. Expected: at depth>5 the merge falls back to wholesale
agent replacement → inner target-only node DROPPED. Assert the drop happens at depth 6 (pin the
documented cap as a known data-loss boundary, not a bug to fix).

### C. Partial-edit / patches sidecar

**C1 — symbol patch with mismatched leaf name.**
Target: `_apply_symbol_patch`. Scenario: `name="foo"` but `code` defines `def bar()`. Expected:
`ValueError`, caught in `_commit_accepted_output_patches` → committed=False, target unmodified.
Assert.

**C2 — region patch with duplicate sentinels.**
Target: `_apply_region_patch`. Scenario: file has two `# JANUSMASK_REGION:X` lines. Expected:
`KeyError('expected exactly one start sentinel...')` → committed=False. Assert. Also: end
before start → `ValueError`.

**C3 — multiple patches to one file compose with shifting offsets.**
Target: `_commit_accepted_output_patches`. Scenario: two `symbol` entries for the same file,
the first shortening a def above the second. Expected: second apply re-parses the
in-progress text so line offsets recompute correctly. Assert both edits land. Pin the
compose-correctness claim in the docstring.

**C4 — region patch on a non-`.py` target (language-agnostic claim).**
Target: `_apply_region_patch` via `_commit_accepted_output_patches`. Scenario: a `.js` (or
`.txt`) target with sentinel comments. Expected: region replaced, committed (non-py path
doesn't `ast.parse`). Assert. Edge: a `.js` target is NOT under sensitive globs, membership
must list it.

**C5 — `_parse_patches` rejects `__JANUSMASK_PATCHES__` with non-string code value.**
Target: `_parse_patches`. Scenario: `code` value is an int / f-string / concatenation.
Expected: returns `None` (no sidecar written by `_save_final_output`). Assert None.

**C6 — untracked-test sidecar synthesis OVERRIDES `.patches.json` (KNOWN memory hazard).**
Target: `commit_accepted_output` untracked-test block (gi:593-629) vs patches dispatch (gi:636).
Scenario: a `.patches.json` exists for the task AND an untracked `tests/test_foo.py` exists in
the PARENT worktree. The untracked block (gi:603) sees untracked tests, BUILDS a
`.files.json` manifest (single-file output + untracked tests), writes it (gi:629), and the
dispatcher at gi:633 routes to `_commit_accepted_output_multi` — the `.patches.json` path at
gi:636 is NEVER reached. Expected per MEMORY note ("Untracked test poisons patches commit"):
the partial-edit is silently converted to a whole-file commit AND the untracked test file is
NOT in `allowed_files=files_touched` so the membership check now REJECTS the whole commit.
Assert: with a `.patches.json` + an untracked `tests/test_*.py` (parent), `commit_accepted_output`
either (a) routes to multi and fails membership on the untracked test, or (b) clobbers the
patches path — document which. This is a real cross-feature interaction bug surface. Mock:
tmp repo, seed a target, write `.patches.json`, create untracked `tests/test_x.py`.

**C7 — untracked-test synthesis with `meta_task_type=None` pulls a sensitive file.**
Target: gi:624-627 — `untracked_files` only matches `tests/test_*.py`, so it can't pull
`harness/**`. Confirm the glob is `tests/test_*.py` ONLY (it is). Assert that an untracked
`harness/test_x.py` or `scripts/test_y.py` is NOT swept in (the `git status --porcelain tests/`
scope + `fnmatch 'tests/test_*.py'` should exclude them). Pin the scoping so a future widening
can't pull sensitive untracked files into the synthesized manifest.

### D. depth_validator (commit f1a746b)

**D1 — `parent_task` vs `parent_task_id` key precedence.**
Target: `check_true_depth`. Scenario: a task carrying BOTH `parent_task` and `parent_task_id`
with DIFFERENT values. The code prefers `parent_task` (gi:62 elif). Assert which wins and that
a lineage using only `parent_task_id` is still followed. Suspected gap: mixed-key chains across
generations (parent uses `parent_task_id`, child uses `parent_task`) — confirm the walk
doesn't silently truncate.

**D2 — cycle and self-parent.**
Target: `check_true_depth`. Scenario: task whose `parent_task` == its own id; and an A→B→A
cycle. Expected: `visited` set catches it → returns False (warning). Assert False, no infinite
loop. (max_depth would also catch it, but pin the cycle guard independently.)

**D3 — depth boundary off-by-one.**
Target: `check_true_depth`. Scenario: a chain of exactly `max_depth` and `max_depth+1` task
files. `depth` increments at the TOP of the loop before reading parent (gi:44-47), so a chain
of N files yields depth==N. Assert depth==max_depth returns True and max_depth+1 returns False.
Pin the boundary (the f1a746b "fix" changed nothing semantic — verify the boundary is what
callers expect).

**D4 — `parent_task=""` / non-string / `tasks_dir` is bool.**
Target: `check_true_depth`. Scenario: `parent_task=""`, `parent_task=123`, `tasks_dir=True`.
Expected: each returns False (guards at gi:25, 38, 69). Assert.

### E. Fuzz / BYPASS (do NOT narrow the bypass)

**E1 — BYPASS path still runs smoke + embedded + narrow-fuzz gates.**
Target: orchestrator bypass branch (orch:1819-1850). Scenario: a task with
`mtt in BYPASS_FUZZER_TYPES` but `mtt not in SKIP_SMOKE_GATE_TYPES`. This requires the
orchestrator loop, which is heavy to drive without agents — prefer a focused unit test on the
gate functions: feed `run_embedded_tests`/`smoke_import`/`run_narrow_fuzz` candidate code that
fails and assert each returns a non-None error. Assert the bypass does NOT mean "no
verification" — it means "differential fuzz replaced by these gates". This pins INV-5 without
weakening the bypass.

**E2 — `fuzz_from_task` strategy-build failure returns non-equivalent (fail-closed).**
Target: `diff_fuzzer.fuzz_from_task`. Scenario: `code_a` whose declared signature can't yield a
hypothesis strategy. Expected: `FuzzResult(equivalent=False, error=...)`. Assert equivalent is
False and error set — the orchestrator then rejects. Pin that a fuzz infra failure can NEVER
present as `equivalent=True` (which would auto-commit on agreement-by-omission). HIGH priority:
this is the dual-agent-agreement integrity boundary.

**E3 — embedded_test_runner / sandbox path correctness (SANDBOX_PATH_FIX).**
Target: `embedded_test_runner.run_embedded_tests`, `sandbox`. Scenario: candidate code that
imports a stdlib module and one that attempts a forbidden filesystem write. Assert the runner
returns None on clean code and an error on a candidate that violates the sandbox, using the
existing `tests/test_sandbox*.py` patterns. (Lower priority — well-covered already.)

### F. Rollback / verification

**F1 — verification_command missing → rollback.**
Target: `_auto_commit_accepted` (orch:1481). Scenario: task with no `verification_command`
(and no parent with one). Drive `_auto_commit_accepted` with a tmp repo + a benign in-scope
single-file commit that succeeds, then assert: returns False, staging removed, a
`verification_missing` row appended to `impl_progress.jsonl`, and HEAD rolled back (commit
reverted). Mock: monkeypatch nothing real — supply a real tmp git repo so `git rev-parse`/`reset`
work. No agents.

**F2 — `_rollback_rejected_commit` does not clobber a peer commit.**
Target: `_rollback_rejected_commit` (orch:1200). Scenario: after this worker's commit (sha S),
simulate a peer by making ANOTHER commit on top so HEAD != S; then call rollback with sha=S.
Expected: it uses `git revert --no-edit S` (NOT `reset --hard HEAD~1`), preserving the peer
commit. Assert the peer commit's file still exists and S's change is reverted. Pin INV-6.

**F3 — verification non-zero exit → rollback + ledger row.**
Target: `_auto_commit_accepted`. Scenario: `verification_command="false"` (exits 1). Assert
commit reverted, `verification_failed` ledger row, returns False. Mock: tmp repo, in-scope
target.

---

## 5. Incompleteness & gap candidates (file:line)

- **`harness/git_integration.py:593-629`** — untracked-test auto-detect block synthesizes a
  `.files.json` manifest BEFORE the dispatcher checks for `.patches.json` (gi:636). Result: a
  partial-edit task with any untracked `tests/test_*.py` in the parent worktree is silently
  converted to a whole-file multi-commit, and the synthesized manifest includes the untracked
  test (NOT in `files_touched`) so the §1b membership check then REJECTS the whole commit.
  Cross-feature collision; matches the MEMORY "untracked test poisons patches commit" hazard.
  (Tests A6/C6.)
- **`harness/git_integration.py:803-819` (`_commit_accepted_output_multi`)** — per-entry scope
  check + `_apply_file_to_target` run interleaved in the loop, so an in-scope entry processed
  BEFORE an out-of-scope entry is WRITTEN to the staging worktree even though the function
  returns committed=False. Partial on-disk mutation with no rollback of the write (bounded only
  because the orchestrator later removes the staging worktree). (Test A5.)
- **`harness/git_integration.py:53,56` (`_enforce_apply_scope` membership)** — `allowed_files`
  entries are compared only `\`→`/`-normalized, while the candidate rel-path is derived from a
  `.resolve()`d `relative_to`. A `files_touched` entry containing `./` or `..` segments will not
  match its own resolved form → false-positive lockout of a legitimate commit. (Test A1.)
- **`harness/git_integration.py:18-34` (`_matches_sensitive`)** — case-sensitive prefix match.
  On a case-insensitive filesystem `Harness/x.py` evades the sensitive gate while writing the
  real `harness/` dir. (Test A2.)
- **`harness/git_integration.py:671-677`** — `_ast_merge` failure falls back to whole-file
  `shutil.copy2`, silently discarding target-only top-level symbols when the existing target has
  a transient parse error. Data-loss surface for single-file commits. (Test B3.)
- **`harness/depth_validator.py:62-65`** — `parent_task` is preferred over `parent_task_id`
  with no reconciliation; mixed-key lineages across generations are walkable but untested. The
  f1a746b "validated" commit was whitespace-only (no behavior change) — a pipeline accepted a
  semantically empty change as a fix. (Tests D1/D3.)
- **`harness/diff_fuzzer.py:473,516,549`** — strategy-build / fuzz-infra failures return
  `equivalent=False` with an error; must NEVER surface as `equivalent=True`. This is the
  agreement-integrity boundary and should be pinned (no current dedicated adversarial test
  found beyond `test_diff_fuzzer*`). (Test E2.)

---

## 6. Runbook

### Test file paths to create (tester sub-agent)
- `tests/adversarial/test_apply_scope_gate_adversarial.py` — A1–A7, C6, C7.
- `tests/adversarial/test_ast_merge_apply_edge_adversarial.py` — B1–B4.
- `tests/adversarial/test_patches_apply_adversarial.py` — C1–C5.
- `tests/adversarial/test_depth_validator_lineage_adversarial.py` — D1–D4.
- `tests/adversarial/test_fuzz_bypass_integrity_adversarial.py` — E1, E2.
- `tests/adversarial/test_auto_commit_rollback_adversarial.py` — F1–F3.

(Some overlap existing files: `test_agent_isolation.py` already covers the happy/basic §1b
cases at lines 153-225; extend with the normalization/case/atomicity adversarial cases — do
NOT duplicate the existing asserts.)

### venv pytest invocations
```bash
PY=/home/xnihil0zer0/JanusMaskJR/.venv/bin/python
cd /home/xnihil0zer0/JanusMaskJR

# §1b gate (new)
$PY -m pytest tests/adversarial/test_apply_scope_gate_adversarial.py -q
# regression-confirm existing gate tests still green
$PY -m pytest tests/adversarial/test_agent_isolation.py -q

# AST-merge + patches
$PY -m pytest tests/adversarial/test_ast_merge_apply_edge_adversarial.py \
              tests/adversarial/test_patches_apply_adversarial.py -q

# depth + fuzz-bypass + rollback
$PY -m pytest tests/adversarial/test_depth_validator_lineage_adversarial.py \
              tests/adversarial/test_fuzz_bypass_integrity_adversarial.py \
              tests/adversarial/test_auto_commit_rollback_adversarial.py -q
```

### tmp-git-repo fixture notes
- Mirror `test_git_integration_acceptance_adversarial.py`: `_git(cwd,*args)` wrapper sets
  `GIT_AUTHOR_*`/`GIT_COMMITTER_*` env; `git init -b main -q`; set `user.email`/`user.name`;
  initial `--allow-empty` commit.
- For staging-worktree tests, create a sibling dir and `git worktree add --detach <sibling>`
  OR call `git_integration.create_staging_worktree(str(sibling), parent_root=root)` — it
  enforces the sibling-of-repo-root placement (raises ValueError otherwise).
- Sidecars: write `state_dir/output/<task_id>.files.json` (dict rel→source) or
  `.patches.json` (list of `{file,kind,name|marker,code}`); whole-file output goes in
  `state_dir/output/<task_id>.py`.
- `_apply_approval_granted` reads `state_dir/control/decisions/<task_id>.json` — write
  `{"decision":"approved"}` to exercise the approval branch.
- For `_auto_commit_accepted` end-to-end tests, pass a `task` dict with `files_touched`,
  `verification_command`, `meta_task_type`; `state_dir` must be a child of the git worktree
  (the function does `git rev-parse` at `cwd=state_dir.parent`).
- HARD: do NOT spawn agy/gemini/claude; do NOT run the pipeline loop; do NOT lift safe states
  (full_stop=halted, autowork.enabled=false). Do NOT re-flag the known pre-existing failures
  (5× `test_escalate_to_autobrief_*`, 2× retry-exit-code tests).
