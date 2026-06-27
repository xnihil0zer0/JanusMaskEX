# NGv2 Closure — Wave 0/1 Target Map (re-verified 2026-06-19)

Repos: JanusMask = `/home/xnihil0zer0/JanusMaskJR` (harness/**); NGv2 = `/home/xnihil0zer0/NobleGreedv2` (`ngv2/` package, importable; `run_hunt.py` exists; `.venv` = **Python 3.13.0**).
Re-confirm a target by reading the file before authoring (code drifts). ✓ = matched roadmap citation.

## WAVE 0
### P0.1 g7_fuzz_jail_credfree (JanusMask, harness_self_fix, BARRIER)
- `harness/sandbox.py:892` — `subprocess.Popen([sys.executable, runner_path, payload_path, result_path])` main execute — UN-JAILED ✓
- `harness/sandbox.py:1077` — `subprocess.Popen([sys.executable, runner_path, payload_path])` batch pool — UN-JAILED ✓
- `harness/sandbox.py:1281` — `subprocess.Popen([sys.executable, runner_path, "--pool"])` worker pool — UN-JAILED ✓
- `harness/agent_jail.py:65` — `build_jail_argv(cmd, *, repo_root, work_dir, state_dir, home=None, extra_ro=(), extra_rw=(), dbus_proxy_socket=None, bind_credentials=True, js_node_bin_dir=None)` — route the three sites with `bind_credentials=False`.
- `harness/diff_fuzzer.py:562,626,999,1107` — call `sandbox.execute()`/`execute_batch()`, no jail routing (verify the route is REACHED after fix).
- NOTE: sandbox.py NOT in `_NEVER_AUTO_APPROVE` (auto-approvable harness/**), but agent_jail.py IS irreducible — keep the edit inside sandbox.py, importing build_jail_argv. Barrier: quiesce fuzzing + restart daemon around it.

### P0.2 g8_dep_install_jailed_lockfile (JanusMask + NGv2, harness_self_fix)
- `harness/target_bootstrap.py:162-184` — `_ensure_venv`: host `pip install -r req` network-on, errors swallowed ✓
- NGv2 `ngv2/poc_runner_live.py:373-384` — `_default_pip_installer`: host `pip install --target`, network live, fail-soft ✓
- NGv2 `ngv2/poc_runner_live.py:327` — `MAX_DEP_INSTALL_ROUNDS = 3`; reactive loop re-runs PoC at ~:272 ✓

## WAVE 1 (NGv2 `ngv2/`)
### P1.1 gate_every_transition_typed_terminals (state_machine) — SPINE ROOT
- `ngv2/gate_executor.py:24` — `_TRANSITION_GATES = {('poc','detonate'):..., ('detonate','novelty'):...}` — only 2 gated; all others advance=True ✓
- `ngv2/transition_planner.py:9` — `PHASE_ORDER = ('source','hunt','triage','verify','poc','detonate','novelty','report','awaiting_submission','submitted','done')` (11) ✓
- `ngv2/transition_planner.py:40` — `plan_next_action`: only re-spawns hunt/poc/detonate on missing artifacts ✓
- `ngv2/run_hunt.py:61` — `_INITIAL_PHASE = 'hunt'` ✓
- `ngv2/conductor_loop.py:11` — `TERMINAL_STEPS = frozenset({'done','parked','blocked'})` — DRIFT: a frozenset of strings, NOT a typed enum; P1.1 introduces the typed-terminal enum.

### P1.2 detonation_authenticity_provenance (validation; touches detonation.py)
- `ngv2/poc_authenticity_gate.py:88-171` — `classify_poc_authenticity` → dict{imports_target, issues_network_request, mode∈(real_target/self_contained_mock/network_live), may_confirm} (AST toggle) ✓
- `ngv2/detonation.py:3-22` — `semantic_verdict`: requires NON-EMPTY `expected_fs_signature` for 'confirmed' (empty/None → inconclusive) ✓

### P1.3 wire_loopback_per_cwe_channels (io_adapter; touches detonation.py — collides w/ P1.2, serialize)
- `ngv2/loopback_listener.py:7` — `LoopbackListener` — DEAD (0 prod importers, test-only) ✓
- `ngv2/auth_bootstrap.py` — DEAD (0 prod importers, test-only) ✓
- `ngv2/workers/_runner.py:221-272` — `_make_detonation_seam`; line 267 `detonate_live(poc_obj, {'repo_root': repo_root}, ...)` — target spec dict has ONLY `repo_root` (this is also P2.2's target) ✓

## DRIFT FLAGS
1. P1.1 terminals = frozenset of strings, not enum (expected; P1.1 builds the enum).
2. (none blocking) jail non-routing at the 3 sandbox sites = the P0.1 work, confirmed present.
