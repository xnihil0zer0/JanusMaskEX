# HANDOFF — Fix all known bugs & gotchas (JanusMaskJR)

> ## ✅ FULLY RESOLVED 2026-06-10 (owner-authorized session)
> Part I (§1–§4b) had already landed in prior sessions (§1 `720b69c`, §2/§3
> planner fixes, §4a/§4b owner hand-edits `36e0d7f`). Part II epics B/C/D all
> built by 2026-06-10 (`144e3ad`). THIS session root-caused the remaining 12
> known test failures: 4 stale orchestrator prompt tests, model-pin scope,
> posture-flag drift (flags now ON per test_p10), 3 mis-archived smoke
> fixtures, home-free sentinel, reconciliation deadline flake, and TWO new
> root causes — tests/unit/test_webui.py was REWRITING the live config.yaml +
> allowlist every sweep (hermeticized `8d5a88d`), and wire_up.py treated
> config COMMENTS as module registrations (pipeline fix `b3cc1ec`, oracle
> `29ab423`). Full serial sweep re-run as the gate. See memory
> bugfix-sweep-2026-06-10.

**Authored:** 2026-06-09, end of the autocompiler Phase-A session.
**For:** the next agent/session.
**Goal:** durably fix the bugs and latent harness defects (gotchas) surfaced during the autocompiler
Phase-A build, **each through the proper write-tier** — never by hand-editing production outside the
pipeline.

---

## 0. Read this first — the cardinal rule & the proven recipe

**CARDINAL RULE:** *Never hand-edit production code outside the pipeline.*
- **Free** paths (anything outside `harness/**`, `config/**`, `scripts/**`, `services/**`): build through the normal pipeline.
- **Sensitive** paths (the four globs above): `meta_task_type: harness_self_fix` **plus** an operator decision file `state/control/decisions/<task_id>.json`.
- **Irreducible** (`_NEVER_AUTO_APPROVE`: `agent_jail.py`, `dbus_proxy.py`, `paths.py`, `git_integration.py`, `orchestrator.py`, `interceptors.py`, `selfheal.py`, `autowork_daemon.py`, `services/**`): **owner hand-edit only — clear with the owner FIRST.**
- Only **oracles/tests** may be hand-authored.

**PROVEN RECIPE (used twice this session — `3461304`, `4d0afa8`):**
1. Diagnose the root cause; pin the exact `file:anchor`.
2. Hand-author a **RED oracle** (contract test) + a `*_wired.py` wiring oracle if the leaf edits a non-test `.py`. Verify RED. Commit them.
3. Author a leaf brief `brief_hooks_<slug>.md` at the repo root with a precise **# Required plan shape** block (see §4 for the must-haves the validator enforces).
4. Allowlist the slug: `echo "<slug>" >> state/control/autowork/auto_promote.allowlist`.
5. Ensure `state/control/orchestrator.flag` == `resume`, no `full_stop`, daemon running.
6. When the plan kicks off, read the staged `task_id` from `plan_hooks_<slug>.json` and write
   `state/control/decisions/<task_id>.json` = `{"decision":"approve","task_id":"<id>","reason":"...","operator":"<you>"}`.
7. Watch `state/impl_progress.jsonl` for `auto_commit`(accepted) or a failure event; on failure, re-diagnose and rerun.

**Monitor cheaply** (one persistent tail, then go quiet):
```bash
tail -F state/impl_progress.jsonl \
  | grep -E '"event": "(plan_kickoff|auto_commit|task_blocked|planner_hallucination_discarded|retry_exhausted|dependency_failed)"'
```

**Operational preconditions to verify before starting:** daemon alive (`ps -p $(cat state/control/autowork.pid)`); no stale `state/control/autowork/git_commit.lock`; allowlist contains your slug(s). Commits land on `master` (currently pushed through `5989af1`). Push when the owner signs off.

---

## 1. CONFIRMED BUG — brief_loader does not normalize a lone `\r` (FAILING TEST EXISTS)

- **Symptom:** `tests/planner/test_brief_loader.py::test_sha256_line_ending_invariant` FAILS. Hypothesis falsifying example `text='0\r\r'`: a brief containing a bare carriage return hashes differently from its `\n` equivalent.
- **Root cause:** `harness/planner/brief_loader.py:190` — `normalized_text = raw_text.replace('\r\n', '\n')` collapses CRLF but leaves bare `\r`, so the content SHA-256 (line 191) is not line-ending-invariant.
- **Fix tier:** SENSITIVE (`harness/planner/**`) → `harness_self_fix` + decision file.
- **Fix:** normalize all three line-ending forms before hashing, e.g. `raw_text.replace('\r\n', '\n').replace('\r', '\n')` (or a regex). Preserve all existing behavior; the frontmatter/section parsing downstream already operates on `normalized_text`.
- **Oracle:** the failing test IS the contract — but it lives in an existing file. Author a NEW focused oracle `tests/planner/test_brief_loader_cr_normalize.py` (so the leaf has a clean pre-committed RED target) asserting `load_brief` produces an identical `.sha256` for `\n`, `\r\n`, and bare `\r` variants of the same content; keep the vcmd naming both it and a `*_wired` oracle (the edit is to an existing wired module — see §3 for why that matters). NOTE: this is an EDIT to an existing module, so per §3 the validator will still demand a `*_wired` token in the vcmd.
- **Note:** `brief_loader.py` was NOT touched this session; this is pre-existing and unrelated to the autocompiler work. Documented in `README.md` known-failures.

---

## 2. GOTCHA → BUG — `files_touched` pollution with sensitive-glob registration files

- **Symptom (observed on `ac-selection`, `ac-fitness-vector`):** the planner copied `config/autocompiler.yaml` (a registration file the task does NOT create) into the task's `files_touched`. At accept, `_enforce_apply_scope` refused the sensitive-glob write → `auto_commit_failed`, retried to exhaustion. Worked around per-task by manually pruning `files_touched`.
- **Root cause:** nothing strips/validates `files_touched` entries that fall under `_SENSITIVE_APPLY_GLOBS` but are not the task's actual emission target (and for which the task lacks `harness_self_fix` + approval). The planner faithfully copied a path mentioned in the brief's "registered in config/..." note.
- **Fix tier:** SENSITIVE (`harness/planner/**`) → `harness_self_fix` + decision.
- **Fix (choose one, prefer the validator):**
  - **`plan_validator.py`** — add a violation when a non-`harness_self_fix` task lists a `_SENSITIVE_APPLY_GLOBS` path in `files_touched` (it can never commit it), so the plan is rejected at planning time with a clear message instead of dead-ending at accept.
  - **or `plan_normalizer.py`** — add a pass that drops sensitive-glob `files_touched` entries from non-`harness_self_fix` tasks (mirrors the new `_strip_unresolvable_dependencies` pass added at `4d0afa8`).
- **Oracle:** `tests/planner/test_files_touched_sensitive_guard.py` — a plan with a `data_model` task listing `config/foo.yaml` in `files_touched` is rejected (validator) or has it stripped (normalizer); a `harness_self_fix` task with an approved sensitive path is untouched.

---

## 3. GOTCHA → BUG — `_is_module_creating` over-triggers the wiring-oracle rule for EDITs of existing modules

- **Symptom (observed on both fix leaves this session):** a `harness_self_fix` task that EDITS an already-existing, already-wired module (`orchestrator_worker.py`, `plan_normalizer.py`) is flagged `missing_wiring_oracle` unless its `verification_command` names a `*_wired.py` test — even though the module is already reachable and the edit creates nothing. The dep-strip leaf's first plan was discarded partly for this; I had to add a `*_wired` oracle (`479fbba`) to satisfy it.
- **Root cause:** `harness/planner/plan_validator.py:31` `_is_module_creating` returns True for ANY task whose `files_touched` has a non-test `.py` and whose `meta_task_type` is not a pure-edit type (`refactor`/`logging_observability`/`docs_writing`/`test_*`). It does NOT check whether the file already exists — so an EDIT of an existing module is treated as "creating."
- **Fix tier:** SENSITIVE (`harness/planner/**`) → `harness_self_fix` + decision.
- **Fix:** make `_is_module_creating` (or its caller at `:164`) consult `repo_root` and treat a task as module-creating only if at least one of its non-test `.py` `files_touched` does **not** already exist on disk. An EDIT of a pre-existing module then needs no wiring oracle. Preserve the current behavior for genuinely new files. (Threading `repo_root` into the validator mirrors how `plan_normalizer` already receives it.)
- **Oracle:** `tests/planner/test_module_creating_existing_edit.py` — an EDIT task touching an existing module is NOT flagged `missing_wiring_oracle`; a task creating a NEW module still IS.
- **Caveat:** confirm the validator has access to `repo_root` at the call site; if not, this fix also threads it (still a single-file `harness/planner/plan_validator.py` edit).

---

## 4. OWNER HAND-EDIT REQUIRED (clear with owner FIRST) — irreducible-tier defects

> These live in `_NEVER_AUTO_APPROVE` files. **Do not dispatch them through the pipeline.** Present the diagnosis + a minimal patch to the owner and let them hand-edit, or get explicit clearance.

### 4a. Emission mis-routing: BYPASS_FUZZER tasks get the patches prompt even when creating a NEW file
- **Symptom (observed on `crossover_impl`):** a `harness_plumbing` (BYPASS_FUZZER) task creating a NEW single file `autocompiler/crossover.py` was prompted with the PARTIAL-EDIT `__JANUSMASK_PATCHES__` dispatch. The agent emitted patches; **patches cannot create a new file** → `auto_commit_failed`. Worked around by forcing whole-file via a loud brief directive + clearing the stale sidecar.
- **Root cause:** `harness/orchestrator.py:1519` — `if (task.get('partial_edit') or mtt in BYPASS_FUZZER_TYPES) and not use_manifest:` adds the patches-dispatch prompt whenever the meta-type bypasses the fuzzer, **regardless of whether the target file exists**. New-file creation must be whole-file.
- **Suggested fix:** gate the patches branch on the target(s) already existing on disk — if any `files_touched` entry does not yet exist, fall through to the whole-file prompt (never offer patches for a create). Single-symbol edit to `_build_*`/prompt-assembly region near `orchestrator.py:1517-1525`.
- **Tier:** `harness/orchestrator.py` is `_NEVER_AUTO_APPROVE` → **owner hand-edit.**

### 4b. Stale 0-byte `git_commit.lock` wedges the daemon
- **Symptom (recurring, from prior sessions + this one):** a daemon/worker that dies mid-commit leaves a 0-byte `state/control/autowork/git_commit.lock`; the next run blocks on it until manually `rm`'d. I cleared it at session start.
- **Root cause:** the stale-aware acquisition at `harness/autowork_daemon.py:1954` exists but does not reliably reap a 0-byte lock whose owning PID is gone (no PID recorded / staleness window).
- **Suggested fix:** write the owning PID (and a timestamp) into the lock on acquire; on contended acquire, if the recorded PID is dead or the file is 0-byte and older than a small threshold, reap and re-acquire. Emit telemetry on reap.
- **Tier:** `harness/autowork_daemon.py` is `_NEVER_AUTO_APPROVE` → **owner hand-edit.**

---

## 5. BRIEF-AUTHORING GOTCHAS (no code change — discipline; already in README §Troubleshooting)

When authoring any brief/leaf in §1–§3 above, obey these or the plan is discarded:
- **Bare section headings only.** `# Inputs`, `# Scope`, `# Non-Goals`, `# Inputs`, `# Deliverables` — a decorated heading (`# Inputs (notes)`) fails `brief_loader` validation → "hallucinated"/empty-plan discard. *(Optional code follow-up: relax the heading match to "starts-with section name" in `brief_loader.py` — sensitive, harness_self_fix — but confirm with owner whether the strictness is intentional.)*
- **EDIT tasks need the literal word `integration` in `spec.non_goals`** or the validator raises `missing_integration_test`.
- **Module-creating/editing leaves must name a `*_wired.py` oracle** in the `verification_command` (until §3 lands for existing-module EDITs).
- **One file per leaf; emit a NEW file WHOLE-FILE** (never patches/manifest). A NEW top-level symbol in an existing file rides as an **R-anchored** trailing node of an existing symbol's patch.
- **Don't list non-target files in `files_touched`** (the §2 trap).

---

## 6. ALREADY FIXED THIS SESSION — reference exemplars (do NOT redo)

- **Stale emission-sidecar retry poison** — `commit_accepted_output` routed the accept path on sidecar existence, so a failed attempt's `state/output/<tid>.{patches,files}.json` hijacked every retry. Fixed `3461304` (oracle `e3629d1`): `_purge_stale_sidecars_safe` in `orchestrator_worker.py`, called from `_print_json_line` on non-accept terminal outcomes. Use as the template for §2/§3 fail-safe bridges.
- **Dependency-slug drift** — epic child frontmatter `dependencies:` are sibling SLUGS; the daemon gates dispatch on real accepted `task_id`s, so slug-deps wedged the dependent leaf. Fixed `4d0afa8` (oracles `5ce1e6c`/`479fbba`): `_strip_unresolvable_dependencies` pass in `plan_normalizer.normalize_plan` drops deps that name no in-plan task. Use as the template for the §2 normalizer option.

---

## 7. Suggested order of work

1. **§1 brief_loader `\r`** — smallest, has a failing test already, clean win.
2. **§3 `_is_module_creating` existing-edit** — removes friction for every future `harness_self_fix` EDIT (including §1/§2's own leaves).
3. **§2 files_touched sensitive guard** — prevents a whole class of `auto_commit_failed` dead-ends.
4. **§4a / §4b** — package the diagnoses + minimal patches and hand to the owner (irreducible tier).
5. Re-run `make test-full` (the serial gate) after each lands; the §1 failing test should go green.

Each of §1–§3 is a single-file `harness/planner/**` edit → one `harness_self_fix` leaf + one decision file. Keep each leaf to one file and one new helper + minimal call-site change. Push after the owner signs off.

---

# PART II — REMAINING AUTOCOMPILER WORK (three epic briefs to author next session)

This part captures everything left to finish the agentic autocompiler / population-Elo system. The
**Phase-A core is built and pushed** (9 pure modules: `flags`, `population`, `fitness`, `elo`,
`selection`, `crossover`, `containment`, `vacuity`, `loop`; 77/77 oracles green; registered in
`config/autocompiler.yaml`). It is **inert** — nothing is wired into the live worker, the
`autocompiler:` config subtree does not exist, no real model has rated a candidate, and the loop has
never run in production. The remaining three phases are written below as **three epic briefs to author
next session** (each is a *skeleton + decided contracts*, not yet the final dispatch-ready brief).

> **The decisive milestone is Epic C (wiring) — that is what makes the autocompiler actually run.**
> Epic B (JS target) is an optional capability expansion. Epic D is one owner hand-edit.

## §8. Prerequisites before ANY of the three epics

1. **Land the §1–§3 plumbing fixes first.** The Epic-C leaves are all `harness_self_fix` EDITs; they
   will hit the same `_is_module_creating` / `files_touched` / emission friction (§2, §3, §4a) the
   Phase-A leaves did. Fixing those removes the friction for every wiring leaf.
2. **Per-leaf RED oracles are a hard precondition.** For each leaf below, hand-author + commit its
   RED oracle (contract) AND, for any leaf creating/editing a non-test `.py`, a `*_wired.py` oracle,
   BEFORE dispatch. This is the proven recipe (§0); the Phase-A run proved it converges first-try when
   the brief embeds the exact source+contract.
3. **Wire-up-gate mitigation for new modules.** Epic-B adds new `autocompiler/**` modules that are
   orphan-by-design until Epic-C wires them. Extend `config/autocompiler.yaml` with their dotted
   paths (the sanctioned dynamic-wiring classification) so `check_wired` accepts them. `.js` files are
   not `.py` and are skipped by the gate.
4. **Recommended dispatch order (value-first, dependency-correct):**
   `§1–§3 fixes → Epic C (Python core, the go-live) → Epic B (JS substrate) → Epic D + the one
   JS-dispatch wiring leaf`. The only cross-epic edge: `ac-wire-js-dispatch` (listed under Epic C for
   phase fidelity) **depends on Epic B** — defer that single leaf until B has landed; everything else
   in Epic C depends only on the built Phase-A modules.
5. **All of Epic C/D is owner-gated.** Sensitive `harness/**` edits need decision files; the Epic-D
   `agent_jail` mount is irreducible (owner hand-edit). Get sign-off before dispatching.

---

## §9. EPIC C — "Go-Live wiring" (author as `brief_hooks_autocompiler_wiring.md`, `epic: true`)

**Intent.** Turn the inert Phase-A core ON behind a default-OFF flag tree: when the flag is OFF every
current path stays byte-identical; when ON, the worker's post-synthesis region runs the population
loop and accepts the population winner through the UNCHANGED `_auto_commit_accepted`. **This is the
epic that makes the autocompiler real.** All leaves additive, `harness_self_fix`, default-OFF.

**Leaves** (each: pre-commit a RED oracle; `harness_self_fix` + decision file; one file each):

| slug | target | kind | oracle | contract |
|---|---|---|---|---|
| `ac-config-tree` | `harness/config.yaml` | additive YAML | `tests/autocompiler/test_config_tree.py` | adds default-OFF `autocompiler:` subtree (master `enabled:false` + sub-keys); `load_config` exposes it. After this lands, `ac_enabled()` can finally return True under test. |
| `ac-wire-determinism` | `harness/sandbox.py::sandbox_child_env` | R-anchored additive `if ac_enabled():` | extend `tests/test_sandbox.py` | flag OFF ⇒ child env byte-identical; ON ⇒ deterministic time across two `execute()` calls. Depends on Epic-B `ac-determinism` (the `_SITECUSTOMIZE_CONTENT`). |
| `ac-wire-decode` | `harness/orchestrator_worker.py` (accept chokepoint `_print_json_line`/`:73`) | R-anchored try/except bridge | `tests/autocompiler/test_worker_decode.py` | flag OFF ⇒ JSON line emitted identically; bridge can NEVER raise back into `_print_json_line` (mirror `_reap_spent_briefs_safe`/`_purge_stale_sidecars_safe`). Depends on Epic-B `ac-decode-validator`. |
| `ac-wire-evolution` | `harness/orchestrator_worker.py` (post-fuzz region near `:598`) | R-anchored `_maybe_run_evolution` helper + 1-line call | `tests/autocompiler/test_worker_evolution.py` | flag OFF ⇒ single-shot accept path byte-identical; ON ⇒ routes through `autocompiler.loop.step`, winner still funnels through the UNCHANGED `_auto_commit_accepted`. The keystone leaf. |
| **`ac-wire-rater`** (NEW — not in the original 22) | `harness/orchestrator_worker.py` or a free `autocompiler/rater.py` | NEW free module + 1-line wire | `tests/autocompiler/test_rater.py` | **connect a REAL pairwise rater to the `model_seam`** the loop/Elo consume. Today the rater is an injected stub; until a real model spawn (a Haiku/Flash-class CLI subprocess, reusing the existing agent-spawn path) is wired, Elo rates nothing in production. Prefer a NEW free `autocompiler/rater.py` (pure over an injected `spawn_seam`) + a thin `harness_self_fix` wire so the bulk stays free-tier and hermetically testable. |
| `ac-wire-js-dispatch` | `harness/diff_fuzzer.py::differential_fuzz` | EDIT-symbol | `tests/autocompiler/test_lang_dispatch.py` | `task['language']=='js'` → `execute_js_batch`; default `'python'` unchanged. **DEPENDS ON EPIC B** — dispatch this leaf LAST, after B's `js_sandbox` exists. |

**Tiers:** `config.yaml`, `sandbox.py`, `orchestrator_worker.py`, `diff_fuzzer.py` are all sensitive
but NOT `_NEVER_AUTO_APPROVE` → `harness_self_fix` + decision file each (proven this session:
`orchestrator_worker.py` was edited via `harness_self_fix` at `3461304`). None require owner hand-edit.

**Key risks / gotchas:**
- The OFF-path byte-identity assertion is the load-bearing safety contract — every oracle must prove
  the flag-OFF path is unchanged. Keep each edit a small new helper + one-line guarded call site;
  NEVER rewrite `main()` or a large symbol (it AST-truncates and rolls back).
- The whole-file drift guard blocks re-dispatch editing >1 symbol; if a wiring leaf needs to touch two
  symbols, split it.
- `ac-wire-evolution` must NOT bypass the verifier: the population winner is accepted only through the
  unchanged `_auto_commit_accepted` (staging worktree + RO-parent gate). Assert this in the oracle.

**Acceptance of the epic:** with the flag flipped ON in a scratch config, a task whose two agents
diverge on a near-miss is RATED into a population, recombined, and a winner is accepted — while the
flag-OFF suite stays 100% green and byte-identical.

---

## §10. EPIC B — "Determinism + JS/TS beachhead substrate" (author as `brief_hooks_autocompiler_js.md`, `epic: true`)

**Intent.** Add the flakiness-reducing determinism seam and a function-level JS/TS differential runner
that reuses the entire Python input-gen/compare/FuzzResult path, swapping only leaf execution. All new
FREE `autocompiler/**` modules (normal pipeline), pure/hermetic over injected spawn seams. JS does NOT
execute here (that needs the Epic-D jail mount) — these leaves are the pure substrate + the runner
script, oracle-tested with the spawn injected.

**Leaves** (each: pre-commit RED oracle; FREE tier; register dotted path in `config/autocompiler.yaml`):

| slug | target | kind | meta_task_type | oracle | contract |
|---|---|---|---|---|---|
| `ac-determinism` | `autocompiler/determinism.py` | NEW whole-file | `data_model` | `test_determinism.py` | pure `_SITECUSTOMIZE_CONTENT` + writer (deterministic time/random/urandom/uuid); pure-string, no spawn. (Consumed by Epic-C `ac-wire-determinism`.) |
| `ac-decode-validator` | `autocompiler/decode.py` | NEW whole-file | `validation` | `test_decode.py` | reasoning-field-FIRST schema; truncated JSON repaired, incomplete `edits` dropped; never raises. (Consumed by Epic-C `ac-wire-decode`.) |
| `ac-js-node-version` | `autocompiler/js/node_version.py` | NEW whole-file | `validation` | `test_node_version.py` | resolves exact `~/.nvm/.../bin/node` subpath; rejects non-`^v\d+\.\d+\.\d+$` and any `..`-escaping `.nvmrc` (safe_subpath-style). |
| `ac-js-codec` | `autocompiler/js/js_codec.py` | NEW whole-file | `data_model` | `test_js_codec.py` | round-trips `undefined`/`NaN`/`Infinity`/`null` DISTINCTLY via `__sentinel__` tags; `Object.is` compare hook. |
| `ac-js-fork-policy` | `autocompiler/js/js_fork_policy.py` | NEW whole-file | `data_model` | `test_js_fork_policy.py` | pure `child_process.fork` argv + process-group SIGKILL plan; no spawn. |
| `ac-js-runner` | `autocompiler/js/js_runner.js` | NEW **non-Python** WHOLE-FILE | `harness_plumbing` | `test_js_runner_e2e.py` | per-batch `fork`, `await`+`Promise.race` timeout (never-resolving Promise ⇒ timeout, not hang), results→**FD 3** (dodge `console.log` stdout pollution), sentinel codec. |
| `ac-js-sandbox-seam` | `autocompiler/js/js_sandbox.py` | NEW whole-file | `io_adapter` | `test_js_sandbox.py` | `execute_js_batch(...) -> list[ExecutionResult]`; spawn INJECTED so the oracle is hermetic. (Consumed by Epic-C `ac-wire-js-dispatch`.) |

**Risks / gotchas:**
- `js_runner.js` is non-Python → emit via the WHOLE-FILE / manifest path, never `__JANUSMASK_PATCHES__`
  (patches can't create files; this is the §4a trap). `harness_plumbing` is BYPASS_FUZZER, so beware the
  §4a emission mis-routing until that fix lands — state WHOLE-FILE loudly in the brief.
- `autocompiler/js/` is a subpackage. The top-level `autocompiler/` worked as a namespace package
  (no `__init__.py`), but VERIFY `discover_modules`/`check_wired` find `autocompiler.js.*` submodules;
  if not, add a one-line `autocompiler/js/__init__.py` as its own first leaf.
- No tree-sitter (not installed) → JS ships whole-file only, function-level, single-threaded
  (`worker_pool_size:1`). Don't propose AST-splicing of JS.
- Determinism is bounded (GIL/libuv/ASLR/FMA) — the layer reduces flakiness, it does not eliminate it;
  JS libuv determinism needs a separate node preload, out of scope. Say so in Non-Goals.

---

## §11. EPIC D — "JS jail mount" (author as `brief_hooks_autocompiler_jsmount.md`; ONE owner-gated leaf)

**Intent.** The single irreducible edit that lets JS actually execute: bind the pinned node binary into
the bwrap agent jail for the JS execute path. This is `_NEVER_AUTO_APPROVE` → **owner hand-edit, signed
off FIRST; not pipeline-dispatchable.** Author it as a one-leaf epic (or a plain owner task note).

| slug | target | gate | contract |
|---|---|---|---|
| `ac-js-jail-mount` | `harness/agent_jail.py::build_jail_argv` | OWNER hand-edit, sign-off FIRST | binds ONLY the pinned `~/.nvm/versions/node/<v>/bin` read-only for the JS execute path; NO global `~/.nvm` tree; preserves `--unshare-net --unshare-ipc`. |

**Notes:** depends on Epic-B `ac-js-node-version` (the version resolver that picks `<v>`). The oracle
can only assert argv composition (a unit test over `build_jail_argv`), not a live JS run, since the
owner applies the edit by hand. Keep the mount minimal and justify it against the adversarial critique
(no global nvm mount).

---

## §12. What these three epics do NOT cover (explicit out-of-scope / future)

- **Richer fitness signal.** `FuzzResult` has no path-coverage / shrink-complexity, so live fitness is
  divergence-rate + `_classify_failures` bucket-count only. A coverage-bearing fuzzer extension is a
  SEPARATE future epic (a `diff_fuzzer.py` capability), not in B/C/D.
- **Formal/Lean oracle lane.** Out of scope (no proof infra); empirical fuzzer remains the oracle.
- **Real-rater quality tuning.** `ac-wire-rater` (Epic C) connects a real rater; calibrating K-factor,
  tournament size, and prompt for the rater against real builds is follow-up work once it runs.
- **Multi-agent population (>2 authors).** The dual-agent contract is preserved; widening the author
  pool is a later idea.

**End state when all three land + flag ON:** the worker's post-synthesis region runs a population loop
that rates near-misses with a real pairwise rater, recombines partial successes via `_ast_merge`,
optionally targets JS as well as Python, and accepts the population winner through the UNCHANGED
`_auto_commit_accepted` gate — with the existing single-shot path preserved byte-for-byte when OFF.
