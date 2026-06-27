---
name: claudecap-landed-split-and-configdir-contract
description: "claudecap parallelism feature LANDED via 3-task single-file split (symbol patches), full oracle 16/16, daemon restarted; + the large-multi-file split rule and the CLAUDE_CONFIG_DIR oracle-binding contract gotcha"
metadata: 
  node_type: memory
  type: project
  originSessionId: 616f554d-443f-40fc-8bb7-280ce6b027c0
---

✅ **claudecap (the GATING parallelism feature) LANDED + oracle-green + daemon-live 2026-06-20.**
Three commits, all single-file symbol/manifest patches, full oracle
`tests/harness/test_claudecap_parallel_isolation.py` = **16/16, 0 skipped**:
- `184cc8f` claudecap-daemon-cap — `_claude_parallel_cap` reader (R-anchor on `_parallel_cap`) + `_iteration` parallel-dispatch branch in **165KB** autowork_daemon.py.
- `c33f808` claudecap-orchestrator-configdir — `_seed_claude_config_dir` (R-anchor on `_apply_agy_pool_env`) + `spawn_agent` CLAUDE_CONFIG_DIR injection in **265KB** orchestrator.py.
- `34aedce` claudecap-config-key — `claude_parallel_cap: 4` in config.yaml `autowork:`.
Daemon restarted (was pid 2362323 → **2451034**, `daemon_start cap=5`) so the new
`_iteration` is live. Empirical proof (real `_iteration`, mocked spawns,
`_autowork_scratch/claudecap_empirical_4way.py`): **cap=4 → 4 disjoint claude tasks
dispatch via the PARALLEL `_spawn_worker` branch, 0 suspend; cap=1 → sequential
suspend path (back-compat).** Remaining optional gold-standard = observe 4 REAL
concurrent claude PTYs (costs OAuth-subscription rate). Builds on
[[absent-peer-promotion-landed-and-orphan-agy-starves-planner]] +
[[worktree-teardown-rc128-fix-and-stuck-vs-slow-lesson]] (Fix#1 b491fbd +
worktree 4e21f39 were the prereqs).

★★ **DURABLE RULE — editing LARGE multi-file harness code: SPLIT into single-file
tasks so each `.py` uses `__JANUSMASK_PATCHES__` symbol patches (file size
IRRELEVANT — only changed symbols are emitted).** A `len(files_touched) > 1` OR
any-non-`.py` task forces a VERBATIM WHOLE-FILE `__JANUSMASK_MANIFEST__`
(`orchestrator.py:_requires_verbatim_manifest` :1396; multi-file submissions are
*validated* to be manifests), which is INFEASIBLE for 165KB/265KB files (a prior
3-file-manifest single-task brief died `synthesis_or_ast_failed` on a gemini
syntax error). NOTE the apply path `_commit_accepted_output_patches`
(git_integration.py:1251) DOES group patch entries by `'file'` across files — but
the dispatch PROMPT + multi-file validation block that route, so the only way to
get symbol patches is one-file-per-task. This is the proven epic-split pattern.

★★ **DURABLE RULE — oracle-coupled multi-file work splits cleanly with `-k` vcmd
slices + dependency edges.** Map each oracle test to its file; give each task a
`-k` slice selecting only its tests (verify each slice collects ≥1 and is
RED-before); add a dep edge where a test needs two files (claudecap-config-key
dep claudecap-daemon-cap because `test_claudecap_impl_symbols_present` needs BOTH
the reader AND the config key). Each task gets its own decision file keyed to its
exact task_id (orchestrator.py + autowork_daemon.py are `_NEVER_AUTO_APPROVE`;
config.yaml is `config/**`).

★★ **GOTCHA — the CLAUDE_CONFIG_DIR oracle-binding contract.** The committed
oracle's `_resolve_config_dir_builder` probes `_SEED_NAMES` IN ORDER
(`_build_agent_env` FIRST, then `_seed_claude_config_dir`, …) over autowork_daemon
+ orchestrator, and BINDS to the first (fn, `_call_variants`-convention) returning
a dict with `CLAUDE_CONFIG_DIR`; it then asserts DISTINCT values for two work_dir
args. `_build_agent_env(agent, state_dir, round_number=1)` derives its per-spawn
work_dir from the `JANUSMASK_TASK_ID` **env var** (orchestrator.py:293/298), which
is CONSTANT under the oracle's direct argument-only calls → if `_build_agent_env`
sets the key, the resolver binds it and distinctness FAILS (first attempt failed
exactly this way: both → `claude-r1-notask-da39a3ee`). FIX: keep
`_build_agent_env`'s returned dict FREE of CLAUDE_CONFIG_DIR; add a dedicated
`_seed_claude_config_dir(agent, work_dir, task_id=None)` deriving the dir as a
PURE FUNCTION of the `work_dir` ARGUMENT (sha256), claude-only, fail-safe on
mkdir OSError; wire it into `spawn_agent` for real per-task isolation (spawn
wiring is NOT oracle-gated → validate empirically). Roadmap fan-out is
owner-gated (deny-all allowlist until owner confirms).
