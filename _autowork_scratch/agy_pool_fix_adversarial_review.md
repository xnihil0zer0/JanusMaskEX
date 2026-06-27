# Adversarial Review — agy_pool config-dir fix

**Subject:** Extend `harness/agy_pool.py::ensure_seeded` to create/repair `<home>/.gemini/config/` + `config/projects/` as real dirs.
**Reviewer posture:** read-only, tried to break it.
**Repro:** `_autowork_scratch/agy_pool_fix_repro.py` (PYTHONPATH=. python3 ...). All assertions pass; output cited below.
**Overall recommendation: SHIP-WITH-ADDITIONS** — the fix is CORRECT and the root-cause is proven verbatim in the live logs, but the spec as written introduces a hermetic-test regression (Q7) that MUST be addressed, and the repair predicate must use `lexists`/`islink` not `exists` (Q3).

---

## Root cause — INDEPENDENTLY CONFIRMED (live logs, not just the brief)
Live agy 1.0.4 pool log `.agents/agy-pool/w0/.gemini/antigravity-cli/cli.log` says, verbatim:
```
project discovery failed: ... create projects dir .../w0/.gemini/config/projects:
    mkdir .../w0/.gemini/config: not a directory
conversation_manager.go:323] failed to ensure project created during new conversation boot
printmode.go:155] Print mode: conversation=, sending message
conversation_manager.go:454] Ignoring user message, no active conversation
printmode.go:158] Print mode: SendUserMessage failed: no active conversation
```
And FS: `.agents/agy-pool/w0/.gemini/config` and `w1/.gemini/config` are both `-r--r--r-- 0` byte files; the working `~/.gemini/config` is a real dir with `projects/`. The `~/.gemini` parent in the pool home is `drwxrwxr-x` (writable) → repair is feasible. Bug is exactly as the brief states.

---

## Per-question verdicts

### Q1 — Correctness of the jail branch — **PASS**
agent_jail.py:266-277: the ro-overlay loop takes the `os.path.exists(_ro)` → `--ro-bind config config` branch once `config` is a real dir (instead of the `/dev/null` materialization). Then agent_jail.py:287-289 re-carves `config/projects` rw with `--bind` *after* the config ro-bind, and bwrap's "later bind wins" makes `projects/` writable inside a read-only `config/`. No ordering issue: the projects rw-bind is emitted strictly after the config ro-bind in the same argv build (lines 274-277 then 287-289). The `os.path.isdir(_gemini_proj)` guard now fires because the fix creates `projects/` on disk. Agy's `mkdir config/projects` becomes a no-op (dir already present) and per-workspace trust writes land in the rw projects/. CONFIRMED by repro PART B (config DIR with projects/) + the existing REV25 jail comment that this is the intended seam.

### Q2 — Emptiness gap (`mcp_config.json`, `.migrated`) — **PASS (empty dir is sufficient)**
The live log proves agy treats config contents as OPTIONAL:
```
cli_setting_manager.go:68] config.json not found or unreadable, using CLI settings only
cli_setting_manager.go:242] cli settings not available, using defaults
```
These are INFO/WARN, non-fatal. The ONLY fatal error is the `config/projects` mkdir against a non-dir `config`. Auth still succeeds (`silent auth succeeded` / `authenticated via keyring`). `mcp_config.json` and `.migrated` are NOT required to boot or submit in print mode — agy regenerates/ignores them. An EMPTY `config/` dir is sufficient. No additions needed here.

### Q3 — Repair safety — **NEEDS-CHANGE (predicate hardening)**
`os.remove` on a 0-byte 0444 file succeeds because deletion depends on the PARENT dir's write/execute perms (`.gemini/` is `drwxrwxr-x`), not the file's own mode. Confirmed in repro PART B3 (removes the 0444 file, then mkdir succeeds). Real dirs with data are preserved (repro B4 — `trust.json` survives). BUT the spec's repair predicate must be precise:
- Use `os.path.lexists(config)` + `not isdir(config)` to decide "non-dir present". DO NOT gate on `os.path.exists` (which follows symlinks and returns False for a dangling symlink, leaving a broken-symlink `config` un-repaired → `makedirs` then raises `FileExistsError`).
- The remover must NEVER be able to hit a directory: `os.remove` on a directory raises `IsADirectoryError` — fine (fail-loud), but to be safe the guard `not isdir(config)` already excludes the dir case, and `remove` should be `os.remove` (file-only), NOT `shutil.rmtree`. The spec's `remove=os.remove` is correct — keep it file-only so a real dir can never be wiped.
**Addition:** specify `lexists`/`islink`-aware predicate (see Additions §1).

### Q4 — Idempotency / re-entrancy — **PASS**
Repro PART B2: a second run on an already-proper dir is a no-op (the `lexists && not isdir` branch is False; `makedirs(projects)` with `exist_ok=True` is a no-op). Two concurrent seeders: both call `makedirs(..., exist_ok=True)` → TOCTOU-safe (the call site already passes `lambda d: os.makedirs(d, exist_ok=True)`). The ONLY race risk is the repair: worker A `remove(config)` then worker B also tries `remove(config)` → `FileNotFoundError`. **Addition:** wrap the `remove` in a `FileNotFoundError`/`OSError` tolerance (the orchestrator caller already wraps the whole `ensure_seeded` in `except OSError: pass`, so an unhandled `FileNotFoundError` from a lost repair race would silently skip the whole seed — acceptable but the next spawn self-heals; better to swallow it locally). See Additions §2.

### Q5 — Other collisions / is `.gemini/config` the only one — **PASS**
The ro-overlay loop also `/dev/null`-binds `.claude/skills`, `.claude/plugins`, `.gemini/GEMINI.md`, `.claude/settings.json`, `.claude/settings.local.json`. Findings:
- **claude is NOT pooled.** `_apply_agy_pool_env` gates on `basename(cmd)=='agy'` (orchestrator.py:236) and only agy gets a `JANUSMASK_AGY_SLOT`. So the `.claude/*` collisions never occur in the pool home — claude runs under the shared real HOME where those are real. No fix needed there.
- **GEMINI.md** is materialized as a 0-byte file in the pool home (live FS confirms `-r--r--r-- 0 GEMINI.md`), but agy NEVER errors on it — grep of all pool logs for "GEMINI.md" is EMPTY. It's an optional context file; a 0-byte/absent one is harmless.
- **`.gemini/config` is the ONLY dir-shaped gemini-side collision that breaks agy.** No sibling the fix misses.

### Q6 — Stale broken homes / auto self-heal — **PASS**
`_build_agent_env` (orchestrator.py:393, called on every agent spawn) → `_apply_agy_pool_env` (line 321) → `ensure_seeded` (line 248). So the existing w0/w1 broken `config` files get repaired automatically on the NEXT agy spawn for that slot. Manual cleanup is NOT required for correctness. (Optional: a one-time `rm .agents/agy-pool/*/.gemini/config` would heal them a few seconds sooner, but the fix is self-healing.)

### Q7 — Regression from new kw-only params — **NEEDS-CHANGE (the real risk)**
Two existing test suites + the call site:
- `tests/test_orchestrator_agy_pool.py::test_pooled_home_set_for_agy_agent_with_slot` points HOME at an empty tmp_path and DOCUMENTS "ensure_seeded finds no sources and creates nothing on disk." The fix creates `config/`+`config/projects/` UNCONDITIONALLY (not gated on a copied src) — repro PART C proves `config existed before=False, after=True`. So this test's premise ("creates nothing on disk") becomes false; it will now write `<repo>/.agents/agy-pool/w2/.gemini/config/projects/` under the REAL PROJECT_DIR during the test run (leaking real-disk state). The test's asserts don't check the FS so it won't fail RED — but it silently pollutes the live repo's `.agents/` tree from a unit test. **That is a regression.**
- `tests/harness/test_agy_pool.py` `_FakeFS` injects `copy/exists/makedirs` but has NO `isdir`/`remove` seam. If the fix calls the DEFAULT `os.path.isdir`/`os.remove`, the FakeFS tests touch the REAL filesystem for the isdir check and (worse) could `os.remove` a real path. The new dir-creation MUST route through the INJECTED `makedirs` seam (FakeFS records it) and the `isdir` probe must default-safe to the FakeFS-present set, not real `os.path.isdir`.
- Adding `isdir=os.path.isdir, remove=os.remove` as DEFAULTED kw-only params does NOT break the call-site signature (orchestrator.py:248 omits them) nor the test signatures (they omit them too). The break is BEHAVIORAL (unconditional real-disk creation), not signature.
**Fix:** (a) the new config-dir creation MUST use the injected `makedirs` seam (already passed); (b) the `isdir` probe should default to `os.path.isdir` BUT the existing FakeFS tests will exercise real isdir — acceptable for isdir (read-only probe) as long as `remove` is only ever reached when a real non-dir exists, which never happens under FakeFS. The orchestrator hermetic test pollution is the one that needs a guard or a test update. See Additions §3.

---

## ADDITIONS required (SHIP-WITH-ADDITIONS)

1. **Predicate (Q3):** repair on `os.path.lexists(config) and not isdir(config)` (catches dangling symlinks + non-dir files), NOT `os.path.exists`.
2. **Race tolerance (Q4):** wrap `remove(config)` so a lost repair race (`FileNotFoundError`) does not abort the whole seed:
   ```python
   if os.path.lexists(config) and not isdir(config):
       try: remove(config)
       except FileNotFoundError: pass
   makedirs(projects)   # exist_ok=True at the call site
   ```
3. **Hermetic-test integrity (Q7):** the config-dir creation must flow through the SAME injected `makedirs` seam already supplied (so FakeFS records it, no real I/O), AND `tests/test_orchestrator_agy_pool.py` must be updated to assert the config dir is created under the tmp worker_home (or the test must point PROJECT_DIR at a tmp dir) — otherwise the unit test silently writes into the live `.agents/` tree. This is the only change that touches a test; per the spec-only-pipeline rule, route the oracle update through test_authoring, not a hand-edit.
4. **No `mcp_config.json`/`.migrated` marker files needed** (Q2 proven) — do NOT add them; an empty config dir boots agy.

---

## Repro output (cited)
```
PART A — RED: copied=[]; config ABSENT after current ensure_seeded (RED-A1);
              injected 0444 file stays NON-DIR after current ensure_seeded (RED-A2)
PART B — GREEN: B1 fresh -> DIR with projects/; B2 idempotent -> DIR with projects/;
              B3 repair 0444 non-dir -> DIR with projects/; B4 real-dir+data preserved
PART C — Regression: config existed before=False after=True  (unconditional creation;
              hermetic tests assume 'creates nothing' with empty HOME)
ALL ASSERTIONS PASSED
```
