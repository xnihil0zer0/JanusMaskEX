# Handoff — Enable pipeline application of multi-file / non-Python (UI + config) edits

Compiled 2026-06-08. **Mission:** fix the JanusMaskJR worker so the gated pipeline can
APPLY edits to non-Python files (`.js/.html/.css/.yaml`) and multi-file bundles, then build
the two overseer-chat leaves currently blocked by this: the **frontend** bundle and the
**config** block. The root cause is fully diagnosed below — do NOT re-derive it.

---

## §0 PASTE PROMPT

> Fix the worker so bypass-fuzzer edit leaves whose targets are non-Python (`.js/.html/.css/.yaml`)
> or multi-file are routed to the VERBATIM whole-file MANIFEST path instead of the Python-only
> symbol-patch path. Read THIS file first. The verbatim apply already exists
> (`git_integration._apply_file_to_target`); the bug is routing in `orchestrator.py:1471`. Land it
> oracle-first as a `harness_self_fix` (RED oracle in `tests/adversarial/`, operator decision file).
> Then build the two blocked leaves with the pinned briefs `brief_hooks_ov-frontend.md` and a new
> `brief_hooks_ov-config.md` (oracles `tests/overseer/test_chat_ui.py` + `test_config_overseer.py`).

---

## §1 ROOT CAUSE (precise, with file:line)

When the worker turns an agent submission into an on-disk edit there are THREE dispatch modes,
selected in `harness/orchestrator.py` (`_build_synthesis_prompt`, ~line 1471):

```python
if task.get('partial_edit') or mtt in BYPASS_FUZZER_TYPES:      # (A) PARTIAL-EDIT  -> __JANUSMASK_PATCHES__
    ...                                                          #     kinds: 'symbol' (Python AST) | 'region' (sentinel)
elif isinstance(files_touched, list) and len(files_touched) > 1:# (B) MULTI-FILE    -> __JANUSMASK_MANIFEST__
    ...                                                          #     {relpath: VERBATIM full source}  (any language)
# else                                                          # (C) single whole-file submission.py
```

**The bug:** `mtt in BYPASS_FUZZER_TYPES` is checked FIRST and is true for every safe edit type
(`harness_plumbing`, `harness_self_fix`, `data_model`, …). So a `harness_plumbing` frontend leaf and
a `harness_self_fix` config leaf are forced into branch (A) — even though (A) can only apply Python
symbols or sentinel regions — and branch (B), which does VERBATIM whole-file writes that work for any
language, becomes unreachable for them. (Introduced by the `BYPASS_WHOLE_FILE` change, 2026-05-28,
to keep large Python rebuilds on patches; it over-reaches to non-Python.)

**Why (A) cannot apply non-Python:** the per-entry applier `_apply_symbol_patch`
(`harness/git_integration.py:~1070`) is pure Python AST — first real op `tree = ast.parse(source)`
(`:~1112`), with **no file-extension check**. Handed `app.js`/`config.yaml`, `ast.parse` raises (or
mis-parses → `KeyError(qualname)` at `:~1145`); `_commit_accepted_output_patches` catches it
(`:~1412`) and returns `committed=False` → rollback → the structural oracle fails. The sibling
`_apply_region_patch` (`:~1255`) is language-agnostic but REQUIRES pre-existing
`# JANUSMASK_REGION:<S>` … `# JANUSMASK_ENDREGION:<S>` sentinels, which fresh `.js`/`.css`/`.yaml`
files do not have.

**Observed failure (frontend leaf `edit-webui-chat-panel-hooks`):** agent emitted
`{'file':'tools/webui_static/app.js','kind':'symbol','name':'boot', ...}` (the only additive option
branch (A) offers for a 54KB JS file — the prompt explicitly says *"Never emit a whole-file manifest
for a partial edit"*). `ast.parse` on JS failed → `auto_commit_failed` → rollback. Same fate awaits
`config` (single `.yaml`, `harness_self_fix` ⇒ branch A ⇒ symbol/region on YAML ⇒ fail).

**Confirmation that Python works:** the `webui_control.py` / `webui_server.py` edit leaves (Python,
branch A, `_apply_symbol_patch` on real Python symbols) BUILT GREEN this session. Only non-Python /
multi-file edits are broken.

### The good news — the verbatim path already exists
Branch (B)'s manifest is parsed by `_save_final_output` (`orchestrator.py:~1775`) into
`state/output/<tid>.files.json`, applied by `_commit_accepted_output_multi`
(`git_integration.py:~884`) via `_apply_file_to_target` (`:~859`), whose non-`.py` arm
(`:~881-882`) is exactly:
```python
else:                                    # non-.py target
    target_path.write_text(out_code, encoding='utf-8')   # verbatim, language-agnostic
```
So we need **routing**, not a new apply engine.

---

## §2 THE FIX (minimal, surgical — primary approach: route to the existing manifest path)

Add a predicate "this leaf must use verbatim whole-file writes" and consult it BEFORE the
bypass→patches fallback, in three places that must agree:

1. **Dispatch prompt — `orchestrator.py:~1471`.** Compute
   `use_manifest = isinstance(files_touched, list) and (len(files_touched) > 1 or any(not str(f).endswith('.py') for f in files_touched))`.
   Change the guard to `if (task.get('partial_edit') or mtt in BYPASS_FUZZER_TYPES) and not use_manifest:`
   (branch A), and make branch B's `elif` fire when `use_manifest` (so non-`.py` single files ALSO get
   the `__JANUSMASK_MANIFEST__` whole-file dispatch, not just `len>1`).

2. **Submission validation — `orchestrator.py:~1652-1692`.** The same `partial_edit or BYPASS_FUZZER`
   guard decides whether to validate the submission as `__JANUSMASK_PATCHES__`. Apply the identical
   `use_manifest` exception so a manifest submission for a non-`.py`/multi-file bypass task validates
   as a manifest (`__JANUSMASK_MANIFEST__`), not rejected for "missing __JANUSMASK_PATCHES__".

3. **Persist — `_save_final_output` (`orchestrator.py:~1775`).** Same branch: when `use_manifest`,
   parse `__JANUSMASK_MANIFEST__` → write `state/output/<tid>.files.json` (NOT `.patches.json`). The
   commit side already prefers `.patches.json` > `.files.json` > `.py`
   (`git_integration.py:~696-704`); with no `.patches.json` emitted, `_commit_accepted_output_multi`
   runs and writes each file verbatim.

Factor `use_manifest` into ONE module-level helper (e.g. `_requires_verbatim_manifest(files_touched)`
in `orchestrator.py` or `taxonomies.py`) and call it in all three spots so they never drift.

**Alternative (if you prefer to keep edits on the patches path):** add a third patch `kind:'whole_file'`
carrying `{'file','code'}` — accept it in `git_integration._parse_patches` (`:~1059`, currently rejects
any kind ∉ {symbol,region}), allow it past the `_commit_accepted_output_patches` validation (`:~1340`),
and in the apply dispatch (`:~1407`) route `whole_file` (or any non-`.py` target) to
`_apply_file_to_target` (verbatim) instead of `_apply_symbol_patch`; document the new kind in the
branch-A prompt (`:~1475`) and instruct the worker to use it for non-Python targets. This is more code
than the routing fix and duplicates the verbatim write the manifest path already has — prefer §2 primary.

---

## §3 ORACLE-FIRST PLAN (this fix is `harness/**` → pipeline + oracle + decision file)

RED oracle home: **`tests/adversarial/test_aw10d_patches_contract.py`** (the existing
`__JANUSMASK_PATCHES__` / manifest contract battery; see also
`tests/adversarial/test_rebuild_partial_edit_largefile.py`). Assert, against a temp git worktree:

1. A `harness_plumbing` task with `files_touched=['a.js','b.css']` and a valid `__JANUSMASK_MANIFEST__`
   submission ⇒ `_save_final_output` writes `state/output/<tid>.files.json` (NOT `.patches.json`), and
   `commit_accepted_output` writes BOTH files **byte-equal** to the manifest values + one commit.
2. A single-file `harness_self_fix` task `files_touched=['x.yaml']` likewise routes to the manifest/
   verbatim path and lands the file verbatim.
3. Negative control: a `symbol`-kind patch targeting a `.js` file is rejected with a clear,
   non-silent error (so future regressions fail loud).
4. Regression: a `harness_plumbing` task editing a single `.py` file STILL uses the patches path and
   `_apply_symbol_patch` (don't break the working Python edit flow — `webui_control` proved it works).

Author the oracle by hand (sanctioned), commit it RED, then dispatch the fix as a `harness_self_fix`
leaf with an operator decision file (see §5). Verify GREEN + run `tests/adversarial/ -q` and a
`tests/planner/ -q` sweep for 0 new regressions (baseline note: `tests/planner/
test_brief_loader.py::test_sha256_line_ending_invariant` is a PRE-EXISTING CRLF failure, not yours).

---

## §4 THE TWO BLOCKED LEAVES (build AFTER the fix lands)

Both are pinned and ready; their RED oracles are committed (`72e8c8c`).

### 4a. Frontend — `brief_hooks_ov-frontend.md` (ALREADY in repo root)
- meta_task_type `harness_plumbing`; `files_touched = [tools/webui_static/app.js, index.html, styles.css]`.
- vcmd `python -m pytest tests/overseer/test_chat_ui.py -q` (STRUCTURAL grep oracle).
- Required hooks (the oracle's exact strings): app.js `function chatIsOpen` + literal
  `if (chatIsOpen()) return;` beside the existing `briefEditorIsOpen()` guard + `pages.chat` +
  `chat-transcript`/`chat-input`/`chat-resend`; index.html `#/chat`; styles.css
  `--mode-tier-r`/`--mode-tier-w`/`--mode-tier-s`. Additive only (mirror the existing
  `briefEditorIsOpen` precedent). The plan `plan_hooks_ov-frontend.json` already carries a
  whole-file directive in `spec.implementation_notes`.
- After the §2 fix the worker will emit `__JANUSMASK_MANIFEST__` (3 verbatim files) and land it.

### 4b. Config — author `brief_hooks_ov-config.md` (NOT yet written; single-file `harness/config.yaml`)
- meta_task_type `harness_self_fix`; `files_touched = [harness/config.yaml]`; vcmd
  `python -m pytest tests/overseer/test_config_overseer.py -q`.
- Oracle requires an ADDITIVE default-OFF block (loaded via `harness.orchestrator.load_config`):
  ```yaml
  overseer:
    enabled: false
    default_mode: observe
    default_backend: claude
    models:
      claude: [opus, sonnet, haiku]
    store_path: state/overseer/sessions.json   # any str
    unlock_policy: {}                           # which Tier-S modes need unlock (any mapping)
  ```
  and must NOT disturb existing `autowork:` / `synthesis:` blocks.
- ⚠️ **`harness/config.yaml` has UNCOMMITTED working-tree edits** (auto_approve flags OFF +
  `synthesis.accept_single_agent_leaf_plans: true`) — an intentional safety posture that must NOT be
  lost. Before dispatching the config leaf, **commit those edits** (preserves them in HEAD; not a
  revert) so the worker's verbatim write builds on top of them; otherwise a whole-file manifest based
  on HEAD will drop them. Owner pre-authorized a default-OFF `overseer:` block ONLY.
- Needs an operator decision file (see §5).

---

## §5 BUILD RECIPE (manual-drive, token-efficient — proven this session)

Pre-flight EVERY dispatch (these are live landmines):
```
rm -f state/control/autowork/full_stop state/control/autowork/git_commit.lock
pgrep -f harness.autowork_daemon          # MUST be empty
ls state/tasks/*.json state/tasks/blocked/*.json   # MUST be empty of strays
```
- The daemon's `_retry_blocked_tasks` retries EVERY file in `state/tasks/blocked/` regardless of the
  allowlist (stale NGv2 tasks live there — archived to
  `_autowork_archive/2026-06-08_overseer_build_declutter/stale_blocked_ngv2_tasks/`). Keep it empty.
- **Stale-sidecar gotcha:** before re-dispatching a tid, delete
  `state/output/<tid>.{patches,files,py}.json|.py`, `state/tasks/blocked/<tid>.*`,
  `state/tasks/processed/<tid>.json`, `state/sessions/*<tid>*` — a surviving `.patches.json` wins over
  any fresh edit (`git_integration.py:~696`) and re-applies the bad symbol patch.

Per leaf:
```
python3 -m harness.planner.cli brief_hooks_ov-<leaf>.md --output-plan plan_hooks_ov-<leaf>.json
python3 -c "from pathlib import Path; import harness.planner.staging as s; s.stage_task(Path('plan_hooks_ov-<leaf>.json'),'<tid>',Path('state'))"
# harness_self_fix only: write the decision file (see below)
python3 -m harness.orchestrator_worker --state-dir state --task-id <tid>
python -m pytest tests/overseer/test_<oracle>.py -q     # must be GREEN
```
Decision file for `harness_self_fix` (config + the fix itself):
`state/control/decisions/<tid>.json` =
`{"task_id":"<tid>","decision":"approve","approved_by":"operator","reason":"...","scope":["<the file>"]}`.

Planner timeouts: detailed edit briefs can exceed 290s — allow ≥540s. Synthesis flake
(`synthesis_or_ast_failed` with NO draft) is transient — re-dispatch once. `web_api` needed precise
per-method + determinism hints in `spec.implementation_notes` (NO `uuid`/`random`/`datetime.now` — the
AST validator rejects them; mint ids from an instance counter).

---

## §6 CURRENT STATE (2026-06-08)

- HEAD `357328a`. **11 of 13 overseer leaves built + oracle-green this session:** the 6 foundations
  (modes, mode_gate, mode_prompts, model_select, session_store, transcript) + driver + actions +
  web_api + webui_control(edit) + webui_server(edit). The 2 EDIT leaves on Python files landed via the
  patches path; the non-Python leaves (frontend, config) are the only ones left, blocked by §1.
- **Root-cause fix #1 already landed** (separate from this handoff): `plan_normalizer.
  _correct_meta_task_type_by_target` (`b3ca66b`, oracle `76bf547`) retypes fuzzer-bound non-Python
  leaves so they bypass the diff-fuzzer — that fixed the `io_adapter`→`fuzz_error` mis-typing. This
  handoff is the NEXT limitation: applying those (now correctly-typed) non-Python edits.
- Safe posture: daemon dead, `full_stop` should be re-created when pausing, allowlist = `overseer_chat`,
  nothing pushed. Generated/superseded artifacts archived under
  `_autowork_archive/2026-06-08_overseer_build_declutter/`.
- Pinned overseer leaf briefs/plans for the built leaves are in
  `_autowork_archive/2026-06-08_overseer_build_declutter/pinned_superseded_by_epic/` (restore if needed);
  `brief_hooks_ov-frontend.md` (+ plan) is in repo root, ready.

## §7 AFTER BOTH LEAVES LAND
13/13 overseer-chat leaves built. Remaining epic work = Phase-H: the live Playwright UI-fidelity sweep
(`brief_hooks_overseer-ui-fidelity-sweep.md`, archived) — a manual/live verification, not a
deterministic leaf. Then the chat panel is functionally complete (default-OFF behind `overseer.enabled`).
