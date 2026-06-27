---
slug: p02_ngv2_jailed_lockfile_install
working_dir: /home/xnihil0zer0/NobleGreedv2
complexity_score: low
required_task_ids:
  - p02-ngv2-jailed-install-oracle
  - p02-ngv2-jailed-install-impl
---

# Title

P0.2-NGv2 — Jailed, lockfile-only dependency install for the NGv2 detonation runner

Port the already-landed JanusMask fix "P0.2-JM jailed lockfile install"
(`harness/target_bootstrap.py::_ensure_venv` / `_jailed_install_argv`) to the
NGv2 detonation engine. Today `ngv2/poc_runner_live.py` installs a target's
missing dependencies **host-side, with the network ON, driven reactively by
package names parsed out of the PoC's stderr** — so an attacker who can make the
cloned target emit a `ModuleNotFoundError: No module named 'evil-pkg'` causes
`evil-pkg` to be `pip install`-ed from PyPI on the host. This brief replaces that
reactive, network-on, stderr-named install with a **bwrap-jailed, `--unshare-net`,
lockfile-only** install: deps come from the target's own pinned lockfile and
nothing else, the install runs inside a network-unshared jail, and a missing
lockfile fails closed (no install).

This closes deliverable **X10** of the NGv2 acceptance contract
(`/home/xnihil0zer0/AI-Data/Research-JanusMask/NGv2-closure-deliverables-and-acceptance-contract.md`):
> "Dependency install is jailed + network-restricted + lockfile-only; an
> attacker-named stderr package is never installed ... assert it is NOT
> installed; assert install ran under `--unshare-net` against a lockfile snapshot."

# Scope

- Edit ONE existing file: `ngv2/poc_runner_live.py`.
- The reactive, stderr-driven install path is split across TWO top-level symbols,
  both of which must change:
  1. `_default_pip_installer(name, target_dir, python_bin=...)` — today runs a
     host-side `pip install --target <dir> <name>` for a single, possibly
     attacker-named package, **network ON, no jail, no lockfile**. Rebuild it so
     the default installer installs from the **target's own lockfile only**
     (`pip install -r <lockfile> --target <dir>`), inside a jail built via NGv2's
     own `build_detonation_jail_argv(..., )` so the install runs under
     `--unshare-net`, with the lockfile's source dir bound read-only and the
     install `target_dir` the only writable surface. **Never** install a bare,
     stderr-named package name. **Fail closed** (return False, install nothing)
     when no lockfile is found or when `bwrap` is unavailable.
  2. `detonate_live(...)` — today contains the reactive loop (the
     `for _round in range(MAX_DEP_INSTALL_ROUNDS)` block) that reads
     `_missing_modules_from_stderr(result['stderr'])` and feeds each
     attacker-influenced missing name to `pip_installer(name, deps_dir)`. Replace
     this stderr-driven, per-name reactive loop so dependency installation is
     driven by the **lockfile only** (a single jailed lockfile install into
     `deps_dir`, then a re-run with `deps_dir` on `PYTHONPATH`), NOT by names
     parsed from stderr. The `pip_installer` and `jail_runner` seams stay
     injectable so the oracle can drive the path with no real network/jail.

- The jail primitive routed through is NGv2's in-module
  `build_detonation_jail_argv` (it already emits `--unshare-net --unshare-ipc
  --unshare-pid` and binds the repo read-only). Do NOT import JanusMask's
  `harness.agent_jail.build_jail_argv` — that is harness-side and not importable
  from `ngv2/**`.

# Non-Goals

- **integration**: wiring this into a live `run_hunt` / conductor traversal is
  OUT OF SCOPE for this leaf. Do not touch `transition_planner`, `gate_executor`,
  `conductor_seams`, `run_hunt`, the FSM phase tuples, or `ngv2/workers/**`. The
  P2.1-cP `provision` producer consumes this installer later; that consumer is a
  separate brief. This leaf hardens the installer symbol(s) and proves the
  contract via the unit oracle ONLY.
- No npm / `node_modules` staging (that is P3.2-c4). Python lockfile only here.
- No change to `semantic_verdict`, the FS-snapshot oracle, the loopback path, or
  `_target_top_packages` (beyond what the lockfile-only rewrite of the reactive
  loop strictly requires).
- No change to the success/verdict gate — the installer must NOT be able to
  manufacture a confirmation.

# Inputs

- Target file: `ngv2/poc_runner_live.py` (existing).
  - Reactive loop to remove: lines ~331-352 inside `detonate_live`
    (`for _round in range(MAX_DEP_INSTALL_ROUNDS)` ... `_missing_modules_from_stderr`
    ... `pip_installer(name, deps_dir)`).
  - Installer to rebuild: `_default_pip_installer` (~line 434).
  - Jail builder to reuse: `build_detonation_jail_argv` (~line 69; already emits
    `--unshare-net`).
  - Constants in module: `JMDEPS_DIRNAME='_jmdeps'`, `MAX_DEP_INSTALL_ROUNDS=3`,
    `PIP_INSTALL_TIMEOUT_S=180.0`.
- JM precedent to mirror (technique only, do not import):
  `harness/target_bootstrap.py::_jailed_install_argv` + `_ensure_venv` —
  `pip install --no-input --disable-pip-version-check -r <lockfile>` inside a
  `build_jail_argv(bind_credentials=False)` jail (`--unshare-net`, repo ro-bound,
  venv the only writable bind), fail-closed when `bwrap` absent.
- Acceptance contract: X10 in
  `/home/xnihil0zer0/AI-Data/Research-JanusMask/NGv2-closure-deliverables-and-acceptance-contract.md`
  (quoted in the Title section).
- Lockfile detection: probe the target `repo_root` for, in order,
  `requirements.txt`, `requirements-dev.txt`, `requirements.lock` (mirror the JM
  precedent's `('requirements.txt','requirements-dev.txt')` set; extend with
  `requirements.lock` if present). If none found → fail closed (no install).
- Existing NGv2 test conventions: `tests/ngv2/test_poc_runner_live_smoke.py`
  imports symbols `from ngv2.poc_runner_live import ...`; existing dep-install
  tests (`tests/test_detonation_dep_install.py`) `import ngv2.poc_runner_live as
  prl` and `monkeypatch.setattr` the seams. The new oracle imports the generated
  module via importlib (NOT exec/eval) and monkeypatches the real subprocess /
  jail-run callable to raise so no real network or install occurs.

# Deliverables

1. A factory-authored RED oracle (test_authoring task) at
   `tests/ngv2/test_poc_runner_jailed_install.py`, mutation_target
   `ngv2.poc_runner_live`, that asserts (RED before, GREEN after):
   - **(a) POSITIVE** — a normal lockfile install succeeds inside the jail: with
     a valid lockfile present and the injected jail-run/install seam capturing the
     argv, the install runs and the captured argv contains `--unshare-net`; the
     re-run uses the installed deps dir on `PYTHONPATH`. (No real network: the
     real `subprocess.run` is monkeypatched to raise; the injected seam records
     the argv and returns success.)
   - **(b) NEGATIVE CONTROL** — an attacker-named package appearing ONLY in the
     PoC's stderr (e.g. stderr names `evil-pkg` via
     `ModuleNotFoundError: No module named 'evil-pkg'`) is **NEVER** installed:
     after detonation, the install seam was never invoked with `evil-pkg` as a
     bare package name; the reactive stderr-driven fetch path is gone. Assert the
     real `subprocess.run` (which would be the un-jailed reactive pip) was NOT
     called with the attacker name.
   - **(c) LOCKFILE-ONLY** — the install argv runs against the lockfile
     (`-r <lockfile>` / pinned), not a free resolve of a stderr-named package;
     assert `-r` + the lockfile path appear in the captured install argv and the
     attacker name does NOT.
   - **(d) FAIL-CLOSED** — with NO lockfile present, the installer installs
     nothing and the detonation does not fall back to a host network install
     (assert the install seam returns False / is not invoked, and no real
     subprocess fires).
   - regression_tests >= 2 (e.g. a benign lockfile install still succeeds AND the
     existing 4-tuple/`fs_snapshot_diff` shape of `detonate_live` is unchanged
     when no install is needed).
   - Seam injection: pass the `pip_installer` / `jail_runner` callables (already
     parameters of `detonate_live`) so the oracle never performs a real
     network/install; monkeypatch the module's `subprocess` to raise as a backstop
     so any un-jailed/reactive path is caught.
   - Import the generated code via importlib (`spec.loader.exec_module` from
     `tmp_path`); do NOT use exec/eval/`__import__`.

2. The implementation (io_adapter task) editing `ngv2/poc_runner_live.py` so the
   reactive stderr-driven install is replaced by the jailed lockfile-only install
   described in Scope, satisfying (a)-(d) above. `files_touched=['ngv2/poc_runner_live.py']`.

# Interfaces

- `_default_pip_installer(name: str, target_dir: str, python_bin: str='/usr/bin/python3') -> bool`
  — KEEP THE SIGNATURE (callers/tests depend on it). Rebuild the BODY so it: (i)
  resolves the lockfile from the target repo_root, (ii) builds the install argv
  `[<pip-or-python> -m pip install --no-input --disable-pip-version-check
  --target <target_dir> -r <lockfile>]` wrapped via
  `build_detonation_jail_argv(cmd, repo_root=<root>, work_dir=<target_dir>,
  extra_ro=[<lockfile-dir>])` so it runs under `--unshare-net`, (iii) returns
  False (installs nothing) when no lockfile is found or `bwrap` is absent
  (fail-closed), and (iv) NEVER puts a bare `name` package on the pip command
  line. If the existing single-name signature cannot carry the lockfile/root, add
  a sibling helper (R-anchored on `_default_pip_installer`) for the jailed
  lockfile install and have `_default_pip_installer` delegate / become a thin
  lockfile-only wrapper — but the reactive single-name behavior must be gone.
- `build_detonation_jail_argv(cmd, *, repo_root, work_dir, extra_ro=(), shared_loopback_netns=False) -> list[str]`
  — REUSE as-is; it already emits `--unshare-net`. This is the NGv2 jail primitive.
- `detonate_live(...)` — KEEP THE SIGNATURE and the `pip_installer` / `jail_runner`
  injectable seams. Replace the `for _round in range(MAX_DEP_INSTALL_ROUNDS)`
  reactive block: do a single lockfile-driven jailed install into `deps_dir`
  (when the first run failed and a lockfile exists), then ONE re-run with
  `deps_dir` on `PYTHONPATH`. Do NOT call `_missing_modules_from_stderr` to pick
  packages to install. `_missing_modules_from_stderr` MAY be retained as a dead
  helper or removed; it must NOT drive any install.

# Required plan shape

Author EXACTLY TWO tasks. Do NOT decompose further; do NOT add a third task.

1. `test_authoring` task — id `p02-ngv2-jailed-install-oracle`:
   - meta_task_type `test_authoring`, mutation_target `ngv2.poc_runner_live`.
   - Produces `tests/ngv2/test_poc_runner_jailed_install.py` (RED), regression_tests >= 2.
   - Imports generated code via importlib; seam-injects `pip_installer`/`jail_runner`
     and monkeypatches real `subprocess` to raise.

2. `implementation` task — id `p02-ngv2-jailed-install-impl`:
   - meta_task_type `io_adapter` (external `ngv2/**`, NOT `harness_self_fix`;
     `ngv2/**` is not sensitive → NO decision file required).
   - `files_touched=['ngv2/poc_runner_live.py']`.
   - **`partial_edit: true` IS REQUIRED.** This edits an EXISTING file and modifies
     **more than one** top-level symbol (`_default_pip_installer` AND `detonate_live`,
     plus possibly an R-anchored sibling install helper). Per the known
     whole_file_drift harness bug, the partial-edit dispatch gate only fires for
     `partial_edit: true` (or a bypass meta_task_type); without it the worker
     emits a naive whole-file rewrite that is rejected as `whole_file_drift`.
     Therefore this task MUST set `partial_edit: true` AND carry a
     `__JANUSMASK_PATCHES__` recipe with ONE entry per modified top-level symbol.
     Do NOT use a whole-file manifest for this existing-file multi-symbol edit.
   - (Single-symbol scoping is NOT possible here — the reactive attack surface
     spans both `_default_pip_installer` and the loop inside `detonate_live`, so
     both must change. If a later refactor truly confined the edit to one symbol,
     single-symbol partial-edit would be preferred — but plan for the two-symbol
     recipe below.)

   `__JANUSMASK_PATCHES__` recipe skeleton (one entry per modified symbol; add an
   R-anchored entry if a new sibling install helper is introduced):

   ```
   __JANUSMASK_PATCHES__ = [
       {"kind": "symbol", "name": "_default_pip_installer"},
       {"kind": "symbol", "name": "detonate_live"},
       # If a new sibling helper is added, R-anchor it on an existing symbol, e.g.:
       # {"kind": "symbol", "name": "_jailed_lockfile_install_argv", "anchor": "after:_default_pip_installer"},
   ]
   ```

- **integration** restated: NO live `run_hunt` / FSM / conductor wiring in either
  task. The installer is hardened and proven via the unit oracle only; the
  P2.1-cP provision producer is the downstream consumer (separate brief).
- regression_tests >= 2 (restated).
- verification_command (bare, no `cd`):
  `python -m pytest tests/ngv2/test_poc_runner_jailed_install.py -q`
