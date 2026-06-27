# G_detondeps — Detonation missing-dep install fallback

Fix for: a synthesized PoC reaching a REAL sink
(`nltk.classify.megam.call_megam`) failed detonation with
`ModuleNotFoundError: No module named 'regex'` — a genuine third-party dep of the
cloned target that is absent from the detonation environment. The bug is
unprovable until the dep is present. Owner decision: surgical-import-first,
install-requirements fallback. The **install fallback** is the primary fix and
lands entirely in `ngv2/poc_runner_live.py::detonate_live`.

Target tree: `/home/xnihil0zer0/NobleGreedv2` @ pristine HEAD `ef15c60`.
All verification was done in a throwaway worktree (`/tmp/ngv2_detondeps`); the
live tree was restored to `ef15c60` (poc_runner_live.py reverted, no commit).

---

## Pinned signatures (verified against the live module before editing)

- `detonate_live(poc, target_spec=None, *, timeout_s=None, success_marker=DEFAULT_SUCCESS_MARKER, expected_fs_signature=None)` (lines ~258-265).
  Return-dict shape kept IDENTICAL: `{exit_code, stdout, stderr, duration_ms, fs_snapshot_diff, timed_out, verdict?}`.
- `build_detonation_jail_argv(cmd, *, repo_root, work_dir, extra_ro=())` -> `list[str]` (line ~106). Reused unchanged.
- `snapshot_tree(root) -> dict[str,str]`, `diff_snapshots(before, after) -> str` (lines ~160, 193). Reused.
- `TIMEOUT_EXIT_CODE = 124`, `DEFAULT_TIMEOUT_S = 30.0`, `DEFAULT_SUCCESS_MARKER = "VULNERABLE"`. Reused.
- `semantic_verdict(...)` (lazy import from `ngv2.detonation`). Gate UNCHANGED.

## Seam design (so the loop is unit-testable without real network/pip/bwrap)

Two optional kwargs added to `detonate_live`, each defaulting to the real path:

- `pip_installer: Callable[[str, str], bool] = _default_pip_installer`
  — host-side `sys.executable -m pip install --target <dir> <name>` (network
  available, OUTSIDE the jail), returns success bool, fail-soft (never raises).
- `jail_runner: Callable[..., dict] = _default_jail_runner`
  — `jail_runner(cmd, *, repo_root, work_dir, extra_ro, child_env, timeout_s) -> {exit_code, stdout, stderr, timed_out}`;
  builds a FRESH `build_detonation_jail_argv` jail per call and runs it; raises
  only `LiveRunnerError` (no bwrap) — fail-closed preserved.

Existing callers (`make_live_runner`, `ngv2.workers._runner` detonate seam) and
oracles (`test_detonation.py`, `test_poc_runner.py`,
`test_runner_hunt_detonation_wiring.py`) call `detonate_live` WITHOUT these kwargs,
so they are unaffected.

---

## Exact edits to `ngv2/poc_runner_live.py`

### 1. Imports

OLD:
```python
import hashlib
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Callable, Iterable, Mapping, Optional, Sequence, Tuple
```
NEW:
```python
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable, Iterable, List, Mapping, Optional, Sequence, Tuple
```

### 2. New module constants (after `DEFAULT_SUCCESS_MARKER`)
```python
JMDEPS_DIRNAME: str = "_jmdeps"
MAX_DEP_INSTALL_ROUNDS: int = 3
PIP_INSTALL_TIMEOUT_S: float = 180.0
_MISSING_MODULE_RE = re.compile(
    r"ModuleNotFoundError: No module named ['\"]([^'\"]+)['\"]"
)
```

### 3. New helpers (after `_entry_cmd`, before `detonate_live`)
- `_missing_modules_from_stderr(stderr) -> List[str]` — every
  `No module named 'X.y'` reduced to top-level `X`, deduped, order-preserving.
- `_target_top_packages(repo_root, cmd) -> frozenset` — top-level dirs with
  `__init__.py` and bare `.py` modules directly under `repo_root`; these are the
  TARGET's own packages and are NEVER auto-installed (a MNFE for them means a
  grounding/sys.path bug, not a missing dep — and installing a same-named PyPI
  package would be a false-positive risk).
- `_default_pip_installer(name, target_dir) -> bool` — real host pip, fail-soft.
- `_default_jail_runner(cmd, *, repo_root, work_dir, extra_ro, child_env, timeout_s) -> dict`
  — real `build_detonation_jail_argv` + `subprocess.run` (incl. TimeoutExpired ->
  `TIMEOUT_EXIT_CODE`, `timed_out=True`).

### 4. `detonate_live` signature — added two optional seam kwargs
```python
    expected_fs_signature: Optional[str] = None,
    pip_installer: Optional[Callable[[str, str], bool]] = None,
    jail_runner: Optional[Callable[..., dict]] = None,
) -> dict:
```
+ docstring paragraph documenting the fallback; + default-seam binding at the top
of the body.

### 5. Body rewrite (run + install loop)
- `_jmdeps` dir is created up-front (`os.makedirs(deps_dir, exist_ok=True)`) BEFORE
  any snapshot.
- `_snapshot_excluding_deps(root)` wraps `snapshot_tree` and drops the
  `_jmdeps/` subtree, so installed deps NEVER appear in the before/after diff.
- `_run_once(env, extra)` snapshots -> `jail_runner(...)` -> snapshots -> builds the
  result dict (identical shape; duration timed around the run).
- First run with the base `child_env`/`extra_ro`.
- Bounded loop (`MAX_DEP_INSTALL_ROUNDS = 3`):
  - break if last run `exit_code == 0` OR `timed_out` (a success or timeout is
    final — never retried).
  - `missing = _missing_modules_from_stderr(stderr)` minus target-own packages
    minus already-installed names.
  - break if no installable missing dep.
  - install each via `pip_installer` (wrapped in `try/except -> ok=False`, so a
    raising seam degrades to the prior failure and never escapes).
  - if NO install succeeded -> break (degrade to original failure).
  - else add `_jmdeps` to `extra_ro` (RO-bind into a fresh jail) and prepend it to
    `PYTHONPATH`, then re-run.
- The FINAL run's result is returned; `semantic_verdict` is computed on the FINAL
  run only when `expected_fs_signature` is supplied — gate UNCHANGED.

Jail not weakened: `_jmdeps` is RO-bound (via `extra_ro` -> `--ro-bind`),
`repo_root` stays RO, pip runs on the host outside bwrap (no new in-jail network).

---

## RED -> GREEN evidence (worktree `/tmp/ngv2_detondeps`)

Oracle: `tests/test_detonation_dep_install.py` (hermetic; fake `pip_installer` +
scripted `jail_runner`; no real pip/network/bwrap).

- **RED** (oracle vs PRISTINE module, edits stashed): `8 failed in 0.18s`
  (TypeError: unexpected kwarg `pip_installer`; AttributeError:
  `_missing_modules_from_stderr` missing).
- **GREEN** (oracle vs edited module): `8 passed in 0.13s`.
  - One iteration caught a real gap: an injected `pip_installer` that RAISES
    propagated. Fixed by wrapping the install call in `try/except -> ok=False`.
    Re-ran: `8 passed`.

Cases proven: (a) one MNFE -> exactly one install of `regex` + exactly one retry,
deps dir on PYTHONPATH + RO-bound; (b) first-time success installs nothing, no
retry; (c) pip failure -> original failure, no raise, `verdict != "confirmed"`
(no false positive); (c') raising installer does not escape; (d) loop bounded to
`1 + MAX_DEP_INSTALL_ROUNDS` runs / `MAX_DEP_INSTALL_ROUNDS` installs; (e)
target's own top package (`nltk` under `repo_root`) does NOT trigger install and
does NOT retry; (e') a genuine third-party dep (`regex`) DOES install even with a
`repo_root` set; parser reduces dotted names + dedups.

## Regression

`python -m pytest -q -k "detonat or poc_runner or runner_hunt or live"`:
- Edited: **132 passed, 8 failed** (the 8 are `test_z3_solver_adapter_wired` —
  z3 not installed in this env; pre-existing, documented in MEMORY).
- Pristine (same -k, z3 subset): same 8 z3 failures -> NOT caused by this change.
- 124 pre-existing passing + 8 new oracle tests = 132 passing. No regression.
- `tests/test_detonation.py tests/test_poc_runner.py tests/test_runner_hunt_detonation_wiring.py`: **15 passed** unchanged.

## poc_writer.py — UNCHANGED (with reason)

The PoC headers (`_PY_HEADER` ~219, `_py_command_injection` ~227, etc.) place
`from {module} import {sym}` at module top-level, NOT inside any try/except. A
`ModuleNotFoundError` therefore propagates uncaught and CPython prints the full
traceback (incl. `ModuleNotFoundError: No module named 'X'`) to stderr — exactly
the clean signal the runner's install fallback parses. No bare-except swallows it.
No change needed or made; over-engineering poc_writer was explicitly cautioned
against.

## Could NOT verify hermetically

- The REAL `_default_pip_installer` (actual `pip install --target` over the
  network) and `_default_jail_runner` (actual bwrap subprocess) were NOT exercised
  — by design the oracle injects fakes (no network/pip/bwrap in CI). Their bodies
  are straightforward wrappers over `subprocess.run` and the existing, already-
  tested `build_detonation_jail_argv`. A real end-to-end nltk/regex detonation
  (host with network + bwrap) remains an owner-side live check.
```

## Restore

Live tree `/home/xnihil0zer0/NobleGreedv2` restored to `ef15c60`
(`git checkout -- ngv2/poc_runner_live.py`; no commit). Worktree to be removed
with `git worktree remove`.
