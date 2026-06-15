# HANDOFF — Make the auto-PoC writer produce CLAIMABLE bounty PoCs (close the real-confirm gap)

> **The brutal one-line summary:** the NobleGreedv2 (NGv2) bounty machinery is built end-to-end through all 9 handoff phases and parks fail-closed safely — but on real cloned repos it has confirmed **zero** real vulnerabilities (`0/5` in the Phase-9 live run). **Confirming a real, novel, claimable PoC is the entire product. Until that works, nothing else is "done."** This handoff is the mission to close that gap. Treat a real confirmed-and-claimable PoC as the ONLY acceptance bar; do not report "complete" on green unit oracles, fixture passes, or "it ran and parked." See memory `[[dont-conflate-built-with-works]]`.

Two repos: **JanusMaskJR (JM)** `/home/xnihil0zer0/JanusMaskJR` — the factory that builds NGv2 through its pipeline; **NobleGreedv2 (NGv2)** `/home/xnihil0zer0/NobleGreedv2` — the runtime. NGv2 venv: `/home/xnihil0zer0/NobleGreedv2/.venv`.

---

## 0. FIRST ACTION for the next session

An attempt at exactly this is **already in flight** (background agent `a1d0d9a978954ffcb`, launched 2026-06-12): it backs `LLMClient` with the `claude` CLI and drives `run_repair_loop(client=…)` over real ranked repos. **Before doing anything, check its outcome:**
- `cd /home/xnihil0zer0/NobleGreedv2 && git rev-parse --short HEAD && git status --porcelain` (production should be clean at `fa00e65`; scratch under `_e2e_run/`/`tmp/`).
- Look for any rendered package: `find /home/xnihil0zer0/NobleGreedv2/_e2e_run /home/xnihil0zer0/NobleGreedv2/phase9_out -name '*submission*.md' -o -name '*_poc.js' 2>/dev/null`.
- Read its final report (if the session has it) for the per-target confirm/fail breakdown.
If it produced a real confirm, your job shifts to **hardening + claimability review** (Sections 5.4–5.5). If it got another honest negative, your job is the **deeper PoC-quality work** (Section 4) — the wiring alone is likely insufficient.

---

## 1. Verified current state (2026-06-12)

- **NGv2 HEAD `fa00e65`, full gate `1462 passed`** (`cd /home/xnihil0zer0/NobleGreedv2 && .venv/bin/python -m pytest tests -q`). `ngv2/**` production is clean; the only dirty files are hand-authored e2e scratch (`_e2e_run/drive_phase9_live.py`, a `.gitignore` entry).
- **All 9 handoff phases are BUILT** (sourcing → clone → wired semantic scan → auto-PoC writer + repair loop → strict detonation → submission package → feedback loop → autonomous hunt loop + concurrency scheduler), and the auto-PoC passed its *synthetic* acceptance bar: **5/5 confirmed against the `_e2e_run/targets/<pattern>/svc.py` fixtures**.
- **Phase-9 live run = `0/5` confirmed** against 5 real, never-seen cloned repos (aws/sagemaker-python-sdk, triton-inference-server/server, autogluon/autogluon, vertaai/modeldb, huggingface/text-generation-inference). Honest negative — nothing faked, nothing submitted, all detonation jail-only.

**This `5/5 fixtures vs 0/5 real` split is the whole problem.** The fixtures were shaped to the writer's deterministic template (single-arg sinks like `lookup_host(payload)`). Real code is not.

---

## 2. Why it confirms nothing real (the Phase-9 diagnosis — verbatim, this is gold)

The auto-PoC correctly grounds the sink-bearing function via AST and imports it with the right absolute path, but then hits three genuine walls on real code:

1. **Multi-argument real sinks.** It correctly grounded `build_docker_image` in triton's `compose.py` (a real `subprocess` caller) and imported it — then called `build_docker_image(payload)` → `TypeError: missing 2 required positional arguments`. The deterministic template only knows the single-arg `f(payload)` shape.
2. **Import-time dependency failure inside the jail.** Many sink modules `ModuleNotFoundError` on package-relative or heavy imports (torch / numpy) inside the **net-isolated** bwrap jail (no network to pip-install, and the repo's own deps aren't installed).
3. **False-positive findings.** Several "eval_usage" hits were PyTorch `model.eval()` (mode-switch), not Python `eval()` — wasted PoC attempts on non-vulns.

So: 88/35/50/105/17 findings per repo, 8 PoC attempts each, **0 invoked the sink correctly**, therefore 0 could ever trigger the (harmless) payload, therefore 0 confirmed. The payload being harmless is irrelevant — nothing executed it.

---

## 3. The recommended fix — and why it is necessary but probably NOT sufficient

### 3.1 What's already wired (do NOT rebuild — FEED it)
The LLM-driven repair capability exists in the module APIs; the live path just passed `client=None`:
- `ngv2/poc_writer.py`: `write_poc(finding, target, language='python', *, client=None, resolver=None, feedback=None, grounding=None, template=None)` (`:381`) → when `client` is not None, calls `_refine(client, finding, grounding, template, …, feedback)` (`:365`) which prompts the model to rewrite the skeleton to the real sink. `synthesize` (`:405`) emits dual Python+Node PoCs; `draft_poc` (`:415`) threads `client`+`feedback` (the P4.3 repair hook).
- `ngv2/poc_repair_loop.py`: `run_repair_loop(finding, target, *, runner=None, client=None, resolver=None, max_attempts=3, timeout_s=30.0, success_marker=…, expected_fs_signature=…)` (`:63`) drives generate→detonate→observe→**repair**, feeding the runner's stderr/fs-diff back as `feedback` into `draft_poc(client=client, feedback=feedback)` (`:82`). `runner` defaults to `detonate_live`.
- `ngv2/llm_client.py`: `LLMClient(complete=<callable>, *, model=None, cascade=None, max_retries=3)` (`:30`); `complete_text(prompt, system=…, max_tokens=…)` (`:52`) is what `_refine` calls; `DEFAULT_MODEL='claude-fable-5'` (`:9`); built-in rate-limit retry. There is a `make_anthropic_client` SDK path **but `ANTHROPIC_API_KEY` is NOT set** in this environment, so that path is dead.

### 3.2 The model backend (verified)
- `claude` CLI IS available: `/home/xnihil0zer0/.nvm/versions/node/v22.17.0/bin/claude`; `~/.claude.json` present; `gemini` CLI also present. **No `ANTHROPIC_API_KEY`.**
- ⇒ Back `LLMClient`'s injected `complete` callable with a **`claude` CLI subprocess** (headless `claude -p`, NDJSON stream → assistant text), the factory's own model-call pattern. Reference the factory's invocation: `JanusMaskJR/config/claude_worker.json`, `claude_mcp.json`, and how `JanusMaskJR/harness/` shells out to `claude` (consumed as NDJSON; see README "every model call is a CLI subprocess consumed as NDJSON"). The wrapper can live in the `_e2e_run/` driver (hand-authorable, fast path) — only put it in `ngv2/**` if it must be production, in which case it goes through the JM pipeline oracle-first.

### 3.3 Why wiring the LLM is necessary but likely insufficient
Feeding the model in will fix wall #1 (it can repair `f(payload)` → `f(payload, mode='build', tag='x')` from the TypeError). It will NOT, by itself, fix:
- **Wall #2 (jail imports):** the model can't `pip install torch` in a net-isolated jail. The PoC must either (a) target sinks reachable WITHOUT heavy imports, (b) stub/mark heavy deps, or (c) the runner must provide the repo's installed venv into the jail (ro-bind the cloned repo's deps if present, or do a bounded `pip install` in a network-allowed *preparation* step OUTSIDE the detonation jail, then detonate net-isolated). Decide and build this deliberately.
- **Wall #3 (false-positive findings):** the scanner feeds `model.eval()` etc. as "eval_usage". Add an FP pre-filter (the existing `ngv2/fp_patterns.py`/`fp_filter.py` + the Phase-7 `verdict_feedback` growth are the seam) so PoC attempts aren't spent on non-vulns. Distinguish Python `eval`/`exec`/`os.system`/`subprocess(shell=True)`/`yaml.load`/`pickle.loads`/`__reduce__` real sinks from look-alikes.
- **Reachability ≠ sink-exists:** a sink in a file is not a vulnerability unless attacker-controlled input REACHES it from an entry point. The Phase-3 wired tree-sitter/taint signals (`ngv2/semantic_signals.py`, `confidence_signals.py`) should gate which findings are worth a PoC — prefer findings with a taint path, not every regex hit. This is the difference between "a PoC that runs a sink" and "a PoC that demonstrates an exploitable vuln an attacker could trigger."

**Bottom line for the next agent: do not declare victory when the model successfully *calls* a sink in the jail. Victory is a PoC that demonstrates ATTACKER-CONTROLLED INPUT reaching a real sink and producing the fs effect, on a vuln that is actually present and reachable at the cloned HEAD.**

---

## 4. Claimability — what makes a confirmed PoC actually CLAIMABLE (read this; "confirmed" ≠ "claimable")

A jail-confirmed fs effect is necessary but not sufficient for a payout. For huntr to accept and pay, the finding must be:
1. **Real & reachable** — attacker-controllable input reaches the sink via a public/exposed entry point (API, CLI, deserialization of untrusted data, etc.), not an internal-only call. Write the reachability story.
2. **Present at a citable commit** — SHA-pinned permalinks (`ngv2/permalink_pin.py`) to the exact vulnerable lines at the cloned commit; verify the lines still exist.
3. **In scope** — within the repo's bounty program scope (some paths/issue-classes are out of scope; check the program). The eligible-cache repos opted into paid programs, but per-program scope still applies.
4. **NOVEL, not a duplicate** — run `ngv2/novelty_gate.py::classify_novelty(finding, known_corpus)` with the corpus loaded by `ngv2/novelty_corpus.py::load_known_corpus()` (664 real prior submissions from `data/ngv2/huntr_existing_submissions.json`). A `CONFIRMED_DUP` is worthless — surface it and move on. **This is the most common way a real confirm is still unclaimable.**
5. **Impactful** — a CVSS vector/score and an impact paragraph that a triager will accept (`ngv2/huntr_submission.py` renders the 10 fields incl. CVSS + Impact).

The deliverable is the full `{ID}_submission.md` + `{ID}_poc.js` package (SHA-pinned), parked at `awaiting_submission` for the owner to review and manually submit. **NEVER auto-submit.**

---

## 5. Implementation plan (phased; oracle-first for `ngv2/**`, hand-authorable for `_e2e_run/`+`tests/`)

### 5.1 Wire a real `claude`-CLI-backed `LLMClient` (fast path: `_e2e_run/` driver)
Build `claude_cli_complete(prompt, system=…) -> str` (subprocess to `claude -p`, parse NDJSON/text, handle non-zero exit + rate-limit text → raise so `LLMClient`'s retry kicks in). `client = LLMClient(complete=claude_cli_complete, model='claude-fable-5')`. Smoke-test it in isolation first (one real call returns text).

### 5.2 Drive the repair loop live, per finding
For each high-value finding: `run_repair_loop(finding, target, client=client, runner=detonate_live, max_attempts=5, timeout_s=…)`. Confirm the model actually adapts the call from the TypeError/stderr feedback across iterations (log each attempt's PoC + jail result). Start by REPRODUCING a real confirm on ONE known-vulnerable case to prove the loop closes with the LLM (e.g. re-target a fixture-like real sink), THEN go wide.

### 5.3 Fix the three walls (Section 3.3) — likely the real work
- Sink-quality filter (FP pre-filter via `fp_patterns`/`fp_filter`; prefer taint-backed findings from `semantic_signals`/`confidence_signals`).
- Jail dependency strategy (decide a/b/c above; build it; an FS prep step outside the net-isolated detonation is probably cleanest).
- Reachability gating (only PoC findings with a plausible attacker entry path).
These are likely pipeline-routed `ngv2/**` leaves (oracle-first) if they touch production scan/PoC logic; the orchestration can live in the driver.

### 5.4 Re-run the live hunt to a REAL confirm
Ranked real eligible repos (`ngv2.selection_ranker.rank_candidates` over `data/ngv2/huntr_eligible_cache.json` + `huntr_repo_bounties.json` + saturation from `huntr_existing_submissions.json`), bounded candidate + LLM-call + wall-clock budget. Drive to ≥1 real jail-confirmed fs-effect PoC.

### 5.5 Claimability review + package
On a confirm: novelty check (5.4 → `classify_novelty`), reachability story, CVSS, SHA-pinned permalinks, render `{ID}_submission.md` + `{ID}_poc.js`, PARK at `awaiting_submission`. Report it for owner review.

---

## 6. Acceptance bar (the ONLY definition of done for this handoff)
≥1 **real, novel, in-scope** PoC that the model synthesized (not hand-written, not deterministic-template), that **actually triggers a real vulnerability** in a real cloned repo inside the bwrap jail (strong fs-oracle `confirmed`), rendered as a complete SHA-pinned submission package and parked for human submission. Anything less — fixture passes, "the loop ran", a confirmed-but-DUP, a sink that fired but isn't attacker-reachable — is **not done**; report it honestly as such with the precise blocker.

---

## 7. Safety guards (HARD — non-negotiable, unchanged from the epic)
- **NEVER auto-submit to any real platform.** Park at `awaiting_submission`; no huntr POST, no Playwright submit-click. Deliverable = on-disk package + parked session; the owner submits manually.
- **Every PoC detonates ONLY in the bwrap jail** (`ngv2/poc_runner_live.py::detonate_live` `:258` — `--unshare-net/ipc/pid`, ro-bind target, tmpfs, wall-clock timeout). **Harmless payloads only** (`id`/`whoami`/`: > $WORK/pwned`). NEVER run a candidate PoC on the host.
- **Confirmation requires real fs effect** (Phase-5 strict `semantic_verdict`; marker-only = `inconclusive`). Never fake/hand-write a confirm.
- Clone into in-tree `tmp/` (NOT `/tmp`), enforce size caps, refuse archived repos, clean up clones (Phase-9 left 186M; it cleaned up after).
- If a jail-dependency strategy needs network (pip install), do it in a SEPARATE preparation step, never inside the net-isolated detonation jail.
- `claude` CLI calls cost tokens — bound `max_attempts` and candidate count; log every call's target.

---

## 8. Build discipline (how NGv2 production is changed — unchanged)
- **Never hand-edit `ngv2/**`.** Every production change routes through the JM pipeline: RED `*_wired` oracle committed to NGv2 master FIRST (tree must be git-CLEAN at dispatch — EXTERNAL_DIRTY_GATE), then `brief_hooks_<slug>.md` at JM root with `working_dir: /home/xnihil0zer0/NobleGreedv2`, append slug to `state/control/autowork/auto_promote.allowlist`, the running daemon (pid `state/control/autowork.pid`) plans/stages/dispatches, verify the landing. `_e2e_run/` and `tests/` are hand-authorable.
- **prove-satisfiable recipe:** build a throwaway reference impl in `/tmp`, prove the RED oracle goes green against it, delete scratch, embed the EXACT validated artifact verbatim in the brief so the blind worker can't mis-implement.
- JM daemon: do NOT start a second; restart only if a JM harness change must load live (`kill -TERM "$(cat state/control/autowork.pid)"` + supervisor respawn + single-survivor check). NGv2 changes need no JM restart.

## 9. Carried-forward gotchas (hard-won across the whole epic — obey ALL)
1. ★★ **`verification_command` MUST be CWD-RELATIVE — NO `cd`.** It runs with `cwd=staging_worktree`; a `cd …NobleGreedv2 && pytest` prefix tests the pre-merge LIVE repo → new-symbol edits fail import → `auto_commit_failed`. Use `.venv/bin/python -m pytest tests/X.py -q` (space-separated union, no cd).
2. **PLANNER QUIRK:** every external `ngv2/**` leaf (new AND edit) MUST name a `*_wired` oracle (a `test_<x>_wired.py` importing the live `ngv2.<module>`) in `verification_command`, else `missing_wiring_oracle`/`planner_hallucination_discarded` (`plan_validator._is_module_creating` resolves `files_touched` vs JM root, not `working_dir`).
3. ★★ **LARGE WHOLE-FILE IMPLS GET PARAPHRASED** (the 362-line `poc_writer.py` looped at 14/19). Keep each new module/edit MODEST; PREFER a new CONSUMER module over editing a shared symbol; write WHOLE-FILE VERBATIM briefs + a `# Required plan shape` ONE-task directive to stop planner over-decomposition. **Recovery if paraphrased:** prove a validated artifact green in `/tmp`, place it at `state/output/<task_id>.{py,files.json}` (precedence `.patches.json` > `.files.json` > `.py`, `harness/git_integration.py:698-706`), re-dispatch — unchanged gates still decide (within `[[never-hand-edit-production-outside-pipeline]]`).
4. **NEW SUB-PACKAGE** needs an empty `ngv2/<pkg>/__init__.py` committed to NGv2 master FIRST (staging worktree won't import it otherwise; `ngv2` is `packages=["ngv2"]`). **R-ANCHOR ordering:** additive extra nodes go BEFORE the anchor def in the patch `code` block, else silently dropped. NEVER patch a class method by replacing the whole class.
5. ★ **ANTI-SEESAW:** before any same-symbol edit, `grep -rl <symbol> /home/xnihil0zer0/NobleGreedv2/tests/` and make `verification_command` run the UNION of every oracle touching it — a green new oracle can silently regress a sibling (cost real cycles in Phase 5: the union was 8 files, not the 6 first assumed).
6. ★ **NO BRIEF-LEVEL DEP GATING:** if a leaf imports a sibling NGv2 module you're building this batch, declare `dependencies: [sibling-slug]` in the brief frontmatter, else the daemon stages the importer first → `smoke_failed` → blocked (recoverable by re-staging from `state/tasks/blocked/` after the dep lands, but the dep declaration avoids the wasted attempt).
7. ★ **RECURRING STALE `git_commit.lock`:** the orchestrator re-execs (os.execv) after a self-commit and can leave a dead-PID `state/control/autowork/git_commit.lock` that WEDGES the daemon. If it stops landing, check that lock; `rm` it only if its PID is dead (never one held by a live pid).
8. **Redundant test_authoring siblings** auto-spawn per single-file brief and `retry_exhausted` harmlessly (~7 min each); optionally prune them from `state/tasks/` before dispatch. If `state/control/autowork/runaway_ceiling.json` appears, `rm` it (suppresses self-heal escalations only; daemon NOT halted). Nudge an idle daemon (1800s heartbeat) with `touch state/control/autowork/auto_promote.allowlist`.
9. ★ **SendMessage is NOT available** in this harness — you cannot steer a running background subagent; stop+re-dispatch fresh carrying progress in the brief. **A subagent whose `tool_uses` keeps CLIMBING is ALIVE, not an orphaned monitor** (mis-read twice → redundant supervisors; harmless only because the daemon SERIALIZES NGv2 tasks under T1 isolation). **The monitor-and-exit pattern makes agents report "complete" with 0 impls landed — always git-verify `Integrate validated code` commits; never trust an agent's "done" alone.** Tell every supervisor brief: "DRIVE each leaf to a confirmed green git landing — do NOT monitor-and-exit."
10. **Data files are at `data/ngv2/`** (NOT bare `data/`): `huntr_eligible_cache.json` (`{repos:[...], fetched_at}`, 96 repos), `huntr_repo_bounties.json` (tiers/payouts), `huntr_existing_submissions.json` (saturation + novelty corpus, 664 entries), and **`fp_patterns.json` is at `ngv2/` (NOT data/)**.

## 10. Verified file anchors
- **Auto-PoC:** `ngv2/poc_writer.py` (`write_poc:381`, `_refine:365`, `synthesize:405`, `draft_poc:415`), `ngv2/poc_repair_loop.py` (`run_repair_loop:63`, `draft_poc` call `:82`), `ngv2/llm_client.py` (`LLMClient.__init__:30`, `complete_text:52`, `make_anthropic_client` SDK path = DEAD no key, `DEFAULT_MODEL='claude-fable-5':9`).
- **Detonation/oracle:** `ngv2/poc_runner_live.py:258 detonate_live`, `ngv2/detonation.py semantic_verdict` (Phase-5 STRICT: marker-only→inconclusive; `expected_fs_signature` threaded via `ngv2/pipeline.py`).
- **Scan/signals:** `ngv2/pattern_scanner.py`, `ngv2/semantic_signals.py`, `ngv2/confidence_signals.py` (`resolve_signals`), wired into `ngv2/session_gate.py::_gate_triage_to_verify`.
- **Sourcing/rank/clone:** `ngv2/selection_ranker.py rank_candidates`, `ngv2/oracle_materializer.py`, `ngv2/acquisition/cloner.py clone_target`, `ngv2/sourcing/huntr_client.py`, `ngv2/huntr_cache_loader.py`.
- **Submission/novelty/feedback:** `ngv2/huntr_submission.py build_huntr_submission` (10 fields), `ngv2/permalink_pin.py pin_and_verify`, `ngv2/submission_quarantine.py partition_findings`, `ngv2/novelty_gate.py:43 classify_novelty`, `ngv2/novelty_corpus.py load_known_corpus`, `ngv2/submission_verdict.py`, `ngv2/verdict_feedback.py`, `ngv2/verdict_reweight.py`, `ngv2/fp_patterns.py`+`fp_filter.py`.
- **Orchestration:** `ngv2/hunt_loop.py run_hunt_loop`, `ngv2/concurrency_scheduler.py` (hard spawn ceiling), `ngv2/spawn_preflight.py` (5-gate), `ngv2/session_api.py:65 create_session`, `:524 advance`, `ngv2/session_db.py`.
- **e2e drivers (hand-authorable, base your work on these):** `_e2e_run/drive_hunt_loop.py` (real loop over a CWE-78 fixture, still green), `_e2e_run/drive_phase9_live.py` (the 0/5 real-repo run — the deterministic-client baseline to improve).
- **Model:** `claude` CLI at `/home/xnihil0zer0/.nvm/versions/node/v22.17.0/bin/claude`; `~/.claude.json` present; **no `ANTHROPIC_API_KEY`**. Factory reference: `JanusMaskJR/config/claude_worker.json`, `claude_mcp.json`.

## 11. Reference memories
`[[real-bounty-machinery-handoff]]` (the full epic ledger: Phases 0–9, all SHAs + gotchas), `[[dont-conflate-built-with-works]]` (the feedback that prompted this handoff), `[[concurrency-isolation-and-ngv2-solver-ast-epic]]` (prove-oracle-then-embed recipe), `[[never-hand-edit-production-outside-pipeline]]`, `[[stale-sidecar-precedence-gotcha]]`, `[[daemon-supervisor-respawn]]`, `[[implementation-is-not-wired-defect]]`.

---

*The discipline that built the machinery — propose with LLMs, decide with deterministic verifiers — is intact. What's missing is that the LLM was never actually invited to the one place it's indispensable: synthesizing a PoC that fits real, messy, multi-argument, dependency-laden code. Invite it, feed it the jail's failures, fix the reachability/dependency/false-positive walls around it, and judge success ONLY by a real, novel, claimable PoC — not by green tests.*
