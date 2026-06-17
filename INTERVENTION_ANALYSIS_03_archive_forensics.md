# Intervention Analysis — Lane 3: Documented-Intervention Archive Forensics

**Scope:** the *documented-intervention artifacts* of the JanusMask factory —
`_autowork_archive/` (21 session dirs), `_autowork_scratch/`, repo-root handoffs
/ EPIC / PROVENANCE docs, adversarial-review/test-plan dirs, and the
`state/control/decisions/` harness-self-fix approval files.
**Method:** keyword-signature classification of artifact *contents* (not memory).
Reproduce with `python3 scripts/intervention_analysis/lane3_archive_forensics.py`
(emits `scripts/intervention_analysis/lane3_counts.json`).

> Counts are derived from the artifacts. Where a metric is noisy it is flagged and
> the cleaner signal (decision-file `reason` fields) is given alongside.

---

## 1. Corpus size analyzed

| Metric | Count |
|---|---:|
| Text/JSON artifacts scanned | **1,261** |
| Archive **session directories** (`_autowork_archive/*`) | **21** |
| `state/control/decisions/*.json` approval files (= individual harness_self_fix interventions) | **231** |
| Manual-drive **recipe-carrier** files (narrative .md / scratch .py) | **51** matched markers; **15** with explicit "manual drive" phrasing |
| Files invoking "oracle-first / hand-author oracle" | **207** |

The 21 archived sessions (each a distinct supervised work session) are:
`2026-06-05`, `2026-06-07_root_metadata_sweep`, `2026-06-08`,
`2026-06-08_overseer_build_declutter`, `2026-06-08_overseer_pillars_and_fsm`,
`2026-06-09_ngv2_wireup_epic`, `2026-06-09_p6_hook_registration`,
`2026-06-10_autocompiler_phases_bcd`, `2026-06-10_bugfix_sweep`,
`2026-06-11_bounty_fsm_pruned`, `2026-06-12_live_bounty_decompose_prune`,
`2026-06-13_ngv2_spawn_entrypoint_complete`, `2026-06-14_backend_epics_complete`,
`2026-06-14_root_declutter` (holds ~25 root HANDOFF_*.md), `ngv2_epic4_mopup`,
`ngv2_epic4_priorrun_partial`, `overseer_decompose_prune`,
`overseer_no_output_evidence`, `overseer_session_verification`,
`phase2_symbol_ledger_attempt1`, `stale_briefs_2026-06-08`.

---

## 2. BLOCKER-CLASS frequency — the root causes that FORCED intervention

Two columns:
* **Decision-file** = artifacts where a harness_self_fix decision `reason` (or the
  task_id slug) names this blocker. This is the *high-precision* signal: each row
  is a root cause the supervisor had to author an approval to fix.
* **All-corpus** = every artifact (incl. handoffs, briefs, scratch) mentioning the
  blocker. Higher recall, but inflated by feature briefs that *name* a topic
  (e.g. "jail"/"smoke"/"AST") without it being a blocker — read as "attention
  surface", not "intervention count".

| Blocker class | Decision-file | All-corpus | NGv2? |
|---|---:|---:|:--:|
| **jail / sandbox / fail-closed security fix** | **57** | 265 | ⚠ shared jail substrate |
| **external-root target resolution** (working_dir/PROJECT_ROOT, external edit leaves, staging reroot) | **18** | 91 | 🔴 NGv2 |
| **AST partial-edit truncation / never-patch-class-methods / R-anchor** | **9** | 161 | — |
| **dep-gate leak or wedge** (premature release, brief-dep deadlock, unresolvable deps) | **5** | 28 | — |
| **non-Python / multi-file apply routing** (verbatim manifest) | **4** | 55 | ⚠ NGv2 builds non-.py |
| **external-build smoke / retry budget** (diff-fuzzer can't resolve external imports) | **3** | 138 | 🔴 NGv2 |
| **implementation ≠ wired (orphan modules / wire-up gate)** | **3** | 58 | ⚠ NGv2 |
| **planner ignores brief verification_command → vacuous accept** | **3** | 53 | — |
| **blind-worker clobber / clobber-bomb** | **3** | 63 | — |
| **stale sidecar (.patches.json / .files.json) precedence / retry-poison** | **2** | 31 | — |
| **stale existing-test assertions / anti-seesaw / hermeticity** | **2** | 40 | — |
| **epic decompose hallucination / child-admission / slug-dep drift** | **2** | 35 | ⚠ NGv2 epics |
| **vcmd vacuous-import bomb** (`python -c "import X"`) | **1** | 31 | — |
| **new-module-must-be-whole-file** (patch path can't add symbols) | **1** | 50 | — |
| **no-output stream-json parse** (overseer empty turns) | 0 | 18 | — |
| **decompose false-block on complex leaves** | 0 | 16 | — |
| **planner attaches stray mutation_target** | 0* | 2 | — |

\* `planner_stray_mutation_target` shows 0 in *decisions* because its fix
(`_strip_stray_mutation_targets`) was **in flight** at the snapshot (RED-oracle
stage per memory `srcdrive-epic-leaf1`), not yet an approved decision — it is a
live, unautomated blocker, not a closed one. Counted from the SRCDRIVE handoffs.

**16 of 231 decision files are NGv2-touching** (reason/slug references
NobleGreedv2 / external root / working_dir): e.g. `T_RETARGET`,
`EXTERNAL_ROOTS_ALLOWLIST`, `PHASE_SEAM1_BRIEF_WORKINGDIR`, `COMMIT_REROOT`,
`STAGING_REROOT`, `WORKINGDIR_ENV_STAMP`, `EXTERNAL_DIRTY_GATE`,
`fix-external-jail-project-ro`, `seq-worker-env-propagation`,
`concurrency_isolation`, `planner-committed-module-dedup-impl`. **Any automation
of the `external-root target resolution` and `external-build smoke/retry` classes
must preserve compatibility with `/home/xnihil0zer0/NobleGreedv2`** (these are the
seams the factory uses to build into the sibling repo).

### Reading the two signals together
The **all-corpus** column is dominated by `jail/sandbox` (265) and
`AST/partial-edit` (161) because those are huge *feature areas* with dozens of
briefs. But the **decision-file** column — what actually forced the supervisor to
hand-author an approval — tells the truer story: after the early jail/security
hardening burst (57, mostly late-May/early-June one-time stand-up of the sandbox),
the *recurring* day-to-day blockers are **external-root resolution (18)**,
**AST/whole-file edit mechanics (9 + the whole-file/vcmd/sidecar cluster)**, and
the **planner-defect cluster** (dep-gate + verification_command + clobber +
mutation_target + decompose), which together account for the bulk of mid-June
interventions.

---

## 3. INTERVENTION-TYPE frequency — what the supervisor did

| Intervention type | Files |
|---|---:|
| **harness_self_fix decision authoring** (RED-oracle → brief → approve decision file) | **216** |
| **hand-author RED oracle** (oracle-first; the one always-manual step) | **209** |
| **owner hand-edit, gated** (`_NEVER_AUTO_APPROVE`, §4a/4b, hand-edit applied/reversed) | **146** |
| **config / allowlist hand-edit** (allowlist slug, posture flags ON, config override) | **55** |
| **gemini-solo / backend swap** (solo↔dual agent, tmux-jailed-claude) | **54** |
| **adversarial verification pass** (falsify prior session's "done" claims, 4-agent sweep) | **33** |
| **daemon pause/resume / supervisor respawn** | **17** |
| **quarantine / prune clobber** (move spent plans, neutralize queued clobbers, drain backlog) | **17** |
| **manual-drive recipe** (stage→inject-oracle→manual worker spawn) | **13** |
| **revert-then-manual-rebuild** (revert clobbered file, hand-drive fresh) | **4** |

The dominant ongoing manual cost is the **oracle-first ritual** (209 files):
*every* harness_self_fix and new-module leaf requires the human/supervisor to
hand-author a RED test oracle and commit it BEFORE the blind worker runs — this is
deliberate (tests are the one hand-authorable artifact per
`never-hand-edit-production-outside-pipeline`), but the **injection** of that
oracle source into the worker prompt is mechanical and currently manual (see §4).

---

## 4. Most-repeated manual-drive recipes (verbatim where short)

### R1 — The canonical "manual single-leaf drive" (`_autowork_scratch/drive_leaf.py`)
The single most-reused workaround. Stages a leaf, **forces** a real pytest
verification_command, and **injects the committed oracle SOURCE** into the worker's
`implementation_notes` so the blind worker sees the exact contract — then the
supervisor spawns the worker by hand:

```
# Usage: python3 _autowork_scratch/drive_leaf.py <plan.json> <impl_task_id> <oracle1> [oracle2 ...]
# Then:  python -m harness.orchestrator_worker --state-dir state \
#          --task-id <impl_task_id> --config harness/config.yaml
stage_task(Path(plan), tid, Path("state"))
t["verification_command"] = "python -m pytest " + " ".join(oracles) + " -q"   # override weak vcmd
t["spec"]["implementation_notes"] += "=== EXACT ORACLE CONTRACT ... ===" + <oracle file contents>
```
This recipe exists *specifically because* of two blocker classes:
`planner_ignores_verification_command` (planner emits a weak `python -c import`
vcmd) and the oracle-injection gap. It also pre-cleans `state/tasks`,
`state/output/<id>.*`, and `state/sessions/*_<id>_*` to **reset the retry budget** —
itself a workaround for `stale_sidecar_precedence`.

### R2 — The manual pipeline triad (FACTORY_ORIENTATION.md / multiple handoffs)
```
harness/planner/cli.py:main()  →  staging.py:stage_task()  →  orchestrator_worker --task-id
```
Repeated across `NGV2_PIPELINE_EXECUTION_HANDOFF.md`,
`HANDOFF_ngv2_bounty_fsm_completion.md`, `HANDOFF_multifile_nonpython_edits.md`,
`HANDOFF_factory_clobber_fix_and_ngv2_worker_rework.md`, `brief_hooks_wire_up_phase.md`.

### R3 — Revert-then-manual-rebuild for whole-file leaves
Seen in `HANDOFF_webui_config_model_backends...md`, `PHV_config_schema.md`,
`ADVERSARIAL_VERIFY_FINDINGS.md`, `drive_epic_harness_hardening...md`: when a leaf
clobbered or the planner mis-shaped it, the supervisor **reverts the file to HEAD**
and re-drives a *fresh* single-file whole-file build (the `config-schema` FRESH
rebuild via revert+manual-drive is the archetype). Driven by
`blind_worker_clobber` + `new_module_must_be_whole_file`.

### R4 — Gemini-solo scoped-config override for large webui files
`config_gemini_solo.yaml` (in `_autowork_scratch/`): a one-off config that swaps the
synthesis backend to Gemini-solo because Claude balks at ~147 KB whole-file webui
leaves and emits placeholders. 54 files reference the solo↔dual / backend-swap lever.

---

## 5. Automation candidates (mapped to the blocker each eliminates)

Prioritized by recurrence × manual cost; each names the blocker class it kills.

1. **Auto-inject committed oracle source into the worker prompt** (kills the
   manual half of *hand_author_oracle*, 209 files, and obsoletes `drive_leaf.py`).
   At stage time, resolve the leaf's paired `tests/**/test_<leaf>.py`, embed its
   SOURCE into `implementation_notes` under a fixed "EXACT ORACLE CONTRACT" header
   automatically. Eliminates recipe R1's central move.

2. **Planner always upgrades a weak `python -c import` vcmd to the paired pytest
   gate** (kills `planner_ignores_verification_command` (53/3) + `vcmd_vacuous_import_bomb`
   (31/1)). The `_sanitize_impl_verification_commands` guard already does this only
   when the command names a sibling oracle; generalize it to *discover* the paired
   oracle by leaf slug. Removes the manual `t["verification_command"]=...` override.

3. **Structural multi-file split + whole-file manifest for new modules at plan
   normalize time** (kills `blind_worker_clobber` (63/3) + `new_module_must_be_whole_file`
   (50/1) + `nonpy_multifile_apply_routing` (55/4)). `_split_multifile_module_tasks`
   exists; make it the default and route all new-module/non-.py leaves through the
   verbatim-manifest path so the blind worker can never emit a clobbering
   multi-file patch. Eliminates recipe R3's revert-rebuild.

4. **Terminal-outcome sidecar purge + retry-budget reset on every dispatch**
   (kills `stale_sidecar_precedence` (31/2)). `worker_purge_stale_sidecars` landed
   the purge; extend it to also clear `state/sessions/*_<id>_*` and `state/tasks/<id>.json`
   on re-dispatch so `.patches.json`/`.files.json` never take precedence over fresh
   `.py`. Removes the pre-clean block hand-coded into `drive_leaf.py`.

5. **External-root working_dir threading through the whole pipeline** (kills
   `external_root_target_resolution` (91/18) — **NGv2-critical**). `stamp-working-dir-blind-draft`
   landed this for blind_draft; complete it end-to-end (planner validation,
   staging reroot, commit reroot, seq-worker env) so external EDIT leaves resolve
   against the real NobleGreedv2 root without per-leaf decision files. **Must be
   regression-tested against `/home/xnihil0zer0/NobleGreedv2`.**

6. **`mutation_target` normalizer = MODULE-only** (kills `planner_stray_mutation_target`,
   the live in-flight blocker). Add `_strip_stray_mutation_targets` as a permanent
   plan_normalizer pass that drops `module.function` mutation targets on new-file
   impl tasks (they map to bogus `module/function.py` and fail the mutation gate).

7. **Brief-dep deadlock-breaker + unresolvable-dep stripper as standing passes**
   (kills `dep_gate_leak_or_wedge` (28/5) + `epic_decompose_hallucination` slug-dep
   drift (35/2)). `brief-dep-deadlock-breaker` and `strip_unresolvable_deps` both
   landed as one-offs; promote to default-on so epic child slug-dep drift never
   wedges dispatch again.

8. **Wire-up gate at ACCEPTANCE for every new module** (kills
   `implementation_not_wired_orphan` (58/3)). Make the `orphan_unwired` check a
   default acceptance gate (with the validated import-tracer that fixed the
   pkg-submodule false positives) so "BUILT" can't be reported without "WIRED".
   **NGv2-relevant** (NGv2 modules are the most-orphaned class).

9. **Daemon-pause as a single authoritative primitive** (kills
   `daemon_pause_clobber_hazard` (55/17 pause/resume interventions)). The artifacts
   show two contradictory pause mechanisms (`state/control/orchestrator.flag`=`pause`
   vs. existence of `state/control/autowork/pause`); unify to one so the supervisor
   never blind-clobbers live workers by pausing the wrong way.

10. **Standing adversarial-verification harness** (reduces *adversarial_verification_pass*,
    33 files). Every handoff opens by re-falsifying the prior session's "done"
    claims by hand (HEAD diff vs. claimed commits, oracle re-run). A scripted
    "verify-claims-against-HEAD" pass would make this a button, not a session.

---

## 6. NGv2 compatibility flags (summary)

Automation candidates **#5, #8** and blocker classes
`external_root_target_resolution`, `external_build_smoke_retry`,
`nonpy_multifile_apply_routing`, `implementation_not_wired_orphan`, and
`epic_decompose_hallucination` all sit on the seam the factory uses to build into
`/home/xnihil0zer0/NobleGreedv2`. 16/231 decision files are explicitly
NGv2/external. Any change to staging-reroot, commit-reroot, working_dir threading,
or the external smoke/diff-fuzzer path **must keep building NGv2 cleanly** — gate
those automations behind a regression run against the sibling repo.
