# Phase IV Run Plan — driving the live acceptance run

Goal: park ≥1 NOVEL, in-scope, attacker-reachable, jail-confirmed PoC at
`awaiting_submission`. Driver scripts: `_e2e_run/drive_hunt_loop.py` (FSM/park
plumbing), `_e2e_run/drive_llm_confirm.py` (the paid LLM repair loop on one sink).

## 0. HARD RULES (encode as asserts / kill paths — non-negotiable)
1. **NEVER auto-submit.** `SessionApi.advance(sid)` is only ever called with ONE
   positional arg (no approval dict). FSM fail-closes and parks. The park IS the
   deliverable. No `mcp__noblegreed__submit_code`, no huntr POST, no form fill.
2. **Detonate jail-only, harmless payloads.** `detonate_live` runs under
   `bwrap --unshare-net`. Payload effect is bounded to: create file `pwned_marker`
   in cwd + print `VULNERABLE` + exit 0. No network, no host FS write, no real
   destructive command. The semantic verdict = exit0 + marker + fs-diff.
3. **Verify-at-source before spending LLM budget.** For each candidate, BEFORE the
   repair loop: (a) re-confirm the repo is still in the live huntr program and
   eligible; (b) re-scrape its live submission list and confirm the specific
   CWE-class/sink is NOT already reported (novelty); (c) re-pin the exact HEAD
   commit you scanned. A stale-cache GO is not a GO.

## 1. Hunt the DELTA, not the repo (pre-LLM, free)
For each candidate from TARGETING.md, in priority order:
1. `git clone` at the latest tag; record the pinned commit SHA.
2. Compute the change-surface: `git diff --name-only <prev_tag>..<latest_tag>`,
   filtered to `*.py` and the candidate's named subtree (e.g. `keras/src/saving/`).
3. Run the live detectors over the delta ONLY:
   - CWE-502: `ngv2.deser_detect.check_deserialization` on changed files.
   - CWE-78/95: `ngv2.pattern_scanner.scan_directory` on changed files.
   - Reachability filter: `_e2e_run/reachability.py` (param-derived) +
     `_e2e_run/sink_quality.py` (`is_excluded_path`, drops vendored/test/docs/build).
4. For **MFF candidates (keras/skops/autogluon/h5py)** reachability is satisfied by
   construction — the loader's input is the attacker artifact — so do NOT drop a
   deser sink for "not param-derived"; instead require the sink be on a
   *public load entrypoint* (`load`, `load_model`, `from_config`, `deserialize`).
5. Output per candidate: a ranked sink list `(file, line, category, load-entrypoint,
   novelty-checked?)`. Only sinks passing novelty + reachability proceed to §2.

## 2. The paid LLM repair loop (budget-capped)
Drive `drive_llm_confirm.py <repo_dir> <sink_rel> <line> <category> <max_attempts>`.

- **Per-sink attempt cap = 4** (the drive script default; pin it explicitly, never
  raise mid-run). The loop feeds real jail stderr/fs-diff back each attempt.
- **Per-candidate sink cap = 2** highest-ranked sinks. If neither confirms in
  ≤4 attempts each → mark candidate `honest_negative`, move on. Do NOT grind.
- **Run-wide LLM call ceiling = 60 synth calls** (≈ 15 candidates × ~4). Hard stop
  the run when hit; surface a budget-exhausted report. (Each synth call is real
  money via the `claude` CLI client — `_e2e_run/claude_cli_client.py`.)
- **Batch size = 4 candidates** at a time (Batch 1 first per TARGETING.md). Review
  Batch 1 results before spending Batch 2 budget — Batch 1 should clear the bar.
- Respect `ConcurrencyScheduler` `HARD_SPAWN_CEILING`; run candidates sequentially
  or ≤ the ceiling. No nohup'd second driver.

## 3. Confirmed-but-must-still-pass-claimability gate
A jail `confirmed` verdict is necessary, NOT sufficient (gptcache was confirmed but
non-claimable). Before parking, the sink MUST clear ALL of:
- **Reachable:** attacker controls the sink's dangerous input via a *public API /
  load entrypoint / network-or-file boundary* — NOT an internal caller passing
  hardcoded values (the gptcache `prompt_install` failure mode). For MFF: the model
  file is the boundary → pass. For CWE-78: must trace param to a public function.
- **In-scope:** sink is in shipped library code (not test/example/vendored/build).
- **Novel:** §0.3 live novelty check passed against the live submission list.
- **In a live, paying program** at the pinned commit.
Only then `db.save_session(..., phase=awaiting_submission)` + `advance(sid)` (1 arg).

## 4. Honest-negative vs machinery-bug (classify every non-confirm)
- **Honest negative** (expected, not a failure): sink confirmed but non-reachable /
  non-novel / out-of-scope; OR no detector-visible sink in the delta; OR LLM could
  not weaponize within the attempt cap. Record reason; this is a valid run outcome.
- **Machinery bug** (STOP and fix, do not paper over): jail won't start / bwrap
  error; `detonate_live` crashes; importlib stub strategy fails for ALL attempts
  with the same infra error (not a payload error); ranker/cloner/SessionDB
  exception; FSM won't park. Capture the traceback; file under GAPS, do not retry
  blindly. (Per memory: diagnose → fix via pipeline → rerun; no latent workarounds.)

## 5. Evidence to capture per candidate (under `_e2e_run/llm_confirm_out/`)
- pinned repo SHA + the `git diff` change-surface file list scanned.
- detector output (deser/pattern/reachability JSON) for the delta.
- live novelty-check result (scraped submission titles + the dedup verdict).
- `<module>_history.json` (every attempt's verdict/exit/fs-diff/poc_code — already
  emitted by the driver).
- on confirm: `<module>_confirmed_poc.py`, the `detonate_live` report (exit/stdout/
  stderr/fs_snapshot_diff proving net-isolation), and the 9-section submission
  package (`ngv2.session_gate.build_submission_package`).
- a one-line claimability verdict per §3 (reachable? novel? in-scope? paying?).
- append a row to a run `RUN_LEDGER.md` (mirror the prior honest format).

## 6. Kill-switch criteria (stop the whole run)
- Run-wide LLM ceiling (60 calls) hit → stop, report.
- ≥1 candidate parked at `awaiting_submission` clearing §3 → **bar met**, stop after
  finishing the current batch; hand to human checkpoint.
- 2 consecutive machinery bugs of the same class → stop, fix tooling, rerun.
- Any attempt to write outside the jail / any submit call detected → hard abort.

## 7. Park-for-human checkpoint (the finish line)
On a §3-clean confirm: session is parked at `awaiting_submission` (NOT submitted).
Produce a human-review packet: pinned SHA, claimability verdict, the confirmed PoC,
the jail report, the 9-section package, and the live novelty evidence. A human
(owner) makes the submit/no-submit call. The agent's job ends at the parked session.
